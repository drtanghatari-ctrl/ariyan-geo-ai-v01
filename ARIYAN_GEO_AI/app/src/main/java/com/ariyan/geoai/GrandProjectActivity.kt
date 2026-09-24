package com.ariyan.geoai

import android.graphics.Typeface
import android.os.Bundle
import android.util.TypedValue
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
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
import com.google.android.material.button.MaterialButton
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
 * sessions): four separate flat lists -- Investigations / Candidates /
 * Timeline / Hypotheses -- switched between via the four buttons
 * below. Investigations and Timeline remain flat, read-only text
 * blocks, by design (no drill-down requested for those). Candidates
 * got DRILL-DOWN ADDED 2026-09-17: each candidate is its own tappable
 * row; tapping one fetches and shows its own confidence history
 * trajectory + full evidence chain + parent-investigation context, in
 * a dialog -- this is the actual "Evidence Graph (backward
 * traceability)" part of Phase 2's own name. Hypotheses got its OWN
 * tab ADDED 2026-09-17 (Phase 2's third and final scoped item): a
 * simple "state a new hypothesis" text input + submit button, plus a
 * flat list of existing ones -- the actual "explicit per-project
 * Hypothesis objects" part of Phase 2's own name, since
 * create_hypothesis() has existed since Phase 0 but never had a real
 * UI path to reach it before now. LINKING a candidate to a hypothesis
 * (also ADDED 2026-09-17, same pass, per the user's own explicit
 * request) happens from the Candidate Detail dialog itself, not from
 * the Hypotheses tab -- a "Link to Hypothesis" button there opens a
 * native picker of existing hypotheses and calls
 * link_candidate_to_hypothesis_json() on selection.
 *
 * All new UI surfaces this session (candidate rows, the Candidate
 * Detail dialog, the Hypotheses tab's input/button/list) are built
 * entirely in Kotlin code rather than new XML layout files/elements
 * with real content -- deliberately, to avoid repeating the
 * double-hyphen-in-XML-comment class of bug this screen's first
 * version hit twice.
 *
 * READ-ONLY plus TWO WRITE PATHS as of this session. Investigations/
 * Timeline call grand_project_query_mobile.py's
 * list_investigations_json()/list_timeline_json(); Candidates calls
 * list_candidates_json() for the row list, then
 * get_candidate_detail_json() per tap for detail; Hypotheses calls
 * list_hypotheses_json() for its row list. The two WRITE paths --
 * create_hypothesis_json() (stating a new hypothesis) and
 * link_candidate_to_hypothesis_json() (linking a candidate to one) --
 * are this screen's first writes; every other call remains a thin
 * JSON-wrapper read over already-tested grand_project_db.py functions.
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
        binding.buttonShowHypotheses.setOnClickListener { loadAndShow(ListKind.HYPOTHESES) }
    }

    private enum class ListKind { INVESTIGATIONS, CANDIDATES, TIMELINE, HYPOTHESES }

    /** Resolves the (one, stopgap) Grand Project's id. Pulled out into
     * its own suspend helper so every flow that needs it (loading a
     * tab, submitting a new hypothesis, fetching the hypothesis
     * picker's list) shares one implementation rather than repeating
     * the same withContext block -- this was inlined three times
     * before this session's Hypothesis UI pass made a fourth call site
     * necessary, at which point pulling it out stopped being
     * optional. */
    private suspend fun getGrandProjectId(): String = withContext(Dispatchers.Default) {
        python.getModule("grand_project_sync")
            .callAttr("get_or_create_default_grand_project", offlineDataRoot)
            .toString()
    }

    /** The actual load-and-render body, as a suspend function rather
     * than a fire-and-forget launch{} -- so callers that are ALREADY
     * inside their own coroutine (submitHypothesis(), below, refreshing
     * the Hypotheses tab right after a successful create) can await it
     * directly, instead of nesting a second independent launch{} whose
     * own setLoading(true)/setLoading(false) would race the outer
     * one's and cause the loading spinner to flicker off then back on.
     * loadAndShow() below is the thin, non-suspend wrapper every button
     * click listener actually calls. */
    private suspend fun loadAndShowSuspend(kind: ListKind) {
        val grandProjectId = getGrandProjectId()
        val jsonText = withContext(Dispatchers.Default) {
            val queryModule = python.getModule("grand_project_query_mobile")
            val fnName = when (kind) {
                ListKind.INVESTIGATIONS -> "list_investigations_json"
                ListKind.CANDIDATES -> "list_candidates_json"
                ListKind.TIMELINE -> "list_timeline_json"
                ListKind.HYPOTHESES -> "list_hypotheses_json"
            }
            queryModule.callAttr(fnName, offlineDataRoot, grandProjectId).toString()
        }
        when (kind) {
            ListKind.CANDIDATES -> renderCandidateRows(jsonText)
            ListKind.HYPOTHESES -> renderHypotheses(jsonText, grandProjectId)
            else -> {
                binding.containerCandidateRows.visibility = View.GONE
                binding.containerHypotheses.visibility = View.GONE
                binding.textGrandProjectResults.visibility = View.VISIBLE
                binding.textGrandProjectResults.text = formatList(kind, jsonText)
            }
        }
    }

    private fun loadAndShow(kind: ListKind) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                loadAndShowSuspend(kind)
            } catch (e: PyException) {
                binding.containerCandidateRows.visibility = View.GONE
                binding.containerHypotheses.visibility = View.GONE
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
     * the rest of this screen rather than needing their own styling.
     *
     * ORDER (changed 2026-09-21): rows are no longer oldest-first.
     * Highest confidence first, then largest absolute DEM z-score
     * (the same abs(score) ranking Pass 2 itself uses), and the sort
     * is stable so exact ties keep their oldest-first order. The #N
     * in each row is therefore the RANK in this list, not the order
     * the candidate was created. Each row also shows its stored DEM
     * z-score so the ordering can be checked by eye. Nothing about
     * the data changes, only the order the rows are shown in. */
    private fun renderCandidateRows(jsonText: String) {
        val array = try {
            JSONArray(jsonText)
        } catch (e: Exception) {
            binding.containerCandidateRows.visibility = View.GONE
            binding.containerHypotheses.visibility = View.GONE
            binding.textGrandProjectResults.visibility = View.VISIBLE
            binding.textGrandProjectResults.text = "Could not parse results."
            return
        }
        if (array.length() == 0) {
            binding.containerCandidateRows.visibility = View.GONE
            binding.containerHypotheses.visibility = View.GONE
            binding.textGrandProjectResults.visibility = View.VISIBLE
            binding.textGrandProjectResults.text = "No candidates recorded yet for this Grand Project."
            return
        }

        binding.textGrandProjectResults.visibility = View.GONE
        binding.containerHypotheses.visibility = View.GONE
        binding.containerCandidateRows.visibility = View.VISIBLE
        binding.containerCandidateRows.removeAllViews()
lastCandidatesJson = jsonText
        addCandidateControls()
        val tapBackground = TypedValue()
        theme.resolveAttribute(android.R.attr.selectableItemBackground, tapBackground, true)
        val density = resources.displayMetrics.density

        val sortedRows = ArrayList<JSONObject>(array.length())
        for (k in 0 until array.length()) {
            val c = array.getJSONObject(k)
            if (hideRejected && c.optString("status") == "REJECTED") continue
            sortedRows.add(c)
        }
        sortedRows.sortWith(
            compareByDescending<JSONObject> { c ->
                if (c.isNull("confidence_numeric")) -1.0 else c.optDouble("confidence_numeric", -1.0)
            }.thenByDescending { c ->
                if (c.isNull("score")) -1.0 else Math.abs(c.optDouble("score", 0.0))
            }
        )

        for (i in 0 until sortedRows.size) {
            val row = sortedRows[i]
            val candidateId = row.optString("id")
            val rowText = buildString {
                append("#").append(i + 1).append("  ").append(row.optString("created_at")).append("\n")
                append(String.format("lat=%.6f  lon=%.6f\n", row.optDouble("lat"), row.optDouble("lon")))
                if (!row.isNull("score")) {
                    append(String.format("DEM z-score: %+.2f\n", row.optDouble("score")))
                }
                append("status: ").append(row.optString("status_label", row.optString("status")))
                val band = row.optString("confidence_band", "")
                if (band.isNotEmpty()) {
                    append("   confidence: ").append(band)
                    if (!row.isNull("confidence_numeric")) {
                        append(String.format(" (%.2f)", row.optDouble("confidence_numeric")))
                    }
                }
if (row.optString("job_trust") == "CORRUPTED") {
                    append("\n!! JOB ").append(row.optString("job_id").take(6)).append(" MARKED CORRUPTED - ignore")
                }
                val lastReason = row.optString("last_review_reason", "")
                if (lastReason.isNotEmpty() && lastReason != "null") {
                    append("\nreview: ").append(lastReason)
                }
                // F1 Known-Site Layer (2026-09-24): gazetteer context, not evidence.
                val knownSiteText = row.optString("known_site_text", "")
                if (knownSiteText.isNotEmpty() && knownSiteText != "null") {
                    append("\nknown site: ").append(knownSiteText)
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


    /** Builds the entire Hypotheses tab in code: a "state a new
     * hypothesis" EditText + submit button at the top, then one plain
     * row per existing hypothesis below. ADDED for Phase 2's
     * Hypothesis UI (user's own explicit request this session).
     * Rebuilds the whole container from scratch on every call
     * (removeAllViews() first, same as renderCandidateRows()) -- this
     * is also how a freshly submitted hypothesis ends up visible: after
     * a successful create, submitHypothesis() below calls
     * loadAndShowSuspend(HYPOTHESES) again, which re-fetches the real
     * list and calls this function again, which naturally clears
     * whatever the user had typed (acceptable here since it only
     * happens right after a successful submit, not while they're still
     * mid-typing).
     *
     * Hypothesis rows themselves are plain, non-clickable text -- no
     * drill-down for hypotheses in this pass. Linking a candidate to a
     * hypothesis happens the OTHER direction, from the Candidate Detail
     * dialog's own "Link to Hypothesis" button (see
     * showHypothesisPicker()), not from here. */
    private fun renderHypotheses(jsonText: String, grandProjectId: String) {
        val array = try {
            JSONArray(jsonText)
        } catch (e: Exception) {
            binding.containerCandidateRows.visibility = View.GONE
            binding.containerHypotheses.visibility = View.GONE
            binding.textGrandProjectResults.visibility = View.VISIBLE
            binding.textGrandProjectResults.text = "Could not parse results."
            return
        }

        binding.textGrandProjectResults.visibility = View.GONE
        binding.containerCandidateRows.visibility = View.GONE
        binding.containerHypotheses.visibility = View.VISIBLE
        binding.containerHypotheses.removeAllViews()

        val density = resources.displayMetrics.density

        val input = EditText(this).apply {
            hint = "State a new hypothesis..."
            setTextColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_text_primary))
            setHintTextColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_text_secondary))
            setPadding((12 * density).toInt(), (10 * density).toInt(), (12 * density).toInt(), (10 * density).toInt())
        }
        binding.containerHypotheses.addView(input)

        val submitButton = MaterialButton(this).apply {
            text = "State Hypothesis"
            setBackgroundColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_accent))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = (8 * density).toInt() }
            setOnClickListener {
                val statement = input.text.toString().trim()
                if (statement.isEmpty()) {
                    Toast.makeText(this@GrandProjectActivity, "Enter a hypothesis statement first.", Toast.LENGTH_SHORT).show()
                } else {
                    submitHypothesis(grandProjectId, statement)
                }
            }
        }
        binding.containerHypotheses.addView(submitButton)

        val spacer = View(this).apply {
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, (20 * density).toInt())
        }
        binding.containerHypotheses.addView(spacer)

        if (array.length() == 0) {
            val emptyView = TextView(this).apply {
                text = "No hypotheses stated yet for this Grand Project."
                typeface = Typeface.MONOSPACE
                textSize = 12f
                setTextColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_text_secondary))
            }
            binding.containerHypotheses.addView(emptyView)
            return
        }

        for (i in 0 until array.length()) {
            val row = array.getJSONObject(i)
            val rowText = buildString {
                append("#").append(i + 1).append("  ").append(row.optString("created_at")).append("\n")
                append(row.optString("statement")).append("\n")
                append("status: ").append(row.optString("current_status", "UNKNOWN"))
                if (!row.isNull("current_confidence")) {
                    append(String.format("   confidence: %.2f", row.optDouble("current_confidence")))
                }
            }
            val rowView = TextView(this).apply {
                text = rowText
                typeface = Typeface.MONOSPACE
                textSize = 12f
                setTextColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_text_secondary))
                setPadding(0, (10 * density).toInt(), 0, (10 * density).toInt())
            }
            binding.containerHypotheses.addView(rowView)
        }
    }

    /** Creates a new hypothesis, then refreshes the Hypotheses tab to
     * show it. The create step and the refresh step are handled with
     * SEPARATE try/catch blocks deliberately: if create_hypothesis_json
     * itself fails, the error message correctly says so and the
     * refresh is skipped entirely (return@launch); if create succeeds
     * but the FOLLOW-UP refresh fails for some unrelated reason, that
     * is reported as a refresh failure instead, not misattributed back
     * to the (already-successful) creation. Calls loadAndShowSuspend()
     * directly rather than the loadAndShow() wrapper, since this
     * function is already inside its own coroutine with its own
     * setLoading(true)/finally{setLoading(false)} -- calling the
     * wrapper here would launch a SECOND, independent coroutine whose
     * own loading-toggle would race this one's. */
    private fun submitHypothesis(grandProjectId: String, statement: String) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.Default) {
                    python.getModule("grand_project_query_mobile")
                        .callAttr("create_hypothesis_json", offlineDataRoot, grandProjectId, statement)
                        .toString()
                }
                Toast.makeText(this@GrandProjectActivity, "Hypothesis stated.", Toast.LENGTH_SHORT).show()
            } catch (e: PyException) {
                Toast.makeText(
                    this@GrandProjectActivity,
                    "Failed to state hypothesis: ${cleanErrorMessage(e.message)}",
                    Toast.LENGTH_LONG
                ).show()
                setLoading(false)
                return@launch
            }
            try {
                loadAndShowSuspend(ListKind.HYPOTHESES)
            } catch (e: PyException) {
                binding.containerCandidateRows.visibility = View.GONE
                binding.containerHypotheses.visibility = View.GONE
                binding.textGrandProjectResults.visibility = View.VISIBLE
                binding.textGrandProjectResults.text = "Hypothesis stated, but failed to refresh the list: ${cleanErrorMessage(e.message)}"
            } finally {
                setLoading(false)
            }
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
                    showDetailDialog(candidateId, formatCandidateDetail(detail))
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
            val reviewLabel = detail.optJSONObject("review")?.optString("status_label", "") ?: ""
            val shownStatus = if (reviewLabel.isNotEmpty() && reviewLabel != "null") reviewLabel else candidate.optString("status")
            sb.append("  status: ").append(shownStatus).append("\n")
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

        // ADDED for Phase 2's Hypothesis UI (linking pass). Null here
        // is the ORDINARY case for a candidate never linked to one --
        // see get_candidate_detail_json()'s own docstring note on this.
        val hypothesis = detail.optJSONObject("hypothesis")
        if (hypothesis != null) {
            sb.append("Linked Hypothesis\n")
            sb.append("  statement: ").append(hypothesis.optString("statement")).append("\n")
            sb.append("  status: ").append(hypothesis.optString("current_status", "UNKNOWN")).append("\n")
            if (!hypothesis.isNull("current_confidence")) {
                sb.append(String.format("  confidence: %.2f\n", hypothesis.optDouble("current_confidence")))
            }
            sb.append("\n")
        }
appendReviewSection(sb, detail)
        appendKnownSiteSection(sb, detail)
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
     * note on why drill-down avoided new XML surfaces this time. ADDED
     * for the Hypothesis UI linking pass: a Neutral "Link to
     * Hypothesis" button alongside the existing Positive "Close"
     * button, opening showHypothesisPicker() for this candidate. Note
     * that tapping either button dismisses this AlertDialog by default
     * (standard Android behavior, not overridden) -- if the user wants
     * to see the newly linked hypothesis reflected in THIS candidate's
     * own detail view, they simply tap the same candidate row again
     * afterward; this is a deliberately simple flow for a first pass,
     * not an attempt to keep the dialog open and refresh it in place. */
    private fun showDetailDialog(candidateId: String, text: String) {
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
            .setNegativeButton("Review") { _, _ -> showReviewPicker(candidateId) }
            .setNeutralButton("Hypothesis") { _, _ -> showHypothesisPicker(candidateId) }
            .show()
    }

    /** Fetches the real list of existing hypotheses for this project
     * and shows them as a native picker (AlertDialog.Builder().setItems(),
     * the simplest possible list-choice dialog, no new layout needed)
     * so the user can pick which one to link this candidate to. ADDED
     * for the Hypothesis UI linking pass, called from the "Link to
     * Hypothesis" button in showDetailDialog() above. Handles the
     * empty case explicitly (no hypotheses stated yet) with a plain
     * Toast pointing at the Hypotheses tab, rather than showing a
     * confusing empty picker. */
    private fun showHypothesisPicker(candidateId: String) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                val grandProjectId = getGrandProjectId()
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("grand_project_query_mobile")
                        .callAttr("list_hypotheses_json", offlineDataRoot, grandProjectId)
                        .toString()
                }
                val array = JSONArray(jsonText)
                if (array.length() == 0) {
                    Toast.makeText(
                        this@GrandProjectActivity,
                        "No hypotheses stated yet -- state one on the Hypotheses tab first.",
                        Toast.LENGTH_LONG
                    ).show()
                    return@launch
                }
                val statements: Array<CharSequence> = Array(array.length()) { i -> array.getJSONObject(i).optString("statement") }
                val hypothesisIds = Array(array.length()) { i -> array.getJSONObject(i).optString("id") }
                AlertDialog.Builder(this@GrandProjectActivity)
                    .setTitle("Link to which hypothesis?")
                    .setItems(statements) { _, which ->
                        linkCandidateToHypothesis(candidateId, hypothesisIds[which], statements[which].toString())
                    }
                    .show()
            } catch (e: PyException) {
                Toast.makeText(
                    this@GrandProjectActivity,
                    "Failed to load hypotheses: ${cleanErrorMessage(e.message)}",
                    Toast.LENGTH_LONG
                ).show()
            } finally {
                setLoading(false)
            }
        }
    }

    /** Links one candidate to one hypothesis via
     * link_candidate_to_hypothesis_json(). ADDED for the Hypothesis UI
     * linking pass. Deliberately does NOT try to re-open or refresh the
     * Candidate Detail dialog afterward -- the dialog is already closed
     * by this point (picking an item in showHypothesisPicker()'s
     * AlertDialog dismisses it, and the Candidate Detail dialog itself
     * was already dismissed when its own Neutral button was tapped) --
     * a confirmation Toast is enough; re-tapping the same candidate row
     * shows the update, same as the note on showDetailDialog() above. */
    private fun linkCandidateToHypothesis(candidateId: String, hypothesisId: String, statement: String) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.Default) {
                    python.getModule("grand_project_query_mobile")
                        .callAttr("link_candidate_to_hypothesis_json", offlineDataRoot, candidateId, hypothesisId)
                        .toString()
                }
                Toast.makeText(this@GrandProjectActivity, "Linked to hypothesis: $statement", Toast.LENGTH_LONG).show()
            } catch (e: PyException) {
                Toast.makeText(
                    this@GrandProjectActivity,
                    "Failed to link: ${cleanErrorMessage(e.message)}",
                    Toast.LENGTH_LONG
                ).show()
            } finally {
                setLoading(false)
            }
        }
    }
    // =================== ADDED 2026-09-24, PHASE 3 REVIEW UI ===================
    // User-set candidate status (Open / Supported / Rejected / Inconclusive,
    // always with a written reason) and user-set job trust (Trusted /
    // Corrupted / Unverified). Python side: grand_project_review.py via
    // grand_project_query_mobile.py. Never changes Steward confidence.

    private var hideRejected = false
    private var lastCandidatesJson: String? = null

    /** Adds the "Hide rejected" toggle and "Job trust..." button at the
     * top of the Candidates list. Called by renderCandidateRows() right
     * after it clears the container. */
    private fun addCandidateControls() {
        val density = resources.displayMetrics.density
        var rejectedCount = 0
        try {
            val all = JSONArray(lastCandidatesJson ?: "[]")
            for (k in 0 until all.length()) {
                if (all.getJSONObject(k).optString("status") == "REJECTED") rejectedCount++
            }
        } catch (e: Exception) {
            // leave count at 0
        }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding((8 * density).toInt(), (4 * density).toInt(), (8 * density).toInt(), (4 * density).toInt())
        }
        val hideButton = MaterialButton(this).apply {
            text = if (hideRejected) "Show rejected ($rejectedCount)" else "Hide rejected ($rejectedCount)"
            setBackgroundColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_accent))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginEnd = (8 * density).toInt() }
            setOnClickListener {
                hideRejected = !hideRejected
                lastCandidatesJson?.let { renderCandidateRows(it) }
            }
        }
        val trustButton = MaterialButton(this).apply {
            text = "Job trust..."
            setBackgroundColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_accent))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            setOnClickListener { showJobTrustStart() }
        }
        bar.addView(hideButton)
        bar.addView(trustButton)
        binding.containerCandidateRows.addView(bar)
    }

    /** Adds the "Review" and "Job" sections to the candidate detail text. */
    private fun appendReviewSection(sb: StringBuilder, detail: JSONObject) {
        val review = detail.optJSONObject("review")
        if (review != null) {
            sb.append("Review (user judgement, not Steward confidence)\n")
            sb.append("  status: ").append(review.optString("status_label")).append("\n")
            if (!review.isNull("job_id")) {
                sb.append("  job: ").append(review.optString("job_id").take(6))
                if (!review.isNull("job_trust")) {
                    sb.append("  trust: ").append(review.optString("job_trust"))
                    sb.append(" (").append(review.optString("job_trust_reason")).append(")")
                } else {
                    sb.append("  trust: not marked")
                }
                sb.append("\n")
            }
        }
        val history = detail.optJSONArray("review_history")
        if (history != null && history.length() > 0) {
            for (i in 0 until history.length()) {
                val h = history.getJSONObject(i)
                sb.append("  ").append(h.optString("reviewed_at")).append("  ")
                sb.append(h.optString("previous_status")).append(" -> ").append(h.optString("new_status")).append("\n")
                sb.append("      reason: ").append(h.optString("reason")).append("\n")
            }
        }
        if (review != null) sb.append("\n")
    }

    /** F1 Known-Site Layer (2026-09-24): nearest sites recorded in the
     * bundled ANE gazetteer (Pedersen, Zenodo 10.5281/zenodo.6384045,
     * CC-BY-4.0). Context only -- never evidence, never changes
     * confidence. "Not in gazetteer" does not mean "new site". */
    private fun appendKnownSiteSection(sb: StringBuilder, detail: JSONObject) {
        val ks = detail.optJSONObject("known_site") ?: return
        sb.append("Known Sites (gazetteer context, not evidence)\n")
        if (ks.has("error")) {
            sb.append("  ").append(ks.optString("error")).append("\n\n")
            return
        }
        sb.append("  ").append(ks.optString("text")).append("\n")
        val extents = ks.optJSONArray("extents_within_near")
        if (extents != null) {
            for (i in 0 until extents.length()) {
                val e = extents.getJSONObject(i)
                if (e.optBoolean("inside")) {
                    sb.append("  inside ").append(e.optString("kind")).append(": ").append(e.optString("name")).append("\n")
                } else {
                    sb.append(String.format("  %.0f m from %s: ", e.optDouble("distance_m"), e.optString("kind")))
                    sb.append(e.optString("name")).append("\n")
                }
            }
        }
        val nearest = ks.optJSONArray("nearest")
        if (nearest != null && nearest.length() > 0) {
            sb.append("  nearest recorded points:\n")
            for (i in 0 until nearest.length()) {
                val n = nearest.getJSONObject(i)
                val dKm = n.optDouble("distance_m") / 1000.0
                sb.append(String.format("    %.2f km  ", dKm)).append(n.optString("name")).append("\n")
            }
        }
        sb.append(String.format("  gazetteer points within %.0f km: %d\n",
            ks.optDouble("density_radius_km"), ks.optInt("density_points")))
        sb.append("  source: ").append(ks.optString("source")).append(" (").append(ks.optString("source_license")).append(")\n")
        sb.append("\n")
    }

    /** Asks for one line of text, then calls onOk with it (trimmed). */
    private fun promptText(
        title: String, hint: String, okLabel: String, message: String? = null, onOk: (String) -> Unit
    ) {
        val density = resources.displayMetrics.density
        val input = EditText(this).apply {
            this.hint = hint
            setTextColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_text_primary))
            setHintTextColor(ContextCompat.getColor(this@GrandProjectActivity, R.color.ariyan_text_secondary))
            val pad = (16 * density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        AlertDialog.Builder(this)
            .setTitle(title)
            .apply { if (message != null) setMessage(message) }
            .setView(input)
            .setPositiveButton(okLabel) { _, _ -> onOk(input.text.toString().trim()) }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /** Candidate review: pick a status, then write a reason. */
    private fun showReviewPicker(candidateId: String) {
        val labels: Array<CharSequence> = arrayOf("Open", "Supported", "Rejected", "Inconclusive")
        val values = arrayOf("OPEN", "SUPPORTED", "REJECTED", "INCONCLUSIVE")
        AlertDialog.Builder(this)
            .setTitle("Review candidate " + candidateId.take(8))
            .setItems(labels) { _, which ->
                promptText("Reason for " + labels[which], "e.g. satellite shows fish pond", "Save") { reason ->
                    callReviewWrite(
                        "set_candidate_status_json", listOf(candidateId, values[which], reason),
                        "Candidate marked " + labels[which]
                    )
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /** Job trust: shows current marks, asks for a job id (6+ characters),
     * then a trust level, then a reason. */
    private fun showJobTrustStart() {
        setLoading(true)
        lifecycleScope.launch {
            var current = ""
            try {
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("grand_project_query_mobile")
                        .callAttr("list_job_trust_json", offlineDataRoot).toString()
                }
                val arr = JSONArray(jsonText)
                val sb = StringBuilder()
                for (i in 0 until arr.length()) {
                    val r = arr.getJSONObject(i)
                    sb.append(r.optString("job_id").take(6)).append("  ").append(r.optString("trust"))
                        .append("  (").append(r.optString("reason")).append(")\n")
                }
                current = if (sb.isEmpty()) "No jobs marked yet." else sb.toString()
            } catch (e: Exception) {
                current = "Could not load current marks."
            } finally {
                setLoading(false)
            }
            promptText("Job trust", "job id, first 6+ characters, e.g. 0fdb99", "Next", current) { jobRef ->
                val labels: Array<CharSequence> = arrayOf("Trusted", "Corrupted", "Unverified")
                val values = arrayOf("TRUSTED", "CORRUPTED", "UNVERIFIED")
                AlertDialog.Builder(this@GrandProjectActivity)
                    .setTitle("Trust for job $jobRef")
                    .setItems(labels) { _, which ->
                        promptText("Reason for " + labels[which], "e.g. built with old COG reader", "Save") { reason ->
                            callReviewWrite(
                                "set_job_trust_json", listOf(jobRef, values[which], reason),
                                "Job $jobRef marked " + labels[which]
                            )
                        }
                    }
                    .setNegativeButton("Cancel", null)
                    .show()
            }
        }
    }

    /** Runs one review write in Python; shows its {"error"} message if any,
     * otherwise a confirmation toast and a refreshed Candidates list. */
    private fun callReviewWrite(fnName: String, args: List<Any>, okMessage: String) {
        setLoading(true)
        lifecycleScope.launch {
            var ok = false
            try {
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("grand_project_query_mobile")
                        .callAttr(fnName, offlineDataRoot, *args.toTypedArray()).toString()
                }
                val result = JSONObject(jsonText)
                if (result.has("error")) {
                    Toast.makeText(this@GrandProjectActivity, result.optString("error"), Toast.LENGTH_LONG).show()
                } else {
                    Toast.makeText(this@GrandProjectActivity, okMessage, Toast.LENGTH_SHORT).show()
                    ok = true
                }
            } catch (e: PyException) {
                Toast.makeText(
                    this@GrandProjectActivity,
                    "Failed to save: ${cleanErrorMessage(e.message)}",
                    Toast.LENGTH_LONG
                ).show()
            } finally {
                setLoading(false)
            }
            if (ok) loadAndShow(ListKind.CANDIDATES)
        }
    }
    // ================= END ADDED 2026-09-24, PHASE 3 REVIEW UI =================


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
     * above instead. ListKind.HYPOTHESES is likewise never routed
     * through here (ADDED same day, Hypothesis UI pass) -- see
     * renderHypotheses() instead. Kept here only for
     * INVESTIGATIONS/TIMELINE, which remain deliberately flat text
     * blocks. */
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
            ListKind.HYPOTHESES -> {
                // Never reached -- see renderHypotheses() instead,
                // same reason as the CANDIDATES case directly above.
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
