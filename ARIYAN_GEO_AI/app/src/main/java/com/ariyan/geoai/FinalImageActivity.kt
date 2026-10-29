package com.ariyan.geoai

import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.chaquo.python.PyException
import com.chaquo.python.Python
import com.google.android.material.button.MaterialButton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.util.Locale

/**
 * fi-v1 (2026-10-16): the Final Image screen -- first brick of the Final
 * Assessment page. Opened per candidate from the Grand Project candidate
 * detail dialog.
 *
 * Shows the real saved DEM around the candidate (final_image.py via
 * final_image_mobile.py): local-relief or elevation colour, shaded by a
 * 4-direction hillshade, with contours, a UTM grid, every candidate of the
 * project inside the window, a scale bar, north arrow and legend.
 * Pinch / pan / double-tap zoom. "Exact cells" (default) keeps every DEM
 * cell a crisp square at any zoom; "Smooth" interpolates and says so.
 *
 * Visual enhancement only: nothing here writes a candidate, a review, a
 * status or a confidence. Marker colours are READ from the stored values.
 *
 * fi-v2.2 (2026-10-29): rotation. Portrait stacks map over the side column,
 * landscape puts them side by side (map ~60 %). The view keeps the same ground
 * on any size change; state is saved as ground, never pixels. "View across"
 * reports the shorter side; the past-native banner uses the active layer's cell.
 */
class FinalImageActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_CANDIDATE_ID = "candidate_id"
        fun newIntent(ctx: Context, candidateId: String) =
            Intent(ctx, FinalImageActivity::class.java).putExtra(EXTRA_CANDIDATE_ID, candidateId)
    }

    private lateinit var python: Python
    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }
    private lateinit var candidateId: String

    private lateinit var view: FinalImageView
    private lateinit var title: TextView
    private lateinit var info: TextView
    private lateinit var legendBar: View
    private lateinit var legendText: TextView
    private lateinit var notes: TextView
    private lateinit var progress: ProgressBar
    private lateinit var modeBtn: MaterialButton
    private lateinit var colourBtn: MaterialButton
    private lateinit var windowBtn: MaterialButton

    private var sessionId: String? = null
    private var meta: JSONObject? = null
    private var halfSizeM = 1000.0
    private var colourBy = "relief"
    private var nativeRes = 30.0

    // fi-v2 (2026-10-21): satellite layer over the terrain
    private lateinit var satBtn: MaterialButton
    private var satProduct: String? = null
    private var satMeta: JSONObject? = null

    // fa-v1 (2026-10-21): Profile & Section A-A'
    private lateinit var profileBtn: MaterialButton
    private lateinit var profilePanel: LinearLayout
    private lateinit var profileTitle: TextView
    private lateinit var profileView: ProfileView
    private lateinit var readout: TextView
    private var profile: JSONObject? = null
    /** the line as asked for (grid pixels); the profile itself may be trimmed to the window */
    private var lineAsk: FloatArray? = null
    private var preset: String? = null
    private var pickA: FloatArray? = null

    // fa-v2 (2026-10-22): DERIVED filters of the same DEM (display only).
    // One overlay at a time: a filter and a satellite layer share the map's overlay slot.
    private lateinit var filterBtn: MaterialButton
    private var filterName: String? = null
    private var filterParams: JSONObject? = null
    private var filterMeta: JSONObject? = null

    // fi-v2.2 (2026-10-29): rotation
    private lateinit var body: LinearLayout
    private lateinit var mapFrame: FrameLayout
    private lateinit var side: ScrollView
    private lateinit var sideCol: LinearLayout
    private lateinit var notesScroll: ScrollView
    private var pendingGround: FloatArray? = null   // from savedInstanceState, applied once
    private var restoring = false

    private fun col(id: Int) = ContextCompat.getColor(this, id)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        candidateId = intent.getStringExtra(EXTRA_CANDIDATE_ID) ?: run { finish(); return }
        python = Python.getInstance()
        val s = savedInstanceState
        if (s != null) {
            restoring = true
            halfSizeM = s.getDouble("halfSizeM", halfSizeM)
            colourBy = s.getString("colourBy") ?: colourBy
            satProduct = s.getString("satProduct")
            filterName = s.getString("filterName")
            filterParams = s.getString("filterParams")?.let { JSONObject(it) }
            preset = s.getString("preset")
            lineAsk = s.getFloatArray("lineAsk")
            pendingGround = s.getFloatArray("ground")
        }
        buildUi()
        if (s != null) {
            view.smooth = s.getBoolean("smooth", false)
            modeBtn.text = if (view.smooth) "Smooth" else "Exact cells"
            windowBtn.text = "Window: " + if (halfSizeM >= 1000) "\u00B1${trimNum(halfSizeM / 1000)} km"
                else "\u00B1${halfSizeM.toInt()} m"
        }
        load(keepView = false)
    }

    override fun onSaveInstanceState(out: Bundle) {
        super.onSaveInstanceState(out)
        out.putDouble("halfSizeM", halfSizeM)
        out.putString("colourBy", colourBy)
        out.putString("satProduct", satProduct)
        out.putString("filterName", filterName)
        out.putString("filterParams", filterParams?.toString())
        out.putString("preset", preset)
        out.putFloatArray("lineAsk", if (profile != null) lineAsk else null)
        if (::view.isInitialized) {
            out.putBoolean("smooth", view.smooth)
            view.groundState()?.let { out.putFloatArray("ground", it) }
        }
    }

    /** called when the manifest has configChanges for this activity */
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (::body.isInitialized) applyOrientation()   // the view's onSizeChanged keeps the ground
    }

    override fun onDestroy() {
        sessionId?.let { sid ->
            runCatching { python.getModule("sat_image_mobile").callAttr("close_layers", sid) }
            runCatching { python.getModule("dem_filters_mobile").callAttr("close_filter", sid) }
            runCatching { python.getModule("final_image_mobile").callAttr("close_session", sid) }
        }
        if (::view.isInitialized) view.clearImage()
        super.onDestroy()
    }

    // ------------------------------------------------------------------ UI

    private fun buildUi() {
        val d = resources.displayMetrics.density
        val pad = (12 * d).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(col(R.color.ariyan_bg))
        }
        title = TextView(this).apply {
            text = "Final Image \u00B7 candidate ${candidateId.take(8)}"
            textSize = 16f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(col(R.color.ariyan_text_primary))
            setPadding(pad, pad, pad, pad / 4)
        }
        root.addView(title)

        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(pad / 2, 0, pad / 2, 0) }
        fun button(t: String, onClick: () -> Unit) = MaterialButton(this).apply {
            text = t; isAllCaps = false; textSize = 12f
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { marginStart = pad / 3; marginEnd = pad / 3 }
        }
        modeBtn = button("Exact cells") { toggleMode() }
        colourBtn = button("Colour: relief") { toggleColour() }
        windowBtn = button("Window: \u00B11 km") { chooseWindow() }
        buttons.addView(modeBtn)
        buttons.addView(colourBtn)
        buttons.addView(windowBtn)
        satBtn = button("Satellite: off") { chooseSatellite() }
        buttons.addView(satBtn)
        filterBtn = button("Filters: off") { chooseFilter() }
        buttons.addView(filterBtn)
        profileBtn = button("Profile") { chooseProfile() }
        buttons.addView(profileBtn)
        buttons.addView(button("Layers") { chooseLayers() })
        buttons.addView(button("Fit") { view.fitToScreen() })
        buttons.addView(button("Centre") { centreOnCandidate() })
        buttons.addView(button("Export") { export() })
        root.addView(HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(buttons) })

        // fi-v2.2: map and side column share `body`; applyOrientation() decides the layout.
        // The map never gets a pixel height; it takes whatever the layout gives it.
        body = LinearLayout(this)
        mapFrame = FrameLayout(this)
        view = FinalImageView(this).apply {
            onViewChanged = { updateInfo() }
            onMarkersTapped = { if (it.size == 1) showMarker(it[0]) else showCluster(it) }
            onGridTapped = { x, y -> onPick(x, y) }
        }
        mapFrame.addView(view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        progress = ProgressBar(this).apply { visibility = View.GONE }
        mapFrame.addView(progress, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
        body.addView(mapFrame)

        sideCol = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        sideCol.addView(buildProfilePanel(pad, d))

        info = smallText(R.color.ariyan_accent).apply { setPadding(pad, pad / 3, pad, 0) }
        sideCol.addView(info)

        val legendRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(pad, pad / 3, pad, 0)
        }
        legendBar = View(this)
        legendRow.addView(legendBar, LinearLayout.LayoutParams((120 * d).toInt(), (10 * d).toInt()))
        legendText = smallText(R.color.ariyan_text_secondary).apply { setPadding(pad / 2, 0, 0, 0) }
        // fi-v2.1: give the legend text the remaining width so long satellite legends wrap
        // inside the row instead of spilling into the notes area below.
        legendRow.addView(legendText, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        sideCol.addView(legendRow, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        sideCol.addView(View(this).apply { setBackgroundColor(col(R.color.ariyan_text_secondary)); alpha = 0.35f },
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, maxOf(1, d.toInt())).apply { topMargin = pad / 3 })

        notes = smallText(R.color.ariyan_text_secondary).apply { setPadding(pad, pad / 3, pad, pad) }
        notesScroll = ScrollView(this).apply {
            clipChildren = true; clipToPadding = true
            setBackgroundColor(col(R.color.ariyan_bg))
            addView(notes)
        }
        sideCol.addView(notesScroll)
        side = ScrollView(this).apply { isFillViewport = true; addView(sideCol) }
        body.addView(side)

        root.addView(body, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        applyOrientation()
        setContentView(root)
    }

    private fun buildProfilePanel(pad: Int, d: Float): View {
        profilePanel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
            setPadding(pad / 2, pad / 3, pad / 2, 0)
        }
        val head = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        profileTitle = smallText(R.color.ariyan_text_primary).apply { typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD) }
        head.addView(profileTitle, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        fun small(t: String, onClick: () -> Unit) = MaterialButton(this).apply {
            text = t; isAllCaps = false; textSize = 11f; minWidth = 0; minimumWidth = 0
            insetTop = 0; insetBottom = 0
            setOnClickListener { onClick() }
        }
        head.addView(small("Export") { exportProfile() })
        head.addView(small("Close") { closeProfile() })
        profilePanel.addView(head)
        profileView = ProfileView(this).apply {
            onCursor = { dm -> showCursor(dm) }
            // fi-v2.2: keep drags on the trace away from the side column's ScrollView
            setOnTouchListener { v, e ->
                if (e.actionMasked == MotionEvent.ACTION_DOWN) v.parent.requestDisallowInterceptTouchEvent(true)
                false
            }
        }
        profilePanel.addView(profileView, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, (210 * d).toInt()))
        readout = smallText(R.color.ariyan_text_secondary).apply { setPadding(pad / 2, pad / 4, pad / 2, 0) }
        profilePanel.addView(readout)
        return profilePanel
    }

    private fun smallText(colour: Int) = TextView(this).apply {
        textSize = 11f
        typeface = Typeface.MONOSPACE
        setTextColor(col(colour))
    }

    /** fi-v2.2: portrait: map over the side column; landscape: side by side, map ~60 % */
    private fun applyOrientation() {
        val d = resources.displayMetrics.density
        val land = resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
        val mp = ViewGroup.LayoutParams.MATCH_PARENT
        val wc = ViewGroup.LayoutParams.WRAP_CONTENT
        body.orientation = if (land) LinearLayout.HORIZONTAL else LinearLayout.VERTICAL
        mapFrame.layoutParams = if (land) LinearLayout.LayoutParams(0, mp, 0.6f) else LinearLayout.LayoutParams(mp, 0, 1f)
        side.layoutParams = if (land) LinearLayout.LayoutParams(0, mp, 0.4f) else LinearLayout.LayoutParams(mp, wc)
        // portrait keeps the 88 dp notes box; landscape lets the whole column scroll
        notesScroll.layoutParams = LinearLayout.LayoutParams(mp, if (land) wc else (88 * d).toInt())
        body.requestLayout()
    }

    private fun spanText(m: Double) =
        if (m >= 1000) String.format(Locale.US, "%.2f km", m / 1000) else "${m.toInt()} m"

    // ------------------------------------------------------------------ data

    private fun load(keepView: Boolean) {
        setLoading(true)
        val old = sessionId
        lifecycleScope.launch {
            try {
                val (m, bmp) = withContext(Dispatchers.Default) {
                    val mod = python.getModule("final_image_mobile")
                    old?.let { mod.callAttr("close_session", it) }
                    val j = JSONObject(mod.callAttr("open_final_image_json", offlineDataRoot, candidateId, halfSizeM, colourBy).toString())
                    if (j.has("error")) Pair(j, null) else {
                        val bytes = mod.callAttr("image_rgba", j.getString("session_id")).toJava(ByteArray::class.java)
                        val b = Bitmap.createBitmap(j.getInt("width"), j.getInt("height"), Bitmap.Config.ARGB_8888)
                        b.copyPixelsFromBuffer(ByteBuffer.wrap(bytes))
                        Pair(j, b)
                    }
                }
                if (bmp == null) {
                    sessionId = null
                    showError(m.optString("error"))
                } else {
                    apply(m, bmp, keepView)
                }
            } catch (e: PyException) {
                showError(e.message ?: "Python error")
            } catch (e: OutOfMemoryError) {
                showError("Not enough memory for this window; choose a smaller window.")
            } finally {
                setLoading(false)
            }
        }
    }

    private fun apply(m: JSONObject, bmp: Bitmap, keepView: Boolean) {
        meta = m
        sessionId = m.getString("session_id")
        nativeRes = m.optDouble("native_resolution_m", 30.0)
        view.levels = parseLevels(m.getJSONObject("contours"))
        view.utmLines = parseUtm(m.optJSONObject("utm_grid"))
        view.markers = parseMarkers(m.getJSONArray("candidates"))
        view.setImage(bmp, m.optDouble("cell_dx_m", nativeRes), keepView)
        pendingGround?.let { view.restoreGround(it); pendingGround = null }   // fi-v2.2: after a rebuild
        title.text = String.format(Locale.US, "Final Image \u00B7 %s  (%.5f, %.5f)",
            candidateId.take(8), m.getDouble("lat"), m.getDouble("lon"))
        updateLegend(m)
        updateNotes(m)
        updateInfo()
        // a new window / colour is a new session: re-open the chosen layer on it
        // (saved images only; never fetches without asking)
        // a hand-drawn A-A' only fits the window it was drawn on; presets are re-run
        // fi-v2.2: after a rebuild the window is the same, so a restored line is kept
        val wasRestoring = restoring
        restoring = false
        if (!keepView && !wasRestoring && preset == null && lineAsk != null) closeProfile()
        val sp = satProduct
        val fn = filterName
        if (sp != null) openSatellite(sp, fetch = false, quiet = true)   // refreshes the profile itself
        else if (fn != null) openFilter(fn, filterParams ?: JSONObject(), quiet = true)
        else refreshProfile(true)
    }

    private fun parseLevels(c: JSONObject): List<FinalImageView.Level> {
        val arr = c.getJSONArray("levels")
        return (0 until arr.length()).map { i ->
            val lv = arr.getJSONObject(i)
            val flat = lv.getJSONArray("flat")
            FinalImageView.Level(lv.getDouble("level_m"), lv.optBoolean("index"),
                FloatArray(flat.length()) { k -> flat.getDouble(k).toFloat() })
        }
    }

    private fun parseUtm(u: JSONObject?): List<FinalImageView.UtmLine> {
        val arr = u?.optJSONArray("lines") ?: return emptyList()
        return (0 until arr.length()).map { i ->
            val ln = arr.getJSONObject(i)
            val pts = ln.getJSONArray("points")
            val f = FloatArray(pts.length() * 2)
            for (k in 0 until pts.length()) {
                val p = pts.getJSONArray(k); f[2 * k] = p.getDouble(0).toFloat(); f[2 * k + 1] = p.getDouble(1).toFloat()
            }
            FinalImageView.UtmLine(ln.getString("axis"), ln.getInt("value"), f)
        }
    }

    private fun parseMarkers(arr: JSONArray): List<FinalImageView.Marker> = (0 until arr.length()).map { i ->
        val o = arr.getJSONObject(i)
        FinalImageView.Marker(o.getString("id"), o.getDouble("x").toFloat(), o.getDouble("y").toFloat(),
            o.optString("style", "unrated"), o.optString("status"),
            if (o.isNull("confidence_label")) null else o.optString("confidence_label"),
            o.optBoolean("focus"))
    }

    private fun updateLegend(m: JSONObject) {
        colourBtn.text = "Colour: " + if (colourBy == "relief") "relief" else "elevation"
        satMeta?.let { updateSatLegend(it); return }
        filterMeta?.let { updateFilterLegend(it); return }
        val ramp = m.getJSONArray("ramp")
        val colours = IntArray(ramp.length()) { i ->
            val s = ramp.getJSONArray(i)
            android.graphics.Color.rgb(s.getInt(1), s.getInt(2), s.getInt(3))
        }
        legendBar.background = GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, colours)
        val lg = m.getJSONObject("legend")
        val lo = lg.getDouble("min"); val hi = lg.getDouble("max")
        legendText.text = if (lg.optString("colour_by") == "relief")
            String.format(Locale.US, "%+.1f \u2026 %+.1f %s (shaded by 4-sun hillshade)", lo, hi, lg.optString("units"))
        else String.format(Locale.US, "%.0f \u2026 %.0f %s (shaded by 4-sun hillshade)", lo, hi, lg.optString("units"))
        colourBtn.text = "Colour: " + if (colourBy == "relief") "relief" else "elevation"
    }

    private fun updateNotes(m: JSONObject) {
        val sb = StringBuilder()
        sb.append("Source: ").append(m.optString("source", "offline DEM tile"))
        sb.append(String.format(Locale.US, ", native %.1f m/cell, %d\u00D7%d cells.\n",
            nativeRes, m.getInt("width"), m.getInt("height")))
        val ci = m.getJSONObject("contours")
        val iv = ci.optDouble("interval_m")
        sb.append(if (iv.isNaN()) "No contours (terrain too flat for a useful interval).\n"
            else "Contours every ${trimNum(iv)} m (thick = every 5th).\n")
        sb.append("Markers: colour = stored confidence (red HIGH, orange MODERATE, yellow LOW, blue unrated), grey \u00D7 = Rejected, white ring = this candidate. Labels that would overlap are hidden; tap a marker to list every candidate at that spot.\n")
        val utm = m.optJSONObject("utm_grid")
        if (utm != null) sb.append("UTM grid zone ").append(utm.opt("zone")).append(utm.optString("hemisphere")).append(".\n")
        for (key in listOf("problems", "notes")) {
            val a = m.optJSONArray(key) ?: continue
            for (i in 0 until a.length()) sb.append(if (key == "problems") "! " else "\u2022 ").append(a.optString(i)).append('\n')
        }
        // fi-v2.1: the DEM statement is wrong under a satellite layer (it IS new, measured data).
        sb.append(if (satMeta != null) "Satellite layer: a sensor measurement, not archaeological proof. The DEM terrain underneath is unchanged."
            else m.optString("statement"))
        satMeta?.let { sb.insert(0, satNotes(it) + "\n\n") }
        filterMeta?.let { sb.insert(0, filterNotes(it) + "\n\n") }
        notes.text = sb.toString()
    }

    private fun updateInfo() {
        val m = meta ?: return
        val d = resources.displayMetrics.density
        val demCellM = m.optDouble("cell_dx_m", nativeRes)
        val w = view.visibleWindow()
        val wM = (w[2] - w[0]).toDouble() * demCellM
        val hM = (w[3] - w[1]).toDouble() * demCellM
        // fi-v2.2: "across" = the SHORTER side, so the same window reads the same in portrait and landscape
        val across = minOf(wM, hM)

        // fi-v2.2: the cell being looked at: satellite pixel under a satellite layer, otherwise
        // the DEM cell (filters are derived from the DEM, same cells)
        val sm = satMeta
        val satPx = sm?.optDouble("pixel_m") ?: Double.NaN
        val onSat = sm != null && !satPx.isNaN() && satPx > 0
        val cellM = if (onSat) satPx else demCellM
        val cellKind = when {
            onSat -> (satLabels[satProduct]?.substringBefore(" (") ?: sm!!.optString("label", "satellite")) + " image cell"
            filterMeta != null -> "DEM cell (derived filter)"
            else -> "DEM cell"
        }
        val pxPerCell = view.scale * (cellM / demCellM).toFloat()   // view.scale = screen px per DEM cell
        val beyond = pxPerCell > 1f

        val resLabel = if (onSat)
            String.format(Locale.US, "%s %.0f m/pixel (DEM %.1f m/cell)", sm!!.optString("label", "Satellite"), satPx, nativeRes)
        else String.format(Locale.US, "Native %.1f m/cell", nativeRes)
        val mode = if (view.smooth) "Smooth (interpolated, visual only)" else "Exact cells"

        info.text = String.format(Locale.US, "%s \u00B7 %.1f dp per %s \u00B7 view %s across (%s \u00D7 %s) \u00B7 %s%s",
            resLabel, pxPerCell / d, if (onSat) "image cell" else "DEM cell",
            spanText(across), spanText(wM), spanText(hM), mode,
            when {
                beyond && !view.smooth -> "\nZoomed past native: each square is one $cellKind (${trimNum(cellM)} m), no new detail added."
                beyond -> "\nZoomed past native ($cellKind, ${trimNum(cellM)} m): colours between cell centres are interpolated, not measured."
                else -> ""
            })
        if (view.pickMode) info.append(if (pickA == null) "\nProfile: tap point A on the map." else "\nProfile: now tap point A\u2032.")
    }

    // ------------------------------------------------------------------ actions

    private fun toggleMode() {
        view.smooth = !view.smooth
        modeBtn.text = if (view.smooth) "Smooth" else "Exact cells"
        updateInfo()
    }

    private fun toggleColour() {
        colourBy = if (colourBy == "relief") "elevation" else "relief"
        load(keepView = true)
    }

    private fun chooseWindow() {
        val choices = meta?.optJSONArray("window_choices_m")?.let { a -> (0 until a.length()).map { a.getDouble(it) } }
            ?: listOf(500.0, 1000.0, 2500.0, 5000.0)
        val labels = choices.map { if (it >= 1000) "\u00B1${trimNum(it / 1000)} km" else "\u00B1${it.toInt()} m" }
        AlertDialog.Builder(this)
            .setTitle("Window around the candidate")
            .setItems(labels.toTypedArray()) { _, i ->
                halfSizeM = choices[i]
                windowBtn.text = "Window: " + labels[i]
                load(keepView = false)
            }
            .show()
    }

    private fun chooseLayers() {
        val names = arrayOf("Contours", "UTM grid", "Candidates", "Labels")
        val checked = booleanArrayOf(view.showContours, view.showUtm, view.showCandidates, view.showLabels)
        AlertDialog.Builder(this)
            .setTitle("Layers")
            .setMultiChoiceItems(names, checked) { _, i, on -> checked[i] = on }
            .setPositiveButton("OK") { _, _ ->
                view.showContours = checked[0]; view.showUtm = checked[1]
                view.showCandidates = checked[2]; view.showLabels = checked[3]
            }
            .show()
    }

    private fun centreOnCandidate() {
        val f = meta?.optJSONObject("focus") ?: return
        view.focusOn(f.getDouble("x").toFloat(), f.getDouble("y").toFloat(), 8f * resources.displayMetrics.density)
    }

    /** Several markers under the finger: list them all so none is lost behind a hidden label. */
    private fun showCluster(list: List<FinalImageView.Marker>) {
        val items = list.map { mk ->
            mk.id.take(8) + "  " + (mk.confidenceLabel ?: "not rated") + "  \u00B7 " + mk.status +
                (if (mk.focus) "  (this candidate)" else "")
        }.toTypedArray()
        AlertDialog.Builder(this).setTitle("${list.size} candidates here")
            .setItems(items) { _, i -> showMarker(list[i]) }
            .setPositiveButton("Close", null).show()
    }

    private fun showMarker(mk: FinalImageView.Marker) {
        val msg = buildString {
            append("Candidate ").append(mk.id).append('\n')
            append("Status: ").append(mk.status).append('\n')
            append("Confidence: ").append(mk.confidenceLabel ?: "not rated").append('\n')
            append("\n(Read from the database; this image never changes it.)")
        }
        val b = AlertDialog.Builder(this).setTitle(if (mk.focus) "This candidate" else "Nearby candidate")
            .setMessage(msg).setPositiveButton("Close", null)
        if (!mk.focus) b.setNeutralButton("Open its image") { _, _ ->
            startActivity(newIntent(this, mk.id)); finish()
        }
        b.show()
    }

    private fun export() {
        val sid = sessionId ?: return
        setLoading(true)
        lifecycleScope.launch {
            try {
                val r = withContext(Dispatchers.Default) {
                    JSONObject(python.getModule("final_image_mobile").callAttr("export_final_image_json", offlineDataRoot, sid).toString())
                }
                if (r.has("error")) showError(r.getString("error")) else {
                    val p = r.getJSONObject("paths")
                    val text = p.keys().asSequence().joinToString("\n\n") { k -> "$k:\n" + p.getString(k) }
                    AlertDialog.Builder(this@FinalImageActivity)
                        .setTitle("Exported (full window, native cells)")
                        .setMessage("$text\n\nThe GeoTIFF opens georeferenced in QGIS / Surfer / ArcGIS. The provenance file records the source tile and checksums.")
                        .setPositiveButton("OK", null).show()
                }
            } catch (e: PyException) {
                showError(e.message ?: "export failed")
            } finally {
                setLoading(false)
            }
        }
    }

    // ------------------------------------------------------------------ satellite layers (fi-v2)

    private val satLabels = linkedMapOf(
        "NDVI" to "NDVI (Sentinel-2, 10 m)",
        "THERMAL" to "Thermal brightness temp. (Landsat, 30 m)",
        "SAR_VV" to "Radar VV (Sentinel-1, 10 m)",
        "SAR_VH" to "Radar VH (Sentinel-1, 10 m)")

    private fun chooseSatellite() {
        val sid = sessionId ?: return
        setLoading(true)
        lifecycleScope.launch {
            val st = try {
                withContext(Dispatchers.Default) {
                    JSONObject(python.getModule("sat_image_mobile").callAttr("layers_status_json", offlineDataRoot, sid).toString())
                }
            } catch (e: PyException) { JSONObject().put("error", e.message) } finally { setLoading(false) }
            if (st.has("error")) { showError(st.optString("error")); return@launch }
            val arr = st.getJSONArray("products")
            val keys = mutableListOf<String?>(null)
            val items = mutableListOf("Off (terrain only)")
            for (i in 0 until arr.length()) {
                val o = arr.getJSONObject(i)
                val p = o.getString("product")
                keys.add(p)
                val state = when {
                    !o.optBoolean("saved") -> "not saved -- fetch"
                    o.optBoolean("allowed") -> "saved, checked"
                    else -> "saved, not shown yet: " + o.optString("check")
                }
                items.add((satLabels[p] ?: p) + "\n   " + state)
            }
            val b = AlertDialog.Builder(this@FinalImageActivity)
                .setTitle("Satellite layer")
                .setSingleChoiceItems(items.toTypedArray(), keys.indexOf(satProduct).coerceAtLeast(0)) { d, i ->
                    d.dismiss()
                    val p = keys[i]
                    if (p == null) clearSatellite() else openSatellite(p, fetch = false, quiet = false)
                }
            if (view.hasOverlay) b.setNeutralButton("Opacity") { _, _ -> chooseOpacity() }
            b.setNegativeButton("Close", null).show()
        }
    }

    private fun chooseOpacity() {
        val steps = listOf(1f, 0.75f, 0.5f, 0.25f)
        AlertDialog.Builder(this).setTitle("Layer opacity")
            .setItems(steps.map { "${(it * 100).toInt()} %" }.toTypedArray()) { _, i -> view.overlayOpacity = steps[i] }
            .show()
    }

    private fun clearSatellite() {
        satProduct = null; satMeta = null
        view.setOverlay(null, 0f, 0f, 1f, 1f)
        satBtn.text = "Satellite: off"
        meta?.let { updateLegend(it); updateNotes(it) }
        updateInfo()
        refreshProfile(true)
    }

    private fun openSatellite(product: String, fetch: Boolean, quiet: Boolean) {
        val sid = sessionId ?: return
        val creds = SecureCredentialStore(this)
        val cid = creds.activeCopernicusClientId()
        val sec = creds.activeCopernicusClientSecret()
        setLoading(true)
        lifecycleScope.launch {
            try {
                val (r, bmp) = withContext(Dispatchers.Default) {
                    val mod = python.getModule("sat_image_mobile")
                    val j = JSONObject(mod.callAttr("open_layer_json", offlineDataRoot, sid, product, cid, sec, fetch).toString())
                    if (j.has("error") || j.optBoolean("needs_fetch") || !j.optBoolean("allowed")) Pair(j, null) else {
                        val g = j.getJSONObject("grid")
                        val bytes = mod.callAttr("layer_rgba", sid, product).toJava(ByteArray::class.java)
                        val bm = Bitmap.createBitmap(g.getInt("width"), g.getInt("height"), Bitmap.Config.ARGB_8888)
                        bm.copyPixelsFromBuffer(ByteBuffer.wrap(bytes))
                        Pair(j, bm)
                    }
                }
                when {
                    r.has("error") -> { if (quiet) clearSatellite(); showError(r.optString("error")) }
                    r.optBoolean("needs_fetch") -> {
                        if (quiet) { clearSatellite(); return@launch }
                        AlertDialog.Builder(this@FinalImageActivity)
                            .setTitle(satLabels[product] ?: product)
                            .setMessage("No saved image covers this window yet.\n\nFetch it from Copernicus now? " +
                                "It is saved once and never fetched again for this area. The first image of each " +
                                "layer is checked against the Statistical API before it is shown.")
                            .setPositiveButton("Fetch") { _, _ -> openSatellite(product, fetch = true, quiet = false) }
                            .setNegativeButton("Cancel", null).show()
                    }
                    bmp == null -> {           // saved but not checked / check failed: hidden, say why
                        clearSatellite()
                        AlertDialog.Builder(this@FinalImageActivity)
                            .setTitle(satLabels[product] ?: product)
                            .setMessage("Layer hidden: " + r.optString("hidden_reason", r.optString("check")) +
                                if (cid.isEmpty()) "\n\nSave a Copernicus login in Settings so the one-time check can run." else "")
                            .setPositiveButton("OK", null).show()
                    }
                    else -> {
                        val pl = r.getJSONObject("placement")
                        if (filterName != null) dropFilter()
                        satProduct = product; satMeta = r
                        view.setOverlay(bmp, pl.getDouble("x0").toFloat(), pl.getDouble("y0").toFloat(),
                            pl.getDouble("sx").toFloat(), pl.getDouble("sy").toFloat())
                        satBtn.text = "Satellite: " + (satLabels[product]?.substringBefore(" (") ?: product)
                        updateSatLegend(r)
                        meta?.let { updateNotes(it) }
                        updateInfo()
                        refreshProfile(true)
                    }
                }
            } catch (e: PyException) {
                showError(e.message ?: "satellite layer failed")
            } catch (e: OutOfMemoryError) {
                showError("Not enough memory for this layer; choose a smaller window.")
            } finally {
                setLoading(false)
            }
        }
    }

    private fun updateSatLegend(r: JSONObject) {
        val lg = r.getJSONObject("legend")
        val ramp = lg.getJSONArray("ramp")
        val colours = IntArray(ramp.length()) { i ->
            val s = ramp.getJSONArray(i)
            android.graphics.Color.rgb(s.getInt(1), s.getInt(2), s.getInt(3))
        }
        legendBar.background = GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, colours)
        val unit = r.optString("unit")
        legendText.text = String.format(Locale.US, "%s  %.2f \u2026 %.2f %s  (hatched = no data)",
            r.optString("label"), lg.getDouble("vmin"), lg.getDouble("vmax"), unit)
    }

    private fun satNotes(r: JSONObject): String = buildString {
        append("LAYER ").append(r.optString("label")).append(": ").append(r.optString("caption")).append('\n')
        append("Scene ").append(r.optString("scene_date"))
        if (!r.isNull("scene_cloud_cover")) append(String.format(Locale.US, ", scene cloud %.0f %%", r.optDouble("scene_cloud_cover")))
        append(String.format(Locale.US, ", %.0f %% of this window has data", 100 * r.optDouble("clear_fraction_window")))
        append(if (r.optDouble("clear_fraction_window") < 0.999)
            // fi-v2.1: radar sees through cloud, so "cloud" is only named for optical/thermal layers
            (if (r.optString("product").startsWith("SAR"))
                "; dark hatched cells have NO data (masked or below the sensor's noise floor) and are not zero.\n"
            else "; dark hatched cells have NO data (cloud or masked) and are not zero.\n") else ".\n")
        append(String.format(Locale.US, "Pixel %.0f m (sensor detail ~%.0f m), each square is one image cell, not resampled.\n",
            r.optDouble("pixel_m"), r.optDouble("sensor_detail_m")))
        append(if (r.optBoolean("reused")) "From the saved library" else "Fetched now and saved")
        append(" \u00B7 ").append(r.optString("check")).append('\n')
        val pv = r.optJSONObject("provenance")
        if (pv != null) append("File ").append(pv.optString("file")).append(" sha256 ")
            .append(pv.optString("sha256").take(12)).append("\u2026 \u00B7 ").append(pv.optString("version"))
    }

    // ------------------------------------------------------------------ DEM filters (fa-v2)

    private val filterTitles = linkedMapOf(
        "smooth" to "Smooth (Gaussian / median)",
        "residual" to "Residual relief (local high-pass)",
        "curvature" to "Curvature (convex / concave)",
        "slope" to "Slope (degrees)",
        "direction" to "Direction (aspect / directional derivative)")

    private fun chooseFilter() {
        if (sessionId == null) return
        val keys = listOf<String?>(null) + filterTitles.keys
        val items = listOf("Off (plain terrain)") + filterTitles.values
        val b = AlertDialog.Builder(this)
            .setTitle("Filters \u00B7 DERIVED, display only")
            .setSingleChoiceItems(items.toTypedArray(), keys.indexOf(filterName).coerceAtLeast(0)) { d, i ->
                d.dismiss()
                val k = keys[i]
                if (k == null) clearFilter() else chooseFilterSettings(k)
            }
        if (filterMeta != null) {
            b.setNeutralButton("Opacity") { _, _ -> chooseOpacity() }
            b.setPositiveButton("Export") { _, _ -> exportFilter() }
        }
        b.setNegativeButton("Cancel", null).show()
    }

    /** every option is one of the fixed, tested settings; nothing is free-typed */
    private fun chooseFilterSettings(name: String) {
        val opts: List<Pair<String, JSONObject>> = when (name) {
            "smooth" -> listOf(1, 2, 3).map { "Gaussian \u03C3 = $it cell" + (if (it > 1) "s" else "") to
                    JSONObject().put("method", "gaussian").put("sigma", it) } +
                listOf(3, 5).map { "Median $it\u00D7$it" to JSONObject().put("method", "median").put("size", it) }
            "residual" -> listOf(60, 150, 300).map { "Radius $it m (DEM minus local mean)" to JSONObject().put("radius_m", it) }
            "curvature" -> listOf(0 to "none", 1 to "Gaussian \u03C3 1", 2 to "Gaussian \u03C3 2").map { (v, t) ->
                "Pre-smooth: $t" to JSONObject().put("smooth_sigma", v) }
            "direction" -> listOf("Aspect (downslope bearing, grey = flat)" to JSONObject().put("mode", "aspect")) +
                listOf(0, 45, 90, 135).map { "Directional derivative toward $it\u00B0" to
                    JSONObject().put("mode", "derivative").put("bearing", it) }
            else -> emptyList()
        }
        if (opts.isEmpty()) { openFilter(name, JSONObject(), quiet = false); return }
        AlertDialog.Builder(this).setTitle(filterTitles[name] ?: name)
            .setItems(opts.map { it.first }.toTypedArray()) { _, i -> openFilter(name, opts[i].second, quiet = false) }
            .setNegativeButton("Cancel", null).show()
    }

    /** forget the filter without touching the overlay (the caller replaces or clears it) */
    private fun dropFilter() {
        sessionId?.let { sid -> runCatching { python.getModule("dem_filters_mobile").callAttr("close_filter", sid) } }
        filterName = null; filterParams = null; filterMeta = null
        filterBtn.text = "Filters: off"
    }

    private fun clearFilter() {
        val had = filterMeta != null
        dropFilter()
        if (had) view.setOverlay(null, 0f, 0f, 1f, 1f)
        meta?.let { updateLegend(it); updateNotes(it) }
        refreshProfile(true)
    }

    private fun openFilter(name: String, params: JSONObject, quiet: Boolean) {
        val sid = sessionId ?: return
        setLoading(true)
        lifecycleScope.launch {
            try {
                val (r, bmp) = withContext(Dispatchers.Default) {
                    val mod = python.getModule("dem_filters_mobile")
                    val j = JSONObject(mod.callAttr("open_filter_json", sid, name, params.toString()).toString())
                    if (j.has("error")) Pair(j, null) else {
                        val bytes = mod.callAttr("filter_rgba", sid).toJava(ByteArray::class.java)
                        val bm = Bitmap.createBitmap(j.getInt("width"), j.getInt("height"), Bitmap.Config.ARGB_8888)
                        bm.copyPixelsFromBuffer(ByteBuffer.wrap(bytes))
                        Pair(j, bm)
                    }
                }
                if (r.has("error") || bmp == null) {
                    if (quiet) clearFilter()
                    showError(r.optString("error", "filter failed"))
                    return@launch
                }
                // one overlay at a time: the filter replaces a satellite layer (it is not deleted, just hidden)
                if (satMeta != null) { satProduct = null; satMeta = null; satBtn.text = "Satellite: off"; updateInfo() }
                filterName = name; filterParams = r.optJSONObject("params") ?: params; filterMeta = r
                val pl = r.getJSONObject("placement")
                view.setOverlay(bmp, pl.getDouble("x0").toFloat(), pl.getDouble("y0").toFloat(),
                    pl.getDouble("sx").toFloat(), pl.getDouble("sy").toFloat())
                filterBtn.text = "Filters: " + r.optString("label").removePrefix("DERIVED: ").substringBefore(" (")
                updateFilterLegend(r)
                meta?.let { updateNotes(it) }
                refreshProfile(true)
            } catch (e: PyException) {
                showError(e.message ?: "filter failed")
            } catch (e: OutOfMemoryError) {
                showError("Not enough memory for this filter; choose a smaller window.")
            } finally {
                setLoading(false)
            }
        }
    }

    private fun updateFilterLegend(r: JSONObject) {
        val lg = r.getJSONObject("legend")
        val ramp = lg.getJSONArray("ramp")
        val colours = IntArray(ramp.length()) { i ->
            val s = ramp.getJSONArray(i)
            android.graphics.Color.rgb(s.getInt(1), s.getInt(2), s.getInt(3))
        }
        legendBar.background = GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, colours)
        val circular = lg.optString("kind") == "circular"
        legendText.text = if (circular)
            String.format(Locale.US, "%s  0\u00B0 \u2026 360\u00B0 (N\u2192E\u2192S\u2192W\u2192N), grey = flat, hatched = no data", r.optString("label"))
        else String.format(Locale.US, "%s  %.3g \u2026 %.3g %s  (hatched = no data)",
            r.optString("label"), lg.getDouble("vmin"), lg.getDouble("vmax"), lg.optString("units"))
    }

    private fun filterNotes(r: JSONObject): String = buildString {
        append("FILTER ").append(r.optString("label")).append(" (").append(r.optString("version")).append(")\n")
        append(String.format(Locale.US, "%d of %d cells have a value; %d-cell border and cells beside gaps are no data.",
            r.optInt("cells") - r.optInt("cells_no_data"), r.optInt("cells"), r.optInt("border_cells")))
        if (r.optInt("flat_cells") > 0) append(" ${r.optInt("flat_cells")} cells are flat (grey, measured).")
        append('\n')
        r.optJSONArray("notes")?.let { a -> for (i in 0 until a.length()) append("\u2022 ").append(a.optString(i)).append('\n') }
        append(r.optString("statement"))
    }

    private fun exportFilter() {
        val sid = sessionId ?: return
        setLoading(true)
        lifecycleScope.launch {
            try {
                val r = withContext(Dispatchers.Default) {
                    JSONObject(python.getModule("dem_filters_mobile").callAttr("export_filter_json", offlineDataRoot, sid).toString())
                }
                if (r.has("error")) showError(r.getString("error")) else {
                    val ps = r.getJSONObject("paths")
                    val text = ps.keys().asSequence().joinToString("\n\n") { k -> "$k:\n" + ps.getString(k) }
                    AlertDialog.Builder(this@FinalImageActivity)
                        .setTitle("Filter exported \u00B7 DERIVED")
                        .setMessage("$text\n\nPNG and GeoTIFF are a DERIVED view of the DEM, labelled so in the provenance file " +
                            "with the filter, its settings, the method rules and the SHA-256 of both images. The raw DEM is unchanged.")
                        .setPositiveButton("OK", null).show()
                }
            } catch (e: PyException) {
                showError(e.message ?: "filter export failed")
            } finally {
                setLoading(false)
            }
        }
    }

    // ------------------------------------------------------------------ profile & section (fa-v1)

    private fun chooseProfile() {
        if (sessionId == null) return
        val items = arrayOf("Draw A\u2013A\u2032 (tap two points on the map)",
            "North\u2013South through this candidate", "East\u2013West through this candidate")
        val b = AlertDialog.Builder(this).setTitle("Profile & section")
            .setItems(items) { _, i ->
                when (i) {
                    0 -> startPick()
                    1 -> runPreset("NS")
                    else -> runPreset("EW")
                }
            }
        if (profile != null) b.setNeutralButton("Close profile") { _, _ -> closeProfile() }
        b.setNegativeButton("Cancel", null).show()
    }

    private fun startPick() {
        pickA = null
        view.pickMode = true
        view.profileA = null; view.profileB = null; view.profileCursor = null; view.invalidate()
        info.text = "Profile: tap point A on the map (pan/zoom still work)."
    }

    private fun onPick(x: Float, y: Float) {
        val a = pickA
        if (a == null) {
            pickA = floatArrayOf(x, y)
            view.profileA = pickA; view.invalidate()
            info.text = "Profile: now tap point A\u2032."
            return
        }
        if (Math.hypot((x - a[0]).toDouble(), (y - a[1]).toDouble()) < 1.0) {
            info.text = "A\u2032 is in the same cell as A; tap a point further away."
            return
        }
        view.pickMode = false
        pickA = null
        preset = null
        lineAsk = floatArrayOf(a[0], a[1], x, y)
        runProfile()
    }

    private fun runPreset(which: String) {
        view.pickMode = false; pickA = null
        preset = which; lineAsk = null
        runProfile()
    }

    /** product shown on the map, if any; the profile only reads layers already open */
    private fun profileProduct(): String = when {
        satMeta != null -> satProduct ?: ""
        filterMeta != null -> "DERIVED"
        else -> ""
    }

    /** re-run the open profile on the current session; a new window drops it (its line no longer fits) */
    private fun refreshProfile(sameWindow: Boolean) {
        if (lineAsk == null && preset == null) return
        if (!sameWindow && preset == null) { closeProfile(); return }
        runProfile()
    }

    private fun runProfile() {
        val sid = sessionId ?: return
        val line = lineAsk; val pre = preset
        if (line == null && pre == null) return
        val product = profileProduct()
        setLoading(true)
        lifecycleScope.launch {
            try {
                val r = withContext(Dispatchers.Default) {
                    val mod = python.getModule("profile_section_mobile")
                    JSONObject((if (pre != null) mod.callAttr("preset_profile_json", sid, pre, product)
                        else mod.callAttr("profile_json", sid, line!![0].toDouble(), line[1].toDouble(),
                            line[2].toDouble(), line[3].toDouble(), product)).toString())
                }
                if (r.has("error")) { showError(r.getString("error")); updateInfo(); return@launch }
                showProfile(r)
            } catch (e: PyException) {
                showError(e.message ?: "profile failed")
            } finally {
                setLoading(false)
            }
        }
    }

    private fun showProfile(p: JSONObject) {
        profile = p
        val a = p.getJSONObject("a"); val b = p.getJSONObject("b")
        // the line as actually profiled (trimmed to the window); presets get their ends from here too
        lineAsk = floatArrayOf(a.getDouble("x").toFloat(), a.getDouble("y").toFloat(),
            b.getDouble("x").toFloat(), b.getDouble("y").toFloat())
        view.profileA = floatArrayOf(lineAsk!![0], lineAsk!![1])
        view.profileB = floatArrayOf(lineAsk!![2], lineAsk!![3])
        view.profileCursor = null
        view.invalidate()
        val satLabel = p.optJSONObject("sat")?.let { satLabels[it.optString("product")]?.substringBefore(" (") }
        profileView.setProfile(p, satLabel)
        val len = p.getDouble("length_m")
        profileTitle.text = String.format(Locale.US, "%s  %s \u00B7 bearing %.0f\u00B0 \u00B7 %d cells%s",
            p.optString("preset").takeIf { it.isNotBlank() }?.let { if (it == "NS") "N\u2013S" else "E\u2013W" } ?: "A\u2013A\u2032",
            if (len >= 1000) String.format(Locale.US, "%.2f km", len / 1000) else "${len.toInt()} m",
            p.getDouble("bearing_deg"), p.getInt("cells"),
            if (p.getInt("cells_no_data") > 0) " (${p.getInt("cells_no_data")} no data)" else "")
        readout.text = profileSummary(p)
        profilePanel.visibility = View.VISIBLE
        // frame the map on the whole line (re-applied once the map has shrunk for the panel)
        view.fitLine(lineAsk!![0], lineAsk!![1], lineAsk!![2], lineAsk!![3])
        // vertical exaggeration is known only once the panels are laid out and drawn
        profileView.post { if (profile === p && profileView.cursorM == null) readout.text = profileSummary(p) }
        updateInfo()
    }

    private fun profileSummary(p: JSONObject): String = buildString {
        val a = p.getJSONObject("a"); val b = p.getJSONObject("b")
        append(String.format(Locale.US, "A  E %.0f N %.0f  \u2192  A\u2032  E %.0f N %.0f  (UTM %s%s, WGS84)\n",
            a.getDouble("easting"), a.getDouble("northing"), b.getDouble("easting"), b.getDouble("northing"),
            p.opt("utm_zone"), p.optString("hemisphere")))
        if (profileView.lastVe.isNotEmpty())
            append("Vertical exaggeration: ").append(profileView.lastVe.entries.joinToString(" \u00B7 ") {
                String.format(Locale.US, "%s %.1f\u00D7", it.key.substringBefore(" ("), it.value) }).append('\n')
        val c = p.getJSONArray("candidates")
        append(if (c.length() == 0) "No candidate within ${p.optDouble("near_line_m", 50.0).toInt()} m of the line.\n"
            else "${c.length()} candidate(s) within ${p.optDouble("near_line_m", 50.0).toInt()} m (dashed lines).\n")
        append("Touch the trace to read the cell under your finger. ").append(p.optString("statement"))
    }

    private fun stepIndex(d0: JSONArray, d1: JSONArray, dm: Double): Int {
        val n = d0.length()
        if (n == 0) return -1
        for (i in 0 until n) if (dm >= d0.getDouble(i) && dm < d1.getDouble(i)) return i
        return if (dm >= d1.getDouble(n - 1)) n - 1 else -1
    }

    private fun showCursor(dm: Double?) {
        val p = profile ?: return
        if (dm == null) { view.profileCursor = null; view.invalidate(); readout.text = profileSummary(p); return }
        val len = p.getDouble("length_m").coerceAtLeast(1e-6)
        val f = (dm / len).coerceIn(0.0, 1.0)
        val a = p.getJSONObject("a"); val b = p.getJSONObject("b")
        val x = a.getDouble("x") + f * (b.getDouble("x") - a.getDouble("x"))
        val y = a.getDouble("y") + f * (b.getDouble("y") - a.getDouble("y"))
        view.profileCursor = floatArrayOf(x.toFloat(), y.toFloat()); view.invalidate()
        val e = a.getDouble("easting") + f * (b.getDouble("easting") - a.getDouble("easting"))
        val n = a.getDouble("northing") + f * (b.getDouble("northing") - a.getDouble("northing"))
        fun num(arr: JSONArray, i: Int, fmt: String) = if (i < 0 || arr.isNull(i)) "no data" else String.format(Locale.US, fmt, arr.getDouble(i))
        val dem = p.getJSONObject("dem")
        val i = stepIndex(dem.getJSONArray("d0"), dem.getJSONArray("d1"), dm)
        readout.text = buildString {
            append(String.format(Locale.US, "d %.0f m \u00B7 E %.0f N %.0f", dm, e, n))
            if (i >= 0) append(" \u00B7 cell c").append(dem.getJSONArray("col").getInt(i)).append(" r").append(dem.getJSONArray("row").getInt(i))
            append('\n')
            append("Elevation ").append(num(dem.getJSONArray("elevation"), i, "%.1f m"))
            append(" \u00B7 Relief ").append(num(dem.getJSONArray("relief"), i, "%+.2f m"))
            p.optJSONObject("sat")?.let { s ->
                val st = s.getJSONObject("steps")
                val k = stepIndex(st.getJSONArray("d0"), st.getJSONArray("d1"), dm)
                val unit = s.optString("units").takeIf { it.isNotBlank() && it != "null" }?.let { " $it" } ?: ""
                append('\n').append(satLabels[s.optString("product")]?.substringBefore(" (") ?: s.optString("product"))
                    .append(' ').append(num(st.getJSONArray("value"), k, "%.3f") + if (k >= 0 && !st.getJSONArray("value").isNull(k)) unit else "")
                    .append(" (its own cell)")
            }
            p.optJSONObject("derived")?.let { dv ->
                val st = dv.getJSONObject("steps")
                val k = stepIndex(st.getJSONArray("d0"), st.getJSONArray("d1"), dm)
                append("\nDERIVED ").append(dv.optString("label")).append(": ")
                    .append(num(st.getJSONArray("value"), k, "%.3f"))
                if (k >= 0 && !st.getJSONArray("value").isNull(k)) append(' ').append(dv.optString("units"))
            }
            append("\nStored cell values, not interpolated.")
        }
    }

    private fun closeProfile() {
        profile = null; lineAsk = null; preset = null; pickA = null
        view.pickMode = false
        view.profileA = null; view.profileB = null; view.profileCursor = null
        view.clearLineFit(); view.invalidate()
        profileView.clear()
        profilePanel.visibility = View.GONE
        updateInfo()
    }

    private fun exportProfile() {
        val sid = sessionId ?: return
        val line = lineAsk ?: return
        val product = profileProduct()
        setLoading(true)
        lifecycleScope.launch {
            try {
                val r = withContext(Dispatchers.Default) {
                    JSONObject(python.getModule("profile_section_mobile").callAttr("export_profile_json", offlineDataRoot, sid,
                        line[0].toDouble(), line[1].toDouble(), line[2].toDouble(), line[3].toDouble(), product).toString())
                }
                if (r.has("error")) showError(r.getString("error")) else {
                    val ps = r.getJSONObject("paths")
                    val text = ps.keys().asSequence().joinToString("\n\n") { k -> "$k:\n" + ps.getString(k) }
                    AlertDialog.Builder(this@FinalImageActivity)
                        .setTitle("Profile exported")
                        .setMessage("$text\n\nCSV = one row per DEM cell crossed (exact values, gaps left empty). " +
                            "The PNG prints the vertical exaggeration on each metre panel; the provenance file " +
                            "records the source tile and the SHA-256 of every output.")
                        .setPositiveButton("OK", null).show()
                }
            } catch (e: PyException) {
                showError(e.message ?: "profile export failed")
            } finally {
                setLoading(false)
            }
        }
    }

    private fun showError(msg: String) {
        AlertDialog.Builder(this).setTitle("Final Image")
            .setMessage(msg.removePrefix("Exception: ") +
                if (msg.contains("FileNotFoundError")) "\n\nThe DEM tile for this spot is not saved offline yet. Download offline data for the area, then reopen." else "")
            .setPositiveButton("OK", null).show()
    }

    private fun setLoading(on: Boolean) {
        progress.visibility = if (on) View.VISIBLE else View.GONE
        listOf(modeBtn, colourBtn, windowBtn, satBtn, filterBtn, profileBtn).forEach { it.isEnabled = !on }
    }

    private fun trimNum(v: Double) = if (v == Math.floor(v)) v.toLong().toString() else String.format(Locale.US, "%.1f", v)
}
