package com.ariyan.geoai

import android.content.Intent
import android.graphics.Typeface
import android.os.Bundle
import android.text.method.LinkMovementMethod
import android.text.util.Linkify
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
import java.util.Locale

/**
 * HistoricalResearchActivity -- Phase 2.5's Historical Research screen,
 * ADDED 2026-09-17, SEARCH TAB REBUILT 2026-10-01 (Historical Search
 * rebuild, step 2, engine hs-v1).
 *
 * SEARCH TAB (rebuilt): calls `historical_research_mobile.
 * run_historical_search_json()` -- English + Persian Wikipedia, Wikidata,
 * Pleiades, OpenAlex (see historical_search_engine.py). Shows:
 *   - per-source counts and every source error in full;
 *   - LOCATED findings: each coordinate with its source and tier
 *     (A = Pleiades precise, B = Wikidata/Wikipedia), Iran flag, caveat,
 *     tappable links. Order = the sources' own search rank, not
 *     likelihood. No confidence percentages anywhere.
 *   - findings with NO coordinate, and LITERATURE (OpenAlex, pointers only).
 * Each located finding has its own "Save" button (saves only that one,
 * kind LOCATED_FINDING, via save_located_finding_json(); saving the same
 * finding twice does not duplicate rows) and "Wide-Area Search..." (saves
 * it first, then asks for a radius -- no radius is ever taken from text).
 *
 * The OLD word-guessing route (capitalised words in snippets geocoded
 * worldwide by Nominatim, e.g. "Persian Gate" -> England/France) is
 * SWITCHED OFF here by the user's decision of 2026-10-01. Its Python is
 * still in the repo and its already-saved rows still show in the Saved
 * tab.
 *
 * SAVED TAB: every geographic_suggestion row for this project. Only
 * LOCATED_FINDING rows get a "Start Wide-Area Search" button (AOI
 * mechanism (c)). Legacy PAIRED_SUGGESTION rows (old route) are
 * read-only since hs-v1.1, as are DISTANCE_ONLY / UNGROUNDED_PLACE rows.
 * Findings whose coordinate the engine WITHHELD (hs-v1.1 not-a-place
 * rule: languages, empires, people, whole-degree placeholders) appear
 * under "Found, but no coordinate" with the reason.
 *
 * All content is built in code into the two empty XML containers, same
 * discipline as every other screen. Project scope: the same interim
 * get_or_create_default_grand_project() stopgap as every other screen.
 */
class HistoricalResearchActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHistoricalResearchBinding
    private lateinit var python: Python

    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }

    // The most recent search result JSON, exactly as Python returned it,
    // so each Save passes back the SAME result it was shown from.
    private var lastSearchJson: String? = null

    // Number of views the search form itself occupies at the top of
    // containerSearch; results are appended after them and cleared on
    // every new search (the old screen kept stacking old results).
    private var searchFormViewCount = 0

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

    private fun renderSearchForm() {
        val density = resources.displayMetrics.density

        val label = TextView(this).apply {
            text = "Historical question (English or Persian)"
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_secondary))
            textSize = 12f
            setPadding(0, (4 * density).toInt(), 0, (4 * density).toInt())
        }
        binding.containerSearch.addView(label)

        val inputQuery = EditText(this).apply {
            hint = "e.g. Where was the battle of the Persian Gate? / \u0645\u062d\u0644 \u0646\u0628\u0631\u062f \u062f\u0631\u0628\u0646\u062f \u067e\u0627\u0631\u0633"
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

        binding.containerSearch.addView(plainText(
            "Searches English and Persian Wikipedia, Wikidata, Pleiades and OpenAlex. " +
                "Can take up to about a minute. Nothing is saved unless you tap Save on a result."
        ))

        searchFormViewCount = binding.containerSearch.childCount
    }

    private fun clearSearchResults() {
        val extra = binding.containerSearch.childCount - searchFormViewCount
        if (extra > 0) binding.containerSearch.removeViews(searchFormViewCount, extra)
    }

    private fun runSearch(query: String) {
        clearSearchResults()
        lastSearchJson = null
        setLoading(true)
        lifecycleScope.launch {
            try {
                val resultJson = withContext(Dispatchers.Default) {
                    python.getModule("historical_research_mobile")
                        .callAttr("run_historical_search_json", query)
                        .toString()
                }
                val result = JSONObject(resultJson)
                if (result.has("error")) {
                    binding.containerSearch.addView(plainText("Search failed: " + str(result, "error")))
                } else {
                    lastSearchJson = resultJson
                    renderSearchResults(result)
                }
            } catch (e: PyException) {
                Toast.makeText(this@HistoricalResearchActivity, "Search failed: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            } catch (e: Exception) {
                Toast.makeText(this@HistoricalResearchActivity, "Search failed: ${e.message}", Toast.LENGTH_LONG).show()
            } finally {
                setLoading(false)
            }
        }
    }

    private fun renderSearchResults(result: JSONObject) {
        val counts = result.optJSONObject("source_counts") ?: JSONObject()
        val errors = result.optJSONObject("source_errors") ?: JSONObject()

        val summary = buildString {
            append("Searched: ").append(str(result, "keyword_query"))
            append("  (").append(str(result, "query_script")).append(")\n")
            append("Sources: ")
            val keys = counts.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                append(key).append("=").append(counts.optInt(key))
                if (str(errors, key).isNotEmpty()) append(" (error)")
                if (keys.hasNext()) append(", ")
            }
            val ek = errors.keys()
            while (ek.hasNext()) {
                val key = ek.next()
                val err = str(errors, key)
                if (err.isNotEmpty()) append("\n  ").append(key).append(": ").append(err.take(220))
            }
        }
        binding.containerSearch.addView(plainText(summary))

        binding.containerSearch.addView(plainText(
            "Order = the sources' own search rank, not likelihood.\n" +
                "Tier A = Pleiades scholarly gazetteer, precise location.\n" +
                "Tier B = Wikidata / Wikipedia (community-edited).\n" +
                "A coordinate is where the source records the subject, not a verified archaeological position."
        ))

        val located = result.optJSONArray("located_findings") ?: JSONArray()
        binding.containerSearch.addView(heading("Located (${located.length()})"))
        if (located.length() == 0) {
            binding.containerSearch.addView(plainText("No source recorded a coordinate for this search. Try the place or event name itself, in English or Persian."))
        }
        for (i in 0 until located.length()) {
            val f = located.getJSONObject(i)
            binding.containerSearch.addView(linkText(locatedFindingText(i + 1, f)))
            addFindingButtons(f)
        }

        val unlocated = result.optJSONArray("unlocated_findings") ?: JSONArray()
        if (unlocated.length() > 0) {
            binding.containerSearch.addView(heading("Found, but no coordinate (${unlocated.length()})"))
            val text = buildString {
                for (i in 0 until unlocated.length()) {
                    val f = unlocated.getJSONObject(i)
                    append("- ").append(titleLine(f))
                    val caveat = str(f, "caveat")
                    if (caveat.contains("COORDINATE WITHHELD")) {
                        append("\n    ").append("COORDINATE WITHHELD" + caveat.substringAfter("COORDINATE WITHHELD").take(180))
                    } else if (caveat.contains("ROUGH") || caveat.contains("UNLOCATED")) {
                        append("\n    ").append(caveat.substringAfter("archaeological position. ").take(160))
                    }
                    val link = firstLink(f)
                    if (link.isNotEmpty()) append("\n    ").append(link)
                    if (i < unlocated.length() - 1) append("\n")
                }
            }
            binding.containerSearch.addView(linkText(text))
        }

        val literature = result.optJSONArray("literature") ?: JSONArray()
        if (literature.length() > 0) {
            binding.containerSearch.addView(heading("Literature (OpenAlex, title match only, ${literature.length()})"))
            val text = buildString {
                for (i in 0 until literature.length()) {
                    val w = literature.getJSONObject(i)
                    append("- ").append(str(w, "year")).append("  ").append(str(w, "title"))
                    val url = str(w, "url")
                    if (url.isNotEmpty()) append("\n    ").append(url)
                    if (i < literature.length() - 1) append("\n")
                }
            }
            binding.containerSearch.addView(linkText(text))
        }
    }

    private fun locatedFindingText(rank: Int, f: JSONObject): String = buildString {
        append("#").append(rank).append(" [").append(str(f, "best_tier")).append("] ").append(titleLine(f)).append("\n")
        val iran = if (f.isNull("in_iran")) "not recorded" else if (f.optBoolean("in_iran")) "yes" else "NO"
        append("  Iran: ").append(iran)
        val types = f.optJSONArray("instance_of")
        if (types != null && types.length() > 0) {
            val labels = mutableListOf<String>()
            for (t in 0 until minOf(3, types.length())) labels.add(str(types.getJSONObject(t), "label"))
            append("   type: ").append(labels.filter { it.isNotEmpty() }.joinToString(", "))
        }
        val date = str(f, "date")
        if (date.isNotEmpty()) append("   date: ").append(date)
        append("\n")
        val coords = f.optJSONArray("coordinates") ?: JSONArray()
        for (c in 0 until coords.length()) {
            val co = coords.getJSONObject(c)
            append("  ").append(str(co, "tier")).append(" ").append(str(co, "source")).append("  ")
            append(String.format(Locale.US, "%.5f, %.5f", co.optDouble("lat"), co.optDouble("lon")))
            if (!co.isNull("referenced")) {
                append(if (co.optBoolean("referenced")) "  (cited)" else "  (no citation)")
            }
            append("\n")
        }
        val caveat = str(f, "caveat")
        if (caveat.isNotEmpty()) append("  ").append(caveat).append("\n")
        val evidence = f.optJSONArray("evidence")
        if (evidence != null && evidence.length() > 0) {
            val t = str(evidence.getJSONObject(0), "text")
            if (t.isNotEmpty()) append("  \"").append(t.take(200)).append(if (t.length > 200) "...\"\n" else "\"\n")
        }
        val links = f.optJSONObject("links") ?: JSONObject()
        for (k in listOf("wikidata", "pleiades", "wikipedia_en")) {
            val u = str(links, k)
            if (u.isNotEmpty()) append("  ").append(u).append("\n")
        }
        if (str(links, "wikipedia_en").isEmpty() && str(links, "wikipedia_fa").isNotEmpty()) {
            append("  ").append(str(links, "wikipedia_fa")).append("\n")
        }
    }.trimEnd()

    private fun titleLine(f: JSONObject): String {
        val en = str(f, "title_en").ifEmpty { str(f, "title") }
        val fa = str(f, "title_fa")
        return if (fa.isNotEmpty() && fa != en) "$en / $fa" else en
    }

    private fun firstLink(f: JSONObject): String {
        val links = f.optJSONObject("links") ?: return ""
        for (k in listOf("wikidata", "pleiades", "wikipedia_en", "wikipedia_fa")) {
            val u = str(links, k)
            if (u.isNotEmpty()) return u
        }
        return ""
    }

    private fun addFindingButtons(f: JSONObject) {
        val density = resources.displayMetrics.density
        val key = str(f, "key")
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = (14 * density).toInt() }
        }
        val buttonSave = MaterialButton(this).apply {
            text = "Save"
            setBackgroundColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_surface))
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_primary))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                .apply { rightMargin = (4 * density).toInt() }
        }
        val buttonArea = MaterialButton(this).apply {
            text = "Wide-Area Search..."
            setBackgroundColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_surface))
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_primary))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                .apply { leftMargin = (4 * density).toInt() }
        }
        buttonSave.setOnClickListener { saveFinding(key, buttonSave, false) }
        buttonArea.setOnClickListener { saveFinding(key, buttonSave, true) }
        row.addView(buttonSave)
        row.addView(buttonArea)
        binding.containerSearch.addView(row)
    }

    /** Saves ONE located finding (duplicate-safe on the Python side).
     * When thenStartJob is true, opens the Wide-Area Search dialog for
     * the saved row afterwards. */
    private fun saveFinding(findingKey: String, saveButton: MaterialButton, thenStartJob: Boolean) {
        val searchJson = lastSearchJson
        if (searchJson == null) {
            Toast.makeText(this, "Run a search first.", Toast.LENGTH_SHORT).show()
            return
        }
        setLoading(true)
        lifecycleScope.launch {
            try {
                val grandProjectId = getGrandProjectId()
                val resultJson = withContext(Dispatchers.Default) {
                    python.getModule("historical_research_mobile").callAttr(
                        "save_located_finding_json",
                        offlineDataRoot, grandProjectId, searchJson, findingKey,
                    ).toString()
                }
                val result = JSONObject(resultJson)
                if (result.has("error")) {
                    Toast.makeText(this@HistoricalResearchActivity, "Save failed: " + str(result, "error"), Toast.LENGTH_LONG).show()
                    return@launch
                }
                // Button stays enabled: tapping again re-asks Python, which
                // answers "already saved" without creating a duplicate.
                saveButton.text = "Saved"
                if (!thenStartJob) {
                    Toast.makeText(
                        this@HistoricalResearchActivity,
                        if (result.optBoolean("already_saved")) "Already saved earlier." else "Saved.",
                        Toast.LENGTH_SHORT
                    ).show()
                    return@launch
                }
                val suggestionId = str(result, "geographic_suggestion_id")
                val primary = result.optJSONObject("primary")
                if (suggestionId.isEmpty() || primary == null) {
                    Toast.makeText(this@HistoricalResearchActivity, "Saved, but no suggestion row was found to start from.", Toast.LENGTH_LONG).show()
                    return@launch
                }
                val located = JSONObject(searchJson).optJSONArray("located_findings") ?: JSONArray()
                var name = findingKey
                for (i in 0 until located.length()) {
                    val f = located.getJSONObject(i)
                    if (str(f, "key") == findingKey) { name = titleLine(f); break }
                }
                val row = JSONObject().apply {
                    put("id", suggestionId)
                    put("kind", "LOCATED_FINDING")
                    put("lat", primary.optDouble("lat"))
                    put("lon", primary.optDouble("lon"))
                    put("resolved_name", name)
                }
                showStartJobDialog(row)
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
            binding.containerSaved.addView(plainText("No saved suggestions yet. Run a search and tap Save on a located result."))
            return
        }

        val density = resources.displayMetrics.density
        for (i in 0 until array.length()) {
            val row = array.getJSONObject(i)
            val kind = str(row, "kind")
            val text = buildString {
                append("#").append(i + 1).append("  ").append(kind).append("\n")
                if (kind == "LOCATED_FINDING") {
                    append("  ").append(str(row, "resolved_name").ifEmpty { str(row, "place_name") }).append("\n")
                    append("  ").append(String.format(Locale.US, "%.5f, %.5f", row.optDouble("lat"), row.optDouble("lon"))).append("\n")
                } else if (kind == "PAIRED_SUGGESTION") {
                    append("  ").append(str(row, "resolved_name").ifEmpty { str(row, "place_name") }).append("\n")
                    append("  radius: ").append(row.optDouble("radius_value")).append(" ").append(str(row, "radius_unit")).append("\n")
                    append("  (old word-guessing route, switched off 2026-10-01; kept for the record, cannot start a job)\n")
                }
                val context = str(row, "context")
                val limit = if (kind == "LOCATED_FINDING") 600 else 140
                if (context.isNotEmpty()) append("  context: ").append(context.take(limit)).append("\n")
                append("  status: ").append(str(row, "status"))
            }
            binding.containerSaved.addView(plainText(text))

            // Only LOCATED_FINDING rows can start a job (2026-10-01): legacy
            // PAIRED_SUGGESTION rows came from the switched-off word-guessing
            // route (e.g. a Galway, Ireland anchor) and stay read-only.
            val startable = kind == "LOCATED_FINDING" && !row.isNull("lat") && !row.isNull("lon")
            if (startable) {
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

    /** AOI mechanism (c): asks for job title, RADIUS and tile size, then
     * calls create_wide_area_search_job_from_suggestion_json(). A
     * LOCATED_FINDING row has no radius, so the radius field starts empty
     * and must be typed; a legacy PAIRED_SUGGESTION row pre-fills its
     * stored radius (miles converted to km). */
    private fun showStartJobDialog(suggestionRow: JSONObject) {
        val density = resources.displayMetrics.density
        val lat = suggestionRow.optDouble("lat")
        val lon = suggestionRow.optDouble("lon")
        var prefillRadiusKm: Double? = null
        if (!suggestionRow.isNull("radius_value") && suggestionRow.has("radius_value")) {
            var r = suggestionRow.optDouble("radius_value")
            if (str(suggestionRow, "radius_unit").equals("miles", ignoreCase = true)) r *= 1.60934
            if (!r.isNaN() && r > 0) prefillRadiusKm = r
        }

        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (16 * density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        val inputTitle = EditText(this).apply {
            hint = "Job title"
            setText(str(suggestionRow, "resolved_name").ifEmpty { str(suggestionRow, "place_name").ifEmpty { "Suggestion-derived search" } })
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_primary))
        }
        val info = TextView(this).apply {
            text = String.format(Locale.US, "Center: %.5f, %.5f", lat, lon)
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_secondary))
            textSize = 12f
            setPadding(0, (8 * density).toInt(), 0, (8 * density).toInt())
        }
        val inputRadius = EditText(this).apply {
            hint = "Radius (km), your choice"
            if (prefillRadiusKm != null) setText(String.format(Locale.US, "%.2f", prefillRadiusKm))
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_primary))
        }
        val inputTileSize = EditText(this).apply {
            hint = "Tile size (meters)"
            setText("1000")
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_text_primary))
        }
        container.addView(inputTitle)
        container.addView(info)
        container.addView(inputRadius)
        container.addView(inputTileSize)

        AlertDialog.Builder(this)
            .setTitle("Start Wide-Area Search")
            .setView(container)
            .setPositiveButton("Create Job") { _, _ ->
                val title = inputTitle.text.toString().trim()
                val radiusKm = inputRadius.text.toString().trim().toDoubleOrNull()
                val tileSize = inputTileSize.text.toString().trim().toDoubleOrNull()
                if (title.isEmpty() || radiusKm == null || radiusKm <= 0 || tileSize == null || tileSize <= 0) {
                    Toast.makeText(this, "Enter a title, a radius in km and a valid tile size.", Toast.LENGTH_LONG).show()
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
                        com.chaquo.python.Kwarg("geographic_suggestion_id", str(suggestionRow, "id")),
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

    /** org.json returns the text "null" for JSON null; this returns "". */
    private fun str(obj: JSONObject, key: String): String =
        if (!obj.has(key) || obj.isNull(key)) "" else obj.optString(key, "")

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

    /** Same as plainText, with web links made tappable. */
    private fun linkText(text: String): TextView {
        val tv = plainText(text)
        tv.setTextColor(ContextCompat.getColor(this, R.color.ariyan_text_primary))
        Linkify.addLinks(tv, Linkify.WEB_URLS)
        tv.movementMethod = LinkMovementMethod.getInstance()
        return tv
    }

    private fun heading(text: String): TextView {
        val density = resources.displayMetrics.density
        return TextView(this).apply {
            this.text = text
            textSize = 15f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(ContextCompat.getColor(this@HistoricalResearchActivity, R.color.ariyan_accent))
            setPadding(0, (14 * density).toInt(), 0, (2 * density).toInt())
        }
    }

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
