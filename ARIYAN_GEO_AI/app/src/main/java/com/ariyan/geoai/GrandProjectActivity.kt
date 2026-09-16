package com.ariyan.geoai

import android.graphics.Typeface
import android.os.Bundle
import android.util.TypedValue
import android.view.View
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
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
 * GrandProjectActivity -- Phase 2's browse screen for the Grand
 * Project database (grand_project_db.py).
 *
 * SCOPE (user's own explicit decisions across this project's Phase 2
 * sessions): three separate flat lists -- Investigations / Candidates
 * / Timeline -- switched between via the three buttons below.
 * Investigations and Timeline remain flat, read-only text blocks, by
 * design (no drill-down requested for those). Candidates got
 * DRILL-DOWN ADDED 2026-09-17: each candidate is now its own tappable
 * row; tapping one fetches and shows its own confidence history
 * trajectory + full evidence chain + parent-investigation context, in
 * a dialog -- this is the actual "Evidence Graph (backward
 * traceability)" part of Phase 2's own name. Deliberately built as a
 * dialog over the existing screen, not a new Activity/layout file --
 * fewer new manifest/XML surfaces, less risk of repeating the earlier
 * XML-comment '--' class of bug from this screen's first version.
 *
 * READ-ONLY throughout. Investigations/Timeline call
 * grand_project_query_mobile.py's list_investigations_json()/
 * list_timeline_json(); Candidates calls list_candidates_json() for
 * the row list, then get_candidate_detail_json() per tap for detail --
 * all four are thin JSON-wrapper functions over already-tested
 * grand_project_db.py read functions. No new persistence logic, no
 * writes, nothing that could corrupt the database this screen displays.
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
                if (kind == ListKind.CANDIDATES) {
                    renderCandidateRows(jsonText)
                } else {
                    binding.containerCandidateRows.visibility = View.GONE
                    binding.textGrandProjectResults.visibility = View.VISIBLE
                    binding.textGrandProjectResults.text = formatList(kind, jsonText)
                }
            } catch (e: PyException) {
                binding.containerCandidateRows.visibility = View.GONE
                binding.textGrandProjectResults.visibility = View.VISIBLE
                binding.textGrandProjectResults.text = "Failed to load: ${cleanErrorMessage(e.message)}"
            } finally {
                setLoading(false)
            }
        }
    }

    /** Builds one tappable row per real candidate into
     * containerCandidateRows, replacing whatever was there before.
     * Rows are built entirely in code (TextView + a resolved
     * selectableItemBackground for standard Android tap feedback) --
     * no new XML layout for a row, matching this function's own class
     * doc note on why drill-down avoided adding new XML surfaces.
     * Falls back to the plain textGrandProjectResults view (same as
     * Investigations/Timeline) for the empty-list and
     * malformed-JSON cases, so those messages look consistent with
     * the rest of this screen rather than needing their own styling. */
    private fun renderCandidateRows(jsonText: String) {
        val array = try {
            JSONArray(jsonText)
        } catch (e: Exception) {
            binding.containerCandidateRows.visibility = View.GONE
            binding.textGrandProjectResults.visibility = View.VISIBLE
            binding.textGrandProjectResults.text = "Could not parse results."
            return
        }
        if (array.length() == 0) {
            binding.containerCandidateRows.visibility = View.GONE
            binding.textGrandProjectResults.visibility = View.VISIBLE
            binding.textGrandProjectResults.text = "No candidates recorded yet for this Grand Project."
            return
        }

        binding.textGrandProjectResults.visibility = View.GONE
        binding.containerCandidateRows.visibility = View.VISIBLE
        binding.containerCandidateRows.removeAllViews()

        val tapBackground = TypedValue()
        theme.resolveAttribute(android.R.attr.selectableItemBackground, tapBackground, true)
        val density = resources.displayMetrics.density

        for (i in 0 until array.length()) {
            val row = array.getJSONObject(i)
            val candidateId = row.optString("id")
            val rowText = buildString {
                append("#").append(i + 1).append("  ").append(row.optString("created_at")).append("\n")
                append(String.format("lat=%.6f  lon=%.6f\n", row.optDouble("lat"), row.optDouble("lon")))
                append("status: ").append(row.optString("status"))
                val band = row.optString("confidence_band", "")
                if (band.isNotEmpty()) {
                    append("   confidence: ").append(band)
                    if (!row.isNull("confidence_numeric")) {
                        append(String.format(" (%.2f)", row.optDouble("confidence_numeric")))
                    }
                }
                append("\n(tap for confidence history + evidence)")
            }
            val rowView = TextView(this).apply {
                text = rowText
                typeface = Typeface.MONOSPACE
                textSize = 12f
                setTextColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_text_secondary))
                setPadding((12 * density).toInt(), (10 * density).toInt(), (12 * density).toInt(), (10 * density).toInt())
                isClickable = true
                isFocusable = true
                setBackgroundResource(tapBackground.resourceId)
                setOnClickListener { showCandidateDetail(candidateId) }
            }
            binding.containerCandidateRows.addView(rowView)
        }
    }

    /** Fetches ONE candidate's combined detail (its own confidence
     * history trajectory + full evidence chain + parent-investigation
     * context, per the user's own explicit "extra information for
     * orientation" request) via
     * grand_project_query_mobile.get_candidate_detail_json() -- a
     * single Python call, not four separate round-trips -- and shows
     * it in a dialog. Reuses setLoading() while fetching, same as
     * loadAndShow() above, so the three top buttons and every visible
     * candidate row are disabled during the fetch rather than allowing
     * a second tap to race the first. */
    private fun showCandidateDetail(candidateId: String) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                val detailJsonText = withContext(Dispatchers.Default) {
                    python.getModule("grand_project_query_mobile")
                        .callAttr("get_candidate_detail_json", offlineDataRoot, candidateId)
                        .toString()
                }
                val detail = JSONObject(detailJsonText)
                if (detail.has("error")) {
                    // Ordinary, expected case -- e.g. stale on-screen
                    // state after underlying data changed. Not a
                    // PyException, matches get_candidate_detail_json()'s
                    // own documented {"error": "..."} convention.
                    Toast.makeText(this@GrandProjectActivity, detail.optString("error"), Toast.LENGTH_SHORT).show()
                } else {
                    showDetailDialog(formatCandidateDetail(detail))
                }
            } catch (e: PyException) {
                Toast.makeText(
                    this@GrandProjectActivity,
                    "Failed to load detail: ${cleanErrorMessage(e.message)}",
                    Toast.LENGTH_LONG
                ).show()
            } finally {
                setLoading(false)
            }
        }
    }

    /** Formats get_candidate_detail_json()'s real combined object into
     * readable sections. Real field names throughout -- nothing
     * renamed or fabricated. `reasoning_snapshot_json`/`detail_json`
     * are JSON-encoded STRINGS nested inside the outer JSON (the
     * database's real, honest storage format -- see
     * get_candidate_detail_json()'s own docstring), so each is parsed
     * again here before rendering, same pattern MainActivity.kt's own
     * appendGprSection()/appendErtSection() already use for nested
     * JSON fields elsewhere in this app. Evidence detail_json's keys
     * are rendered generically (iterated, not hardcoded per field) --
     * evidence_type varies (DEM/NDVI/THERMAL/OPTICAL/SAR/GPR/ERT), each
     * with its own real shape, and this avoids assuming any one
     * shape here. */
    private fun formatCandidateDetail(detail: JSONObject): String {
        val sb = StringBuilder()

        val investigation = detail.optJSONObject("investigation")
        if (investigation != null) {
            sb.append("Investigation\n")
            sb.append("  objective: ").append(investigation.optString("objective", "(none)")).append("\n")
            sb.append("  status: ").append(investigation.optString("execution_status")).append("\n")
            val summary = investigation.optString("interpretation_summary", "")
            if (summary.isNotEmpty()) {
                sb.append("  summary: ").append(summary).append("\n")
            }
            sb.append("\n")
        }

        val candidate = detail.optJSONObject("candidate")
        if (candidate != null) {
            sb.append("Candidate\n")
            sb.append(String.format("  lat=%.6f  lon=%.6f\n", candidate.optDouble("lat"), candidate.optDouble("lon")))
            sb.append("  status: ").append(candidate.optString("status")).append("\n")
            val band = candidate.optString("confidence_band", "")
            if (band.isNotEmpty()) {
                sb.append("  current confidence: ").append(band)
                if (!candidate.isNull("confidence_numeric")) {
                    sb.append(String.format(" (%.2f)", candidate.optDouble("confidence_numeric")))
                }
                sb.append("\n")
            }
            sb.append("\n")
        }

        val history = detail.optJSONArray("confidence_history")
        if (history != null && history.length() > 0) {
            sb.append("Confidence History (").append(history.length()).append(" entries, oldest first)\n")
            for (i in 0 until history.length()) {
                val h = history.getJSONObject(i)
                sb.append("  ").append(h.optString("recorded_at")).append("  ")
                sb.append(h.optString("band", "?"))
                if (!h.isNull("numeric_confidence")) {
                    sb.append(String.format(" (%.2f)", h.optDouble("numeric_confidence")))
                }
                sb.append("\n")
                val reasoningRaw = h.optString("reasoning_snapshot_json", "")
                if (reasoningRaw.isNotEmpty() && reasoningRaw != "null") {
                    try {
                        val reasoning = JSONArray(reasoningRaw)
                        for (j in 0 until reasoning.length()) {
                            sb.append("      · ").append(reasoning.optString(j)).append("\n")
                        }
                    } catch (e: Exception) {
                        // Not valid JSON -- skip silently, the rest of
                        // the dialog still renders correctly.
                    }
                }
            }
            sb.append("\n")
        }

        val evidence = detail.optJSONArray("evidence")
        if (evidence != null && evidence.length() > 0) {
            sb.append("Evidence (").append(evidence.length()).append(" entries)\n")
            for (i in 0 until evidence.length()) {
                val e = evidence.getJSONObject(i)
                sb.append("  ").append(e.optString("evidence_type")).append("  ")
                sb.append(e.optString("relation")).append("\n")
                val detailRaw = e.optString("detail_json", "")
                if (detailRaw.isNotEmpty() && detailRaw != "null") {
                    try {
                        val detailObj = JSONObject(detailRaw)
                        val keys = detailObj.keys()
                        for (key in keys) {
                            sb.append("      ").append(key).append(": ").append(detailObj.get(key).toString()).append("\n")
                        }
                    } catch (e2: Exception) {
                        // Not a valid JSON object -- skip silently.
                    }
                }
            }
        }

        if (sb.isEmpty()) {
            sb.append("No detail available.")
        }
        return sb.toString()
    }

    /** Shows candidate detail text in a dialog, built entirely in code
     * (ScrollView + monospace, selectable TextView -- same visual
     * style as textGrandProjectResults/textResults elsewhere in this
     * app) rather than a new XML layout file, per this class's own doc
     * note on why drill-down avoided new XML surfaces this time. */
    private fun showDetailDialog(text: String) {
        val density = resources.displayMetrics.density
        val textView = TextView(this).apply {
            this.text = text
            typeface = Typeface.MONOSPACE
            textSize = 12f
            setTextIsSelectable(true)
            setTextColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_text_secondary))
            val pad = (16 * density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        val scrollView = ScrollView(this).apply {
            addView(textView)
        }
        AlertDialog.Builder(this)
            .setTitle("Candidate Detail")
            .setView(scrollView)
            .setPositiveButton("Close", null)
            .show()
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
     * docstrings) -- nothing fabricated, nothing renamed. NOTE:
     * ListKind.CANDIDATES is no longer routed through this function as
     * of the 2026-09-17 drill-down change -- see renderCandidateRows()
     * above instead. Kept here only for INVESTIGATIONS/TIMELINE, which
     * remain deliberately flat text blocks. */
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
            ListKind.CANDIDATES -> {
                // No longer reached -- see NOTE in this function's own
                // doc comment above.
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