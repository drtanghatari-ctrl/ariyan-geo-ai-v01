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
        // any radius <= 0 that way (radius = tile_size_m / 2, floored at 500 m).
        // Nothing in the UI passes EXTRA_RADIUS_M today; a positive value
        // would override it.
        val radiusM = intent.getDoubleExtra(EXTRA_RADIUS_M, 0.0)
        val gridSize = intent.getIntExtra(EXTRA_GRID_SIZE, 96)
        val apiKey = intent.getStringExtra(EXTRA_API_KEY) ?: ""
        val demType = intent.getStringExtra(EXTRA_DEMTYPE) ?: "SRTMGL1"
        val ndviClientId = intent.getStringExtra(EXTRA_NDVI_CLIENT_ID) ?: ""
        val ndviClientSecret = intent.getStringExtra(EXTRA_NDVI_CLIENT_SECRET) ?: ""

        if (!running.compareAndSet(false, true)) {
            reportFailure(jobId, "Another wide-area search job is already running -- wait for it to finish, or stop it first.")
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
            startForeground(NOTIFICATION_ID, buildNotification("Starting wide-area search…"))
            acquireWakeLock()
        } catch (t: Throwable) {
            Log.e("WideAreaSearchService", "startForeground/acquireWakeLock failed for job $jobId", t)
            running.set(false)
            reportFailure(jobId, "Foreground-service start failed: ${t.javaClass.simpleName}: ${t.message}\n${t.stackTraceToString().take(1500)}")
            stopSelf(startId)
            return START_NOT_STICKY
        }

        thread(name = "wide-area-search-$jobId") {
            try {
                val python = Python.getInstance()
                val module = python.getModule("wide_area_search_mobile")
                val resultJson = module.callAttr(
                    "run_wide_area_search_job",
                    dataRoot, jobId,
                    Kwarg("radius_m", radiusM),
                    Kwarg("grid_size", gridSize),
                    Kwarg("api_key", apiKey),
                    Kwarg("demtype", demType),
                    Kwarg("ndvi_client_id", ndviClientId),
                    Kwarg("ndvi_client_secret", ndviClientSecret),
                ).toString()
                sendBroadcast(Intent(ACTION_JOB_FINISHED).apply {
                    setPackage(packageName)
                    putExtra(EXTRA_JOB_ID, jobId)
                    putExtra(EXTRA_RESULT_JSON, resultJson)
                })
            } catch (t: Throwable) {
                // Widened to Throwable, same reasoning and same real
                // precedent as OfflineDownloadService.kt's own catch
                // block -- a crash anywhere in this call (Python not
                // yet initialized, a Chaquopy-internal error that
                // isn't a PyException, an unexpected Kotlin exception)
                // must still be visible to the user, not just kill
                // this thread silently with the notification stuck.
                Log.e("WideAreaSearchService", "Wide-area search job $jobId failed", t)
                reportFailure(jobId, "${t.javaClass.simpleName}: ${t.message}\n${t.stackTraceToString().take(1500)}")
            } finally {
                running.set(false)
                releaseWakeLock()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf(startId)
            }
        }

        return START_NOT_STICKY
    }

    private fun reportFailure(jobId: String?, message: String) {
        try {
            sendBroadcast(Intent(ACTION_JOB_FAILED).apply {
                setPackage(packageName)
                if (jobId != null) putExtra(EXTRA_JOB_ID, jobId)
                putExtra(EXTRA_ERROR_MESSAGE, message)
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

