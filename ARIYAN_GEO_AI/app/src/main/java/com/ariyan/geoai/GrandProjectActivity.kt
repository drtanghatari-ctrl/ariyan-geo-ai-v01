package com.ariyan.geoai

import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.ariyan.geoai.databinding.ActivityGrandProjectBinding
import com.chaquo.python.PyException
import com.chaquo.python.Python
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/**
 * GrandProjectActivity -- Phase 2's FIRST, deliberately flat browse
 * screen for the Grand Project database (grand_project_db.py).
 *
 * SCOPE (user's own explicit decision, this session): three separate
 * flat lists -- Investigations / Candidates / Timeline -- switched
 * between via the three buttons below. NO drill-down between them yet
 * (e.g. tapping a candidate to see its own confidence history +
 * evidence chain) -- that is the actual "Evidence Graph
 * (backward traceability)" part of Phase 2's own name, deliberately
 * deferred as a separate, later step so this first version stays
 * small and independently verifiable, matching this project's
 * "smallest real version first" discipline used throughout (Wikipedia
 * before the combiner, geocoding before claim extraction, etc.).
 *
 * READ-ONLY. This screen calls ONLY grand_project_query_mobile.py's
 * three JSON-wrapper functions (list_investigations_json/
 * list_candidates_json/list_timeline_json), which themselves call
 * already-tested grand_project_db.py read functions unchanged -- no
 * new persistence logic, no writes, nothing that could corrupt the
 * database this screen is displaying.
 *
 * PROJECT SCOPE: uses the SAME interim stopgap MainActivity.kt's
 * persistToGrandProject() already uses --
 * grand_project_sync.get_or_create_default_grand_project() -- since no
 * real Grand Project selection UI exists yet. This screen therefore
 * shows the one default project's data, not a chosen one. Future UI
 * work should replace this stopgap with real selection, not build on
 * it (same note as grand_project_sync.py's own docstring).
 */
class GrandProjectActivity : AppCompatActivity() {

    private lateinit var binding: ActivityGrandProjectBinding
    private lateinit var python: Python

    // Same real path convention as MainActivity.kt's own offlineDataRoot
    // -- see that class's doc comment for why this exact value.
    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityGrandProjectBinding.inflate(layoutInflater)
        setContentView(binding.root)

        python = Python.getInstance()

        binding.buttonShowInvestigations.setOnClickListener { loadAndShow(ListKind.INVESTIGATIONS) }
        binding.buttonShowCandidates.setOnClickListener { loadAndShow(ListKind.CANDIDATES) }
        binding.buttonShowTimeline.setOnClickListener { loadAndShow(ListKind.TIMELINE) }
    }

    private enum class ListKind { INVESTIGATIONS, CANDIDATES, TIMELINE }

    private fun loadAndShow(kind: ListKind) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                val grandProjectId = withContext(Dispatchers.Default) {
                    python.getModule("grand_project_sync")
                        .callAttr("get_or_create_default_grand_project", offlineDataRoot)
                        .toString()
                }
                val jsonText = withContext(Dispatchers.Default) {
                    val queryModule = python.getModule("grand_project_query_mobile")
                    val fnName = when (kind) {
                        ListKind.INVESTIGATIONS -> "list_investigations_json"
                        ListKind.CANDIDATES -> "list_candidates_json"
                        ListKind.TIMELINE -> "list_timeline_json"
                    }
                    queryModule.callAttr(fnName, offlineDataRoot, grandProjectId).toString()
                }
                binding.textGrandProjectResults.text = formatList(kind, jsonText)
            } catch (e: PyException) {
                binding.textGrandProjectResults.text = "Failed to load: ${cleanErrorMessage(e.message)}"
            } finally {
                setLoading(false)
            }
        }
    }

    /** Same "first line only" convention MainActivity.kt's own
     * cleanErrorMessage() uses -- Chaquopy's PyException.message
     * appends a full traceback after a blank line; this app has no
     * logcat access anyway (see project-wide network/ADB constraints),
     * so the full traceback is never visible either way -- the clean
     * first line is deliberately the more useful thing to show
     * on-screen. */
    private fun cleanErrorMessage(raw: String?): String {
        if (raw.isNullOrBlank()) return "Unknown Python error"
        return raw.substringBefore("\n\n").trim()
    }

    /** Real fields per row, exactly as grand_project_db.py's own list
     * functions return them (see grand_project_query_mobile.py's own
     * docstrings) -- nothing fabricated, nothing renamed. */
    private fun formatList(kind: ListKind, jsonText: String): String {
        val array = try {
            JSONArray(jsonText)
        } catch (e: Exception) {
            return "Could not parse results."
        }
        if (array.length() == 0) {
            return "No ${kind.name.lowercase()} recorded yet for this Grand Project."
        }

        val sb = StringBuilder()
        when (kind) {
            ListKind.INVESTIGATIONS -> {
                sb.append("Investigations (").append(array.length()).append("):\n\n")
                for (i in 0 until array.length()) {
                    val row = array.getJSONObject(i)
                    sb.append("#").append(i + 1).append("  ").append(row.optString("created_at")).append("\n")
                    sb.append("  objective: ").append(row.optString("objective", "(none)")).append("\n")
                    sb.append("  status: ").append(row.optString("execution_status")).append("\n")
                    val summary = row.optString("interpretation_summary", "")
                    if (summary.isNotEmpty()) {
                        sb.append("  summary: ").append(summary).append("\n")
                    }
                    sb.append("\n")
                }
            }
            ListKind.CANDIDATES -> {
                sb.append("Candidates (").append(array.length()).append("):\n\n")
                for (i in 0 until array.length()) {
                    val row = array.getJSONObject(i)
                    sb.append("#").append(i + 1).append("  ").append(row.optString("created_at")).append("\n")
                    sb.append(String.format("  lat=%.6f  lon=%.6f\n", row.optDouble("lat"), row.optDouble("lon")))
                    sb.append("  status: ").append(row.optString("status")).append("\n")
                    val band = row.optString("confidence_band", "")
                    if (band.isNotEmpty()) {
                        sb.append("  confidence: ").append(band)
                        if (!row.isNull("confidence_numeric")) {
                            sb.append(String.format(" (%.2f)", row.optDouble("confidence_numeric")))
                        }
                        sb.append("\n")
                    }
                    sb.append("\n")
                }
            }
            ListKind.TIMELINE -> {
                sb.append("Timeline (").append(array.length()).append(" events):\n\n")
                for (i in 0 until array.length()) {
                    val row = array.getJSONObject(i)
                    sb.append(row.optString("occurred_at")).append("  ")
                    sb.append(row.optString("event_type")).append("\n")
                    val desc = row.optString("description", "")
                    if (desc.isNotEmpty()) {
                        sb.append("  ").append(desc).append("\n")
                    }
                    sb.append("\n")
                }
            }
        }
        return sb.toString()
    }

    private fun setLoading(loading: Boolean) {
        binding.progressBarGrandProject.visibility = if (loading) View.VISIBLE else View.GONE
        binding.buttonShowInvestigations.isEnabled = !loading
        binding.buttonShowCandidates.isEnabled = !loading
        binding.buttonShowTimeline.isEnabled = !loading
    }
}