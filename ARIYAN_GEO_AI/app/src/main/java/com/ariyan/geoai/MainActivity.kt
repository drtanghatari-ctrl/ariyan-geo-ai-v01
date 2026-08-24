package com.ariyan.geoai
import android.Manifest
import android.content.pm.PackageManager
import android.location.Location
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationServices
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
 * Calls investigation_mobile.run_investigation_json() (single-source DEM)
 * or investigation_multi_mobile.run_investigation_multi_json()
 * (DEM + NDVI correlation) depending on the "Include NDVI correlation"
 * switch, and renders the returned evidence record.
 *
 * Two DEM sources are available:
 *  - Synthetic (default): offline, no network, every result explicitly
 *    labeled synthetic on screen.
 *  - Real (opt-in via switchRealDem): a live OpenTopography fetch, decoded
 *    as AAIGrid rather than GeoTIFF because Chaquopy cannot build
 *    GDAL/rasterio for Android (see dem_source_mobile.py). Requires the
 *    user's own OpenTopography API key, entered in-app and held only in
 *    memory for this session -- never written to disk.
 *
 * Two NDVI sources are available when NDVI correlation is included:
 *  - Synthetic (default): offline, no network, always labeled synthetic.
 *  - Real (opt-in via switchRealNdvi): a live Copernicus Data Space
 *    Ecosystem Statistical API core/halo vegetation-stress check per DEM
 *    candidate (see ndvi_source_mobile.py). Requires the user's own
 *    Copernicus OAuth client ID/secret, entered in-app and held only in
 *    memory for this session -- never written to disk.
 *
 * There is still no AI Debate Engine wired into this entry point and no
 * depth estimation in this build; see HANDOFF.md for the honest current
 * state and what's next.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var python: Python
    private lateinit var fusedLocationClient: FusedLocationProviderClient

    private val locationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) fetchLocation() else toast("Location permission denied")
        }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Chaquopy's Python interpreter is started once per process by
        // AriyanApplication.onCreate(). By the time any Activity runs,
        // Python.isStarted() is guaranteed true.
       python = Python.getInstance()
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this)

        binding.switchRealDem.setOnCheckedChangeListener { _, checked ->
            setRealDemUiVisible(checked)
        }
        setRealDemUiVisible(false)

        binding.switchRealNdvi.setOnCheckedChangeListener { _, checked ->
            setRealNdviUiVisible(checked)
        }
        setRealNdviUiVisible(false)

        binding.buttonRun.setOnClickListener { onRunClicked() }
        binding.buttonUseLocation.setOnClickListener { onUseLocationClicked() }
    }

    private fun setRealDemUiVisible(useRealDem: Boolean) {
        binding.layoutApiKey.visibility = if (useRealDem) View.VISIBLE else View.GONE
        binding.layoutDemType.visibility = if (useRealDem) View.VISIBLE else View.GONE
        binding.textRealDemNotice.visibility = if (useRealDem) View.VISIBLE else View.GONE
        binding.textSyntheticNotice.visibility = if (useRealDem) View.GONE else View.VISIBLE
    }

    private fun setRealNdviUiVisible(useRealNdvi: Boolean) {
        binding.layoutNdviClientId.visibility = if (useRealNdvi) View.VISIBLE else View.GONE
        binding.layoutNdviClientSecret.visibility = if (useRealNdvi) View.VISIBLE else View.GONE
        binding.textRealNdviNotice.visibility = if (useRealNdvi) View.VISIBLE else View.GONE
    }

    private fun onRunClicked() {
        val coordsParts = binding.inputCoords.text?.toString()?.trim().orEmpty().split(",").map { it.trim() }
        val lat = coordsParts.getOrNull(0)?.toDoubleOrNull()
        val lon = coordsParts.getOrNull(1)?.toDoubleOrNull()
        val radius = binding.inputRadius.text?.toString()?.trim()?.toDoubleOrNull()
        val grid = binding.inputGrid.text?.toString()?.trim()?.toIntOrNull()
        val useRealDem = binding.switchRealDem.isChecked
        val apiKey = binding.inputApiKey.text?.toString()?.trim().orEmpty()
        val demType = binding.inputDemType.text?.toString()?.trim()
            ?.ifEmpty { "SRTMGL1" } ?: "SRTMGL1"
        val includeNdvi = binding.switchNdviCorrelation.isChecked
        val useRealNdvi = binding.switchRealNdvi.isChecked
        val ndviClientId = binding.inputNdviClientId.text?.toString()?.trim().orEmpty()
        val ndviClientSecret = binding.inputNdviClientSecret.text?.toString()?.trim().orEmpty()

        if (lat == null || lat < -90.0 || lat > 90.0 || lon == null || lon < -180.0 || lon > 180.0) {
            toast("Enter coordinates as \"lat, lon\", e.g. 51.1789, -1.8262"); return
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
        if (includeNdvi && useRealNdvi && (ndviClientId.isEmpty() || ndviClientSecret.isEmpty())) {
            toast("Enter your Copernicus client ID and secret, or turn off \"Use real Copernicus NDVI\""); return
        }

        setRunning(true)

        lifecycleScope.launch {
            try {
                val json = withContext(Dispatchers.Default) {
                    runInvestigation(
                        lat, lon, radius, grid,
                        useRealDem, apiKey, demType,
                        includeNdvi, useRealNdvi, ndviClientId, ndviClientSecret
                    )
                }
                renderResult(json)
            } catch (e: PyException) {
                // Surface the real Python error rather than a generic
                // "something went wrong" -- this app is a scientific
                // instrument, not a consumer toy, and dem_source_mobile.py
                // / ndvi_source_mobile.py already produce human-readable
                // messages for every network/HTTP/parsing failure. Show
                // just that message, not the full traceback noise Chaquopy
                // appends.
                binding.textConfidence.text = "Investigation failed"
                binding.textResults.text = cleanErrorMessage(e.message)
            } finally {
                setRunning(false)
            }
        }
    }
    private fun onUseLocationClicked() {
        val hasPermission = ContextCompat.checkSelfPermission(
            this, Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
        if (hasPermission) {
            fetchLocation()
        } else {
            locationPermissionLauncher.launch(Manifest.permission.ACCESS_FINE_LOCATION)
        }
    }

    private fun fetchLocation() {
        try {
            fusedLocationClient.lastLocation.addOnSuccessListener { location: Location? ->
                if (location != null) {
                    binding.inputCoords.setText(
                        String.format("%.7f, %.7f", location.latitude, location.longitude)
                    )
                } else {
                    toast("No recent location fix available — ensure GPS/location is on and try again")
                }
            }.addOnFailureListener {
                toast("Could not get location: ${it.message}")
            }
        } catch (e: SecurityException) {
            toast("Location permission not granted")
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
        useRealDem: Boolean, apiKey: String, demType: String,
        includeNdvi: Boolean, useRealNdvi: Boolean,
        ndviClientId: String, ndviClientSecret: String
    ): String {
        return if (includeNdvi) {
            val module = python.getModule("investigation_multi_mobile")
            val result = module.callAttr(
                "run_investigation_multi_json",
                lat, lon, radiusM, gridSize,
                Kwarg("use_real_dem", useRealDem),
                Kwarg("api_key", apiKey),
                Kwarg("demtype", demType),
                Kwarg("use_real_ndvi", useRealNdvi),
                Kwarg("ndvi_client_id", ndviClientId),
                Kwarg("ndvi_client_secret", ndviClientSecret)
            )
            result.toString()
        } else {
            val module = python.getModule("investigation_mobile")
            val result = module.callAttr(
                "run_investigation_json",
                lat, lon, radiusM, gridSize,
                Kwarg("use_real_dem", useRealDem),
                Kwarg("api_key", apiKey),
                Kwarg("demtype", demType)
            )
            result.toString()
        }
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
        val correlation = record.optJSONArray("correlation")
        if (correlation != null && correlation.length() > 0) {
            sb.append("\nCorrelation:\n")
            for (i in 0 until correlation.length()) {
                val c = correlation.getJSONObject(i)
                sb.append(" ").append(c.optString("status")).append(" ")
                sb.append("sources=").append(c.optJSONArray("supporting_sources")?.toString() ?: "[]")
                sb.append("\n ").append(c.optString("note")).append("\n")
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
