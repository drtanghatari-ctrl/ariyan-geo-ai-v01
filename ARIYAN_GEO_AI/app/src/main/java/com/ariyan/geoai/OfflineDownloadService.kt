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
import com.chaquo.python.Python
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * OfflineDownloadService — runs run_country_download_json() as a real
 * foreground service, independent of OfflineDataActivity's lifecycle.
 * See earlier class doc history for the Doze/App-Standby rationale.
 *
 * DIAGNOSTIC WIDENING (2026-09-04, this session) -- a real on-device test
 * showed NOTHING happening at all after tapping Download: no persistent
 * notification, no progress, no visible crash dialog. The previous
 * version of this file only caught PyException inside the download
 * thread -- any OTHER failure (e.g. buildNotification()/startForeground()
 * itself throwing, acquireWakeLock() throwing, Python.getInstance()
 * throwing something that isn't a PyException) would fail completely
 * silently: no broadcast, no log the user could see, nothing. The user
 * has no working ADB path (Google's official platform-tools download is
 * blocked by sanctions on their network), so logcat-based debugging is
 * not available -- this version instead catches EVERYTHING, at every
 * stage, and routes it through the SAME ACTION_DOWNLOAD_FAILED broadcast
 * OfflineDataActivity.kt already displays in textDownloadResult. No new
 * UI, no new permissions, no external tools needed to see what actually
 * went wrong.
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
            reportFailure("Service started without country/root extras -- this should not happen from the UI.")
            stopSelf(startId)
            return START_NOT_STICKY
        }

        if (!running.compareAndSet(false, true)) {
            stopSelf(startId)
            return START_NOT_STICKY
        }

        // WIDENED (this session): startForeground() and the wake lock
        // used to run with no surrounding try/catch at all. If EITHER
        // threw (e.g. a Samsung/OEM policy silently rejecting the
        // foreground-service promotion, or a notification-channel
        // issue), the Service would die here with zero visible signal
        // to the user -- no crash dialog, no notification, nothing.
        // Now any such failure is reported through the same error path
        // as everything else.
        try {
            startForeground(NOTIFICATION_ID, buildNotification("$iso — starting…"))
            acquireWakeLock()
        } catch (t: Throwable) {
            Log.e("OfflineDownloadService", "startForeground/acquireWakeLock failed for $iso", t)
            running.set(false)
            reportFailure("Foreground-service start failed: ${t.javaClass.simpleName}: ${t.message}\n${t.stackTraceToString().take(1500)}")
            stopSelf(startId)
            return START_NOT_STICKY
        }

        thread(name = "offline-download-$iso") {
            try {
                val python = Python.getInstance()
                val module = python.getModule("offline_download_runner")
                val resultJson = module.callAttr("run_country_download_json", root, iso).toString()
                sendBroadcast(Intent(ACTION_DOWNLOAD_FINISHED).apply {
                    setPackage(packageName)
                    putExtra(EXTRA_RESULT_JSON, resultJson)
                })
            } catch (t: Throwable) {
                // WIDENED (this session): was `catch (e: PyException)` only.
                // Catching Throwable here means a crash ANYWHERE in this
                // block -- Python not yet initialized, a Chaquopy-internal
                // error that isn't a PyException, an unexpected Kotlin
                // exception -- is reported the same way, instead of
                // silently killing this thread with the Service left
                // running indefinitely with its notification stuck.
                Log.e("OfflineDownloadService", "Download failed for $iso", t)
                reportFailure("${t.javaClass.simpleName}: ${t.message}\n${t.stackTraceToString().take(1500)}")
            } finally {
                running.set(false)
                releaseWakeLock()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf(startId)
            }
        }

        return START_NOT_STICKY
    }

    private fun reportFailure(message: String) {
        try {
            sendBroadcast(Intent(ACTION_DOWNLOAD_FAILED).apply {
                setPackage(packageName)
                putExtra(EXTRA_ERROR_MESSAGE, message)
            })
        } catch (t: Throwable) {
            // Broadcasting itself should never realistically throw, but
            // this is a last-resort diagnostic path -- never let the
            // reporting mechanism itself crash silently.
            Log.e("OfflineDownloadService", "Failed to broadcast failure", t)
        }
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        Log.w("OfflineDownloadService", "System-imposed foreground service timeout hit for startId=$startId")
    }

    override fun onDestroy() {
        super.onDestroy()
        releaseWakeLock()
    }

    private fun acquireWakeLock() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ariyangeoai:offline-download")
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
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setOngoing(true)
            .setContentIntent(openIntent)
            .build()
    }
}