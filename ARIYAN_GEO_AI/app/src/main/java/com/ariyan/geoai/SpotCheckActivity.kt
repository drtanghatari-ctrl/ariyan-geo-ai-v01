package com.ariyan.geoai

import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
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
 * d4-v1 (2026-11-02, user-approved): tank / silo spot-check list, opened from
 * Mission Control > Analysis & Models. Candidates with a heavily built-up
 * land-cover ring and NO mapped industry within 300 m, ranked by built-up
 * share (spotcheck_tanks.spotcheck_json). Tap a row to open its Final Image and
 * look at True colour; then record what you saw with one of the verdict chips.
 * A verdict is a note only: it never changes a status, review, confidence or
 * evidence row. The counts at the top are what a later rule decision rests on.
 * maps-v1: each card also opens its coordinates in Google Maps (MapsLink).
 */
class SpotCheckActivity : AppCompatActivity() {

    private lateinit var python: Python
    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }
    private lateinit var content: LinearLayout
    private var hideChecked = false
    private val d by lazy { resources.displayMetrics.density }
    private fun px(v: Int) = (v * d).toInt()
    private fun col(id: Int) = ContextCompat.getColor(this, id)

    private val verdictColours = mapOf(
        "TANK_OR_SILO" to AriyanDecor.ROSE, "OTHER_INDUSTRY" to AriyanDecor.ORANGE,
        "VILLAGE_OR_TOWN" to AriyanDecor.AMBER, "OPEN_GROUND_OR_SITE" to AriyanDecor.ACCENT,
        "CANT_TELL" to 0xFF6E7681.toInt()
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        python = Python.getInstance()
        hideChecked = savedInstanceState?.getBoolean("hideChecked") ?: false
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(px(12), px(10), px(12), px(24)) }
        setContentView(ScrollView(this).apply { setBackgroundColor(col(R.color.ariyan_bg)); addView(content) })
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putBoolean("hideChecked", hideChecked)
    }

    override fun onResume() {
        super.onResume()
        load()
    }

    private fun load() {
        content.removeAllViews()
        header()
        val loading = text("Ranking candidates\u2026", 13f, col(R.color.ariyan_text_secondary))
        content.addView(loading)
        lifecycleScope.launch {
            val o = withContext(Dispatchers.Default) {
                try {
                    JSONObject(python.getModule("spotcheck_tanks").callAttr("spotcheck_json", offlineDataRoot, 40, !hideChecked).toString())
                } catch (e: PyException) {
                    JSONObject().put("error", e.message)
                }
            }
            content.removeView(loading)
            if (o.has("error")) {
                content.addView(text(o.optString("error"), 13f, AriyanDecor.ROSE))
                return@launch
            }
            summary(o)
            val rows = o.optJSONArray("rows")
            if (rows == null || rows.length() == 0) {
                content.addView(text(o.optString("note").ifBlank {
                    if (hideChecked) "Every listed candidate has a verdict." else "No candidate matches."
                }, 13f, col(R.color.ariyan_text_secondary)).apply { setPadding(px(4), px(10), 0, 0) })
            } else for (i in 0 until rows.length()) content.addView(row(i + 1, rows.getJSONObject(i), o.optJSONObject("verdict_names") ?: JSONObject()))
            content.addView(text(o.optString("statement"), 11f, col(R.color.ariyan_text_secondary)).apply {
                setPadding(px(4), px(14), px(4), 0)
            })
        }
    }

    private fun header() {
        val frame = FrameLayout(this)
        frame.addView(AriyanDecor.HeaderBanner(this), FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(px(16), px(14), px(16), px(14)) }
        val r = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        r.addView(AriyanDecor.Glyph(this, "grid", AriyanDecor.ORANGE), LinearLayout.LayoutParams(px(28), px(28)))
        r.addView(text("Tank / silo spot-check", 21f, col(R.color.ariyan_text_primary), bold = true).apply { setPadding(px(10), 0, 0, 0) })
        box.addView(r)
        box.addView(text("Built-up surroundings, no mapped industry. Tap a candidate, look at its True colour layer, " +
            "then record what you saw.", 13f, AriyanDecor.ACCENT).apply { setPadding(0, px(6), 0, 0) })
        frame.addView(box)
        content.addView(frame, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { bottomMargin = px(8) })
    }

    private fun summary(o: JSONObject) {
        val s = o.optJSONObject("summary") ?: return
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(px(14), px(12), px(14), px(12))
            background = AriyanDecor.panel(d, AriyanDecor.ORANGE)
        }
        box.addView(text(String.format(Locale.US, "%,d candidates listed \u00B7 %,d checked", s.optInt("listed"), s.optInt("checked")),
            15f, col(R.color.ariyan_text_primary), bold = true))
        box.addView(text(String.format(Locale.US, "Ring at least %.0f%% built-up (ESA WorldCover); %,d near mapped industry left out " +
            "(already labelled).", 100 * o.optDouble("min_ring_built"), s.optInt("excluded_near_mapped_industry")),
            12f, col(R.color.ariyan_text_secondary)).apply { setPadding(0, px(4), 0, 0) })
        val v = s.optJSONObject("verdicts") ?: JSONObject()
        val names = o.optJSONObject("verdict_names") ?: JSONObject()
        val chips = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        names.keys().forEach { k ->
            val n = v.optInt(k)
            if (n > 0) chips.addView(chip(names.optString(k) + " " + n, verdictColours[k] ?: AriyanDecor.ACCENT, false),
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(6) })
        }
        box.addView(chips)
        box.addView(text(if (hideChecked) "Show checked ones too" else "Hide checked ones", 13f, col(R.color.ariyan_bg), bold = true).apply {
            gravity = Gravity.CENTER; setPadding(px(14), px(8), px(14), px(8))
            background = AriyanDecor.pill(d, AriyanDecor.ORANGE)
            isClickable = true
            setOnClickListener { hideChecked = !hideChecked; load() }
        }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(10) })
        content.addView(box, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { bottomMargin = px(4) })
    }

    private fun row(rank: Int, r: JSONObject, names: JSONObject): View {
        val cid = r.getString("id")
        val current = r.optJSONObject("verdict")?.optString("verdict")
        val edge = verdictColours[current ?: ""] ?: AriyanDecor.LINE
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(px(12), px(10), px(12), px(10))
            background = AriyanDecor.panel(d, if (current != null) edge else AriyanDecor.TEAL, 12f)
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(8) }
        }
        val head = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; isClickable = true
            setOnClickListener { startActivity(FinalImageActivity.newIntent(this@SpotCheckActivity, cid)) }
        }
        head.addView(text(String.format(Locale.US, "%d. %s  \u00B7  ring %.0f%% built  \u00B7  centre %.0f%%", rank, cid.take(8),
            100 * r.optDouble("ring_built"), 100 * r.optDouble("centre_built")), 14f, col(R.color.ariyan_text_primary), bold = true))
        head.addView(text(String.format(Locale.US, "%.5f, %.5f  \u00B7  %s%s", r.optDouble("lat"), r.optDouble("lon"), r.optString("status"),
            if (r.isNull("job_title")) "" else "  \u00B7  " + r.optString("job_title")), 12f, col(R.color.ariyan_text_secondary)))
        val ind = r.optJSONObject("industry_2km")
        head.addView(text(if (ind != null) String.format(Locale.US, "Nearest mapped industry %.0f m (%s)", ind.optDouble("distance_m"), ind.optString("kind"))
            else "No mapped industry within 2 km", 12f, col(R.color.ariyan_text_secondary)))
        if (!r.isNull("known_site")) head.addView(text(r.optString("known_site"), 12f, col(R.color.ariyan_text_secondary)))
        head.addView(text("Tap to open its Final Image \u203A", 12f, AriyanDecor.TEAL, bold = true).apply { setPadding(0, px(4), 0, 0) })
        card.addView(head)
        // maps-v1: a sharper look in Google Maps (10 m Sentinel-2 hides small tanks)
        card.addView(text("Open in Google Maps \u2197", 12f, AriyanDecor.BLUE, bold = true).apply {
            setPadding(0, px(6), 0, 0); isClickable = true
            setOnClickListener { MapsLink.open(this@SpotCheckActivity, r.optDouble("lat"), r.optDouble("lon"), cid.take(8)) }
        })
        val chips = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, px(8), 0, 0) }
        names.keys().forEach { k ->
            val c = verdictColours[k] ?: AriyanDecor.ACCENT
            chips.addView(chip(names.optString(k), c, k == current).apply {
                isClickable = true
                setOnClickListener { save(cid, k) }
            }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { rightMargin = px(6) })
        }
        card.addView(HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(chips) })
        return card
    }

    private fun save(cid: String, verdict: String) {
        lifecycleScope.launch {
            val o = withContext(Dispatchers.Default) {
                try {
                    JSONObject(python.getModule("spotcheck_tanks").callAttr("record_verdict_json", offlineDataRoot, cid, verdict, "").toString())
                } catch (e: PyException) {
                    JSONObject().put("error", e.message)
                }
            }
            if (o.has("error")) android.widget.Toast.makeText(this@SpotCheckActivity, "Not saved: " + o.optString("error"),
                android.widget.Toast.LENGTH_LONG).show()
            load()
        }
    }

    private fun text(s: String, size: Float, colour: Int, bold: Boolean = false) = TextView(this).apply {
        text = s; textSize = size; setTextColor(colour)
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun chip(s: String, c: Int, selected: Boolean) = text(s, 12f, if (selected) col(R.color.ariyan_bg) else c, bold = true).apply {
        setPadding(px(12), px(6), px(12), px(6))
        background = if (selected) AriyanDecor.pill(d, c) else AriyanDecor.pill(d, AriyanDecor.withAlpha(c, 30), AriyanDecor.withAlpha(c, 120))
        gravity = Gravity.CENTER
    }
}
