package com.ariyan.geoai

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import com.chaquo.python.Kwarg
import com.chaquo.python.Python
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * WideAreaSearchService -- runs wide_area_search_mobile.run_wide_area_search_job()
 * as a real foreground service, independent of WideAreaSearchActivity's
 * lifecycle -- MIRRORS OfflineDownloadService.kt structurally, line for
 * line in shape (same companion-object constants pattern, same
 * startForeground/wake-lock/thread/broadcast structure, same
 * catch-everything philosophy) -- this project already has one real,
 * on-device-intended foreground service precedent; this is deliberately
 * NOT a second, differently-shaped implementation of the same idea.
 *
 * WHY A FOREGROUND SERVICE, NOT JUST A COROUTINE IN THE ACTIVITY: a
 * real wide-area search job can mean dozens to hundreds of real HTTP
 * calls across many tiles (see investigation_multi_mobile.py's own
 * REAL NETWORK-COST NOTE) -- easily a multi-hour run. Doze/App Standby
 * cuts a plain background process's network access entirely once the
 * screen locks or the device goes idle (the exact real symptom
 * OfflineDownloadService.kt's own class doc already documents hitting
 * for the offline-data download case); a foreground service with its
 * own notification is the real, confirmed way around that on this
 * platform, not a theoretical justification.
 *
 * RESUMABILITY LIVES IN THE PYTHON LAYER, NOT HERE: this service does
 * not itself track which tiles are done -- it simply calls
 * run_wide_area_search_job(data_root, job_id, ...) once per start, and
 * that function's own real per-tile status column in
 * wide_area_search_tile (see grand_project_db.py) is what makes a
 * second call with the same job_id continue from wherever the first
 * one left off (e.g. if this service was killed mid-run and the user
 * taps Resume in WideAreaSearchActivity later). This service is
 * therefore safe to start again for the same job_id at any time.
 *
 * PASS 2 (REFINEMENT) USES THIS SAME SERVICE: when EXTRA_REFINE_TOP_N is
 * greater than 0, this start runs grand_project_refinement.
 * run_refinement_pass_json() for that job instead of the wide-area search
 * -- a full-evidence re-investigation of the top N Pass 1 candidates.
 * Sharing the service keeps the one-job-at-a-time rule (one shared
 * OpenTopography quota and Copernicus token), the foreground
 * notification and the wake lock exactly as they already are. The
 * finished/failed broadcasts carry EXTRA_IS_REFINEMENT so the Activity
 * can word its message for a refinement rather than for a search.
 *
 * LAND-COVER FILTER: a Pass 2 start also carries EXTRA_REFINE_SKIP_FLAGGED
 * (default true when absent). It is passed to run_refinement_pass_json as
 * skip_flagged, so the run leaves out exactly the candidates the
 * confirmation dialog said it would (trees / buildings / open water, see
 * land_cover_flags.py). The service itself does no land-cover work.
 *
 * SELECTED CANDIDATES (2026-09-23): when EXTRA_REFINE_CANDIDATE_IDS is a
 * non-blank string (ids or unique prefixes, one per line), this start runs
 * grand_project_refinement.run_selected_refinement_json() instead: exactly
 * those candidates of this job, repeats allowed, with
 * EXTRA_REFINE_REQUIRE_LIVE_DEM (default true) deciding whether a candidate
 * whose DEM would come from the offline library is discarded and the pass
 * stopped. It takes precedence over EXTRA_REFINE_TOP_N if both are given.
 */
class WideAreaSearchService : Service() {

    companion object {
        const val EXTRA_JOB_ID = "job_id"
        const val EXTRA_DATA_ROOT = "data_root"
        const val EXTRA_RADIUS_M = "radius_m"
        const val EXTRA_GRID_SIZE = "grid_size"
        const val EXTRA_API_KEY = "api_key"
        const val EXTRA_DEMTYPE = "demtype"
        const val EXTRA_NDVI_CLIENT_ID = "ndvi_client_id"
        const val EXTRA_NDVI_CLIENT_SECRET = "ndvi_client_secret"

        // true = run this start as a DEM-ONLY SWEEP (see
        // wide_area_search_mobile._run_wide_area_search_job_impl()'s own
        // DEM-ONLY SWEEP note): no Copernicus calls and no Detection
        // Stability re-fetches. Chosen per START in WideAreaSearchActivity,
        // not stored on the job; absent/false = the normal full run.
        const val EXTRA_DEM_ONLY = "dem_only"

        // true (only together with EXTRA_DEM_ONLY) = read each tile's DEM
        // from the offline library FIRST and skip the second-DEM cross-check
        // (see wide_area_search_mobile's OFFLINE-FIRST DEM note). Chosen per
        // START in WideAreaSearchActivity's run-mode dialog, never stored on
        // the job; absent/false = the normal online-first behaviour.
        const val EXTRA_DEM_OFFLINE_FIRST = "dem_offline_first"

        // > 0 = run PASS 2 (grand_project_refinement) on the top N Pass 1
        // candidates of this job instead of the wide-area search; absent/0
        // = the normal search start. See the class doc.
        const val EXTRA_REFINE_TOP_N = "refine_top_n"

        // Only meaningful together with EXTRA_REFINE_TOP_N. true (also the
        // value when absent) = Pass 2 leaves out candidates that
        // land_cover_flags has flagged as trees / buildings / open water;
        // false = include them. Chosen per START in the Activity's Pass 2
        // confirmation dialog.
        const val EXTRA_REFINE_SKIP_FLAGGED = "refine_skip_flagged"

        // Non-blank = run PASS 2 on exactly these candidates of this job
        // (newline-separated ids or unique prefixes). See the class doc.
        const val EXTRA_REFINE_CANDIDATE_IDS = "refine_candidate_ids"

        // Only with EXTRA_REFINE_CANDIDATE_IDS. true (also when absent) =
        // never record a refinement whose primary DEM came from the offline
        // library; stop the pass instead.
        const val EXTRA_REFINE_REQUIRE_LIVE_DEM = "refine_require_live_dem"

        // Set on the finished/failed broadcasts of a Pass 2 run so the
        // Activity words its message for a refinement.
        const val EXTRA_IS_REFINEMENT = "is_refinement"

        const val ACTION_JOB_FINISHED = "com.ariyan.geoai.WIDE_AREA_SEARCH_FINISHED"
        const val ACTION_JOB_FAILED = "com.ariyan.geoai.WIDE_AREA_SEARCH_FAILED"
        const val EXTRA_RESULT_JSON = "result_json"
        const val EXTRA_ERROR_MESSAGE = "error_message"

        private const val CHANNEL_ID = "wide_area_search"
        private const val NOTIFICATION_ID = 4301

        // Mirrors OfflineDownloadService's own single-run-at-a-time
        // design -- one wide-area search job runs at a time; a second
        // start request while one is already running is refused (the
        // user should let the current job finish, or explicitly stop
        // it, rather than two jobs racing each other's network
        // calls/credentials).
        private val running = AtomicBoolean(false)
        val isRunning: Boolean get() = running.get()
    }

    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val jobId = intent?.getStringExtra(EXTRA_JOB_ID)
        val dataRoot = intent?.getStringExtra(EXTRA_DATA_ROOT)

        if (jobId == null || dataRoot == null) {
            reportFailure(null, "Service started without job_id/data_root extras -- this should not happen from the UI.")
            stopSelf(startId)
            return START_NOT_STICKY
        }

        // 0.0 (the default) means "derive the analysis radius from this job's own
        // tile size" -- wide_area_search_mobile.run_wide_area_search_job() treats
        // any radius <= 0 that way (see derive_analysis_window()).
        // Nothing in the UI passes EXTRA_RADIUS_M today; a positive value
        // would override it.
        val radiusM = intent.getDoubleExtra(EXTRA_RADIUS_M, 0.0)
        // 0 (the default) means "derive the DEM grid from this job's own tile size" --
        // wide_area_search_mobile.derive_analysis_window() sizes radius and grid together
        // so the detector's usable interior covers each whole tile. Nothing in the UI
        // passes EXTRA_GRID_SIZE today; a positive value would override it.
        val gridSize = intent.getIntExtra(EXTRA_GRID_SIZE, 0)
        val apiKey = intent.getStringExtra(EXTRA_API_KEY) ?: ""
        val demType = intent.getStringExtra(EXTRA_DEMTYPE) ?: "SRTMGL1"
        val ndviClientId = intent.getStringExtra(EXTRA_NDVI_CLIENT_ID) ?: ""
        val ndviClientSecret = intent.getStringExtra(EXTRA_NDVI_CLIENT_SECRET) ?: ""
        val demOnly = intent.getBooleanExtra(EXTRA_DEM_ONLY, false)
        val demOfflineFirst = demOnly && intent.getBooleanExtra(EXTRA_DEM_OFFLINE_FIRST, false)
        val refineTopN = intent.getIntExtra(EXTRA_REFINE_TOP_N, 0)
        val refineSkipFlagged = intent.getBooleanExtra(EXTRA_REFINE_SKIP_FLAGGED, true)
        val refineCandidateIds = intent.getStringExtra(EXTRA_REFINE_CANDIDATE_IDS)?.trim().orEmpty()
        val refineRequireLiveDem = intent.getBooleanExtra(EXTRA_REFINE_REQUIRE_LIVE_DEM, true)
        val isSelectedRefinement = refineCandidateIds.isNotEmpty()
        val isRefinement = refineTopN > 0 || isSelectedRefinement
        val selectedCount = refineCandidateIds.lines().count { it.isNotBlank() }

        if (!running.compareAndSet(false, true)) {
            reportFailure(jobId, "Another wide-area search job is already running -- wait for it to finish, or stop it first.", isRefinement)
            stopSelf(startId)
            return START_NOT_STICKY
        }

        // Same widened try/catch as OfflineDownloadService.kt's own
        // startForeground/wake-lock block, for the same real reason:
        // this project has no working ADB/logcat path (see the
        // project-wide network/environment notes), so a silent failure
        // here would be invisible to the user -- every failure mode is
        // routed through the same broadcast every other failure uses.
        try {
            startForeground(
                NOTIFICATION_ID,
                buildNotification(
                    if (isSelectedRefinement) "Starting Pass 2 refinement of $selectedCount selected candidate(s)…"
                    else if (isRefinement) "Starting Pass 2 refinement of the top $refineTopN candidates…"
                    else if (demOfflineFirst) "Starting wide-area search (DEM-only sweep, offline library first)…"
                    else if (demOnly) "Starting wide-area search (DEM-only sweep)…"
                    else "Starting wide-area search…"
                )
            )
            acquireWakeLock()
        } catch (t: Throwable) {
            Log.e("WideAreaSearchService", "startForeground/acquireWakeLock failed for job $jobId", t)
            running.set(false)
            reportFailure(jobId, "Foreground-service start failed: ${t.javaClass.simpleName}: ${t.message}\n${t.stackTraceToString().take(1500)}", isRefinement)
            stopSelf(startId)
            return START_NOT_STICKY
        }

        thread(name = "wide-area-search-$jobId") {
            try {
                val python = Python.getInstance()
                val resultJson = if (isSelectedRefinement) {
                    // PASS 2, SELECTED: exactly the named candidates of this
                    // job (resolved in Python against this job only).
                    python.getModule("grand_project_refinement").callAttr(
                        "run_selected_refinement_json",
                        dataRoot, jobId, refineCandidateIds,
                        Kwarg("api_key", apiKey),
                        Kwarg("demtype", demType),
                        Kwarg("ndvi_client_id", ndviClientId),
                        Kwarg("ndvi_client_secret", ndviClientSecret),
                        Kwarg("require_live_dem", refineRequireLiveDem),
                    ).toString()
                } else if (isRefinement) {
                    // PASS 2: full-evidence refinement of the top N Pass 1
                    // candidates. One candidate failing never fails the pass
                    // (handled in Python); an unknown job id raises, and is
                    // reported by the catch below.
                    python.getModule("grand_project_refinement").callAttr(
                        "run_refinement_pass_json",
                        dataRoot, jobId,
                        Kwarg("n", refineTopN),
                        Kwarg("api_key", apiKey),
                        Kwarg("demtype", demType),
                        Kwarg("ndvi_client_id", ndviClientId),
                        Kwarg("ndvi_client_secret", ndviClientSecret),
                        Kwarg("skip_flagged", refineSkipFlagged),
                    ).toString()
                } else {
                    python.getModule("wide_area_search_mobile").callAttr(
                        "run_wide_area_search_job",
                        dataRoot, jobId,
                        Kwarg("radius_m", radiusM),
                        Kwarg("grid_size", gridSize),
                        Kwarg("api_key", apiKey),
                        Kwarg("demtype", demType),
                        Kwarg("ndvi_client_id", ndviClientId),
                        Kwarg("ndvi_client_secret", ndviClientSecret),
                        Kwarg("dem_only", demOnly),
                        Kwarg("dem_offline_first", demOfflineFirst),
                    ).toString()
                }
                sendBroadcast(Intent(ACTION_JOB_FINISHED).apply {
                    setPackage(packageName)
                    putExtra(EXTRA_JOB_ID, jobId)
                    putExtra(EXTRA_RESULT_JSON, resultJson)
                    putExtra(EXTRA_IS_REFINEMENT, isRefinement)
                })
            } catch (t: Throwable) {
                // Widened to Throwable, same reasoning and same real
                // precedent as OfflineDownloadService.kt's own catch
                // block -- a crash anywhere in this call (Python not
                // yet initialized, a Chaquopy-internal error that
                // isn't a PyException, an unexpected Kotlin exception)
                // must still be visible to the user, not just kill
                // this thread silently with the notification stuck.
                Log.e("WideAreaSearchService", "Wide-area search job $jobId failed (refinement=$isRefinement)", t)
                reportFailure(jobId, "${t.javaClass.simpleName}: ${t.message}\n${t.stackTraceToString().take(1500)}", isRefinement)
            } finally {
                running.set(false)
                releaseWakeLock()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf(startId)
            }
        }

        return START_NOT_STICKY
    }

    private fun reportFailure(jobId: String?, message: String, isRefinement: Boolean = false) {
        try {
            sendBroadcast(Intent(ACTION_JOB_FAILED).apply {
                setPackage(packageName)
                if (jobId != null) putExtra(EXTRA_JOB_ID, jobId)
                putExtra(EXTRA_ERROR_MESSAGE, message)
                putExtra(EXTRA_IS_REFINEMENT, isRefinement)
            })
        } catch (t: Throwable) {
            // Broadcasting itself should never realistically throw,
            // but this is a last-resort diagnostic path -- never let
            // the reporting mechanism itself crash silently.
            Log.e("WideAreaSearchService", "Failed to broadcast failure", t)
        }
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        Log.w("WideAreaSearchService", "System-imposed foreground service timeout hit for startId=$startId")
    }

    override fun onDestroy() {
        super.onDestroy()
        releaseWakeLock()
    }

    private fun acquireWakeLock() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ariyangeoai:wide-area-search")
        wakeLock?.acquire(12 * 60 * 60 * 1000L)
    }

    private fun releaseWakeLock() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    private fun buildNotification(text: String): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Wide-area search", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val openIntent = PendingIntent.getActivity(
            this, 0, Intent(this, WideAreaSearchActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("ARIYAN GEO AI — wide-area search")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setOngoing(true)
            .setContentIntent(openIntent)
            .build()
    }
}
