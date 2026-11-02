package com.ariyan.geoai

import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.chaquo.python.PyException
import com.chaquo.python.Python
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.Locale

/**
 * dbe-v1 (2026-11-02): AI Debate Engine screen, opened from Mission Control.
 *
 * Lists every debate stored by dbr-v1 (newest first, 50 at a time, filterable
 * by agreement) with a project-wide summary: how often each perspective leads
 * and how often the Steward capped the debate's confidence. Tapping a row shows
 * the four perspectives, the synthesis and the Steward's verdict, with a button
 * to that candidate's Final Image. Read-only: nothing is re-run or re-created
 * (mission_control.debates_json / debate_detail_json).
 */
class DebateEngineActivity : AppCompatActivity() {

    private val filters = listOf(
        "ALL" to "All", "LEADING_INTERPRETATION" to "Leading", "CONTESTED" to "Contested",
        "WEAK_SIGNAL" to "Weak signal", "NO_DATA" to "No data"
    )
    private val agreementNames = mapOf(
        "LEADING_INTERPRETATION" to "Leading interpretation", "CONTESTED" to "Contested",
        "WEAK_SIGNAL" to "Weak signal", "NO_DATA" to "No data"
    )

    private lateinit var python: Python
    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }
    private val d by lazy { resources.displayMetrics.density }
    private fun px(v: Int) = (v * d).toInt()
    private fun col(id: Int) = ContextCompat.getColor(this, id)

    private lateinit var filterRow: LinearLayout
    private lateinit var summaryBox: LinearLayout
    private lateinit var listBox: LinearLayout
    private lateinit var moreButton: Button
    private var agreement = "ALL"
    private var offset = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        python = Python.getInstance()
        agreement = savedInstanceState?.getString("agreement") ?: "ALL"
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(px(12), px(12), px(12), px(20)) }
        root.addView(text("AI Debate Engine", 22f, R.color.ariyan_text_primary, bold = true))
        root.addView(text("Four perspectives argue each candidate; the Steward governs the result.", 13f,
            R.color.ariyan_accent).apply { setPadding(0, 0, 0, px(8)) })
        filterRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        root.addView(HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(filterRow) })
        summaryBox = card()
        root.addView(summaryBox)
        listBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(listBox)
        moreButton = Button(this).apply {
            text = "Load 50 more"; isAllCaps = false; visibility = View.GONE
            setOnClickListener { load(append = true) }
        }
        root.addView(moreButton)
        setContentView(ScrollView(this).apply { setBackgroundColor(col(R.color.ariyan_bg)); addView(root) })
        buildFilters()
        load(append = false)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString("agreement", agreement)
    }

    private fun buildFilters() {
        filterRow.removeAllViews()
        filters.forEach { (key, label) ->
            filterRow.addView(Button(this).apply {
                text = label; isAllCaps = false; textSize = 13f
                setTextColor(col(if (key == agreement) R.color.ariyan_bg else R.color.ariyan_text_primary))
                background = GradientDrawable().apply {
                    setCornerRadius(16 * d)
                    setColor(if (key == agreement) col(R.color.ariyan_accent) else col(R.color.ariyan_surface))
                }
                setOnClickListener {
                    if (agreement != key) {
                        agreement = key; buildFilters(); load(append = false)
                    }
                }
            }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, px(38)).apply { setMargins(0, 0, px(6), 0) })
        }
    }

    private fun load(append: Boolean) {
        if (!append) {
            offset = 0
            listBox.removeAllViews()
            summaryBox.removeAllViews()
            summaryBox.addView(text("Loading stored debates\u2026", 13f, R.color.ariyan_text_secondary))
        }
        moreButton.isEnabled = false
        val want = agreement
        lifecycleScope.launch {
            val o = withContext(Dispatchers.Default) {
                try {
                    JSONObject(python.getModule("mission_control")
                        .callAttr("debates_json", offlineDataRoot, want, 50, offset).toString())
                } catch (e: PyException) {
                    JSONObject().put("error", e.message)
                }
            }
            if (want != agreement) return@launch           // filter changed while loading
            moreButton.isEnabled = true
            if (o.has("error")) {
                summaryBox.removeAllViews()
                summaryBox.addView(text(o.optString("error"), 13f, R.color.ariyan_warn))
                return@launch
            }
            if (!append) renderSummary(o)
            val rows = o.optJSONArray("rows")
            val n = rows?.length() ?: 0
            for (i in 0 until n) listBox.addView(row(rows!!.getJSONObject(i)))
            if (!append && n == 0) {
                listBox.addView(text(if (agreement == "ALL") (o.optString("note").ifBlank { "No debates stored yet." })
                    else "No stored debate with this agreement.", 13f, R.color.ariyan_text_secondary).apply {
                    setPadding(px(4), px(10), 0, 0)
                })
            }
            offset += n
            moreButton.visibility = if (o.optBoolean("more")) View.VISIBLE else View.GONE
        }
    }

    private fun renderSummary(o: JSONObject) {
        summaryBox.removeAllViews()
        summaryBox.addView(text("SUMMARY (all stored debates)", 13f, R.color.ariyan_accent, bold = true))
        val s = o.optJSONObject("summary")
        if (s == null || s.optInt("debates") == 0) {
            line(summaryBox, o.optString("note").ifBlank { "No debates stored yet." }, true)
            line(summaryBox, o.optString("statement"))
            return
        }
        line(summaryBox, String.format(Locale.US, "%,d debates on %,d candidates", s.optInt("debates"), s.optInt("candidates")), true)
        if (!s.isNull("scanned")) {
            line(summaryBox, String.format(Locale.US, "(summary over the newest %,d)", s.optInt("scanned")))
        }
        val total = maxOf(1, s.optInt("debates"))
        val lead = s.optJSONObject("by_leading") ?: JSONObject()
        line(summaryBox, "Leading perspective:", true)
        lead.keys().asSequence().map { it to lead.optInt(it) }.sortedByDescending { it.second }.forEach { (k, v) ->
            line(summaryBox, String.format(Locale.US, "   %s  %,d (%.0f%%)", if (k == "none") "none (no data)" else k, v, 100.0 * v / total))
        }
        val agr = s.optJSONObject("by_agreement") ?: JSONObject()
        line(summaryBox, "Agreement:", true)
        filters.drop(1).forEach { (k, _) ->
            val v = agr.optInt(k)
            if (v > 0) line(summaryBox, String.format(Locale.US, "   %s  %,d", agreementNames[k], v))
        }
        val rated = s.optInt("steward_rated")
        if (rated > 0) {
            line(summaryBox, String.format(Locale.US, "The Steward capped the debate's confidence in %,d of %,d (%.0f%%).",
                s.optInt("steward_capped"), rated, 100.0 * s.optInt("steward_capped") / rated), true)
        }
        line(summaryBox, o.optString("statement"))
    }

    private fun row(r: JSONObject): View {
        val band = nz(r, "steward_band")
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(10), px(8), px(10), px(8))
            background = GradientDrawable().apply { setCornerRadius(8 * d); setColor(col(R.color.ariyan_surface)) }
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(6) }
            isClickable = true
            setOnClickListener { detail(r.getInt("id")) }
            addView(text(String.format(Locale.US, "%s  \u00B7  %s", r.optString("candidate_id").take(8),
                nz(r, "leading") ?: "no leading view"), 14f, R.color.ariyan_text_primary, bold = true))
            addView(text(String.format(Locale.US, "%s  \u00B7  Steward %s%s", agreementNames[r.optString("agreement")] ?: r.optString("agreement"),
                band ?: "not rated", if (r.optBoolean("steward_capped")) " (capped)" else ""), 12f,
                R.color.ariyan_text_secondary).apply {
                setTextColor(MissionControlActivity.BAND_COLOURS[band] ?: col(R.color.ariyan_text_secondary))
            })
            addView(text(String.format(Locale.US, "%s  \u00B7  %s  \u00B7  %s", (nz(r, "recorded_at") ?: "").take(16).replace("T", " "),
                if (r.optString("origin") == "refinement") "Pass 2 refinement" else "run", nz(r, "status") ?: "candidate gone"),
                12f, R.color.ariyan_text_secondary))
        }
    }

    private fun detail(id: Int) {
        lifecycleScope.launch {
            val o = withContext(Dispatchers.Default) {
                try {
                    JSONObject(python.getModule("mission_control").callAttr("debate_detail_json", offlineDataRoot, id).toString())
                } catch (e: PyException) {
                    JSONObject().put("error", e.message)
                }
            }
            if (o.has("error")) {
                AlertDialog.Builder(this@DebateEngineActivity).setMessage(o.optString("error"))
                    .setPositiveButton("Close", null).show()
                return@launch
            }
            val box = LinearLayout(this@DebateEngineActivity).apply {
                orientation = LinearLayout.VERTICAL; setPadding(px(18), px(8), px(18), px(8))
            }
            val c = o.optJSONObject("candidate") ?: JSONObject()
            line(box, String.format(Locale.US, "Candidate %s  \u00B7  %.5f, %.5f  \u00B7  %s", o.optString("candidate_id").take(8),
                c.optDouble("lat"), c.optDouble("lon"), nz(c, "status") ?: "?"), true)
            line(box, String.format(Locale.US, "%s, %s  \u00B7  %d debate(s) stored for this candidate",
                (nz(o, "recorded_at") ?: "").take(16).replace("T", " "),
                if (o.optString("origin") == "refinement") "Pass 2 refinement" else "run",
                o.optInt("debates_for_candidate")))
            val syn = o.optJSONObject("synthesis") ?: JSONObject()
            heading(box, "SYNTHESIS")
            line(box, (agreementNames[syn.optString("agreement_level")] ?: syn.optString("agreement_level")) +
                (nz(syn, "leading_position")?.let { "  \u00B7  leading: $it" } ?: ""), true)
            nz(syn, "steward_note")?.let { line(box, it) }
            val pos = o.optJSONArray("positions")
            if (pos != null) for (i in 0 until pos.length()) {
                val p = pos.getJSONObject(i)
                heading(box, p.optString("perspective").uppercase(Locale.US))
                if (p.optBoolean("insufficient_data")) line(box, "Insufficient data to argue a position.", true)
                else line(box, String.format(Locale.US, "%s (%.2f, %s)", p.optString("stance"),
                    p.optDouble("confidence_score"), p.optString("confidence_label")), true)
                val rs = p.optJSONArray("reasoning")
                if (rs != null) for (k in 0 until rs.length()) line(box, "\u2022 " + rs.optString(k))
            }
            val st = o.optJSONObject("steward") ?: JSONObject()
            heading(box, "STEWARD")
            nz(st, "error")?.let { line(box, "Steward error: $it", true) }
            nz(st, "band")?.let { band ->
                line(box, String.format(Locale.US, "%s %.2f%s", band, st.optDouble("numeric"),
                    if (st.optBoolean("capped") && !st.isNull("raw")) String.format(Locale.US, "  (capped from %.2f)", st.optDouble("raw")) else ""), true)
            }
            val sr = st.optJSONArray("reasoning")
            if (sr != null) for (k in 0 until sr.length()) line(box, "\u2022 " + sr.optString(k))
            line(box, o.optString("statement"))
            val cid = o.optString("candidate_id")
            AlertDialog.Builder(this@DebateEngineActivity)
                .setTitle("Stored debate")
                .setView(ScrollView(this@DebateEngineActivity).apply { addView(box) })
                .setPositiveButton("Final Image") { _, _ ->
                    startActivity(FinalImageActivity.newIntent(this@DebateEngineActivity, cid))
                }
                .setNegativeButton("Close", null)
                .show()
        }
    }

    // ---------------------------------------------------------------- widgets

    private fun nz(o: JSONObject, k: String): String? = o.optString(k).takeIf { !o.isNull(k) && it.isNotBlank() && it != "null" }

    private fun text(s: String, size: Float, colour: Int, bold: Boolean = false) = TextView(this).apply {
        text = s; textSize = size; setTextColor(col(colour))
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun line(box: LinearLayout, s: String, primary: Boolean = false) {
        box.addView(text(s, 13f, if (primary) R.color.ariyan_text_primary else R.color.ariyan_text_secondary).apply {
            setPadding(0, px(4), 0, 0)
        })
    }

    private fun heading(box: LinearLayout, s: String) {
        box.addView(text(s, 12f, R.color.ariyan_accent, bold = true).apply { setPadding(0, px(12), 0, 0) })
    }

    private fun card() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(px(12), px(10), px(12), px(12))
        background = GradientDrawable().apply {
            setCornerRadius(10 * d); setColor(col(R.color.ariyan_surface))
            setStroke(maxOf(1, d.toInt()), 0xFF30363D.toInt())
        }
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { setMargins(0, px(8), 0, px(4)) }
    }
}
