package com.ariyan.geoai

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.ForegroundInfo
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * ap-v1 (2026-10-05): drives auto_pipeline.py for one auto run.
 *
 * Each worker execution calls run_slice_json() repeatedly (each slice
 * ~9 min of work, at least one step) while the state is RUNNING. The
 * worker runs as a foreground (dataSync) worker so Doze cannot cut its
 * network, exactly like WideAreaSearchService.
 *
 *  RUNNING  -> keep slicing in this execution
 *  PAUSED   -> re-enqueue itself with initialDelay = retry_after_s
 *              (quota, Copernicus throttle, land-cover offline, a failed
 *              step's back-off). The pause is recorded in the run's
 *              append-only event log by Python, not here.
 *  DONE / FAILED / CANCELLED -> stop (final notification).
 *
 * All state lives in the database (auto_run_event); the worker holds
 * none. If the process dies, WorkManager re-runs the worker and the
 * step machine resumes from its events -- every step is idempotent.
 * Credentials are read from SecureCredentialStore at each execution,
 * never stored in WorkManager's input data.
 */
class AutoPipelineWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    companion object {
        const val KEY_RUN_ID = "run_id"
        const val KEY_DATA_ROOT = "data_root"
        private const val CHANNEL_ID = "auto_pipeline"
        private const val SLICE_BUDGET_S = 540
        private const val TAG = "AutoPipelineWorker"

        fun uniqueName(runId: String) = "auto_run_$runId"

        /** Enqueue (or re-enqueue after a pause) the worker for one run. */
        fun enqueue(context: Context, runId: String, dataRoot: String, delaySeconds: Long = 0) {
            val req = OneTimeWorkRequestBuilder<AutoPipelineWorker>()
                .setInputData(workDataOf(KEY_RUN_ID to runId, KEY_DATA_ROOT to dataRoot))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setInitialDelay(delaySeconds.coerceAtLeast(0), TimeUnit.SECONDS)
                .addTag("auto_pipeline")
                .build()
            WorkManager.getInstance(context)
                .enqueueUniqueWork(uniqueName(runId), ExistingWorkPolicy.REPLACE, req)
        }

        fun cancel(context: Context, runId: String) {
            WorkManager.getInstance(context).cancelUniqueWork(uniqueName(runId))
        }
    }

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val runId = inputData.getString(KEY_RUN_ID) ?: return@withContext Result.failure()
        val dataRoot = inputData.getString(KEY_DATA_ROOT) ?: return@withContext Result.failure()
        try {
            setForeground(foregroundInfo(runId, "Automatic run ${runId.take(8)} working…"))
        } catch (t: Throwable) {
            Log.w(TAG, "setForeground failed; continuing as a normal worker", t)
        }
        if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
        val module = Python.getInstance().getModule("auto_pipeline")
        val creds = SecureCredentialStore(applicationContext)

        while (true) {
            if (isStopped) return@withContext Result.success()
            val text = try {
                module.callAttr(
                    "run_slice_json", dataRoot, runId,
                    creds.openTopographyApiKey, creds.copernicusClientId,
                    creds.copernicusClientSecret, SLICE_BUDGET_S
                ).toString()
            } catch (t: Throwable) {
                Log.e(TAG, "run_slice_json crashed for $runId", t)
                enqueue(applicationContext, runId, dataRoot, 15 * 60)
                return@withContext Result.success()
            }
            val r = JSONObject(text)
            if (r.has("error")) {
                notifyFinal(runId, "Automatic run error: ${r.optString("error")}")
                return@withContext Result.failure()
            }
            val step = r.optString("next_step", "")
            when (r.optString("state")) {
                "RUNNING" -> setProgress(workDataOf("state" to "RUNNING", "step" to step))
                "PAUSED" -> {
                    val wait = r.optLong("retry_after_s", 900)
                    notifyFinal(runId, "Automatic run paused at $step for ~${wait / 60} min: " +
                        r.optString("message", ""))
                    enqueue(applicationContext, runId, dataRoot, wait)
                    return@withContext Result.success()
                }
                "DONE" -> { notifyFinal(runId, "Automatic run ${runId.take(8)} finished."); return@withContext Result.success() }
                "FAILED" -> { notifyFinal(runId, "Automatic run failed at $step: ${r.optString("message")}"); return@withContext Result.success() }
                else -> return@withContext Result.success()   // CANCELLED
            }
        }
        Result.success()
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val m = applicationContext.getSystemService(NotificationManager::class.java)
            m.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Automatic runs", NotificationManager.IMPORTANCE_LOW))
        }
    }

    private fun foregroundInfo(runId: String, text: String): ForegroundInfo {
        ensureChannel()
        val n = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("ARIYAN automatic run")
            .setContentText(text)
            .setOngoing(true)
            .build()
        val id = 4100 + (runId.hashCode() and 0xff)
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(id, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else ForegroundInfo(id, n)
    }

    private fun notifyFinal(runId: String, text: String) {
        try {
            ensureChannel()
            val n = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_sys_download_done)
                .setContentTitle("ARIYAN automatic run")
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .build()
            applicationContext.getSystemService(NotificationManager::class.java)
                .notify(4400 + (runId.hashCode() and 0xff), n)
        } catch (t: Throwable) {
            Log.w(TAG, "notify failed", t)
        }
    }
}
