package com.ariyan.geoai

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope
import com.google.android.gms.tasks.Tasks
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * DriveBackupWorker — backs up one country's downloaded offline DEM+NDVI
 * package to the user's own Google Drive, so it survives an app
 * uninstall/reinstall or a move to a new phone (this app's internal
 * storage does NOT survive either of those — see the STORAGE CORRECTION
 * note from planning: Drive backup is the actual mechanism that makes
 * "transfer to a new phone" possible, not just a nice-to-have).
 *
 * SCOPE: requests only https://www.googleapis.com/auth/drive.file — the
 * narrow, non-sensitive scope that only lets this app see files IT
 * created, never the user's whole Drive (matches the scope decision
 * already made in planning, specifically to avoid Google's heavier
 * app-verification process for broader scopes).
 *
 * AUTHORIZATION: uses the current (Google Sign-In for Android is
 * deprecated) com.google.android.gms.auth.api.identity.AuthorizationClient
 * API, NOT the older GoogleSignInClient/GoogleApiClient. A WorkManager
 * Worker runs in the background and cannot launch an interactive consent
 * screen (no Activity to attach a PendingIntent result to), so this
 * Worker ONLY attempts a SILENT authorization — which Google's own docs
 * confirm returns a real access token with no UI at all once the user has
 * granted access at least once before (see AuthorizationResult.hasResolution()
 * == false). The first-time interactive consent grant is a SEPARATE
 * concern, to be wired into OfflineDataActivity.kt (an Activity, so it CAN
 * launch the consent PendingIntent) — not yet done; until that exists,
 * this Worker will fail informatively (see getAccessTokenOrNull()) rather
 * than silently do nothing.
 *
 * UPLOAD MECHANISM: real Drive v3 REST multipart upload
 * (POST https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart),
 * built BY HAND with plain HttpURLConnection rather than pulling in the
 * full google-api-client/google-http-client library — matches this
 * project's established lean-APK preference (see build.gradle.kts's own
 * comments on avoiding scipy/rasterio/GDAL for the same reason, and
 * geotiff_cog_reader.py's hand-written TIFF parser instead of
 * tifffile/imagecodecs). The exact multipart/related body shape (metadata
 * part as application/json first, media part with the real file's mime
 * type second, boundary-delimited) was confirmed against Google's current
 * official Drive API upload documentation before writing this, and
 * independently verified byte-for-byte in a local sandbox test against
 * that documented shape.
 *
 * WHAT GETS BACKED UP (see collectBackupCandidates() for the authoritative
 * list and reasoning): dem_manifest.json, ndvi_manifest.json, every
 * dem/*.tif tile, every ndvi/*.npz composite cell. Deliberately NOT
 * backed up: offline_status.json (transient download-progress state, no
 * value once a download finishes) and ndvi_scenes_cache/ (large
 * disposable raw Sentinel-2 band downloads, already folded into the
 * final ndvi/*.npz composites, re-derivable by re-running the download).
 *
 * IDEMPOTENCY / RESUME: tracks what's already been uploaded in a local
 * drive_backup_manifest.json (relative path -> Drive fileId + the local
 * file's size/lastModified at upload time) written alongside
 * dem_manifest.json/ndvi_manifest.json in the same country folder. A
 * file already recorded with an unchanged size+lastModified is skipped on
 * a re-run — this manifest is purely a Kotlin-side backup-status concern
 * and is never read or written by the Python offline module, keeping the
 * module boundary clean.
 *
 * HONEST STATE: the pure-logic pieces (multipart body byte format,
 * backup-manifest JSON round-trip / skip-if-unchanged comparison logic)
 * were verified in a local sandbox test against the real documented Drive
 * API shape before this file was written. The real network calls (the
 * actual AuthorizationClient token exchange and the actual Drive upload
 * HTTP requests) are, like every other real-network piece of this
 * project's offline mode, unverified until the on-device confirmation
 * stage — this sandbox cannot run Android/Play Services code at all, only
 * plain-Python equivalents of the wire format. Wiring the interactive
 * first-time consent grant + a "Back up to Drive" trigger into
 * OfflineDataActivity.kt, so this Worker can actually be enqueued and its
 * real-world result checked in the user's own Drive, is the next step —
 * not yet done as of this commit.
 */
class DriveBackupWorker(appContext: Context, params: WorkerParameters) : CoroutineWorker(appContext, params) {

    companion object {
        const val KEY_COUNTRY_ISO = "country_iso"
        const val KEY_UPLOADED_COUNT = "uploaded_count"
        const val KEY_SKIPPED_COUNT = "skipped_count"
        const val KEY_FAILED_COUNT = "failed_count"
        const val KEY_ERROR = "error"

        private val DRIVE_FILE_SCOPE = Scope("https://www.googleapis.com/auth/drive.file")
        private const val UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
        private const val BOUNDARY = "ariyan_geo_ai_drive_backup_boundary"

        // Every backed-up Drive file is named with this prefix so it's
        // unambiguous which files in the user's Drive belong to this app.
        // Deliberately NO Drive folder hierarchy is created -- the
        // drive.file scope already means this app can only ever see files
        // it itself created, so a flat naming convention is sufficient and
        // avoids an entire extra find-or-create-folder API round trip for
        // no real benefit.
        private const val NAME_PREFIX = "ariyan_offline_"
    }

    override suspend fun doWork(): Result {
        val iso = inputData.getString(KEY_COUNTRY_ISO)
            ?: return Result.failure(workDataOf(KEY_ERROR to "No country_iso provided to DriveBackupWorker"))

        val accessToken = getAccessTokenOrNull()
            ?: return Result.failure(workDataOf(
                KEY_ERROR to "No Google Drive authorization available (silent authorize() needs a prior interactive grant). Grant Drive access from OfflineDataActivity first."
            ))

        val offlineDataRoot = File(applicationContext.filesDir, "offline_data")
        val countryDir = File(offlineDataRoot, iso.lowercase())
        if (!countryDir.isDirectory) {
            return Result.failure(workDataOf(KEY_ERROR to "No offline data downloaded yet for $iso"))
        }

        val candidates = collectBackupCandidates(countryDir, iso)
        val manifest = BackupManifest.load(countryDir)

        var uploaded = 0
        var skipped = 0
        var failed = 0

        for ((index, candidate) in candidates.withIndex()) {
            setProgressAsync(workDataOf(
                "phase" to "uploading",
                "done" to index,
                "total" to candidates.size,
                "detail" to candidate.driveName
            ))

            val existing = manifest.entryFor(candidate.relativePath)
            if (existing != null &&
                existing.sizeBytes == candidate.file.length() &&
                existing.lastModified == candidate.file.lastModified()
            ) {
                skipped++
                continue
            }

            try {
                val driveFileId = uploadFile(accessToken, candidate)
                manifest.record(candidate.relativePath, driveFileId, candidate.file.length(), candidate.file.lastModified())
                uploaded++
            } catch (e: Exception) {
                // A single file's real upload failure (network blip, a
                // transient Drive error, an expired token mid-run) doesn't
                // abort the whole backup job -- matches this project's
                // existing precedent (offline_data_manager.py: one bad
                // tile/scene doesn't fail the whole country download).
                // Recorded via the failed count below; the file will be
                // retried on the next backup run since it was never
                // written into the manifest.
                failed++
            }
        }

        manifest.save(countryDir)

        val output = workDataOf(
            KEY_UPLOADED_COUNT to uploaded,
            KEY_SKIPPED_COUNT to skipped,
            KEY_FAILED_COUNT to failed
        )

        // If EVERY file failed and nothing succeeded or was already
        // present, this looks like a transient/systemic problem (e.g. no
        // network right now) worth WorkManager's own retry+backoff, rather
        // than a real terminal failure.
        return if (failed > 0 && uploaded == 0 && skipped == 0) {
            Result.retry()
        } else {
            Result.success(output)
        }
    }

    /**
     * Attempts a SILENT (non-interactive) authorization only. Per Google's
     * current documentation: once a user has granted a scope at least once
     * before, calling AuthorizationClient.authorize() again in a later
     * session returns a real access token with no user interaction needed
     * at all (hasResolution() == false). If the user has never granted
     * drive.file access before, hasResolution() will be true (Google wants
     * to show a consent screen) -- but a background Worker has no Activity
     * to launch that consent PendingIntent from, so this deliberately
     * returns null in that case rather than attempting anything with the
     * PendingIntent. The interactive first-time grant must happen in
     * OfflineDataActivity.kt instead (not yet wired up).
     */
    private suspend fun getAccessTokenOrNull(): String? {
        return try {
            val client = Identity.getAuthorizationClient(applicationContext)
            val request = AuthorizationRequest.Builder()
                .setRequestedScopes(listOf(DRIVE_FILE_SCOPE))
                .build()
            val result = Tasks.await(client.authorize(request))
            if (result.hasResolution()) null else result.accessToken
        } catch (e: Exception) {
            null
        }
    }

    private data class BackupCandidate(
        val file: File,
        val relativePath: String,
        val driveName: String,
        val mimeType: String,
    )

    /**
     * The authoritative list of what this backup job uploads, and what it
     * deliberately skips -- see this file's class-level doc comment for
     * the reasoning on each exclusion.
     */
    private fun collectBackupCandidates(countryDir: File, iso: String): List<BackupCandidate> {
        val isoLower = iso.lowercase()
        val candidates = mutableListOf<BackupCandidate>()

        for (manifestName in listOf("dem_manifest.json", "ndvi_manifest.json")) {
            val f = File(countryDir, manifestName)
            if (f.isFile) {
                candidates.add(BackupCandidate(f, manifestName, "$NAME_PREFIX${isoLower}_$manifestName", "application/json"))
            }
        }

        File(countryDir, "dem").listFiles { f -> f.isFile && f.name.endsWith(".tif") }?.forEach { f ->
            candidates.add(BackupCandidate(f, "dem/${f.name}", "$NAME_PREFIX${isoLower}_dem_${f.name}", "image/tiff"))
        }

        File(countryDir, "ndvi").listFiles { f -> f.isFile && f.name.endsWith(".npz") }?.forEach { f ->
            candidates.add(BackupCandidate(f, "ndvi/${f.name}", "$NAME_PREFIX${isoLower}_ndvi_${f.name}", "application/octet-stream"))
        }

        return candidates
    }

    /**
     * Real Drive v3 multipart upload, built by hand. Shape confirmed
     * against Google's current official documentation and independently
     * byte-verified in sandbox before this file was written (see class doc
     * comment). Returns the new file's Drive fileId on success; throws on
     * any real failure (non-2xx response, network error) rather than
     * silently swallowing it -- the caller in doWork() decides how to
     * count/handle that failure.
     */
    private fun uploadFile(accessToken: String, candidate: BackupCandidate): String {
        val metadataJson = JSONObject().apply { put("name", candidate.driveName) }.toString()
        val fileBytes = candidate.file.readBytes()

        val connection = URL(UPLOAD_URL).openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.doOutput = true
        connection.setRequestProperty("Authorization", "Bearer $accessToken")
        connection.setRequestProperty("Content-Type", "multipart/related; boundary=$BOUNDARY")

        try {
            connection.outputStream.use { out ->
                out.write("--$BOUNDARY\r\n".toByteArray())
                out.write("Content-Type: application/json; charset=UTF-8\r\n\r\n".toByteArray())
                out.write(metadataJson.toByteArray())
                out.write("\r\n--$BOUNDARY\r\n".toByteArray())
                out.write("Content-Type: ${candidate.mimeType}\r\n\r\n".toByteArray())
                out.write(fileBytes)
                out.write("\r\n--$BOUNDARY--".toByteArray())
            }

            val status = connection.responseCode
            if (status !in 200..299) {
                val errorBody = connection.errorStream?.bufferedReader()?.readText().orEmpty()
                throw IOException("Drive upload failed for ${candidate.driveName}: HTTP $status $errorBody")
            }

            val responseBody = connection.inputStream.bufferedReader().readText()
            return JSONObject(responseBody).getString("id")
        } finally {
            connection.disconnect()
        }
    }

    /**
     * Tracks which local files have already been backed up to Drive, and
     * with what Drive fileId, size, and lastModified -- so a re-run only
     * uploads what's new or changed. Purely a Kotlin-side backup-status
     * concern: never read or written by the Python offline module, and
     * kept as its own JSON file (drive_backup_manifest.json) alongside
     * dem_manifest.json/ndvi_manifest.json rather than inside either of
     * them, so the two concerns (what's been downloaded vs. what's been
     * backed up) stay cleanly separate.
     */
    private class BackupManifest private constructor(private val entries: MutableMap<String, Entry>) {

        data class Entry(val driveFileId: String, val sizeBytes: Long, val lastModified: Long)

        fun entryFor(relativePath: String): Entry? = entries[relativePath]

        fun record(relativePath: String, driveFileId: String, sizeBytes: Long, lastModified: Long) {
            entries[relativePath] = Entry(driveFileId, sizeBytes, lastModified)
        }

        fun save(countryDir: File) {
            val obj = JSONObject()
            for ((path, entry) in entries) {
                obj.put(path, JSONObject().apply {
                    put("drive_file_id", entry.driveFileId)
                    put("size_bytes", entry.sizeBytes)
                    put("last_modified", entry.lastModified)
                })
            }
            val dest = File(countryDir, "drive_backup_manifest.json")
            val tmp = File(countryDir, "drive_backup_manifest.json.part")
            tmp.writeText(obj.toString())
            // Same atomic-save pattern already proven on the Python side
            // (offline_data_manager.py: temp file + rename, never leaves a
            // half-written manifest at the real path).
            tmp.renameTo(dest)
        }

        companion object {
            fun load(countryDir: File): BackupManifest {
                val f = File(countryDir, "drive_backup_manifest.json")
                if (!f.isFile) return BackupManifest(mutableMapOf())
                return try {
                    val obj = JSONObject(f.readText())
                    val entries = mutableMapOf<String, Entry>()
                    val keys = obj.keys()
                    while (keys.hasNext()) {
                        val path = keys.next()
                        val rec = obj.getJSONObject(path)
                        entries[path] = Entry(rec.getString("drive_file_id"), rec.getLong("size_bytes"), rec.getLong("last_modified"))
                    }
                    BackupManifest(entries)
                } catch (e: Exception) {
                    // A corrupted/unreadable local manifest is treated the
                    // same as "no backup has run yet" -- re-uploading a file
                    // that's already in Drive just creates a harmless,
                    // user-recoverable duplicate, whereas crashing the whole
                    // backup job over one bad local JSON file would not be.
                    BackupManifest(mutableMapOf())
                }
            }
        }
    }
}
