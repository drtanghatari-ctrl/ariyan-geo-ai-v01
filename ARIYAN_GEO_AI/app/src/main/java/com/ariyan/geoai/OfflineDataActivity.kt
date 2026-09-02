package com.ariyan.geoai

import android.content.IntentSender
import android.os.Bundle
import android.view.View
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.ariyan.geoai.databinding.ActivityOfflineDataBinding
import com.chaquo.python.PyException
import com.chaquo.python.Python
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.ApiException
import com.google.android.gms.common.api.Scope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

/**
 * OfflineDataActivity — lets the user download a country's offline DEM +
 * NDVI package (see offline_download_runner.py / offline_data_manager.py
 * / offline_country_registry.py) so an investigation can still run with
 * no network access, and back that downloaded data up to their own
 * Google Drive (DriveBackupWorker.kt) so it survives an app
 * uninstall/reinstall or a move to a new phone.
 *
 * Calls offline_download_runner.py's thin JSON-string wrapper functions,
 * in the exact same style MainActivity.kt already uses for
 * investigation_mobile.py/debate_mobile.py -- plain strings in,
 * JSON string out, parsed here with org.json.
 *
 * PROGRESS: run_country_download_json() is a long, blocking call (a
 * whole-country DEM + NDVI download can realistically take hours -- see
 * offline_data_manager.py's own docstring on why NDVI_GRID_SIZE was kept
 * coarse specifically to keep this tractable at all). Rather than a
 * Kotlin callback crossing the Chaquopy boundary, a separate lightweight
 * coroutine polls offline_status.json (via
 * get_offline_download_status_json()) every 1.5s while the download
 * runs, entirely file-based -- the same mechanism already proven by
 * dem_manifest.json/ndvi_manifest.json elsewhere in this project.
 *
 * STORAGE: offline_data_root is this app's own private internal storage
 * (filesDir/offline_data) -- no extra storage permission needed, and not
 * visible to other apps or the user's file browser.
 *
 * DRIVE BACKUP (this commit): DriveBackupWorker.kt was already built and
 * CI-compiling, but explicitly documented its own next step as "wiring
 * the interactive first-time consent grant + a 'Back up to Drive'
 * trigger into OfflineDataActivity.kt" -- that is what this section
 * does. Two pieces:
 *
 *   1. Interactive consent ("Grant Google Drive access" button): a
 *      background Worker cannot show UI, so the FIRST TIME the app needs
 *      drive.file access, an Activity has to ask for it. Calls
 *      AuthorizationClient.authorize() here (same drive.file scope
 *      DriveBackupWorker.kt already requests); if hasResolution() is
 *      true, launches the returned PendingIntent via
 *      registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult())
 *      and completes the grant in the callback with
 *      Identity.getAuthorizationClient(this).getAuthorizationResultFromIntent(data).
 *      This exact registerForActivityResult + getAuthorizationResultFromIntent
 *      shape was confirmed against Google's current official "Authorize
 *      access to Google user data" Android developer documentation
 *      before writing it (not assumed/recalled from memory), matching
 *      this project's established practice of verifying Android API
 *      shapes against live docs before committing (already done once for
 *      the silent-authorize() piece when DriveBackupWorker.kt itself was
 *      written). Once granted here, DriveBackupWorker's own SILENT
 *      authorize() call (its only option, being a background Worker)
 *      succeeds on every future run with no further UI.
 *
 *   2. "Back up this country to Drive" button: enqueues DriveBackupWorker
 *      as a WorkManager OneTimeWorkRequest for the selected country and
 *      observes its WorkInfo (progress data written via the Worker's own
 *      setProgressAsync() calls, plus final outputData on
 *      success/failure) to render live upload progress and the final
 *      uploaded/skipped/failed counts or error message.
 *
 * HONEST STATE: this Activity's download flow (list/summary/download)
 * has still NOT been run on an actual device or in CI -- see the
 * download section below, unchanged from before this commit. This
 * newly-added Drive consent + backup wiring is ALSO new, unverified
 * Kotlin -- the real AuthorizationClient token exchange and real Drive
 * upload HTTP calls remain unverified until the on-device confirmation
 * stage, per the same honest gap already flagged in
 * DriveBackupWorker.kt's own class doc comment.
 */
class OfflineDataActivity : AppCompatActivity() {

    private lateinit var binding: ActivityOfflineDataBinding
    private lateinit var python: Python
    private val offlineDataRoot: String by lazy { File(filesDir, "offline_data").absolutePath }

    // Dropdown shows "IR — Iran"; this maps that label back to the real
    // ISO code Python needs, rather than re-parsing the display string.
    private var isoByLabel: Map<String, String> = emptyMap()
    private var statusPollingJob: Job? = null

    // -- Drive backup: the narrow, non-sensitive scope DriveBackupWorker
    // itself requests -- this app can only ever see files IT created,
    // never the user's whole Drive. Declared once here so the interactive
    // request below asks for exactly the same scope the Worker's own
    // silent authorize() call will later rely on already being granted.
    private val driveFileScope = Scope("https://www.googleapis.com/auth/drive.file")

    // Must be registered unconditionally during Activity construction
    // (before onCreate/onStart), per Android's ActivityResultLauncher
    // contract -- registering it inside a click listener would crash.
    private val driveConsentLauncher = registerForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult()
    ) { activityResult ->
        try {
            val authorizationResult = Identity.getAuthorizationClient(this)
                .getAuthorizationResultFromIntent(activityResult.data)
            onDriveAuthorizationResult(authorizationResult.accessToken != null)
        } catch (e: ApiException) {
            // The user declined the consent screen, or it was dismissed
            // some other way -- not a crash-worthy condition, just report
            // it plainly (matches this project's honesty-over-guessing
            // convention elsewhere, e.g. GPR's never-fabricate-a-value rule).
            binding.textDriveStatus.text = "Drive access was not granted (${e.statusCode})."
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOfflineDataBinding.inflate(layoutInflater)
        setContentView(binding.root)

        python = Python.getInstance()

        loadCountryList()

        binding.buttonRefreshStatus.setOnClickListener { refreshCountrySummary() }
        binding.buttonDownload.setOnClickListener { onDownloadClicked() }
        binding.buttonGrantDriveAccess.setOnClickListener { requestDriveAuthorization() }
        binding.buttonBackupDrive.setOnClickListener { startDriveBackup() }
    }

    override fun onDestroy() {
        super.onDestroy()
        statusPollingJob?.cancel()
    }

    private fun loadCountryList() {
        lifecycleScope.launch {
            try {
                val json = withContext(Dispatchers.IO) { listOfflineCountriesJson() }
                val obj = JSONObject(json)
                val labels = mutableListOf<String>()
                val map = mutableMapOf<String, String>()
                val keys = obj.keys()
                while (keys.hasNext()) {
                    val iso = keys.next()
                    val name = obj.optString(iso, iso)
                    val label = "$iso — $name"
                    labels.add(label)
                    map[label] = iso
                }
                isoByLabel = map

                val adapter = ArrayAdapter(this@OfflineDataActivity, android.R.layout.simple_dropdown_item_1line, labels)
                binding.inputCountry.setAdapter(adapter)
                if (labels.isNotEmpty()) {
                    binding.inputCountry.setText(labels[0], false)
                    refreshCountrySummary()
                }
            } catch (e: PyException) {
                toast("Could not load offline country list: ${cleanErrorMessage(e.message)}")
            }
        }
    }

    private fun selectedIso(): String? {
        val label = binding.inputCountry.text?.toString()?.trim().orEmpty()
        return isoByLabel[label]
    }

    private fun refreshCountrySummary() {
        val iso = selectedIso() ?: return
        lifecycleScope.launch {
            try {
                val json = withContext(Dispatchers.IO) { getOfflineCountrySummaryJson(iso) }
                renderCountrySummary(json)
            } catch (e: PyException) {
                binding.textCountrySummary.text = cleanErrorMessage(e.message)
            }
        }
    }

    private fun onDownloadClicked() {
        val iso = selectedIso()
        if (iso == null) {
            toast("Pick a country first")
            return
        }

        setDownloading(true)
        binding.textDownloadResult.text = ""

        statusPollingJob = lifecycleScope.launch {
            while (isActive) {
                try {
                    val statusJson = withContext(Dispatchers.IO) { getOfflineDownloadStatusJson(iso) }
                    renderDownloadStatus(statusJson)
                } catch (e: PyException) {
                    // A transient read failure (e.g. the file is mid-write) is not
                    // worth surfacing to the user every 1.5s -- just skip this tick
                    // and try again on the next poll.
                }
                delay(1500)
            }
        }

        lifecycleScope.launch {
            try {
                val summaryJson = withContext(Dispatchers.Default) { runCountryDownloadJson(iso) }
                statusPollingJob?.cancel()
                // One final read so the progress bar/status text reflect the real
                // completed state, not whatever the last poll tick happened to catch.
                val finalStatusJson = withContext(Dispatchers.IO) { getOfflineDownloadStatusJson(iso) }
                renderDownloadStatus(finalStatusJson)
                renderDownloadSummary(summaryJson)
                refreshCountrySummary()
            } catch (e: PyException) {
                statusPollingJob?.cancel()
                binding.textDownloadResult.text = cleanErrorMessage(e.message)
            } finally {
                setDownloading(false)
            }
        }
    }

    // -- Chaquopy calls (must run off the main thread -- callers above already do) --

    private fun listOfflineCountriesJson(): String {
        val module = python.getModule("offline_download_runner")
        return module.callAttr("list_offline_countries_json").toString()
    }

    private fun getOfflineCountrySummaryJson(iso: String): String {
        val module = python.getModule("offline_download_runner")
        return module.callAttr("get_offline_country_summary_json", offlineDataRoot, iso).toString()
    }

    private fun getOfflineDownloadStatusJson(iso: String): String {
        val module = python.getModule("offline_download_runner")
        return module.callAttr("get_offline_download_status_json", offlineDataRoot, iso).toString()
    }

    private fun runCountryDownloadJson(iso: String): String {
        val module = python.getModule("offline_download_runner")
        return module.callAttr("run_country_download_json", offlineDataRoot, iso).toString()
    }

    // -- Rendering (offline download) --

    private fun renderCountrySummary(json: String) {
        val record = JSONObject(json)
        val name = record.optString("country_name", record.optString("country_iso", "?"))
        val dem = record.optJSONObject("dem")
        val ndvi = record.optJSONObject("ndvi")
        val sb = StringBuilder()
        sb.append(name).append(" -- already downloaded:\n")
        sb.append("  DEM tiles: ").append(dem?.optInt("total", 0) ?: 0)
        appendByStatus(sb, dem?.optJSONObject("by_status"))
        sb.append("\n  NDVI cells: ").append(ndvi?.optInt("total", 0) ?: 0)
        appendByStatus(sb, ndvi?.optJSONObject("by_status"))
        binding.textCountrySummary.text = sb.toString()
    }

    private fun appendByStatus(sb: StringBuilder, byStatus: JSONObject?) {
        if (byStatus == null || byStatus.length() == 0) return
        sb.append("  (")
        val keys = byStatus.keys()
        val parts = mutableListOf<String>()
        while (keys.hasNext()) {
            val k = keys.next()
            parts.add("$k=${byStatus.optInt(k, 0)}")
        }
        sb.append(parts.joinToString(", ")).append(")")
    }

    private fun renderDownloadStatus(json: String) {
        val status = JSONObject(json)
        val phase = status.optString("phase", "?")
        val done = status.optInt("done", 0)
        val total = status.optInt("total", 0)
        val detail = status.optString("detail", "")

        if (total > 0) {
            binding.progressBarOffline.max = total
            binding.progressBarOffline.progress = done
        }
        binding.textDownloadStatus.text = if (total > 0) {
            "$phase: $done / $total   $detail"
        } else {
            "$phase   $detail"
        }
    }

    private fun renderDownloadSummary(json: String) {
        val record = JSONObject(json)
        val sb = StringBuilder()
        sb.append("Download complete for ").append(record.optString("country_iso", "?")).append(":\n\n")
        sb.append("DEM tiles: ").append(record.optInt("dem_total", 0)).append("\n")
        appendByStatusBlock(sb, record.optJSONObject("dem_by_status"))
        sb.append("\nNDVI cells: ").append(record.optInt("ndvi_total", 0)).append("\n")
        appendByStatusBlock(sb, record.optJSONObject("ndvi_by_status"))
        binding.textDownloadResult.text = sb.toString()
    }

    private fun appendByStatusBlock(sb: StringBuilder, byStatus: JSONObject?) {
        if (byStatus == null) return
        val keys = byStatus.keys()
        while (keys.hasNext()) {
            val k = keys.next()
            sb.append("  ").append(k).append(": ").append(byStatus.optInt(k, 0)).append("\n")
        }
    }

    private fun setDownloading(downloading: Boolean) {
        binding.buttonDownload.isEnabled = !downloading
        binding.progressBarOffline.visibility = if (downloading) View.VISIBLE else View.GONE
        if (downloading) {
            binding.textDownloadStatus.text = "starting…"
        }
    }

    // -- Drive backup: interactive consent --

    /**
     * Requests the drive.file scope. If the user has never granted it
     * before, Google returns a PendingIntent that has to be launched from
     * an Activity (never possible from DriveBackupWorker itself, since a
     * background Worker has no UI) -- that's what driveConsentLauncher is
     * for. If access was already granted in a previous session,
     * hasResolution() is false and this completes immediately with no UI
     * at all, matching Google's documented silent-reauthorization
     * behavior (the same behavior DriveBackupWorker.kt's own
     * getAccessTokenOrNull() already relies on).
     */
    private fun requestDriveAuthorization() {
        binding.textDriveStatus.text = "Requesting Google Drive access…"
        val request = AuthorizationRequest.Builder()
            .setRequestedScopes(listOf(driveFileScope))
            .build()
        Identity.getAuthorizationClient(this)
            .authorize(request)
            .addOnSuccessListener { authorizationResult ->
                if (authorizationResult.hasResolution()) {
                    try {
                        val intentSenderRequest = IntentSenderRequest.Builder(
                            authorizationResult.pendingIntent!!.intentSender
                        ).build()
                        driveConsentLauncher.launch(intentSenderRequest)
                    } catch (e: IntentSender.SendIntentException) {
                        binding.textDriveStatus.text = "Couldn't open the Drive consent screen: ${e.message}"
                    }
                } else {
                    onDriveAuthorizationResult(authorizationResult.accessToken != null)
                }
            }
            .addOnFailureListener { e ->
                binding.textDriveStatus.text = "Drive authorization request failed: ${e.message}"
            }
    }

    private fun onDriveAuthorizationResult(granted: Boolean) {
        binding.textDriveStatus.text = if (granted) {
            "Google Drive access granted. You can now back up a downloaded country's data."
        } else {
            "Drive access was not granted."
        }
    }

    // -- Drive backup: running DriveBackupWorker + observing its progress --

    /**
     * Enqueues DriveBackupWorker for the selected country and observes its
     * WorkInfo. If drive.file access was never granted (or the earlier
     * silent/interactive flow above never ran), DriveBackupWorker's own
     * getAccessTokenOrNull() will fail informatively -- that real error
     * message (its KEY_ERROR output data) is surfaced here as-is rather
     * than guessed at or pre-checked, matching how download errors from
     * the Python side are already surfaced via cleanErrorMessage() above.
     */
    private fun startDriveBackup() {
        val iso = selectedIso()
        if (iso == null) {
            toast("Pick a country first")
            return
        }

        binding.progressBarDrive.visibility = View.VISIBLE
        binding.progressBarDrive.isIndeterminate = true
        binding.textDriveStatus.text = "starting backup…"

        val request = OneTimeWorkRequestBuilder<DriveBackupWorker>()
            .setInputData(workDataOf(DriveBackupWorker.KEY_COUNTRY_ISO to iso))
            .build()

        val workManager = WorkManager.getInstance(applicationContext)
        workManager.enqueue(request)
        workManager.getWorkInfoByIdLiveData(request.id).observe(this) { info ->
            renderDriveWorkInfo(info)
        }
    }

    private fun renderDriveWorkInfo(info: WorkInfo?) {
        if (info == null) return
        when (info.state) {
            WorkInfo.State.RUNNING -> {
                val phase = info.progress.getString("phase") ?: "uploading"
                val done = info.progress.getInt("done", 0)
                val total = info.progress.getInt("total", 0)
                val detail = info.progress.getString("detail") ?: ""
                binding.progressBarDrive.visibility = View.VISIBLE
                binding.progressBarDrive.isIndeterminate = false
                binding.textDriveStatus.text = if (total > 0) {
                    binding.progressBarDrive.max = total
                    binding.progressBarDrive.progress = done
                    "$phase: $done / $total   $detail"
                } else {
                    "$phase   $detail"
                }
            }
            WorkInfo.State.SUCCEEDED -> {
                binding.progressBarDrive.visibility = View.GONE
                val uploaded = info.outputData.getInt(DriveBackupWorker.KEY_UPLOADED_COUNT, 0)
                val skipped = info.outputData.getInt(DriveBackupWorker.KEY_SKIPPED_COUNT, 0)
                val failed = info.outputData.getInt(DriveBackupWorker.KEY_FAILED_COUNT, 0)
                binding.textDriveStatus.text =
                    "Backup finished: $uploaded uploaded, $skipped already up to date, $failed failed."
            }
            WorkInfo.State.FAILED -> {
                binding.progressBarDrive.visibility = View.GONE
                binding.textDriveStatus.text =
                    info.outputData.getString(DriveBackupWorker.KEY_ERROR) ?: "Backup failed."
            }
            WorkInfo.State.CANCELLED -> {
                binding.progressBarDrive.visibility = View.GONE
                binding.textDriveStatus.text = "Backup was cancelled."
            }
            else -> {
                // ENQUEUED / BLOCKED -- nothing new to show the user yet.
            }
        }
    }

    /** Same pattern as MainActivity.cleanErrorMessage() -- Chaquopy's
     * PyException.message is typically the Python exception plus a full
     * traceback; keep just the first line for the UI. */
    private fun cleanErrorMessage(raw: String?): String {
        if (raw.isNullOrBlank()) return "Unknown Python error"
        return raw.substringBefore("\n\n").trim()
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
