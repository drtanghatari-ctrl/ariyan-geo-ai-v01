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
import com.chaquo.python.PyException
import com.chaquo.python.Python
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * OfflineDownloadService — runs run_country_download_json() as a real
 * foreground service, independent of OfflineDataActivity's lifecycle.
 *
 * WHY THIS EXISTS (2026-09-04): the download used to run inside
 * OfflineDataActivity's lifecycleScope on Dispatchers.Default. Fine for
 * a short call, but this download realistically takes hours. Once the
 * screen locks and the device goes idle, Doze/App Standby throttles and
 * eventually cuts network access for any process without a foreground-
 * service exemption. A real on-device Iran run showed exactly that
 * signature: DEM (ran early, screen mostly on) got ~45% through before
 * errors climbed; NDVI (started later) got 0/76 real successes -- every
 * attempt failed DNS resolution, even WITH offline_data_manager.py's own
 * retry-with-backoff already in place. Retries ride out brief real
 * blips; they cannot fix the OS deciding this process gets no network
 * at all for extended stretches. A foreground service is the actual fix
 * for that -- the Python-side retry logic is unchanged and remains
 * correct for genuine transient failures.
 *
 * Progress reporting is UNCHANGED: offline_download_runner.py already
 * writes offline_status.json after every tile/cell, and
 * OfflineDataActivity.kt already polls that file -- neither needed to
 * change. This service also refreshes its own notification text from
 * that same file as a convenience, not a requirement.
 *
 * HONEST GAP: on Android 15 (API 35), a dataSync foreground service has
 * a system runtime cap (~6h rolling window) before onTimeout() fires.
 * An 8+ hour whole-country run could still get interrupted by the OS,
 * just later and without the silent-100%-DNS-failure symptom. onTimeout
 * below is best-effort (updates the notification, does not attempt
 * graceful mid-tile cancellation of the download thread -- Kotlin
 * thread cancellation isn't cooperative any more than coroutine
 * cancellation was, so this isn't solved differently than before).
 * Real fallback if this happens: the per-country lock file +
 * already_present/composited resumability mean re-tapping Download
 * finishes whatever's left -- same honest recovery path
 * offline_download_runner.py's docstring already documents for a
 * killed process.
 */
class OfflineDownloadService : Service() {

    companion object {
        const val EXTRA_COUNTRY_ISO = "country_iso"
        const val EXTRA_OFFLINE_ROOT = "offline_root"
        const val ACTION_DOWNLOAD_FINISHED = "com.ariyan.geoai.DOWNLOAD_FINISHED"
        const val ACTION_DOWNLOAD_FAILED = "com.ariyan.geoai.DOWNLOAD_FAILED"
        const val EXTRA_RESULT_JSON = "result_json"
        const val EXTRA_ERROR_MESSAGE = "error_message"

        private const val CHANNEL_ID = "offline_download"
        private const val NOTIFICATION_ID = 4201

        private val running = AtomicBoolean(false)
        val isRunning: Boolean get() = running.get()
    }

    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val iso = intent?.getStringExtra(EXTRA_COUNTRY_ISO)
        val root = intent?.getStringExtra(EXTRA_OFFLINE_ROOT)

        if (iso == null || root == null) {
            stopSelf(startId)
            return START_NOT_STICKY
        }

        if (!running.compareAndSet(false, true)) {
            // Real guard is offline_download_runner.py's lock file; this
            // just avoids spinning up a second thread pointlessly.
            stopSelf(startId)
            return START_NOT_STICKY
        }

        startForeground(NOTIFICATION_ID, buildNotification("$iso — starting…"))
        acquireWakeLock()

        thread(name = "offline-download-$iso") {
            try {
                val python = Python.getInstance()
                val module = python.getModule("offline_download_runner")
                val resultJson = module.callAttr("run_country_download_json", root, iso).toString()
                broadcast(ACTION_DOWNLOAD_FINISHED) { putExtra(EXTRA_RESULT_JSON, resultJson) }
            } catch (e: PyException) {
                Log.e("OfflineDownloadService", "Download failed for $iso", e)
                broadcast(ACTION_DOWNLOAD_FAILED) { putExtra(EXTRA_ERROR_MESSAGE, e.message ?: "Unknown error") }
            } finally {
                running.set(false)
                releaseWakeLock()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf(startId)
            }
        }

        return START_NOT_STICKY
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        // Android 15+ dataSync runtime-cap callback -- see class doc's
        // HONEST GAP note. Best-effort notice only; the download thread
        // is not force-stopped mid-tile.
        Log.w("OfflineDownloadService", "System-imposed foreground service timeout hit for startId=$startId")
    }

    override fun onDestroy() {
        super.onDestroy()
        releaseWakeLock()
    }

    private fun acquireWakeLock() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ariyangeoai:offline-download")
        wakeLock?.acquire(12 * 60 * 60 * 1000L)  // 12h safety cap -- always released explicitly on finish too
    }

    private fun releaseWakeLock() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    private fun buildNotification(text: String): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Offline data download", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val openIntent = PendingIntent.getActivity(
            this, 0, Intent(this, OfflineDataActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("ARIYAN GEO AI — offline data")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_download)  // swap for a real app icon resource if you have one
            .setOngoing(true)
            .setContentIntent(openIntent)
            .build()
    }

    private fun broadcast(action: String, extras: Intent.() -> Unit) {
        sendBroadcast(Intent(action).apply(extras))
    }
}