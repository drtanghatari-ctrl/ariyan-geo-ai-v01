package com.ariyan.geoai

import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.ariyan.geoai.databinding.ActivityMainBinding
import com.chaquo.python.Kwarg
import com.chaquo.python.PyException
import com.chaquo.python.Python
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * MainActivity — the entire native UI shell for the ARIYAN GEO AI Android
 * vertical slice.
 *
 * Calls investigation_mobile.run_investigation_json() (the real,
 * test-verified Python pipeline embedded via Chaquopy) and renders the
 * returned evidence record. Two DEM sources are available:
 *
 *  - Synthetic (default): offline, no network, every result explicitly
 *    labeled synthetic on screen.
 *  - Real (opt-in via the switch): a live OpenTopography fetch, decoded
 *    as AAIGrid rather than GeoTIFF because Chaquopy cannot build
 *    GDAL/rasterio for Android (see dem_source_mobile.py). Requires the
 *    user's own OpenTopography API key, entered in-app and held only in
 *    memory for this session -- never written to disk.
 *
 * There is still no AI Debate Engine, no multi-source (DEM+NDVI)
 * correlation wired into this entry point, and no depth estimation in
 * this build; see HANDOFF.md for the honest current state and what's
 * next.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var python: Python

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Chaquopy's Python interpreter is started once per process by
        // AriyanApplication.onCreate(). By the time any Activity runs,
        // Python.isStarted() is guaranteed true.
        python = Python.getInstance()

        binding.switchRealDem.setOnCheckedChangeListener { _, checked ->
            setRealDemUiVisible(checked)
        }
        setRealDemUiVisible(false)

        binding.buttonRun.setOnClickListener { onRunClicked() }
    }

    private fun setRealDemUiVisible(useRealDem: Boolean) {
        binding.layoutApiKey.visibility = if (useRealDem) View.VISIBLE else View.GONE
        binding.layoutDemType.visibility = if (useRealDem) View.VISIBLE else View.GONE
        binding.textRealDemNotice.visibility = if (useRealDem) View.VISIBLE else View.GONE
        binding.textSyntheticNotice.visibility = if (useRealDem) View.GONE else View.VISIBLE
    }

    private fun onRunClicked() {
        val lat = binding.inputLat.text?.toString()?.trim()?.toDoubleOrNull()
        val lon = binding.inputLon.text?.toString()?.trim()?.toDoubleOrNull()
        val radius = binding.inputRadius.text?.toString()?.trim()?.toDoubleOrNull()
        val grid = binding.inputGrid.text?.toString()?.trim()?.toIntOrNull()
        val useRealDem = binding.switchRealDem.isChecked
        val apiKey = binding.inputApiKey.text?.toString()?.trim().orEmpty()
        val demType = binding.inputDemType.text?.toString()?.trim()
            ?.ifEmpty { "SRTMGL1" } ?: "SRTMGL1"
        val includeNdvi = binding.switchNdviCorrelation.isChecked
        if (lat == null || lat < -90.0 || lat > 90.0) {
            toast("Enter a valid latitude (-90 to 90)"); return
        }
        if (lon == null || lon < -180.0 || lon > 180.0) {
            toast("Enter a valid longitude (-180 to 180)"); return
        }
        if (radius == null || radius <= 0.0) {
            toast("Enter a positive radius in meters"); return
        }
        if (grid == null || grid < 8) {
            toast("Grid size must be at least 8"); return
        }
        if (useRealDem && apiKey.isEmpty()) {
            toast("Enter your OpenTopography API key, or turn off \"Use real DEM\""); return
        }

        setRunning(true)

        lifecycleScope.launch {
            try {
                val json = withContext(Dispatchers.Default) {
                    runInvestigation(lat, lon, radius, grid, useRealDem, apiKey, demType)
                }
                renderResult(json)
            } catch (e: PyException) {
                // Surface the real Python error rather than a generic
                // "something went wrong" -- this app is a scientific
                // instrument, not a consumer toy, and dem_source_mobile.py
                // already produces human-readable messages for every
                // network/HTTP/parsing failure. Show just that message,
                // not the full traceback noise Chaquopy appends.
                binding.textConfidence.text = "Investigation failed"
                binding.textResults.text = cleanErrorMessage(e.message)
            } finally {
                setRunning(false)
            }
        }
    }

    /** Chaquopy's PyException.message is typically
     * "ExceptionType: message\n\nTraceback (most recent call last): ...".
     * Keep only the first line for the UI -- the full traceback is
     * still in Logcat via the exception itself if deeper debugging is
     * ever needed. */
    private fun cleanErrorMessage(raw: String?): String {
        if (raw.isNullOrBlank()) return "Unknown Python error"
        return raw.substringBefore("\n\n").trim()
    }

    /** Runs on a background thread. Chaquopy calls block, so this must
     * never be called from the main thread. */
    private fun runInvestigation(
        lat: Double, lon: Double, radiusM: Double, gridSize: Int,
        useRealDem: Boolean, apiKey: String, demType: String
    ): String {
        val module = python.getModule("investigation_mobile")
        val result = module.callAttr(
            "run_investigation_json",
            lat, lon, radiusM, gridSize,
            Kwarg("use_real_dem", useRealDem),
            Kwarg("api_key", apiKey),
            Kwarg("demtype", demType)
        )
        return result.toString()
    }

    private fun renderResult(jsonText: String) {
        val record = JSONObject(jsonText)
        val confidence = record.optString("confidence_statement", "")
        binding.textConfidence.text = confidence

        val anomalies = record.optJSONArray("anomalies")
        val sb = StringBuilder()
        sb.append("Evidence: ")
        val evidence = record.optJSONArray("evidence")
        if (evidence != null && evidence.length() > 0) {
            val ev0 = evidence.getJSONObject(0)
            sb.append(ev0.optString("source", "?"))
            sb.append(" (synthetic=").append(ev0.optBoolean("synthetic", true)).append(")\n")
            val notes = ev0.optString("notes", "")
            if (notes.isNotEmpty()) {
                sb.append(notes).append("\n")
            }
            sb.append("\n")
        } else {
            sb.append("none\n\n")
        }

        sb.append("Candidates: ").append(anomalies?.length() ?: 0).append("\n")
        if (anomalies != null) {
            for (i in 0 until anomalies.length()) {
                val a = anomalies.getJSONObject(i)
                sb.append(String.format(
                    "  #%d  lat=%.6f lon=%.6f  |z|=%.2f  area=%d cells  polarity=%s\n",
                    i + 1,
                    a.optDouble("lat"),
                    a.optDouble("lon"),
                    a.optDouble("peak_zscore"),
                    a.optInt("area_cells"),
                    a.optString("polarity")
                ))
            }
        }

        val limitations = record.optJSONArray("limitations")
        if (limitations != null && limitations.length() > 0) {
            sb.append("\nLimitations:\n")
            for (i in 0 until limitations.length()) {
                sb.append("  • ").append(limitations.getString(i)).append("\n")
            }
        }

        binding.textResults.text = sb.toString()
    }

    private fun setRunning(running: Boolean) {
        binding.progressBar.visibility = if (running) View.VISIBLE else View.GONE
        binding.buttonRun.isEnabled = !running
        if (running) {
            binding.textConfidence.text = getString(R.string.running)
            binding.textResults.text = ""
        }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
