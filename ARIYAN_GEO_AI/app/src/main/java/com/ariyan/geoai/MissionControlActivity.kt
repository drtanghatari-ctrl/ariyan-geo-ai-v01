package com.ariyan.geoai

import android.app.Activity
import android.app.Application
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.drawable.BitmapDrawable
import android.widget.ImageView
import androidx.appcompat.app.AlertDialog
import android.view.MotionEvent
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.provider.Settings
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
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Locale

/**
 * Mission Control, the screen the app opens on.
 *
 * mc-v1 (2026-11-02): a hub and a read-only summary. Every module tile opens a
 * real, existing screen (the single-point Investigation screen is unchanged and
 * is one of the tiles). Everything shown comes from mission_control.mission_json():
 * the study area, candidates per Steward band with the real ceiling and its
 * reason, the best candidates (tap -> Final Image), and the data that really
 * exists on the phone. API keys are only shown as "set" / "not set". Nothing
 * here changes a status, a review or a confidence.
 *
 * mc-v1.1 (2026-11-02): decorated like the mock-up (AriyanDecor.kt): header
 * banner, tab strip, stat boxes, a round confidence gauge whose needle sits on
 * the highest STORED confidence, glyph tiles, ranked target cards with
 * rediscovery / calib-v1 chips, data-source rows, principle chips. Landscape
 * pairs the cards in two columns.
 *
 * mc-v1.2 (2026-11-02): the mock-up's centre piece, a real 3D terrain of the
 * top Candidate Target: its stored DEM window (+/-1 km, the same data the Final
 * Image uses) drawn by Surface3DView with the hillshaded relief drape and the
 * candidate pins of that window. Built once per top candidate and kept while
 * Mission Control is open; drag to rotate, pinch to zoom, double-tap to reset.
 * Nothing is computed into a result and nothing is written.
 *
 * mc-v1.3 (2026-11-02): (1) the 3D card states the real height range of the
 * window, so the exaggerated view is not misread; (2) a strip of layer
 * thumbnails for the same window: terrain plus every satellite layer, shown
 * only when it is already SAVED on the phone (mission_control.thumbs_json never
 * fetches); (3) the remaining mock-up tabs: Analysis & Models (the rules and
 * models in use, read from code and database), Visualization (jumps to the 3D
 * card) and Settings (SettingsActivity).
 *
 * mc-v1.3.1 (2026-11-02): after a Final Image has been opened (where a missing
 * layer may have been fetched), the thumbnail strip is re-read when Mission
 * Control comes back, so a newly saved layer shows without restarting the app.
 * Only the strip is rebuilt; the 3D view is kept.
 *
 * logo-v1 (2026-11-02): the header shows the ARIYAN emblem (res/drawable-nodpi/
 * ariyan_emblem.png, the user's own design); the launcher icon uses the same art.
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
        /** mc-v1.3.1: set when a Final Image opens; the thumbnail strip is re-read once on return. */
        @Volatile private var thumbsStale = false

        /** Remember every Final Image opened, whichever screen opened it. */
        fun registerFinalImageWatcher(app: Application) {
            if (watcherRegistered) return
            watcherRegistered = true
            app.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
                override fun onActivityCreated(a: Activity, b: Bundle?) {
                    if (a is FinalImageActivity) {
                        thumbsStale = true
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

        val BAND_COLOURS = AriyanDecor.BAND_COLOURS
        val BAND_NAMES = mapOf(
            "SUBSTANTIAL" to "Substantial", "HIGH" to "High", "MODERATE" to "Moderate", "LOW" to "Low",
            "NO_DATA" to "No data", "NOT_RATED" to "Not rated yet"
        )
        val STATUS_COLOURS = mapOf(
            "Supported" to AriyanDecor.ACCENT, "Open" to AriyanDecor.BLUE,
            "Inconclusive" to AriyanDecor.AMBER, "Rejected" to AriyanDecor.ROSE
        )
    }

    private class Thumb(val label: String, val state: String, val note: String, val bitmap: Bitmap?)
    private class Terrain(val meta: JSONObject, val drape: Bitmap?, val heights: FloatArray?, val thumbs: List<Thumb>)

    private class Tile(val title: String, val sub: String, val glyph: String, val colour: Int, val action: () -> Unit)

    private lateinit var python: Python
    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }
    private lateinit var content: LinearLayout
    private val d by lazy { resources.displayMetrics.density }
    private val landscape get() = resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
    private fun px(v: Int) = (v * d).toInt()
    private fun col(id: Int) = ContextCompat.getColor(this, id)

    // mc-v1.2: the 3D terrain card, kept across reloads while the top candidate is unchanged
    private var terrainCard: LinearLayout? = null
    private var terrainFor: String? = null
    private var glView: Surface3DView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        registerFinalImageWatcher(application)
        python = Python.getInstance()
        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(12), px(10), px(12), px(24))
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(col(R.color.ariyan_bg))
            addView(content)
        })
    }

    override fun onResume() {
        super.onResume()
        glView?.onResume()
        load()
    }

    override fun onPause() {
        super.onPause()
        glView?.onPause()
    }

    // ------------------------------------------------------------------ load

    private fun load() {
        content.removeAllViews()
        header()
        tabStrip()
        if (!ExternalStorageAccess.isGranted(this)) permissionCard()
        tiles(null)
        val loading = text("Loading recorded results\u2026", 13f, col(R.color.ariyan_text_secondary)).apply {
            setPadding(px(4), px(8), 0, 0)
        }
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
                content.addView(panel("COULD NOT READ THE PROJECT", "steward", AriyanDecor.ROSE).apply {
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
        content.removeAllViews()
        header()
        tabStrip()
        if (!ExternalStorageAccess.isGranted(this)) permissionCard()
        pair(studyArea(o), assessment(o))
        terrainHero(o)
        tiles(o)
        pair(targets(o), sources(o))
        footer(o)
    }

    /** Two panels side by side in landscape, stacked in portrait. */
    private fun pair(a: View?, b: View?) {
        val views = listOfNotNull(a, b)
        if (!landscape || views.size < 2) {
            views.forEach { content.addView(it) }
            return
        }
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        views.forEachIndexed { i, v ->
            row.addView(v, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(if (i == 0) 0 else px(5), px(6), if (i == 0) px(5) else 0, px(6))
            })
        }
        content.addView(row)
    }

    // ---------------------------------------------------------------- blocks

    private fun header() {
        val frame = FrameLayout(this)
        frame.addView(AriyanDecor.HeaderBanner(this), FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(16), px(16), px(16), px(16))
        }
        val titleRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        // logo-v1 (2026-11-02): the ARIYAN emblem (user's design) instead of the drawn target glyph
        titleRow.addView(ImageView(this).apply {
            setImageResource(R.drawable.ariyan_emblem)
            scaleType = ImageView.ScaleType.FIT_CENTER
            contentDescription = "ARIYAN GEO AI emblem"
        }, LinearLayout.LayoutParams(px(56), px(56)))
        titleRow.addView(text("ARIYAN GEO AI", 24f, col(R.color.ariyan_text_primary), bold = true).apply {
            setPadding(px(10), 0, 0, 0); letterSpacing = 0.04f
        })
        box.addView(titleRow)
        box.addView(text("Scientific Geospatial Laboratory", 13f, col(R.color.ariyan_text_secondary)).apply {
            setPadding(px(66), 0, 0, 0)
        })
        box.addView(text("Evidence.  Reasoning.  Confidence.", 14f, AriyanDecor.ACCENT, bold = true).apply {
            setPadding(px(66), px(8), 0, 0); letterSpacing = 0.05f
        })
        frame.addView(box)
        content.addView(frame, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { bottomMargin = px(8) })
    }

    private fun tabStrip() {
        val last = lastFinalImage()
        val tabs = listOf<Pair<String, (() -> Unit)?>>(
            "Mission Control" to null,
            "Investigation" to { go(MainActivity::class.java) },
            "Data & Evidence" to { go(OfflineDataActivity::class.java) },
            "AI Debate Engine" to { go(DebateEngineActivity::class.java) },
            "Analysis & Models" to { showModels() },
            "Image Processing" to { openLastFinalImage(last) },
            "Visualization" to { scrollToTerrain() },
            "Report & Archive" to { go(GrandProjectActivity::class.java) },
            "Wide-area search" to { go(WideAreaSearchActivity::class.java) },
            "Historical research" to { go(HistoricalResearchActivity::class.java) },
            "Settings" to { go(SettingsActivity::class.java) }
        )
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, 0, 0, px(4)) }
        tabs.forEach { (name, action) ->
            val active = action == null
            row.addView(text(name, 13f, if (active) col(R.color.ariyan_bg) else col(R.color.ariyan_text_primary), bold = active).apply {
                setPadding(px(14), px(8), px(14), px(8))
                background = AriyanDecor.pill(d, if (active) AriyanDecor.ACCENT else AriyanDecor.SURFACE,
                    if (active) null else AriyanDecor.LINE)
                if (action != null) { isClickable = true; setOnClickListener { action() } }
            }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT).apply { rightMargin = px(6) })
        }
        content.addView(HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(row) })
    }

    private fun permissionCard() {
        content.addView(panel("STORAGE ACCESS NEEDED", "data", AriyanDecor.ROSE).apply {
            line(this, "ARIYAN keeps its database and offline data in ARIYAN_GEO_AI/offline_data. " +
                "Without \u201CAll files access\u201D nothing can be read.", true)
            addView(actionPill("Grant access", AriyanDecor.ROSE) {
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

    private fun studyArea(o: JSONObject): View {
        val p = o.optJSONObject("project")
        return panel("STUDY AREA", "layers", AriyanDecor.TEAL).apply {
            if (p == null) {
                line(this, o.optString("empty_note"), true)
                addView(actionPill("Open Investigation", AriyanDecor.ACCENT) { go(MainActivity::class.java) })
                return@apply
            }
            addView(text(p.optString("name"), 17f, col(R.color.ariyan_text_primary), bold = true).apply {
                setPadding(0, px(6), 0, px(6))
            })
            val stats = LinearLayout(this@MissionControlActivity).apply { orientation = LinearLayout.HORIZONTAL }
            listOf(
                Triple(p.optInt("jobs"), plural(p.optInt("jobs"), "Job", "Jobs"), AriyanDecor.TEAL),
                Triple(p.optInt("investigations"), plural(p.optInt("investigations"), "Investigation", "Investigations"), AriyanDecor.BLUE),
                Triple(p.optInt("candidates"), plural(p.optInt("candidates"), "Candidate", "Candidates"), AriyanDecor.AMBER)
            ).forEachIndexed { i, (n, label, c) ->
                stats.addView(statBox(n, label, c), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                    if (i > 0) leftMargin = px(6)
                })
            }
            addView(stats)
            if (p.optInt("jobs_unfinished") > 0) {
                line(this, String.format(Locale.US, "%d %s not finished", p.optInt("jobs_unfinished"),
                    plural(p.optInt("jobs_unfinished"), "job", "jobs")))
            }
            val sc = p.optJSONObject("status_counts") ?: JSONObject()
            val chips = listOf("Supported", "Open", "Inconclusive", "Rejected").filter { sc.has(it) }
                .map { chip(String.format(Locale.US, "%s %,d", it, sc.optInt(it)), STATUS_COLOURS[it] ?: AriyanDecor.ACCENT) }
            chipRows(this, chips, 2)
            nz(p, "last_activity")?.let { line(this, "Last activity: " + it.take(16).replace("T", " ") + " UTC") }
            addView(actionPill("Open Investigation", AriyanDecor.ACCENT) { go(MainActivity::class.java) })
        }
    }

    private fun assessment(o: JSONObject): View? {
        val c = o.optJSONObject("confidence") ?: return null
        val bands = c.optJSONArray("bands") ?: return null
        return panel("FINAL SCIENTIFIC ASSESSMENT", "steward", AriyanDecor.AMBER).apply {
            val highest = nz(c, "highest")
            val value = if (c.isNull("highest_numeric")) null else c.optDouble("highest_numeric")
            addView(AriyanDecor.Gauge(this@MissionControlActivity, value, highest),
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                    topMargin = px(6)
                })
            addView(text(if (highest != null) "Highest stored confidence \u00B7 band ceiling " +
                String.format(Locale.US, "%.2f", c.optDouble("highest_ceiling")) else "No candidate has a Steward rating yet.",
                12f, col(R.color.ariyan_text_secondary)).apply { gravity = Gravity.CENTER })
            val segs = (0 until bands.length()).map { bands.getJSONObject(it) }.map { it.optString("band") to it.optInt("count") }
            addView(AriyanDecor.CountBar(this@MissionControlActivity, segs.map { (BAND_COLOURS[it.first] ?: AriyanDecor.LINE) to it.second }),
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, px(12)).apply { topMargin = px(10) })
            chipRows(this, segs.filter { it.second > 0 }.map { (b, n) ->
                chip(String.format(Locale.US, "%s %,d", BAND_NAMES[b] ?: b, n), BAND_COLOURS[b] ?: AriyanDecor.LINE)
            }, 2)
            line(this, String.format(Locale.US, "%,d active %s; %,d Rejected not counted.", c.optInt("active_candidates"),
                plural(c.optInt("active_candidates"), "candidate", "candidates"), c.optInt("rejected")))
            nz(c, "why")?.let { line(this, "Why not higher: $it", true) }
            val words = c.optJSONArray("steward_words")
            if (words != null && words.length() > 0) {
                val quote = LinearLayout(this@MissionControlActivity).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(px(10), px(6), px(8), px(6))
                    background = GradientDrawable().apply {
                        cornerRadius = 8 * d; setColor(AriyanDecor.withAlpha(AriyanDecor.AMBER, 22))
                    }
                }
                quote.addView(text("THE STEWARD (top candidate)", 11f, AriyanDecor.AMBER, bold = true))
                for (i in 0 until words.length()) {
                    quote.addView(text("\u201C" + words.optString(i) + "\u201D", 13f, col(R.color.ariyan_text_primary)).apply {
                        setTypeface(typeface, Typeface.ITALIC); setPadding(0, px(3), 0, 0)
                    })
                }
                addView(quote, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(8) })
            }
        }
    }

    /** mc-v1.2: real 3D terrain of the top Candidate Target (the mock-up's centre). */
    private fun terrainHero(o: JSONObject) {
        val top = o.optJSONArray("top")
        if (top == null || top.length() == 0) return
        val t = top.getJSONObject(0)
        val cid = t.getString("id")
        terrainCard?.let { card ->
            if (terrainFor == cid) {
                (card.parent as? android.view.ViewGroup)?.removeView(card)
                content.addView(card)
                if (thumbsStale) {
                    thumbsStale = false
                    refreshThumbs(card, cid)
                }
                return
            }
        }
        glView?.onPause()
        glView = null
        val card = panel("3D TERRAIN \u00B7 TOP CANDIDATE " + cid.take(8), "mountain", AriyanDecor.ORANGE)
        terrainCard = card
        terrainFor = cid
        thumbsStale = false                     // this build reads the thumbnails fresh
        val status = text("Loading the stored DEM window\u2026", 13f, col(R.color.ariyan_text_secondary)).apply {
            setPadding(0, px(6), 0, 0)
        }
        card.addView(status)
        val frame = FrameLayout(this).apply {
            background = GradientDrawable().apply { cornerRadius = 10 * d; setColor(0xFF0B0E13.toInt()) }
        }
        card.addView(frame, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            px(if (landscape) 300 else 280)).apply { topMargin = px(8) })
        val caption = text("", 12f, col(R.color.ariyan_text_secondary)).apply { setPadding(0, px(6), 0, 0) }
        card.addView(caption)
        card.addView(actionPill("Open its Final Image", AriyanDecor.ORANGE) {
            startActivity(FinalImageActivity.newIntent(this, cid))
        })
        content.addView(card)
        lifecycleScope.launch {
            val result = withContext(Dispatchers.Default) {
                var sid: String? = null
                val fim = python.getModule("final_image_mobile")
                try {
                    val j = JSONObject(fim.callAttr("open_final_image_json", offlineDataRoot, cid, 1000.0, "relief").toString())
                    if (j.has("error")) return@withContext Terrain(j, null, null, emptyList())
                    sid = j.getString("session_id")
                    val bytes = fim.callAttr("image_rgba", sid).toJava(ByteArray::class.java)
                    val bmp = Bitmap.createBitmap(j.getInt("width"), j.getInt("height"), Bitmap.Config.ARGB_8888)
                    bmp.copyPixelsFromBuffer(ByteBuffer.wrap(bytes))
                    val s3d = python.getModule("surface3d_mobile")
                    val m = JSONObject(s3d.callAttr("open_surface_json", sid).toString())
                    if (m.has("error")) return@withContext Terrain(m, null, null, emptyList())
                    val hb = s3d.callAttr("surface_heights", sid).toJava(ByteArray::class.java)
                    val fb = ByteBuffer.wrap(hb).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
                    val hg = FloatArray(fb.remaining()).also { fb.get(it) }
                    m.put("candidates", j.optJSONArray("candidates"))
                    m.put("source_label", j.optString("source"))
                    // mc-v1.3: thumbnails of what is already saved for this window (never fetched here)
                    val thumbs = readThumbs(sid!!, j.optString("source"), bmp)
                    Terrain(m, bmp, hg, thumbs)
                } catch (e: PyException) {
                    Terrain(JSONObject().put("error", e.message), null, null, emptyList())
                } catch (e: OutOfMemoryError) {
                    Terrain(JSONObject().put("error", "not enough memory for the 3D preview"), null, null, emptyList())
                } finally {
                    sid?.let { try { fim.callAttr("close_session", it) } catch (_: PyException) {} }
                }
            }
            if (terrainFor != cid) return@launch
            val m = result.meta
            val bmp = result.drape
            val hg = result.heights
            if (bmp == null || hg == null) {
                status.text = "3D preview unavailable: " + m.optString("error", "unknown error") +
                    ". The Final Image button still opens the full view."
                frame.visibility = View.GONE
                return@launch
            }
            card.removeView(status)
            val pins = mutableListOf<Surface3DView.Pin>()
            val cands = m.optJSONArray("candidates")
            if (cands != null) for (i in 0 until cands.length()) {
                val c = cands.getJSONObject(i)
                pins += Surface3DView.Pin(c.optDouble("x").toFloat(), c.optDouble("y").toFloat(),
                    FinalImageView.styleColour(c.optString("style")), c.optBoolean("focus"))
            }
            val ve = m.optDouble("ve_auto", 1.0).toFloat()
            val gv = Surface3DView(this@MissionControlActivity).apply {
                onGlError = { msg -> caption.text = "3D error: $msg" }
                // let the 3D view rotate without the page scrolling
                setOnTouchListener { v, e ->
                    if (e.actionMasked == MotionEvent.ACTION_DOWN) v.parent?.requestDisallowInterceptTouchEvent(true)
                    false
                }
            }
            glView = gv
            frame.addView(gv, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
            frame.addView(text("Drag to rotate \u00B7 pinch to zoom \u00B7 double-tap to reset", 11f, 0xFFE6EDF3.toInt()).apply {
                setPadding(px(8), px(4), px(8), px(4))
                background = AriyanDecor.pill(d, 0x99000000.toInt())
            }, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL).apply { bottomMargin = px(8) })
            gv.setSurface(hg, m.getInt("width"), m.getInt("height"),
                m.getDouble("cell_dx_m").toFloat(), m.getDouble("cell_dy_m").toFloat(),
                ve, Surface3DView.Drape(bmp, 0f, 0f, 1f, 1f), pins, null, true)
            caption.text = String.format(Locale.US,
                "Real DEM window \u00B11 km (%s), relief colours hillshaded. Height \u00D7%s (automatic). " +
                    "%d candidate %s in view; the top candidate is the large pin.",
                m.optString("source_label").ifBlank { m.optString("source") },
                if (ve % 1f == 0f) ve.toInt().toString() else ve.toString(),
                pins.size, if (pins.size == 1) "pin" else "pins")
            if (!m.isNull("z_min_m") && !m.isNull("z_max_m")) {
                val lo = m.optDouble("z_min_m"); val hi = m.optDouble("z_max_m")
                card.addView(text(String.format(Locale.US, "Real ground heights in this window: %,.1f to %,.1f m (span %.1f m). " +
                    "The view is stretched \u00D7%s, so small rises look tall.", lo, hi, hi - lo,
                    if (ve % 1f == 0f) ve.toInt().toString() else ve.toString()), 12f, AriyanDecor.AMBER).apply {
                    setPadding(0, px(6), 0, 0)
                }, card.indexOfChild(caption) + 1)
            }
            if (result.thumbs.isNotEmpty()) {
                card.addView(thumbStrip(result.thumbs, cid), card.childCount - 1)   // above the button
            }
        }
    }

    /** mc-v1.3: terrain + every satellite layer already saved for this window (Python never fetches).
     * Runs on a background thread with an open Final Image session. */
    private fun readThumbs(sid: String, source: String, drape: Bitmap): List<Thumb> {
        val thumbs = mutableListOf(Thumb("Terrain (relief, hillshaded)", "SAVED",
            "DEM " + source, drape.copy(Bitmap.Config.ARGB_8888, false)))
        try {
            val sim = python.getModule("sat_image_mobile")
            val th = JSONObject(python.getModule("mission_control").callAttr("thumbs_json", offlineDataRoot, sid).toString())
            val layers = th.optJSONArray("layers")
            if (layers != null) for (i in 0 until layers.length()) {
                val l = layers.getJSONObject(i)
                val state = l.optString("state")
                var tb: Bitmap? = null
                var note = when (state) {
                    "SAVED" -> listOfNotNull(nz(l, "scene_date"),
                        if (l.isNull("clear_fraction")) null
                        else String.format(Locale.US, "%.0f%% clear", 100 * l.optDouble("clear_fraction"))).joinToString(" \u00B7 ")
                    "NOT_SAVED" -> "not saved for this window"
                    else -> l.optString("reason")
                }
                if (state == "SAVED") {
                    try {
                        val rb = sim.callAttr("layer_rgba", sid, l.getString("product")).toJava(ByteArray::class.java)
                        tb = Bitmap.createBitmap(l.getInt("width"), l.getInt("height"), Bitmap.Config.ARGB_8888)
                        tb.copyPixelsFromBuffer(ByteBuffer.wrap(rb))
                    } catch (e: PyException) {
                        note = e.message ?: "could not open"
                    }
                }
                thumbs += Thumb(l.optString("label"), if (tb == null && state == "SAVED") "ERROR" else state, note, tb)
            }
        } catch (e: PyException) {
            thumbs += Thumb("Satellite layers", "ERROR", e.message ?: "could not list", null)
        } finally {
            try { python.getModule("sat_image_mobile").callAttr("close_layers", sid) } catch (_: PyException) {}
        }
        return thumbs
    }

    /** mc-v1.3.1: re-read only the thumbnail strip (same window), keeping the 3D view. */
    private fun refreshThumbs(card: LinearLayout, cid: String) {
        lifecycleScope.launch {
            val thumbs = withContext(Dispatchers.Default) {
                var sid: String? = null
                val fim = python.getModule("final_image_mobile")
                try {
                    val j = JSONObject(fim.callAttr("open_final_image_json", offlineDataRoot, cid, 1000.0, "relief").toString())
                    if (j.has("error")) return@withContext null
                    sid = j.getString("session_id")
                    val bytes = fim.callAttr("image_rgba", sid).toJava(ByteArray::class.java)
                    val bmp = Bitmap.createBitmap(j.getInt("width"), j.getInt("height"), Bitmap.Config.ARGB_8888)
                    bmp.copyPixelsFromBuffer(ByteBuffer.wrap(bytes))
                    readThumbs(sid!!, j.optString("source"), bmp)
                } catch (e: PyException) {
                    null
                } catch (e: OutOfMemoryError) {
                    null
                } finally {
                    sid?.let { try { fim.callAttr("close_session", it) } catch (_: PyException) {} }
                }
            } ?: return@launch
            if (terrainFor != cid) return@launch
            val old = card.findViewWithTag<View>("thumbStrip")
            val at = if (old != null) card.indexOfChild(old).also { card.removeView(old) } else card.childCount - 1
            card.addView(thumbStrip(thumbs, cid), at)
        }
    }

    /** mc-v1.3: terrain + satellite thumbnails of the 3D window (saved images only). */
    private fun thumbStrip(thumbs: List<Thumb>, cid: String): View {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, px(10), 0, 0); tag = "thumbStrip" }
        box.addView(text("LAYERS FOR THIS WINDOW (saved on the phone; nothing is fetched here)", 11f,
            col(R.color.ariyan_text_secondary), bold = true).apply { letterSpacing = 0.04f })
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, px(6), 0, 0) }
        thumbs.forEach { t ->
            val c = when (t.state) {
                "SAVED" -> AriyanDecor.ACCENT
                "NOT_SAVED" -> AriyanDecor.LINE
                else -> AriyanDecor.ORANGE
            }
            val cell = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(px(6), px(6), px(6), px(6))
                background = AriyanDecor.panel(d, c, 10f)
                isClickable = true
                setOnClickListener { startActivity(FinalImageActivity.newIntent(this@MissionControlActivity, cid)) }
            }
            val img = FrameLayout(this).apply {
                background = GradientDrawable().apply { cornerRadius = 6 * d; setColor(0xFF0B0E13.toInt()) }
            }
            if (t.bitmap != null) {
                img.addView(ImageView(this).apply {
                    // exact cells: no smoothing when the small image is enlarged
                    setImageDrawable(BitmapDrawable(resources, t.bitmap).apply { isFilterBitmap = false })
                    scaleType = ImageView.ScaleType.CENTER_CROP
                }, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
            } else {
                img.addView(text(if (t.state == "NOT_SAVED") "not saved" else "hidden", 11f,
                    col(R.color.ariyan_text_secondary)).apply { gravity = Gravity.CENTER },
                    FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
            }
            cell.addView(img, LinearLayout.LayoutParams(px(104), px(104)))
            cell.addView(text(t.label, 11f, col(R.color.ariyan_text_primary), bold = true).apply {
                setPadding(0, px(4), 0, 0); maxLines = 2
            }, LinearLayout.LayoutParams(px(104), LinearLayout.LayoutParams.WRAP_CONTENT))
            cell.addView(text(t.note, 10f, col(R.color.ariyan_text_secondary)).apply { maxLines = 3 },
                LinearLayout.LayoutParams(px(104), LinearLayout.LayoutParams.WRAP_CONTENT))
            row.addView(cell, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT).apply { rightMargin = px(8) })
        }
        box.addView(HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(row) })
        box.addView(text("Missing layers: open the Final Image and choose them from Satellite (uses Copernicus quota once; saved after).",
            11f, col(R.color.ariyan_text_secondary)).apply { setPadding(0, px(6), 0, 0) })
        return box
    }

    private fun scrollToTerrain() {
        val card = terrainCard
        val sv = content.parent as? ScrollView
        if (card == null || sv == null || card.parent == null) {
            android.widget.Toast.makeText(this, "The 3D terrain appears once there is a candidate target.",
                android.widget.Toast.LENGTH_SHORT).show()
            return
        }
        sv.smoothScrollTo(0, card.top)
    }

    /** mc-v1.3: Analysis & Models, read from the app's own code and database. */
    private fun showModels() {
        lifecycleScope.launch {
            val o = withContext(Dispatchers.Default) {
                try {
                    JSONObject(python.getModule("mission_control").callAttr("models_json", offlineDataRoot).toString())
                } catch (e: PyException) {
                    JSONObject().put("error", e.message)
                }
            }
            val box = LinearLayout(this@MissionControlActivity).apply {
                orientation = LinearLayout.VERTICAL; setPadding(px(18), px(6), px(18), px(8))
            }
            if (o.has("error")) line(box, o.optString("error"), true)
            val rows = o.optJSONArray("models")
            if (rows != null) for (i in 0 until rows.length()) {
                val r = rows.getJSONObject(i)
                val c = AriyanDecor.PERSPECTIVE_COLOURS[i % AriyanDecor.PERSPECTIVE_COLOURS.size]
                val card = LinearLayout(this@MissionControlActivity).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(px(10), px(8), px(10), px(10))
                    background = AriyanDecor.panel(d, c, 10f)
                }
                card.addView(text(r.optString("name"), 14f, c, bold = true))
                card.addView(chip(r.optString("version"), c, small = true), LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(4) })
                line(card, r.optString("role"), true)
                line(card, r.optString("limits"))
                box.addView(card, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(10) })
            }
            nz(o, "statement")?.let { line(box, it) }
            AlertDialog.Builder(this@MissionControlActivity)
                .setTitle("Analysis & Models")
                .setView(ScrollView(this@MissionControlActivity).apply { addView(box) })
                .setPositiveButton("Close", null)
                .show()
        }
    }

    private fun tiles(o: JSONObject?) {
        val last = lastFinalImage()
        val debates = o?.optInt("debates_stored", -1) ?: -1
        val items = listOf(
            Tile("Investigation", "Single point + AI debate", "target", AriyanDecor.ACCENT) { go(MainActivity::class.java) },
            Tile("Wide-area search", "Jobs, Auto run, DEM library", "grid", AriyanDecor.TEAL) { go(WideAreaSearchActivity::class.java) },
            Tile("Grand Project", "Candidates, reviews, reports", "stack", AriyanDecor.BLUE) { go(GrandProjectActivity::class.java) },
            Tile("Data & Evidence", "Offline country data", "data", AriyanDecor.VIOLET) { go(OfflineDataActivity::class.java) },
            Tile("Historical research", "Texts and place names", "book", AriyanDecor.AMBER) { go(HistoricalResearchActivity::class.java) },
            Tile("AI Debate Engine",
                if (debates >= 0) String.format(Locale.US, "%,d stored %s", debates, plural(debates, "debate", "debates"))
                else "Stored debates", "debate", AriyanDecor.ROSE) { go(DebateEngineActivity::class.java) },
            Tile("Last Final Image", if (last != null) "Candidate " + last.take(8) else "None opened yet",
                "mountain", AriyanDecor.ORANGE) { openLastFinalImage(last) }
        )
        val cols = if (landscape) 4 else 2
        content.addView(sectionTitle("MODULES"))
        items.chunked(cols).forEach { chunk ->
            val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            chunk.forEach { t ->
                row.addView(tile(t), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f).apply {
                    setMargins(px(3), px(3), px(3), px(3))
                })
            }
            repeat(cols - chunk.size) {
                row.addView(View(this), LinearLayout.LayoutParams(0, 1, 1f).apply { setMargins(px(3), 0, px(3), 0) })
            }
            content.addView(row)
        }
        content.addView(View(this), LinearLayout.LayoutParams(1, px(6)))
    }

    private fun targets(o: JSONObject): View? {
        val top = o.optJSONArray("top") ?: return null
        return panel("CANDIDATE TARGETS", "target", AriyanDecor.ACCENT).apply {
            if (top.length() == 0) {
                line(this, "No candidates yet (Rejected ones are left out).", true)
                return@apply
            }
            line(this, "Best by Steward band, confidence, Supported first, then |z|. Tap one to open its Final Image.")
            for (i in 0 until top.length()) addView(targetCard(i + 1, top.getJSONObject(i)),
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(8) })
        }
    }

    private fun targetCard(rank: Int, t: JSONObject): View {
        val band = t.optString("band")
        val bc = BAND_COLOURS[band] ?: AriyanDecor.LINE
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            background = GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,
                intArrayOf(AriyanDecor.withAlpha(bc, 34), AriyanDecor.SURFACE)).apply {
                cornerRadius = 10 * d; setStroke(maxOf(1, d.toInt()), AriyanDecor.withAlpha(bc, 90))
            }
            isClickable = true
            setOnClickListener { startActivity(FinalImageActivity.newIntent(this@MissionControlActivity, t.getString("id"))) }
        }
        card.addView(View(this).apply { setBackgroundColor(bc) }, LinearLayout.LayoutParams(px(4), LinearLayout.LayoutParams.MATCH_PARENT))
        card.addView(text(rank.toString(), 14f, col(R.color.ariyan_bg), bold = true).apply {
            gravity = Gravity.CENTER
            background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(bc) }
        }, LinearLayout.LayoutParams(px(28), px(28)).apply { setMargins(px(10), px(10), px(4), 0) })
        val body = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(px(6), px(8), px(10), px(9)) }
        val conf = if (t.isNull("numeric")) BAND_NAMES[band] ?: band
            else String.format(Locale.US, "%s %.2f", BAND_NAMES[band] ?: band, t.optDouble("numeric"))
        body.addView(text(t.getString("id").take(8) + "  \u00B7  " + conf, 15f, bc, bold = true))
        val z = if (t.isNull("z")) "" else String.format(Locale.US, "  \u00B7  |z| %.1f", Math.abs(t.optDouble("z")))
        body.addView(text(String.format(Locale.US, "%.5f, %.5f%s", t.optDouble("lat"), t.optDouble("lon"), z), 12f,
            col(R.color.ariyan_text_secondary)))
        (nz(t, "job_title") ?: if (nz(t, "job_id") == null) "single investigation" else null)?.let {
            body.addView(text("Job: $it", 12f, col(R.color.ariyan_text_secondary)))
        }
        val ks = nz(t, "known_site")
        val chips = mutableListOf(chip(t.optString("status"), STATUS_COLOURS[t.optString("status")] ?: AriyanDecor.ACCENT, small = true))
        if (t.optBoolean("calib_strong")) chips += chip("calib-v1 strong", AriyanDecor.TEAL, small = true)
        if (ks != null && ks.contains("likely rediscovery")) chips += chip("likely rediscovery", AriyanDecor.VIOLET, small = true)
        chipRows(body, chips, 3)
        ks?.let { body.addView(text(it, 12f, col(R.color.ariyan_text_secondary)).apply { setPadding(0, px(4), 0, 0) }) }
        card.addView(body, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        return card
    }

    private fun sources(o: JSONObject): View? {
        val src = o.optJSONArray("sources") ?: return null
        val creds = SecureCredentialStore(this)
        val glyphs = listOf("mountain", "mountain", "mountain", "layers", "grid", "target", "steward", "data")
        return panel("DATA SOURCES (on this phone)", "data", AriyanDecor.VIOLET).apply {
            for (i in 0 until src.length()) {
                val s = src.getJSONObject(i)
                sourceRow(this, s.optBoolean("ok"), s.optString("name"), s.optString("detail"), glyphs.getOrElse(i) { "data" })
            }
            val ot = creds.activeOpenTopographyApiKey().isNotEmpty()
            val cp = creds.activeCopernicusClientId().isNotEmpty()
            sourceRow(this, ot, "OpenTopography key", if (ot) "set" else "not set (live DEM unavailable)", "steward")
            sourceRow(this, cp, "Copernicus key", if (cp) "set" else "not set (satellite evidence unavailable)", "steward")
        }
    }

    private fun footer(o: JSONObject?) {
        val principles = o?.optJSONArray("principles")
        val names = if (principles != null) (0 until principles.length()).map { principles.optString(it) }
            else listOf("Real Data Only", "Scientific Integrity", "No Synthetic Data", "Uncertainty Quantified", "Human Oversight")
        content.addView(sectionTitle("PRINCIPLES").apply { setPadding(px(3), px(16), 0, px(2)) })
        val holder = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        chipRows(holder, names.map { chip("\u2713 $it", AriyanDecor.ACCENT) }, if (landscape) 5 else 2)
        content.addView(holder)
        o?.let { nz(it, "statement") }?.let {
            content.addView(text(it, 11f, col(R.color.ariyan_text_secondary)).apply {
                gravity = Gravity.CENTER; setPadding(px(8), px(10), px(8), 0)
            })
        }
    }

    // --------------------------------------------------------------- widgets

    private fun go(cls: Class<*>) = startActivity(Intent(this, cls))

    private fun lastFinalImage(): String? =
        getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_LAST_FINAL_IMAGE, null)

    private fun openLastFinalImage(last: String?) {
        if (last != null) startActivity(FinalImageActivity.newIntent(this, last))
        else android.widget.Toast.makeText(this, "Open a candidate's Final Image once; it will appear here.",
            android.widget.Toast.LENGTH_LONG).show()
    }

    private fun plural(n: Int, one: String, many: String) = if (n == 1) one else many

    private fun nz(o: JSONObject, k: String): String? = o.optString(k).takeIf { !o.isNull(k) && it.isNotBlank() && it != "null" }

    private fun text(s: String, size: Float, colour: Int, bold: Boolean = false) = TextView(this).apply {
        text = s; textSize = size; setTextColor(colour)
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun sectionTitle(s: String) = text(s, 12f, col(R.color.ariyan_text_secondary), bold = true).apply {
        setPadding(px(3), px(8), 0, px(2)); letterSpacing = 0.08f
    }

    private fun panel(title: String, glyph: String, tint: Int): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(px(14), px(12), px(14), px(14))
        background = AriyanDecor.panel(d, tint)
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { setMargins(0, px(6), 0, px(6)) }
        val head = LinearLayout(this@MissionControlActivity).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        head.addView(AriyanDecor.Glyph(this@MissionControlActivity, glyph, tint), LinearLayout.LayoutParams(px(20), px(20)))
        head.addView(text(title, 13f, tint, bold = true).apply { setPadding(px(8), 0, 0, 0); letterSpacing = 0.06f })
        addView(head)
    }

    private fun line(box: LinearLayout, s: String, primary: Boolean = false) {
        box.addView(text(s, 13f, col(if (primary) R.color.ariyan_text_primary else R.color.ariyan_text_secondary)).apply {
            setPadding(0, px(6), 0, 0)
        })
    }

    private fun statBox(n: Int, label: String, c: Int) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_HORIZONTAL
        setPadding(px(4), px(8), px(4), px(8))
        background = GradientDrawable().apply { cornerRadius = 10 * d; setColor(AriyanDecor.withAlpha(c, 30)) }
        addView(text(String.format(Locale.US, "%,d", n), 18f, c, bold = true).apply { gravity = Gravity.CENTER })
        addView(text(label, 11f, col(R.color.ariyan_text_secondary)).apply { gravity = Gravity.CENTER })
    }

    private fun chip(s: String, c: Int, small: Boolean = false) = text(s, if (small) 11f else 12f, c, bold = true).apply {
        setPadding(px(10), px(if (small) 3 else 5), px(10), px(if (small) 3 else 5))
        background = AriyanDecor.pill(d, AriyanDecor.withAlpha(c, 34), AriyanDecor.withAlpha(c, 110))
        gravity = Gravity.CENTER
    }

    /** Lays chips out in rows of up to perRow (no flow layout on the platform). */
    private fun chipRows(box: LinearLayout, chips: List<View>, perRow: Int) {
        chips.chunked(perRow).forEach { chunk ->
            val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            chunk.forEach { v ->
                row.addView(v, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT).apply { setMargins(0, px(6), px(6), 0) })
            }
            box.addView(row)
        }
    }

    private fun actionPill(label: String, c: Int, action: () -> Unit) = text(label, 14f, col(R.color.ariyan_bg), bold = true).apply {
        gravity = Gravity.CENTER
        setPadding(px(16), px(10), px(16), px(10))
        background = GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,
            intArrayOf(c, AriyanDecor.withAlpha(c, 200))).apply { cornerRadius = 40 * d }
        isClickable = true
        setOnClickListener { action() }
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(12) }
    }

    private fun sourceRow(box: LinearLayout, ok: Boolean, name: String, detail: String, glyph: String) {
        val c = if (ok) AriyanDecor.ACCENT else AriyanDecor.ORANGE
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(px(8), px(7), px(8), px(7))
            background = GradientDrawable().apply { cornerRadius = 8 * d; setColor(AriyanDecor.withAlpha(c, 16)) }
        }
        row.addView(AriyanDecor.Glyph(this, glyph, c), LinearLayout.LayoutParams(px(22), px(22)))
        val texts = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(px(10), 0, px(6), 0) }
        texts.addView(text(name, 13f, col(R.color.ariyan_text_primary), bold = true))
        texts.addView(text(detail, 12f, col(R.color.ariyan_text_secondary)))
        row.addView(texts, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(text(if (ok) "\u2713" else "\u2717", 16f, c, bold = true))
        box.addView(row, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(6) })
    }

    private fun tile(t: Tile) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(px(12), px(12), px(10), px(12))
        background = AriyanDecor.panel(d, t.colour, 12f)
        isClickable = true
        setOnClickListener { t.action() }
        addView(View(this@MissionControlActivity).apply {
            background = GradientDrawable().apply { cornerRadius = 10 * d; setColor(AriyanDecor.withAlpha(t.colour, 40)) }
        }.let { bg ->
            FrameLayout(this@MissionControlActivity).apply {
                addView(bg, FrameLayout.LayoutParams(px(36), px(36)))
                addView(AriyanDecor.Glyph(this@MissionControlActivity, t.glyph, t.colour),
                    FrameLayout.LayoutParams(px(24), px(24)).apply { leftMargin = px(6); topMargin = px(6) })
            }
        }, LinearLayout.LayoutParams(px(36), px(36)))
        addView(text(t.title, 14f, col(R.color.ariyan_text_primary), bold = true).apply { setPadding(0, px(8), 0, 0) })
        addView(text(t.sub, 11f, col(R.color.ariyan_text_secondary)).apply { setPadding(0, px(2), 0, 0) })
    }
}
