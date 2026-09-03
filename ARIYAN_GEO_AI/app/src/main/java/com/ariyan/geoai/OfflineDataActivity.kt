package com.ariyan.geoai

import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
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
 * REAL-SHARED-STORAGE REDESIGN (this session) -- GOOGLE DRIVE BACKUP
 * REMOVED ENTIRELY. Previously, downloads were saved to app-private
 * internal storage (wiped on uninstall) and a separate Google Drive
 * backup flow (DriveBackupWorker.kt, now deleted) was the only way to
 * make them survive an uninstall or a phone switch -- which required a
 * full Google Cloud project/OAuth client setup. That whole chain is gone
 * now. User's own explicit choice this session: point downloads at REAL
 * SHARED STORAGE instead (see ExternalStorageAccess.kt) -- a real,
 * human-visible folder (/storage/emulated/0/ARIYAN_GEO_AI/offline_data)
 * that survives an uninstall on its own, no cloud account needed. The
 * one real cost: a broad on-device permission (MANAGE_EXTERNAL_STORAGE /
 * "All files access" on Android 11+, plain WRITE_EXTERNAL_STORAGE on
 * Android 10 and below) -- explained plainly to the user before they
 * agreed to it.
 *
 * Calls offline_download_runner.py's thin JSON-string wrapper functions.
 * NEITHER offline_download_runner.py NOR offline_data_manager.py needed
 * to change for this redesign -- they already just take an
 * offline_data_root path string and write there, agnostic to whether
 * that path is app-private or shared storage.
 *
 * PROGRESS: run_country_download_json() is a long, blocking call. A
 * separate lightweight coroutine polls offline_status.json every 1.5s
 * while the download runs, entirely file-based.
 *
 * BUGFIX (2026-09-02) #1 -- CONCURRENT-DOWNLOAD RACE (unchanged from
 * before): isDownloadRunning below is a same-Activity-instance nicety on
 * top of the real fix (a per-country lock file, offline_download_runner.py).
 *
 * HONEST STATE: this Activity's download flow has been run successfully
 * on-device against app-private storage. The new real-shared-storage
 * path (permission grant + writing to /storage/emulated/0/...) has NOT
 * yet been run on-device -- that confirmation is the honest next step
 * once this build compiles clean.
 */
class OfflineDataActivity : AppCompatActivity() {

    private lateinit var binding: ActivityOfflineDataBinding
    private lateinit var python: Python

    // Real shared-storage root (survives uninstall) -- see
    // ExternalStorageAccess.kt. MainActivity.kt uses the exact same call,
    // so both Activities always agree on where offline data actually lives.
    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }

    // Dropdown shows "IR — Iran"; this maps that label back to the real
    // ISO code Python needs, rather than re-parsing the display string.
    private var isoByLabel: Map<String, String> = emptyMap()
    private var statusPollingJob: Job? = null

    // Same-Activity-instance re-entry guard -- see BUGFIX #1 above.
    private var isDownloadRunning = false

    // Storage-access permission request, Android 11+ path (a system
    // Settings screen, not a normal permission dialog). Re-checks the
    // real granted state via refreshStorageAccessUi() on return, since
    // Settings never reports a meaningful result code here -- same
    // "always re-check state yourself" lesson already learned once from
    // the Drive consent flow's null-Intent bug.
    private val manageStorageSettingsLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { refreshStorageAccessUi() }

    // Storage-access permission request, Android 10-and-below path (a
    // normal runtime permission dialog, same mechanism MainActivity.kt
    // already uses for ACCESS_FINE_LOCATION).
    private val storagePermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { refreshStorageAccessUi() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOfflineDataBinding.inflate(layoutInflater)
        setContentView(binding.root)

        python = Python.getInstance()

        loadCountryList()
        refreshStorageAccessUi()

        binding.buttonGrantStorageAccess.setOnClickListener { requestStorageAccess() }
        binding.buttonRefreshStatus.setOnClickListener { refreshCountrySummary() }
        binding.buttonDownload.setOnClickListener { onDownloadClicked() }
    }

    override fun onResume() {
        super.onResume()
        // Catches the case where the user granted access via Settings and
        // came back with the system Back button rather than through the
        // launcher's own callback.
        refreshStorageAccessUi()
    }

    override fun onDestroy() {
        super.onDestroy()
        statusPollingJob?.cancel()
    }

    // -- Storage access --

    private fun requestStorageAccess() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                manageStorageSettingsLauncher.launch(ExternalStorageAccess.manageAllFilesSettingsIntent(this))
            } catch (e: ActivityNotFoundException) {
                // Some OEM builds don't support the per-app deep link --
                // fall back to the generic settings screen.
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
        binding.buttonDownload.isEnabled = granted && !isDownloadRunning
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
        if (isDownloadRunning) {
            toast("A download is already running for this session — wait for it to finish.")
            return
        }

        isDownloadRunning = true
        setDownloading(true)
        binding.textDownloadResult.text = ""

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

        lifecycleScope.launch {
            try {
                val summaryJson = withContext(Dispatchers.Default) { runCountryDownloadJson(iso) }
                statusPollingJob?.cancel()
                val finalStatusJson = withContext(Dispatchers.IO) { getOfflineDownloadStatusJson(iso) }
                renderDownloadStatus(finalStatusJson)
                renderDownloadSummary(summaryJson)
                refreshCountrySummary()
            } catch (e: PyException) {
                statusPollingJob?.cancel()
                binding.textDownloadResult.text = cleanErrorMessage(e.message)
            } finally {
                isDownloadRunning = false
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
        binding.buttonDownload.isEnabled = !downloading && ExternalStorageAccess.isGranted(this)
        binding.progressBarOffline.visibility = if (downloading) View.VISIBLE else View.GONE
        if (downloading) {
            binding.textDownloadStatus.text = "starting…"
        }
    }

    /** Same pattern as MainActivity.cleanErrorMessage() -- keep just the
     * first line of a Chaquopy PyException's message for the UI. */
    private fun cleanErrorMessage(raw: String?): String {
        if (raw.isNullOrBlank()) return "Unknown Python error"
        return raw.substringBefore("\n\n").trim()
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}