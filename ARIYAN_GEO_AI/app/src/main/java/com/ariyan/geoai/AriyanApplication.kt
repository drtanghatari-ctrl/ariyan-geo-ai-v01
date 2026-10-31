package com.ariyan.geoai

import android.app.Application
import android.os.Build
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Starts the embedded Python interpreter exactly once, at process start.
 * Python.start() is idempotent-guarded by isStarted() so this is safe
 * even if something else tries to start it again later.
 *
 * crash-v1 (2026-10-31): the phone has no logcat access, so when the app
 * closes on an unexpected error it first writes the full error and stack
 * trace to offline_data/crash_reports/crash_<UTC time>.txt (or the app's own
 * files folder if shared storage is not writable), then lets Android close the
 * app as usual. Nothing else is recorded: no personal data, no keys.
 */
class AriyanApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        installCrashRecorder()
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
    }

    private fun installCrashRecorder() {
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            runCatching { writeReport(thread, error) }
            if (previous != null) previous.uncaughtException(thread, error)
            else { android.os.Process.killProcess(android.os.Process.myPid()); System.exit(10) }
        }
    }

    private fun writeReport(thread: Thread, error: Throwable) {
        val fmt = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }
        val stamp = fmt.format(Date())
        val sw = StringWriter()
        error.printStackTrace(PrintWriter(sw))
        val text = buildString {
            append("ARIYAN GEO AI crash report (crash-v1)\n")
            append("UTC: ").append(stamp).append('\n')
            append("Thread: ").append(thread.name).append('\n')
            append("Android ").append(Build.VERSION.RELEASE).append(" (SDK ").append(Build.VERSION.SDK_INT).append("), ")
            append(Build.MANUFACTURER).append(' ').append(Build.MODEL).append('\n')
            append("Error: ").append(error.toString()).append("\n\n")
            append(sw.toString())
        }
        val dirs = listOf(File(ExternalStorageAccess.offlineDataRoot(), "crash_reports"), File(filesDir, "crash_reports"))
        for (dir in dirs) {
            val ok = runCatching {
                dir.mkdirs()
                File(dir, "crash_$stamp.txt").writeText(text)
            }.isSuccess
            if (ok) break
        }
    }
}
