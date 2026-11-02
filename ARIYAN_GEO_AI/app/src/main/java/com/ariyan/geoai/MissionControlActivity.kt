package com.ariyan.geoai

import android.app.Activity
import android.app.Application
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.widget.Button
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
 * mc-v1 (2026-11-02): Mission Control, the screen the app opens on.
 *
 * A hub and a read-only summary. Every module tile opens a real, existing
 * screen (the single-point Investigation screen is unchanged and is one of the
 * tiles). Everything shown comes from mission_control.mission_json(): the
 * study area, candidates per Steward band with the real ceiling and its reason
 * (no invented percentage), the best candidates (tap -> Final Image), and the
 * data that really exists on the phone. API keys are checked here and only
 * shown as "set" / "not set", never their values. Nothing here changes a
 * status, a review or a confidence.
 *
 * "Last Final Image": the candidate of the last Final Image screen opened in
 * this process is remembered in SharedPreferences through an activity
 * lifecycle callback registered here, so FinalImageActivity needs no change.
 */
class MissionControlActivity : AppCompatActivity() {

    companion object {
        private const val PREFS = "mission_control"
        private const val KEY_LAST_FINAL_IMAGE = "last_final_image"
        private var watcherRegistered = false

        /** Remember every Final Image opened, whichever screen opened it. */
        fun registerFinalImageWatcher(app: Application) {
            if (watcherRegistered) return
            watcherRegistered = true
            app.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
                override fun onActivityCreated(a: Activity, b: Bundle?) {
                    if (a is FinalImageActivity) {
                        val cid = a.intent?.getStringExtra(FinalImageActivity.EXTRA_CANDIDATE_ID) ?: return
                        a.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                            .putString(KEY_LAST_FINAL_IMAGE, cid).apply()
                    }
                }
                override fun onActivityStarted(a: Activity) {}
                override fun onActivityResumed(a: Activity) {}
                override fun onActivityPaused(a: Activity) {}
                override fun onActivityStopped(a: Activity) {}
                override fun onActivitySaveInstanceState(a: Activity, b: Bundle) {}
                override fun onActivityDestroyed(a: Activity) {}
            })
        }

        val BAND_COLOURS = mapOf(
            "SUBSTANTIAL" to 0xFF2E7D32.toInt(), "HIGH" to 0xFF3FB68B.toInt(),
            "MODERATE" to 0xFFD9A62B.toInt(), "LOW" to 0xFFD9822B.toInt(),
            "NO_DATA" to 0xFF6E7681.toInt(), "NOT_RATED" to 0xFF3A414A.toInt()
        )
        val BAND_NAMES = mapOf(
            "SUBSTANTIAL" to "Substantial", "HIGH" to "High", "MODERATE" to "Moderate", "LOW" to "Low",
            "NO_DATA" to "No data", "NOT_RATED" to "Not rated yet"
        )
    }

    private class Tile(val title: String, val sub: String, val action: () -> Unit)

    private lateinit var python: Python
    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }
    private lateinit var content: LinearLayout
    private val d by lazy { resources.displayMetrics.density }
    private fun px(v: Int) = (v * d).toInt()
    private fun col(id: Int) = ContextCompat.getColor(this, id)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        registerFinalImageWatcher(application)
        python = Python.getInstance()
        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(12), px(12), px(12), px(20))
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(col(R.color.ariyan_bg))
            addView(content)
        })
    }

    override fun onResume() {
        super.onResume()
        load()
    }

    // ------------------------------------------------------------------ load

    private fun load() {
        content.removeAllViews()
        header()
        if (!ExternalStorageAccess.isGranted(this)) permissionCard()
        tiles(null)
        val loading = text("Loading recorded results\u2026", 13f, R.color.ariyan_text_secondary)
        content.addView(loading)
        lifecycleScope.launch {
            val o = withContext(Dispatchers.Default) {
                try {
                    JSONObject(python.getModule("mission_control").callAttr("mission_json", offlineDataRoot, 10).toString())
                } catch (e: PyException) {
                    JSONObject().put("error", e.message)
                }
            }
            content.removeView(loading)
            if (o.has("error")) {
                content.addView(card("COULD NOT READ THE PROJECT").apply {
                    line(this, o.optString("error"), true)
                    line(this, "The module tiles above still work. If this mentions the database guard, " +
                        "restore from offline_data/db_backups/ before running anything.")
                })
                footer(null)
                return@launch
            }
            render(o)
        }
    }

    private fun render(o: JSONObject) {
        // replace the placeholder tiles with ones that know the debate count
        content.removeAllViews()
        header()
        if (!ExternalStorageAccess.isGranted(this)) permissionCard()
        studyArea(o)
        tiles(o)
        confidence(o)
        targets(o)
        sources(o)
        footer(o)
    }

    // ---------------------------------------------------------------- blocks

    private fun header() {
        content.addView(text("ARIYAN GEO AI", 24f, R.color.ariyan_text_primary, bold = true))
        content.addView(text("Evidence. Reasoning. Confidence.", 13f, R.color.ariyan_accent).apply {
            setPadding(0, 0, 0, px(10))
        })
    }

    private fun permissionCard() {
        content.addView(card("STORAGE ACCESS NEEDED").apply {
            line(this, "ARIYAN keeps its database and offline data in ARIYAN_GEO_AI/offline_data. " +
                "Without \u201CAll files access\u201D nothing can be read.", true)
            addView(button("Grant access") {
                try {
                    startActivity(
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R)
                            ExternalStorageAccess.manageAllFilesSettingsIntent(this@MissionControlActivity)
                        else Intent(Settings.ACTION_APPLICATION_SETTINGS)
                    )
                } catch (e: ActivityNotFoundException) {
                    startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                }
            })
        })
    }

    private fun studyArea(o: JSONObject) {
        val p = o.optJSONObject("project")
        content.addView(card("STUDY AREA").apply {
            if (p == null) {
                line(this, o.optString("empty_note"), true)
                return@apply
            }
            line(this, p.optString("name"), true)
            line(this, String.format(Locale.US, "%,d wide-area jobs%s  \u00B7  %,d investigations",
                p.optInt("jobs"),
                if (p.optInt("jobs_unfinished") > 0) " (${p.optInt("jobs_unfinished")} not finished)" else "",
                p.optInt("investigations")))
            val sc = p.optJSONObject("status_counts") ?: JSONObject()
            val parts = listOf("Supported", "Open", "Inconclusive", "Rejected")
                .filter { sc.has(it) }.joinToString("  \u00B7  ") { String.format(Locale.US, "%s %,d", it, sc.optInt(it)) }
            line(this, String.format(Locale.US, "%,d candidates: %s", p.optInt("candidates"), parts))
            nz(p, "last_activity")?.let { line(this, "Last activity: " + it.take(16).replace("T", " ") + " UTC") }
        })
    }

    private fun tiles(o: JSONObject?) {
        val last = getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_LAST_FINAL_IMAGE, null)
        val debates = o?.optInt("debates_stored", -1) ?: -1
        val items = listOf(
            Tile("Investigation", "Single point + AI debate") { go(MainActivity::class.java) },
            Tile("Wide-area search", "Jobs, Auto run, DEM library") { go(WideAreaSearchActivity::class.java) },
            Tile("Grand Project", "Candidates, reviews, reports") { go(GrandProjectActivity::class.java) },
            Tile("Data & Evidence", "Offline country data") { go(OfflineDataActivity::class.java) },
            Tile("Historical research", "Texts and place names") { go(HistoricalResearchActivity::class.java) },
            Tile("AI Debate Engine",
                if (debates >= 0) String.format(Locale.US, "%,d stored debates", debates) else "Stored debates") {
                go(DebateEngineActivity::class.java)
            },
            Tile("Last Final Image",
                if (last != null) "Candidate " + last.take(8) else "None opened yet") {
                if (last != null) startActivity(FinalImageActivity.newIntent(this, last))
            }
        )
        val cols = if (resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE) 4 else 2
        content.addView(sectionTitle("MODULES"))
        items.chunked(cols).forEach { chunk ->
            val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            chunk.forEach { t ->
                row.addView(tile(t.title, t.sub, t.action), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f).apply {
                    setMargins(px(3), px(3), px(3), px(3))
                })
            }
            repeat(cols - chunk.size) {
                row.addView(View(this), LinearLayout.LayoutParams(0, 1, 1f).apply { setMargins(px(3), 0, px(3), 0) })
            }
            content.addView(row)
        }
        content.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
    }

    private fun confidence(o: JSONObject) {
        val c = o.optJSONObject("confidence") ?: return
        val bands = c.optJSONArray("bands") ?: return
        content.addView(card("FINAL SCIENTIFIC ASSESSMENT").apply {
            val highest = nz(c, "highest")
            if (highest != null) {
                addView(text("Highest band reached: " + (BAND_NAMES[highest] ?: highest), 17f,
                    R.color.ariyan_text_primary, bold = true).apply {
                    setTextColor(BAND_COLOURS[highest] ?: col(R.color.ariyan_text_primary))
                })
                line(this, String.format(Locale.US, "Ceiling for this band: %.2f", c.optDouble("highest_ceiling")), true)
            } else {
                line(this, "No candidate has a Steward rating yet.", true)
            }
            val segs = (0 until bands.length()).map { bands.getJSONObject(it) }
                .map { it.optString("band") to it.optInt("count") }
            addView(BandBar(this@MissionControlActivity, segs),
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, px(18)).apply { topMargin = px(8) })
            segs.filter { it.second > 0 }.forEach { (b, n) ->
                addView(text(String.format(Locale.US, "\u25A0 %s  %,d", BAND_NAMES[b] ?: b, n), 13f,
                    R.color.ariyan_text_secondary).apply {
                    setTextColor(BAND_COLOURS[b] ?: col(R.color.ariyan_text_secondary)); setPadding(0, px(3), 0, 0)
                })
            }
            line(this, String.format(Locale.US, "%,d active candidates; %,d Rejected not counted.",
                c.optInt("active_candidates"), c.optInt("rejected")))
            nz(c, "why")?.let { line(this, "Why not higher: $it", true) }
            val words = c.optJSONArray("steward_words")
            if (words != null && words.length() > 0) {
                line(this, "The Steward's own words (top candidate):")
                for (i in 0 until words.length()) line(this, "\u201C" + words.optString(i) + "\u201D")
            }
        })
    }

    private fun targets(o: JSONObject) {
        val top = o.optJSONArray("top") ?: return
        content.addView(card("CANDIDATE TARGETS").apply {
            if (top.length() == 0) {
                line(this, "No candidates yet (Rejected ones are left out).", true)
                return@apply
            }
            line(this, "Best by Steward band, confidence, Supported first, then |z|. Tap one to open its Final Image.")
            for (i in 0 until top.length()) {
                val t = top.getJSONObject(i)
                val band = t.optString("band")
                val row = LinearLayout(this@MissionControlActivity).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(px(8), px(7), px(8), px(7))
                    background = GradientDrawable().apply {
                        setCornerRadius(8 * d); setColor(col(R.color.ariyan_surface))
                    }
                    isClickable = true
                    setOnClickListener {
                        startActivity(FinalImageActivity.newIntent(this@MissionControlActivity, t.getString("id")))
                    }
                }
                val conf = if (t.isNull("numeric")) BAND_NAMES[band] ?: band
                    else String.format(Locale.US, "%s %.2f", BAND_NAMES[band] ?: band, t.optDouble("numeric"))
                row.addView(text(String.format(Locale.US, "%d. %s  \u00B7  %s  \u00B7  %s", i + 1,
                    t.getString("id").take(8), conf, t.optString("status")), 14f, R.color.ariyan_text_primary, bold = true).apply {
                    setTextColor(BAND_COLOURS[band] ?: col(R.color.ariyan_text_primary))
                })
                val z = if (t.isNull("z")) "" else String.format(Locale.US, "  \u00B7  |z| %.1f", Math.abs(t.optDouble("z")))
                row.addView(text(String.format(Locale.US, "%.5f, %.5f%s%s", t.optDouble("lat"), t.optDouble("lon"), z,
                    if (t.optBoolean("calib_strong")) "  \u00B7  calib-v1 strong" else ""), 12f, R.color.ariyan_text_secondary))
                (nz(t, "job_title") ?: if (nz(t, "job_id") == null) "single investigation" else null)?.let {
                    row.addView(text("Job: $it", 12f, R.color.ariyan_text_secondary))
                }
                nz(t, "known_site")?.let { row.addView(text(it, 12f, R.color.ariyan_text_secondary)) }
                addView(row, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(6) })
            }
        })
    }

    private fun sources(o: JSONObject) {
        val src = o.optJSONArray("sources") ?: return
        val creds = SecureCredentialStore(this)
        content.addView(card("DATA SOURCES (on this phone)").apply {
            for (i in 0 until src.length()) {
                val s = src.getJSONObject(i)
                status(this, s.optBoolean("ok"), s.optString("name"), s.optString("detail"))
            }
            status(this, creds.activeOpenTopographyApiKey().isNotEmpty(), "OpenTopography key",
                if (creds.activeOpenTopographyApiKey().isNotEmpty()) "set" else "not set (live DEM unavailable)")
            status(this, creds.activeCopernicusClientId().isNotEmpty(), "Copernicus key",
                if (creds.activeCopernicusClientId().isNotEmpty()) "set" else "not set (satellite evidence unavailable)")
        })
    }

    private fun footer(o: JSONObject?) {
        val principles = o?.optJSONArray("principles")
        val names = if (principles != null) (0 until principles.length()).map { principles.optString(it) }
            else listOf("Real Data Only", "Scientific Integrity", "No Synthetic Data", "Uncertainty Quantified", "Human Oversight")
        content.addView(text(names.joinToString("  \u00B7  "), 12f, R.color.ariyan_accent, bold = true).apply {
            gravity = Gravity.CENTER; setPadding(0, px(14), 0, px(4))
        })
        o?.let { nz(it, "statement") }?.let {
            content.addView(text(it, 11f, R.color.ariyan_text_secondary).apply { gravity = Gravity.CENTER })
        }
    }

    // --------------------------------------------------------------- widgets

    private fun go(cls: Class<*>) = startActivity(Intent(this, cls))

    private fun nz(o: JSONObject, k: String): String? = o.optString(k).takeIf { !o.isNull(k) && it.isNotBlank() && it != "null" }

    private fun text(s: String, size: Float, colour: Int, bold: Boolean = false) = TextView(this).apply {
        text = s; textSize = size; setTextColor(col(colour))
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun sectionTitle(s: String) = text(s, 12f, R.color.ariyan_text_secondary, bold = true).apply {
        setPadding(px(3), px(6), 0, px(2))
    }

    private fun card(title: String): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(px(12), px(10), px(12), px(12))
        background = GradientDrawable().apply {
            setCornerRadius(10 * d); setColor(col(R.color.ariyan_surface))
            setStroke(maxOf(1, d.toInt()), 0xFF30363D.toInt())
        }
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { setMargins(0, px(6), 0, px(6)) }
        addView(text(title, 13f, R.color.ariyan_accent, bold = true))
    }

    private fun line(box: LinearLayout, s: String, primary: Boolean = false) {
        box.addView(text(s, 13f, if (primary) R.color.ariyan_text_primary else R.color.ariyan_text_secondary).apply {
            setPadding(0, px(4), 0, 0)
        })
    }

    private fun status(box: LinearLayout, ok: Boolean, name: String, detail: String) {
        box.addView(text((if (ok) "\u2713  " else "\u2717  ") + name, 13f, R.color.ariyan_text_primary).apply {
            setTextColor(if (ok) col(R.color.ariyan_accent) else col(R.color.ariyan_warn)); setPadding(0, px(6), 0, 0)
        })
        box.addView(text("     $detail", 12f, R.color.ariyan_text_secondary))
    }

    private fun tile(title: String, sub: String, action: () -> Unit) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(px(10), px(12), px(10), px(12))
        background = GradientDrawable().apply {
            setCornerRadius(10 * d); setColor(col(R.color.ariyan_surface))
            setStroke(maxOf(1, d.toInt()), 0xFF30363D.toInt())
        }
        isClickable = true
        setOnClickListener { action() }
        addView(text(title, 14f, R.color.ariyan_text_primary, bold = true))
        addView(text(sub, 11f, R.color.ariyan_text_secondary).apply { setPadding(0, px(3), 0, 0) })
    }

    private fun button(label: String, action: () -> Unit) = Button(this).apply {
        text = label; isAllCaps = false; setOnClickListener { action() }
    }

    /** Candidates per band as one proportional bar (real counts, no percentage claim). */
    private class BandBar(ctx: Context, val segs: List<Pair<String, Int>>) : View(ctx) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        override fun onDraw(canvas: Canvas) {
            val total = segs.sumOf { it.second }
            paint.color = 0xFF30363D.toInt()
            canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), paint)
            if (total <= 0) return
            var x = 0f
            for ((b, n) in segs) {
                if (n <= 0) continue
                val w = maxOf(2f, width * n.toFloat() / total)
                paint.color = BAND_COLOURS[b] ?: 0xFF6E7681.toInt()
                canvas.drawRect(x, 0f, minOf(width.toFloat(), x + w), height.toFloat(), paint)
                x += w
            }
        }
    }
}
