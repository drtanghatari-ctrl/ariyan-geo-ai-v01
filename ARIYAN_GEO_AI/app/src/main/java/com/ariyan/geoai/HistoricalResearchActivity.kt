package com.ariyan.geoai

import android.content.Intent
import android.graphics.Typeface
import android.os.Bundle
import android.util.TypedValue
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.ariyan.geoai.databinding.ActivityHistoricalResearchBinding
import com.chaquo.python.PyException
import com.chaquo.python.Python
import com.google.android.material.button.MaterialButton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/**
 * HistoricalResearchActivity -- Phase 2.5's Historical Research &
 * Probable-Area Engine, ADDED 2026-09-17. Until now none of that real
 * Python (`historical_source_mobile_combined.py`,
 * `historical_claim_extraction_mobile.py`,
 * `grand_project_historical_sync.py`) had any Kotlin call path at all;
 * see `historical_research_mobile.py`'s own module doc for why that
 * mattered (a real broken-import bug in that pipeline went undetected
 * for an entire prior session as a direct result).
 *
 * TWO TABS, same button-switch pattern as every other screen built this
 * session: "Search" (ask a free-text question, run the real three-
 * source fetch + extraction, preview the result, then explicitly Save
 * it -- searching never silently writes to the database) and "Saved
 * Suggestions" (every `geographic_suggestion` row saved for this
 * project; a `PAIRED_SUGGESTION` row gets a "Start Wide-Area Search"
 * button, which is AOI mechanism (c) -- turning a reviewed suggestion
 * directly into a wide-area search job via
 * `wide_area_search_mobile.create_wide_area_search_job_from_
 * suggestion_json()`). `DISTANCE_ONLY`/`UNGROUNDED_PLACE` rows are
 * shown read-only, since they carry no real coordinates to act on.
 *
 * All content built entirely in Kotlin code into two empty XML
 * containers, same discipline as every other screen this session (see
 * `activity_historical_research.xml`'s own class doc for why).
 *
 * PROJECT SCOPE: uses the SAME interim stopgap every other Grand-
 * Project-aware screen already uses --
 * `grand_project_sync.get_or_create_default_grand_project()` -- since
 * no real Grand Project selection UI exists yet.
 */
class HistoricalResearchActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHistoricalResearchBinding
    private lateinit var python: Python

    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }

    // The most recently RUN (but not necessarily yet saved) search
    // result, held in memory so the "Save These Results" button can
    // persist exactly what's on screen without re-running the search.
    // Cleared (set to null) once saved, so a stale save can't be
    // accidentally repeated.
    private var lastCombinedEvidenceJson: String? = null
    private var lastSuggestionsJson: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityHistoricalResearchBinding.inflate(layoutInflater)
        setContentView(binding.root)

        python = Python.getInstance()

        binding.buttonShowSearch.setOnClickListener { showSearchTab() }
        binding.buttonShowSaved.setOnClickListener { loadSavedTab() }

        showSearchTab()
    }

    // =========================== SEARCH TAB ===========================

    private fun showSearchTab() {
        binding.containerSaved.visibility = View.GONE
        binding.containerSearch.visibility = View.VISIBLE
        binding.containerSearch.removeAllViews()
        renderSearchForm()
    }

    /** Builds the question field and Search button. Rebuilt from
     * scratch each time the Search tab is shown, same
     * removeAllViews() convention as every other screen this
     * session. */
    private fun renderSearchForm() {
        val density = resources.displayMetrics.density

        val label = TextView(this).apply {
            text = "Historical question"
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_secondary))
            textSize = 12f
            setPadding(0, (4 * density).toInt(), 0, (4 * density).toInt())
        }
        binding.containerSearch.addView(label)

        val inputQuery = EditText(this).apply {
            hint = "e.g. Darius III treasure Persepolis"
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_primary))
            setHintTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_secondary))
            setPadding((12 * density).toInt(), (10 * density).toInt(), (12 * density).toInt(), (10 * density).toInt())
        }
        binding.containerSearch.addView(inputQuery)

        val buttonSearch = MaterialButton(this).apply {
            text = "Search"
            setBackgroundColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_accent))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = (12 * density).toInt() }
            setOnClickListener {
                val query = inputQuery.text.toString().trim()
                if (query.isEmpty()) {
                    Toast.makeText(this@HistoricalResearchActivity, "Enter a question first.", Toast.LENGTH_SHORT).show()
                } else {
                    runSearch(query)
                }
            }
        }
        binding.containerSearch.addView(buttonSearch)
    }

    /** Runs the real, live three-source search + extraction (can take
     * several real seconds -- suggest_probable_areas() does its own
     * real Nominatim geocoding per candidate place), then renders a
     * READ-ONLY preview of the result plus a "Save These Results"
     * button. Nothing is written to the database until that button is
     * tapped. */
    private fun runSearch(query: String) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                val resultJson = withContext(Dispatchers.Default) {
                    python.getModule("historical_research_mobile")
                        .callAttr("run_historical_research_json", query)
                        .toString()
                }
                val result = JSONObject(resultJson)
                lastCombinedEvidenceJson = result.getJSONObject("combined_evidence").toString()
                lastSuggestionsJson = result.getJSONObject("suggestions").toString()
                renderSearchResults(result)
            } catch (e: PyException) {
                Toast.makeText(this@HistoricalResearchActivity, "Search failed: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            } finally {
                setLoading(false)
            }
        }
    }

    private fun renderSearchResults(result: JSONObject) {
        // Keep the question field + Search button, just clear anything
        // rendered below a previous search (containerSearch already
        // holds the form from renderSearchForm() -- this appends below
        // it rather than wiping the whole tab, so re-searching doesn't
        // lose the typed question).
        val density = resources.displayMetrics.density
        val evidence = result.getJSONObject("combined_evidence")
        val suggestions = result.getJSONObject("suggestions")
        val sourceCounts = evidence.getJSONObject("source_counts")
        val sourceErrors = evidence.getJSONObject("source_errors")

        val summary = buildString {
            append("Sources: ")
            val keys = sourceCounts.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                append(key).append("=").append(sourceCounts.getInt(key))
                val err = sourceErrors.optString(key, "")
                if (err.isNotEmpty() && err != "null") append(" (error)")
                if (keys.hasNext()) append(", ")
            }
        }
        binding.containerSearch.addView(plainText(summary))

        val suggestedAreas = suggestions.getJSONArray("suggested_areas")
        if (suggestedAreas.length() == 0) {
            binding.containerSearch.addView(plainText("No paired place+distance suggestions found in this search's results. Try a different or more specific question -- short search snippets don't always contain that kind of phrasing."))
        } else {
            for (i in 0 until suggestedAreas.length()) {
                val area = suggestedAreas.getJSONObject(i)
                val anchor = area.getJSONObject("anchor")
                val radius = area.getJSONObject("radius")
                val sourceItem = area.getJSONObject("source_item")
                val text = buildString {
                    append("Suggestion #").append(i + 1).append(": ")
                    append(anchor.optString("resolved_name", anchor.optString("query", "?"))).append("\n")
                    append("  radius: ").append(radius.optDouble("value")).append(" ").append(radius.optString("unit")).append("\n")
                    append("  from: ").append(sourceItem.optString("title")).append(" (").append(sourceItem.optString("source")).append(")\n")
                    append("  context: ").append(area.optString("context").take(160))
                }
                binding.containerSearch.addView(plainText(text))
            }
        }

        val buttonSave = MaterialButton(this).apply {
            text = "Save These Results"
            setBackgroundColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_accent))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = (12 * density).toInt() }
            setOnClickListener { saveSearchResults() }
        }
        binding.containerSearch.addView(buttonSave)
    }

    /** Persists whatever the last real search run produced (exactly as
     * `run_historical_research_json()` returned it, unmodified) via
     * `save_historical_research_json()`. Refuses to run twice in a row
     * on the same result (lastCombinedEvidenceJson/lastSuggestionsJson
     * are cleared to null immediately after a successful save) -- a
     * second tap without a new search first is a no-op with a plain
     * Toast, not a silent duplicate save. */
    private fun saveSearchResults() {
        val evidenceJson = lastCombinedEvidenceJson
        val suggestionsJson = lastSuggestionsJson
        if (evidenceJson == null || suggestionsJson == null) {
            Toast.makeText(this, "Nothing new to save -- run a search first.", Toast.LENGTH_SHORT).show()
            return
        }
        setLoading(true)
        lifecycleScope.launch {
            try {
                val grandProjectId = getGrandProjectId()
                val resultJson = withContext(Dispatchers.Default) {
                    python.getModule("historical_research_mobile").callAttr(
                        "save_historical_research_json",
                        offlineDataRoot, grandProjectId, evidenceJson, suggestionsJson,
                    ).toString()
                }
                val result = JSONObject(resultJson)
                val suggestionIds = result.getJSONArray("geographic_suggestion_ids")
                Toast.makeText(
                    this@HistoricalResearchActivity,
                    "Saved ${suggestionIds.length()} suggestion(s).",
                    Toast.LENGTH_LONG
                ).show()
                lastCombinedEvidenceJson = null
                lastSuggestionsJson = null
                loadSavedTab()
            } catch (e: PyException) {
                Toast.makeText(this@HistoricalResearchActivity, "Save failed: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            } finally {
                setLoading(false)
            }
        }
    }

    // =========================== SAVED SUGGESTIONS TAB ===========================

    private fun loadSavedTab() {
        setLoading(true)
        lifecycleScope.launch {
            try {
                val grandProjectId = getGrandProjectId()
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("historical_research_mobile")
                        .callAttr("list_geographic_suggestions_json", offlineDataRoot, grandProjectId)
                        .toString()
                }
                renderSavedSuggestions(jsonText)
            } catch (e: PyException) {
                binding.containerSearch.visibility = View.GONE
                binding.containerSaved.visibility = View.VISIBLE
                binding.containerSaved.removeAllViews()
                binding.containerSaved.addView(plainText("Failed to load saved suggestions: ${cleanErrorMessage(e.message)}"))
            } finally {
                setLoading(false)
            }
        }
    }

    private fun plainText(text: String): TextView {
        val density = resources.displayMetrics.density
        return TextView(this).apply {
            this.text = text
            typeface = Typeface.MONOSPACE
            textSize = 12f
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_secondary))
            setPadding(0, (10 * density).toInt(), 0, (10 * density).toInt())
        }
    }

    /** Real fields per row, exactly as
     * `list_geographic_suggestions_json()` (a thin wrapper over
     * `grand_project_db.get_geographic_suggestions_for_project()`)
     * returns them. A `PAIRED_SUGGESTION` row (the only kind with real
     * lat/lon/radius) gets a "Start Wide-Area Search" button --
     * `DISTANCE_ONLY`/`UNGROUNDED_PLACE` rows are shown read-only. */
    private fun renderSavedSuggestions(jsonText: String) {
        binding.containerSearch.visibility = View.GONE
        binding.containerSaved.visibility = View.VISIBLE
        binding.containerSaved.removeAllViews()

        val array = try {
            JSONArray(jsonText)
        } catch (e: Exception) {
            binding.containerSaved.addView(plainText("Could not parse results."))
            return
        }
        if (array.length() == 0) {
            binding.containerSaved.addView(plainText("No saved suggestions yet -- run a search and tap \"Save These Results\"."))
            return
        }

        val density = resources.displayMetrics.density
        for (i in 0 until array.length()) {
            val row = array.getJSONObject(i)
            val kind = row.optString("kind")
            val text = buildString {
                append("#").append(i + 1).append("  ").append(kind).append("\n")
                if (kind == "PAIRED_SUGGESTION") {
                    append("  ").append(row.optString("resolved_name", row.optString("place_name"))).append("\n")
                    append("  radius: ").append(row.optDouble("radius_value")).append(" ").append(row.optString("radius_unit")).append("\n")
                }
                val context = row.optString("context", "")
                if (context.isNotEmpty()) append("  context: ").append(context.take(140)).append("\n")
                append("  status: ").append(row.optString("status"))
            }
            binding.containerSaved.addView(plainText(text))

            if (kind == "PAIRED_SUGGESTION" && !row.isNull("lat") && !row.isNull("lon")) {
                val buttonStart = MaterialButton(this).apply {
                    this.text = "Start Wide-Area Search"
                    setBackgroundColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_surface))
                    setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_primary))
                    layoutParams = LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
                    ).apply { topMargin = (2 * density).toInt(); bottomMargin = (12 * density).toInt() }
                    setOnClickListener { showStartJobDialog(row) }
                }
                binding.containerSaved.addView(buttonStart)
            }
        }
    }

    /** AOI mechanism (c): prompts for a job title and tile size, then
     * calls `wide_area_search_mobile.create_wide_area_search_job_from_
     * suggestion_json()` with this suggestion's own real lat/lon/
     * radius -- turning a reviewed suggestion directly into a wide-area
     * search job. Converts radius_unit="miles" to km first, since that
     * function's own real parameter is radius_km specifically (the
     * suggestion row preserves whatever unit the original source text
     * used, per suggest_probable_areas()'s own real parsing -- this is
     * the one place that unit choice actually needs to become a single
     * consistent number). The created job then shows up in Wide-Area
     * Search's own Jobs tab like any other job -- this dialog does not
     * duplicate that screen's own start/monitor UI. */
    private fun showStartJobDialog(suggestionRow: JSONObject) {
        val density = resources.displayMetrics.density
        val lat = suggestionRow.optDouble("lat")
        val lon = suggestionRow.optDouble("lon")
        var radiusKm = suggestionRow.optDouble("radius_value", 1.0)
        val unit = suggestionRow.optString("radius_unit", "km")
        if (unit.equals("miles", ignoreCase = true)) {
            radiusKm *= 1.60934
        }

        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (16 * density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        val inputTitle = EditText(this).apply {
            hint = "Job title"
            setText(suggestionRow.optString("resolved_name", suggestionRow.optString("place_name", "Suggestion-derived search")))
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_primary))
        }
        val inputTileSize = EditText(this).apply {
            hint = "Tile size (meters)"
            setText("1000")
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_primary))
        }
        val info = TextView(this).apply {
            text = "Center: %.4f, %.4f  --  radius %.2f km".format(lat, lon, radiusKm)
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_secondary))
            textSize = 12f
            setPadding(0, (8 * density).toInt(), 0, (8 * density).toInt())
        }
        container.addView(inputTitle)
        container.addView(info)
        container.addView(inputTileSize)

        AlertDialog.Builder(this)
            .setTitle("Start Wide-Area Search")
            .setView(container)
            .setPositiveButton("Create Job") { _, _ ->
                val title = inputTitle.text.toString().trim()
                val tileSize = inputTileSize.text.toString().trim().toDoubleOrNull()
                if (title.isEmpty() || tileSize == null || tileSize <= 0) {
                    Toast.makeText(this, "Enter a title and a valid tile size.", Toast.LENGTH_LONG).show()
                    return@setPositiveButton
                }
                createJobFromSuggestion(suggestionRow, title, lat, lon, radiusKm, tileSize)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun createJobFromSuggestion(
        suggestionRow: JSONObject, title: String, lat: Double, lon: Double, radiusKm: Double, tileSizeM: Double
    ) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                val grandProjectId = getGrandProjectId()
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("wide_area_search_mobile").callAttr(
                        "create_wide_area_search_job_from_suggestion_json",
                        offlineDataRoot, grandProjectId, title, lat, lon, radiusKm,
                        com.chaquo.python.Kwarg("tile_size_m", tileSizeM),
                        com.chaquo.python.Kwarg("geographic_suggestion_id", suggestionRow.optString("id")),
                    ).toString()
                }
                val result = JSONObject(jsonText)
                if (result.has("error")) {
                    Toast.makeText(this@HistoricalResearchActivity, result.optString("error"), Toast.LENGTH_LONG).show()
                } else {
                    Toast.makeText(
                        this@HistoricalResearchActivity,
                        "Job created with ${result.optInt("n_tiles")} tiles. Start it from the Wide-Area Search screen's Jobs tab.",
                        Toast.LENGTH_LONG
                    ).show()
                    startActivity(Intent(this@HistoricalResearchActivity, WideAreaSearchActivity::class.java))
                }
            } catch (e: PyException) {
                Toast.makeText(this@HistoricalResearchActivity, "Failed to create job: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            } finally {
                setLoading(false)
            }
        }
    }

    // =========================== SHARED ===========================

    private suspend fun getGrandProjectId(): String = withContext(Dispatchers.Default) {
        python.getModule("grand_project_sync")
            .callAttr("get_or_create_default_grand_project", offlineDataRoot)
            .toString()
    }

    private fun cleanErrorMessage(raw: String?): String {
        if (raw.isNullOrBlank()) return "Unknown Python error"
        return raw.substringBefore("\n\n").trim()
    }

    private fun setLoading(loading: Boolean) {
        binding.progressBarHistoricalResearch.visibility = if (loading) View.VISIBLE else View.GONE
        binding.buttonShowSearch.isEnabled = !loading
        binding.buttonShowSaved.isEnabled = !loading
    }
}

