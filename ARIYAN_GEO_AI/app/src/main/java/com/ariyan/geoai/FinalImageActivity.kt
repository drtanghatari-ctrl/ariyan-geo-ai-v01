package com.ariyan.geoai

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
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

    private fun col(id: Int) = ContextCompat.getColor(this, id)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        candidateId = intent.getStringExtra(EXTRA_CANDIDATE_ID) ?: run { finish(); return }
        python = Python.getInstance()
        buildUi()
        load(keepView = false)
    }

    override fun onDestroy() {
        sessionId?.let { sid -> runCatching { python.getModule("final_image_mobile").callAttr("close_session", sid) } }
        if (::view.isInitialized) view.clearImage()
        super.onDestroy()
    }

    // ---------------------------------------------------------------- UI

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
        buttons.addView(button("Layers") { chooseLayers() })
        buttons.addView(button("Fit") { view.fitToScreen() })
        buttons.addView(button("Centre") { centreOnCandidate() })
        buttons.addView(button("Export") { export() })
        root.addView(HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(buttons) })

        val frame = FrameLayout(this)
        view = FinalImageView(this).apply {
            onViewChanged = { updateInfo() }
            onMarkerTapped = { showMarker(it) }
        }
        frame.addView(view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        progress = ProgressBar(this).apply { visibility = View.GONE }
        frame.addView(progress, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
        root.addView(frame, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        info = smallText(R.color.ariyan_accent).apply { setPadding(pad, pad / 3, pad, 0) }
        root.addView(info)

        val legendRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(pad, pad / 3, pad, 0)
        }
        legendBar = View(this)
        legendRow.addView(legendBar, LinearLayout.LayoutParams((120 * d).toInt(), (10 * d).toInt()))
        legendText = smallText(R.color.ariyan_text_secondary).apply { setPadding(pad / 2, 0, 0, 0) }
        legendRow.addView(legendText)
        root.addView(legendRow)

        notes = smallText(R.color.ariyan_text_secondary).apply { setPadding(pad, pad / 3, pad, pad) }
        root.addView(ScrollView(this).apply { addView(notes) },
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, (88 * d).toInt()))
        setContentView(root)
    }

    private fun smallText(colour: Int) = TextView(this).apply {
        textSize = 11f
        typeface = Typeface.MONOSPACE
        setTextColor(col(colour))
    }

    // ---------------------------------------------------------------- data

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
        title.text = String.format(Locale.US, "Final Image \u00B7 %s  (%.5f, %.5f)",
            candidateId.take(8), m.getDouble("lat"), m.getDouble("lon"))
        updateLegend(m)
        updateNotes(m)
        updateInfo()
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
        sb.append("Markers: colour = stored confidence (red HIGH, orange MODERATE, yellow LOW, blue unrated), grey \u00D7 = Rejected, white ring = this candidate.\n")
        val utm = m.optJSONObject("utm_grid")
        if (utm != null) sb.append("UTM grid zone ").append(utm.opt("zone")).append(utm.optString("hemisphere")).append(".\n")
        for (key in listOf("problems", "notes")) {
            val a = m.optJSONArray(key) ?: continue
            for (i in 0 until a.length()) sb.append(if (key == "problems") "! " else "\u2022 ").append(a.optString(i)).append('\n')
        }
        sb.append(m.optString("statement"))
        notes.text = sb.toString()
    }

    private fun updateInfo() {
        val m = meta ?: return
        val pxPerCell = view.scale / resources.displayMetrics.density
        val w = view.visibleWindow()
        val acrossM = (w[2] - w[0]) * m.optDouble("cell_dx_m", nativeRes)
        val mode = if (view.smooth) "Smooth (interpolated, visual only)" else "Exact cells"
        val beyond = view.scale > 1f
        info.text = String.format(Locale.US, "Native %.1f m/cell \u00B7 %.1f dp per cell \u00B7 view %s across \u00B7 %s%s",
            nativeRes, pxPerCell, if (acrossM >= 1000) String.format(Locale.US, "%.2f km", acrossM / 1000) else "${acrossM.toInt()} m",
            mode,
            if (beyond && !view.smooth) "\nZoomed past native: each square is one real DEM cell, no new detail added."
            else if (beyond) "\nZoomed past native: colours between cell centres are interpolated, not measured." else "")
    }

    // ---------------------------------------------------------------- actions

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

    private fun showError(msg: String) {
        AlertDialog.Builder(this).setTitle("Final Image")
            .setMessage(msg.removePrefix("Exception: ") +
                if (msg.contains("FileNotFoundError")) "\n\nThe DEM tile for this spot is not saved offline yet. Download offline data for the area, then reopen." else "")
            .setPositiveButton("OK", null).show()
    }

    private fun setLoading(on: Boolean) {
        progress.visibility = if (on) View.VISIBLE else View.GONE
        listOf(modeBtn, colourBtn, windowBtn).forEach { it.isEnabled = !on }
    }

    private fun trimNum(v: Double) = if (v == Math.floor(v)) v.toLong().toString() else String.format(Locale.US, "%.1f", v)
}
