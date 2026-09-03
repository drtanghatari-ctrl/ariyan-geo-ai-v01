package com.ariyan.geoai
import android.Manifest
import android.content.Intent
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
import java.io.File

/**
 * MainActivity — the entire native UI shell for the ARIYAN GEO AI Android
 * vertical slice.
 *
 * Calls investigation_mobile.run_investigation_json() (single-source DEM)
 * or investigation_multi_mobile.run_investigation_multi_json()
 * (DEM + NDVI correlation, optionally + a third GPR evidence entry)
 * depending on the "Include NDVI correlation" switch, and renders the
 * returned evidence record.
 *
 * REAL-DATA-FIRST REDESIGN (this session) -- SYNTHETIC MODE REMOVED
 * ENTIRELY. Previously this Activity had switchRealDem/switchRealNdvi
 * toggles, both defaulting OFF, meaning the actual default investigation
 * used SyntheticDEMSource / SyntheticNDVISource -- fabricated terrain --
 * unless the user remembered to flip a switch and retype an API key
 * every single session (credentials were held only in memory before).
 * That directly violated this project's own hard requirement: nothing
 * synthetic/fake, ever. Fixed by removing the toggles and the synthetic
 * path entirely, on both the Kotlin side (this file, activity_main.xml)
 * and the Python side (investigation_mobile.py / investigation_multi_
 * mobile.py, rewritten to always attempt real data first).
 *
 * NEW BEHAVIOR:
 *  - DEM: a real, live OpenTopography fetch is ALWAYS attempted first,
 *    using the API key entered below (opentopography.org, free). If
 *    that fails for ANY reason (no network, bad/expired key, rate
 *    limit, HTTP/parse error), Python automatically falls back to this
 *    device's own offline DEM library (see OfflineDataActivity.kt /
 *    offline_data_manager.py) for the SAME coordinate, if that
 *    country's data has been pre-downloaded. If NEITHER succeeds, the
 *    investigation fails with a single, honest, combined error message
 *    (surfaced via the existing try/catch below) -- there is no third,
 *    fabricated fallback anymore.
 *  - NDVI (when "Include NDVI correlation" is on): a real, live,
 *    per-DEM-candidate Copernicus core/halo check is ALWAYS attempted
 *    first, using the Copernicus OAuth client ID/secret entered below
 *    (dataspace.copernicus.eu, free). If that's unavailable for every
 *    candidate this run, Python automatically falls back to this
 *    device's offline Sentinel-2 composite for a full-AOI correlation
 *    instead. If neither is available, the DEM results are still
 *    returned -- an NDVI-side failure never blocks the DEM investigation.
 *  - CREDENTIALS ARE NOW SAVED, not memory-only: SecureCredentialStore.kt
 *    (new this session) persists the OpenTopography API key, DEM
 *    dataset type, and Copernicus client ID/secret in an on-device
 *    EncryptedSharedPreferences store, loaded back into the input
 *    fields in onCreate() and re-saved every time "Run Investigation"
 *    is tapped. This is the piece that makes "real data always
 *    attempted, no manual toggle" actually usable day to day -- without
 *    it, the user would be back to retyping credentials every session.
 *
 * Optional GPR field pick (opt-in via switchGpr): a single real manual
 * pick -- a two-way radar travel time a human has read directly off a
 * real radargram, plus the site's chosen soil type -- converted to a
 * depth estimate (with explicit min/max uncertainty range, never a
 * single precise number) via gpr_source_mobile.py / gpr_depth_model.py,
 * and attached as a THIRD, independent evidence entry
 * (evidence_record.py's third_evidence slot, rendered here from the
 * record's "third_evidence_detail" field). This is field-verification
 * evidence anchored at the single site under investigation, not an
 * independent full-area scan like DEM or NDVI. It is ONLY supported by
 * investigation_multi_mobile.run_investigation_multi_json() -- the
 * single-source investigation_mobile module has no GPR parameters -- so
 * switchGpr requires switchNdviCorrelation to also be on; onRunClicked()
 * below validates this explicitly rather than silently ignoring a GPR
 * pick the user thought they were submitting. GPR manual-pick entry is
 * confirmed working on-device and is also fed into the AI Debate Engine
 * (debate_mobile.py matches the GPR pick to nearby DEM candidates by
 * distance and factors real subsurface confirmation into the
 * Geomorphology / Anthropogenic-Archaeological / Data-Artifact-Skeptic
 * perspectives).
 *
 * After a successful investigation, the AI Debate Engine
 * (debate_mobile.run_debate_json()) is called and, if it succeeds, its
 * per-candidate positions/synthesis are appended to the results view.
 * The call is defensive: a debate-engine failure never blocks showing
 * the investigation results themselves -- it is caught and simply omits
 * the debate section.
 *
 * HONEST STATE (updated -- keep this note truthful, don't just delete it):
 * debate_engine.py (rule-based, offline, four perspectives: Geomorphology,
 * Anthropogenic/Archaeological, Data Artifact/Skeptic, Vegetation/
 * Agronomic) and debate_mobile.py (the JSON-string wrapper this Activity
 * calls) both exist in app/src/main/python/ and have been CONFIRMED
 * WORKING on an actual compiled APK on a physical device (real
 * OpenTopography DEM + real Copernicus Sentinel-2 NDVI; synthesis
 * correctly landed on CONTESTED for a genuinely ambiguous candidate).
 * insufficient-data positions render explicitly labeled "[insufficient
 * data]" rather than being silently omitted. GPR manual-pick entry has
 * been CONFIRMED WORKING ON-DEVICE as a third evidence source. THIS
 * SESSION'S CHANGES (real-data-first, credential persistence, offline
 * fallback wiring) have NOT yet been run on an actual device -- that
 * on-device confirmation is the honest next step once this build
 * compiles clean, same practice as every other real piece of this
 * project. There is no automatic GPR device-export parsing in this
 * build (manual pick entry only -- see gpr_source_mobile.py's own
 * honest-state docstring).
 *
 * OFFLINE-DATA NAV BUTTON: buttonOfflineData launches OfflineDataActivity
 * via a plain Intent -- pure navigation, unchanged this session.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var python: Python
    private lateinit var fusedLocationClient: FusedLocationProviderClient
    private lateinit var credentialStore: SecureCredentialStore

    // This app's own private internal storage for pre-downloaded offline
    // DEM/NDVI data -- the exact same path OfflineDataActivity.kt already
    // uses (filesDir/offline_data), so the live-fetch-fails fallback in
    // investigation_mobile.py / investigation_multi_mobile.py reads from
    // whatever OfflineDataActivity has actually downloaded there.
    private val offlineDataRoot: String by lazy { File(filesDir, "offline_data").absolutePath }

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

        // Real-data-first redesign: load any previously-saved credentials
        // back into the input fields, so the user doesn't have to retype
        // them every session -- see SecureCredentialStore.kt and this
        // class's own doc comment.
        credentialStore = SecureCredentialStore(this)
        if (credentialStore.openTopographyApiKey.isNotEmpty()) {
            binding.inputApiKey.setText(credentialStore.openTopographyApiKey)
        }
        if (credentialStore.demType.isNotEmpty()) {
            binding.inputDemType.setText(credentialStore.demType)
        }
        if (credentialStore.copernicusClientId.isNotEmpty()) {
            binding.inputNdviClientId.setText(credentialStore.copernicusClientId)
        }
        if (credentialStore.copernicusClientSecret.isNotEmpty()) {
            binding.inputNdviClientSecret.setText(credentialStore.copernicusClientSecret)
        }

        binding.switchNdviCorrelation.setOnCheckedChangeListener { _, checked ->
            setNdviUiVisible(checked)
        }
        setNdviUiVisible(binding.switchNdviCorrelation.isChecked)

        binding.switchGpr.setOnCheckedChangeListener { _, checked ->
            setGprUiVisible(checked)
        }
        setGprUiVisible(false)

        binding.buttonRun.setOnClickListener { onRunClicked() }
        binding.buttonUseLocation.setOnClickListener { onUseLocationClicked() }
        binding.buttonOfflineData.setOnClickListener {
            startActivity(Intent(this, OfflineDataActivity::class.java))
        }
    }

    /** Shows/hides the NDVI credential fields and their explanatory notes
     * based on whether "Include NDVI correlation" is on. There is no
     * longer a separate "use real NDVI" switch -- real NDVI is always
     * attempted whenever NDVI correlation is included at all (see class
     * doc comment); this function only controls whether the fields
     * needed for that are visible. */
    private fun setNdviUiVisible(includeNdvi: Boolean) {
        binding.textNdviNotice.visibility = if (includeNdvi) View.VISIBLE else View.GONE
        binding.textRealNdviNotice.visibility = if (includeNdvi) View.VISIBLE else View.GONE
        binding.layoutNdviClientId.visibility = if (includeNdvi) View.VISIBLE else View.GONE
        binding.layoutNdviClientSecret.visibility = if (includeNdvi) View.VISIBLE else View.GONE
    }

    private fun setGprUiVisible(useGpr: Boolean) {
        binding.layoutGprSoilPreset.visibility = if (useGpr) View.VISIBLE else View.GONE
        binding.layoutGprTwoWayTime.visibility = if (useGpr) View.VISIBLE else View.GONE
        binding.layoutGprDeviceNote.visibility = if (useGpr) View.VISIBLE else View.GONE
        binding.textRealGprNotice.visibility = if (useGpr) View.VISIBLE else View.GONE
    }

    private fun onRunClicked() {
        val coordsParts = binding.inputCoords.text?.toString()?.trim().orEmpty().split(",").map { it.trim() }
        val lat = coordsParts.getOrNull(0)?.toDoubleOrNull()
        val lon = coordsParts.getOrNull(1)?.toDoubleOrNull()
        val radius = binding.inputRadius.text?.toString()?.trim()?.toDoubleOrNull()
        val grid = binding.inputGrid.text?.toString()?.trim()?.toIntOrNull()
        val apiKey = binding.inputApiKey.text?.toString()?.trim().orEmpty()
        val demType = binding.inputDemType.text?.toString()?.trim()
            ?.ifEmpty { "SRTMGL1" } ?: "SRTMGL1"
        val includeNdvi = binding.switchNdviCorrelation.isChecked
        val ndviClientId = binding.inputNdviClientId.text?.toString()?.trim().orEmpty()
        val ndviClientSecret = binding.inputNdviClientSecret.text?.toString()?.trim().orEmpty()
        val useGpr = binding.switchGpr.isChecked
        val gprSoilPresetKey = binding.inputGprSoilPreset.text?.toString()?.trim().orEmpty()
        val gprTwoWayTimeNs = binding.inputGprTwoWayTime.text?.toString()?.trim()?.toDoubleOrNull()
        val gprDeviceNote = binding.inputGprDeviceNote.text?.toString()?.trim().orEmpty()

        if (lat == null || lat < -90.0 || lat > 90.0 || lon == null || lon < -180.0 || lon > 180.0) {
            toast("Enter coordinates as \"lat, lon\", e.g. 51.1789, -1.8262"); return
        }
        if (radius == null || radius <= 0.0) {
            toast("Enter a positive radius in meters"); return
        }
        if (grid == null || grid < 8) {
            toast("Grid size must be at least 8"); return
        }
        if (useGpr && !includeNdvi) {
            toast("GPR only attaches via the multi-evidence path -- turn on \"Include NDVI correlation\" above too, or turn off \"Attach GPR field pick\""); return
        }
        if (useGpr && gprSoilPresetKey.isEmpty()) {
            toast("Enter a soil preset key for the GPR pick, or turn off \"Attach GPR field pick\""); return
        }
        if (useGpr && (gprTwoWayTimeNs == null || gprTwoWayTimeNs <= 0.0)) {
            toast("Enter a positive two-way travel time (ns) for the GPR pick"); return
        }
        // NOTE: apiKey / ndviClientId / ndviClientSecret are intentionally
        // NOT required here anymore. Real data is always attempted first
        // when a key IS present; if one is genuinely empty, Python treats
        // that exactly like a live-fetch failure and falls back to the
        // offline library automatically (see investigation_mobile.py /
        // investigation_multi_mobile.py) -- so a user relying entirely on
        // pre-downloaded offline data, with no live credentials configured
        // at all, is a legitimate, supported case, not a blocked one.

        // Real-data-first redesign: persist whatever credentials were
        // actually entered/used for this run, so they're pre-filled next
        // time -- see SecureCredentialStore.kt.
        credentialStore.openTopographyApiKey = apiKey
        credentialStore.demType = demType
        if (includeNdvi) {
            credentialStore.copernicusClientId = ndviClientId
            credentialStore.copernicusClientSecret = ndviClientSecret
        }

        setRunning(true)

        lifecycleScope.launch {
            try {
                val json = withContext(Dispatchers.Default) {
                    runInvestigation(
                        lat, lon, radius, grid,
                        apiKey, demType,
                        includeNdvi, ndviClientId, ndviClientSecret,
                        useGpr, gprSoilPresetKey, gprTwoWayTimeNs, gprDeviceNote
                    )
                }
                // The debate engine is rule-based, offline, and stdlib-only
                // (debate_engine.py) -- it never touches the network, so it
                // is safe to call automatically after every investigation.
                // Still wrapped defensively: a debate-engine failure must
                // never hide the investigation result the user already has.
                val debateJson = withContext(Dispatchers.Default) {
                    try {
                        runDebate(json)
                    } catch (e: PyException) {
                        null
                    }
                }
                renderResult(json, debateJson)
            } catch (e: PyException) {
                // Surface the real Python error rather than a generic
                // "something went wrong" -- this app is a scientific
                // instrument, not a consumer toy, and dem_source_mobile.py
                // / ndvi_source_mobile.py / gpr_source_mobile.py /
                // offline_evidence_fallback.py already produce
                // human-readable messages for every network/HTTP/parsing/
                // offline-availability failure. Show just that message, not
                // the full traceback noise Chaquopy appends.
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
     * never be called from the main thread. Real data is always
     * attempted first on the Python side now -- see
     * investigation_mobile.py / investigation_multi_mobile.py's own
     * docstrings for the full real-live-then-offline-fallback logic;
     * this function just passes through whatever the user entered plus
     * offlineDataRoot, unconditionally. */
    private fun runInvestigation(
        lat: Double, lon: Double, radiusM: Double, gridSize: Int,
        apiKey: String, demType: String,
        includeNdvi: Boolean,
        ndviClientId: String, ndviClientSecret: String,
        useGpr: Boolean, gprSoilPresetKey: String, gprTwoWayTimeNs: Double?,
        gprDeviceNote: String
    ): String {
        return if (includeNdvi) {
            val module = python.getModule("investigation_multi_mobile")
            val result = module.callAttr(
                "run_investigation_multi_json",
                lat, lon, radiusM, gridSize,
                Kwarg("api_key", apiKey),
                Kwarg("demtype", demType),
                Kwarg("ndvi_client_id", ndviClientId),
                Kwarg("ndvi_client_secret", ndviClientSecret),
                Kwarg("offline_data_root", offlineDataRoot),
                Kwarg("use_gpr", useGpr),
                Kwarg("gpr_soil_preset_key", gprSoilPresetKey),
                Kwarg("gpr_two_way_time_ns", gprTwoWayTimeNs),
                Kwarg("gpr_entry_method", "manual"),
                Kwarg("gpr_device_note", gprDeviceNote)
            )
            result.toString()
        } else {
            val module = python.getModule("investigation_mobile")
            val result = module.callAttr(
                "run_investigation_json",
                lat, lon, radiusM, gridSize,
                Kwarg("api_key", apiKey),
                Kwarg("demtype", demType),
                Kwarg("offline_data_root", offlineDataRoot)
            )
            result.toString()
        }
    }

    /** Runs on a background thread, same constraint as runInvestigation().
     * Calls debate_mobile.run_debate_json(), which never raises on its own
     * (it catches internally and returns {"error": "..."} JSON) -- but this
     * still runs inside a try/catch upstream in case Chaquopy itself throws
     * (e.g. the module failing to import). */
    private fun runDebate(investigationJson: String): String {
        val module = python.getModule("debate_mobile")
        val result = module.callAttr("run_debate_json", investigationJson)
        return result.toString()
    }

    private fun renderResult(jsonText: String, debateJsonText: String?) {
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

        appendGprSection(sb, record)

        val limitations = record.optJSONArray("limitations")
        if (limitations != null && limitations.length() > 0) {
            sb.append("\nLimitations:\n")
            for (i in 0 until limitations.length()) {
                sb.append("  • ").append(limitations.getString(i)).append("\n")
            }
        }

        appendDebateSection(sb, debateJsonText)

        binding.textResults.text = sb.toString()
    }

    /** Renders evidence_record.py's optional "third_evidence_detail" array
     * -- currently only ever populated by a real GPR manual field pick
     * (see gpr_source_mobile.GPREvidence.as_evidence_record()). Absent
     * entirely when switchGpr was off, or when the GPR depth-model
     * conversion itself failed for this run (that failure instead shows
     * up as an honest entry in "limitations", not here -- see
     * investigation_multi_mobile._build_gpr_evidence()). Depth values are
     * always rendered as an explicit min/max range, matching this
     * project's existing honesty conventions for approximated evidence
     * (same pattern as the real-NDVI core/halo notices above). */
    private fun appendGprSection(sb: StringBuilder, record: JSONObject) {
        val thirdEvidenceDetail = record.optJSONArray("third_evidence_detail")
        if (thirdEvidenceDetail == null || thirdEvidenceDetail.length() == 0) return

        sb.append("\nGPR (single-site field verification, not a full-area scan):\n")
        for (i in 0 until thirdEvidenceDetail.length()) {
            val g = thirdEvidenceDetail.getJSONObject(i)
            sb.append("  soil preset: ").append(g.optString("soil_preset"))
            sb.append("  entry: ").append(g.optString("entry_method")).append("\n")
            val depths = g.optJSONArray("depth_estimates_m")
            if (depths != null) {
                for (j in 0 until depths.length()) {
                    val d = depths.getJSONObject(j)
                    sb.append(String.format(
                        "  depth ≈ %.2f m (range %.2f–%.2f m) from two-way time %.1f ns\n",
                        d.optDouble("depth_m"),
                        d.optDouble("depth_min_m"),
                        d.optDouble("depth_max_m"),
                        d.optDouble("two_way_time_ns")
                    ))
                }
            }
            val note = g.optString("note", "")
            if (note.isNotEmpty()) {
                sb.append("  ").append(note).append("\n")
            }
        }
    }

    /** Renders the AI Debate Engine's output (debate_mobile.run_debate_json())
     * if it succeeded. This is a ranked heuristic opinion across four rule-
     * based perspectives, not a verified conclusion -- rendered as such,
     * matching debate_engine.py's own synthesis framing
     * (LEADING_INTERPRETATION / CONTESTED / WEAK_SIGNAL / NO_DATA). All four
     * perspectives are always shown, including any marked insufficient_data
     * by debate_engine.py (labeled "[insufficient data]" rather than
     * silently omitted) -- an honest "this perspective had no evidence to
     * argue from" is itself a real finding this project does not hide.
     * Each perspective's reasoning bullet points are also rendered. A
     * top-level "gpr_note" is rendered too, when debate_mobile.py reports
     * that real GPR evidence existed for this investigation but wasn't
     * close enough to any candidate to be used in its debate.
     * candidateId: debate_mobile.py always assigns a real, non-null
     * "candidate_id", but this still checks isNull() explicitly rather
     * than relying only on optString()'s fallback -- org.json's
     * optString(name, fallback) only substitutes the fallback when the
     * key is ABSENT, not when the key is present holding a JSON null. */
    private fun appendDebateSection(sb: StringBuilder, debateJsonText: String?) {
        if (debateJsonText.isNullOrBlank()) return
        val debateResult = try {
            JSONObject(debateJsonText)
        } catch (e: Exception) {
            return
        }
        if (debateResult.has("error")) return

        val debates = debateResult.optJSONArray("debates")
        if (debates == null || debates.length() == 0) return

        sb.append("\nAI Debate (offline, rule-based -- not a verified conclusion):\n")
        for (i in 0 until debates.length()) {
            val debate = debates.getJSONObject(i)
            val candidateId = if (debate.isNull("candidate_id")) {
                "#${i + 1}"
            } else {
                debate.optString("candidate_id", "#${i + 1}")
            }
            sb.append("  Candidate ").append(candidateId).append(":\n")

            val positions = debate.optJSONArray("positions")
            if (positions != null) {
                for (j in 0 until positions.length()) {
                    val p = positions.getJSONObject(j)
                    val insufficient = p.optBoolean("insufficient_data", false)
                    sb.append("    - ").append(p.optString("perspective")).append(" [")
                    sb.append(if (insufficient) "insufficient data" else p.optString("confidence_label"))
                    sb.append("]: ").append(p.optString("stance")).append("\n")

                    val reasoning = p.optJSONArray("reasoning")
                    if (reasoning != null) {
                        for (k in 0 until reasoning.length()) {
                            sb.append("        · ").append(reasoning.optString(k)).append("\n")
                        }
                    }
                }
            }

            val synthesis = debate.optJSONObject("synthesis")
            if (synthesis != null) {
                sb.append("    Synthesis (").append(synthesis.optString("agreement_level")).append("): ")
                sb.append(synthesis.optString("steward_note")).append("\n")
            }
        }

        val gprNote = debateResult.optString("gpr_note", "")
        if (gprNote.isNotEmpty()) {
            sb.append("  ").append(gprNote).append("\n")
        }
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
