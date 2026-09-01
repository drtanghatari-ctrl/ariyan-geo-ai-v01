package com.ariyan.geoai

import android.os.Bundle
import android.view.View
import android.widget.ArrayAdapter
import android.widget.Toast
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
import java.io.File

/**
 * OfflineDataActivity — lets the user download a country's offline DEM +
 * NDVI package (see offline_download_runner.py / offline_data_manager.py
 * / offline_country_registry.py) so an investigation can still run with
 * no network access.
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
 * visible to other apps or the user's file browser. Backing this up to
 * the user's own Google Drive (so a large download survives an
 * uninstall/reinstall or a new device) is DriveBackupWorker.kt's job --
 * not yet built; this Activity only downloads and shows status.
 *
 * HONEST STATE: this Activity itself, and the download flow end-to-end,
 * have NOT yet been run on an actual device or in CI -- only
 * offline_download_runner.py/offline_data_manager.py's own Python logic
 * has been sandbox-tested (see those files' docstrings). This is new,
 * unverified Kotlin, to be confirmed at the on-device stage per the
 * agreed build order.
 */
class OfflineDataActivity : AppCompatActivity() {

    private lateinit var binding: ActivityOfflineDataBinding
    private lateinit var python: Python
    private val offlineDataRoot: String by lazy { File(filesDir, "offline_data").absolutePath }

    // Dropdown shows "IR — Iran"; this maps that label back to the real
    // ISO code Python needs, rather than re-parsing the display string.
    private var isoByLabel: Map<String, String> = emptyMap()
    private var statusPollingJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOfflineDataBinding.inflate(layoutInflater)
        setContentView(binding.root)

        python = Python.getInstance()

        loadCountryList()

        binding.buttonRefreshStatus.setOnClickListener { refreshCountrySummary() }
        binding.buttonDownload.setOnClickListener { onDownloadClicked() }
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

    // -- Rendering --

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

    /** Same pattern as MainActivity.cleanErrorMessage() -- Chaquopy's
     * PyException.message is typically the Python exception plus a full
     * traceback; keep just the first line for the UI. */
    private fun cleanErrorMessage(raw: String?): String {
        if (raw.isNullOrBlank()) return "Unknown Python error"
        return raw.substringBefore("\n\n").trim()
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
