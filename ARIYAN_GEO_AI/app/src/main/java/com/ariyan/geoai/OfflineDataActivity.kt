package com.ariyan.geoai

import android.content.ActivityNotFoundException
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.ariyan.geoai.databinding.ActivityOfflineDataBinding
import com.chaquo.python.PyException
import com.chaquo.python.Python
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * OfflineDataActivity — lets the user download a country's offline DEM +
 * NDVI package (see offline_download_runner.py / offline_data_manager.py
 * / offline_country_registry.py) so an investigation can still run with
 * no network access.
 *
 * FOREGROUND-SERVICE REDESIGN (2026-09-04) -- the actual download is now
 * kicked off via OfflineDownloadService.kt, not run directly here. See
 * that file's class doc for why: this Activity's coroutine had no
 * exemption from Doze/App Standby, and a real on-device Iran run showed
 * the download's network access getting cut off entirely for extended
 * stretches once the screen locked -- even with offline_data_manager.py's
 * own retry-with-backoff already in place. Progress polling
 * (offline_status.json, below) is UNCHANGED -- it's file-based and
 * doesn't care whether the Service or this Activity's own coroutine is
 * the one writing that file.
 *
 * REAL-SHARED-STORAGE REDESIGN (earlier session) -- downloads save to
 * real shared storage (/storage/emulated/0/ARIYAN_GEO_AI/offline_data),
 * gated on the MANAGE_EXTERNAL_STORAGE / WRITE_EXTERNAL_STORAGE
 * permission flow below. See ExternalStorageAccess.kt.
 *
 * HONEST STATE: the foreground-service change above has not yet been
 * run on-device. Everything else in this file (storage-access flow,
 * country list, manifest summary rendering) has been on-device confirmed
 * previously and is unchanged here.
 */
class OfflineDataActivity : AppCompatActivity() {

    private lateinit var binding: ActivityOfflineDataBinding
    private lateinit var python: Python

    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }

    private var isoByLabel: Map<String, String> = emptyMap()
    private var statusPollingJob: Job? = null

    // ISO of the country currently downloading, if any -- used by
    // onResume()/the broadcast receiver to keep polling the right file
    // across an Activity recreation while OfflineDownloadService keeps
    // running underneath it. In-memory only -- does not survive true
    // process death; see this file's class doc HONEST STATE note if
    // that gap ever matters in practice.
    private var downloadingIso: String? = null

    private val manageStorageSettingsLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { refreshStorageAccessUi() }

    private val storagePermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { refreshStorageAccessUi() }

    // POST_NOTIFICATIONS (API 33+) -- best-effort. If denied, the
    // foreground service still runs correctly, it just won't show a
    // visible progress notification.
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* no-op either way */ }

    private val downloadResultReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val iso = downloadingIso ?: return
            when (intent.action) {
                OfflineDownloadService.ACTION_DOWNLOAD_FINISHED -> {
                    val resultJson = intent.getStringExtra(OfflineDownloadService.EXTRA_RESULT_JSON) ?: return
                    statusPollingJob?.cancel()
                    lifecycleScope.launch {
                        val finalStatusJson = withContext(Dispatchers.IO) { getOfflineDownloadStatusJson(iso) }
                        renderDownloadStatus(finalStatusJson)
                        renderDownloadSummary(resultJson)
                        refreshCountrySummary()
                        setDownloading(false)
                    }
                }
                OfflineDownloadService.ACTION_DOWNLOAD_FAILED -> {
                    val err = intent.getStringExtra(OfflineDownloadService.EXTRA_ERROR_MESSAGE) ?: "Unknown error"
                    statusPollingJob?.cancel()
                    binding.textDownloadResult.text = cleanErrorMessage(err)
                    setDownloading(false)
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOfflineDataBinding.inflate(layoutInflater)
        setContentView(binding.root)

        python = Python.getInstance()

        val filter = IntentFilter().apply {
            addAction(OfflineDownloadService.ACTION_DOWNLOAD_FINISHED)
            addAction(OfflineDownloadService.ACTION_DOWNLOAD_FAILED)
        }
        ContextCompat.registerReceiver(this, downloadResultReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }

        loadCountryList()
        refreshStorageAccessUi()

        binding.buttonGrantStorageAccess.setOnClickListener { requestStorageAccess() }
        binding.buttonRefreshStatus.setOnClickListener { refreshCountrySummary() }
        binding.buttonDownload.setOnClickListener { onDownloadClicked() }
    }

    override fun onResume() {
        super.onResume()
        refreshStorageAccessUi()

        // Service kept running through an Activity recreation (or this
        // Activity instance just never had a poller for it) -- reattach.
        val iso = downloadingIso
        if (iso != null && OfflineDownloadService.isRunning && statusPollingJob?.isActive != true) {
            setDownloading(true)
            startStatusPolling(iso)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        statusPollingJob?.cancel()
        unregisterReceiver(downloadResultReceiver)
    }

    // -- Storage access --

    private fun requestStorageAccess() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                manageStorageSettingsLauncher.launch(ExternalStorageAccess.manageAllFilesSettingsIntent(this))
            } catch (e: ActivityNotFoundException) {
                manageStorageSettingsLauncher.launch(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
            }
        } else {
            storagePermissionLauncher.launch(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
        }
    }

    private fun refreshStorageAccessUi() {
        val granted = ExternalStorageAccess.isGranted(this)
        binding.buttonGrantStorageAccess.visibility = if (granted) View.GONE else View.VISIBLE
        binding.textStorageAccessStatus.text = if (granted) {
            "Storage access granted. Downloads are saved to:\n${ExternalStorageAccess.offlineDataRoot().absolutePath}"
        } else {
            "Not granted yet -- downloads are disabled until you grant storage access above."
        }
        binding.buttonDownload.isEnabled = granted && !OfflineDownloadService.isRunning
    }

    // -- Country list / summary --

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
        if (!ExternalStorageAccess.isGranted(this)) {
            toast("Grant storage access above first")
            return
        }
        val iso = selectedIso()
        if (iso == null) {
            toast("Pick a country first")
            return
        }
        if (OfflineDownloadService.isRunning) {
            toast("A download is already running — wait for it to finish.")
            return
        }

        downloadingIso = iso
        setDownloading(true)
        binding.textDownloadResult.text = ""
        startStatusPolling(iso)

        val serviceIntent = Intent(this, OfflineDownloadService::class.java).apply {
            putExtra(OfflineDownloadService.EXTRA_COUNTRY_ISO, iso)
            putExtra(OfflineDownloadService.EXTRA_OFFLINE_ROOT, offlineDataRoot)
        }
        ContextCompat.startForegroundService(this, serviceIntent)
    }

    private fun startStatusPolling(iso: String) {
        statusPollingJob = lifecycleScope.launch {
            while (isActive) {
                try {
                    val statusJson = withContext(Dispatchers.IO) { getOfflineDownloadStatusJson(iso) }
                    renderDownloadStatus(statusJson)
                } catch (e: PyException) {
                    // Transient read failure -- skip this tick, try again next poll.
                }
                delay(1500)
            }
        }
    }

    // -- Chaquopy calls (must run off the main thread -- callers above already do) --

    p