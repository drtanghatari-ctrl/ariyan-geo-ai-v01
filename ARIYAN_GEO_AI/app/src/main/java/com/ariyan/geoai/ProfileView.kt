package com.ariyan.geoai

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.view.MotionEvent
import android.view.View
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.pow

/**
 * fa-v1 (2026-10-21): the Profile & Section trace panel.
 *
 * Draws what profile_section.py returned, nothing more: one flat step per
 * real DEM cell crossed (elevation, relief), and one flat step per real
 * satellite cell crossed (optional). Cells with no data are gaps. No
 * smoothing, no curve fitting. The vertical exaggeration of each metre
 * panel is computed from the panel's own size and always printed.
 *
 * Touch / drag anywhere reads the cell under that distance; onCursor gives
 * the distance so the map can show the same point.
 */
class ProfileView(context: Context) : View(context) {

    class Trace(val d0: DoubleArray, val d1: DoubleArray, val v: Array<Double?>,
                val lo: Double, val hi: Double, val title: String, val colour: Int, val metres: Boolean)

    class Cand(val d: Double, val label: String, val colour: Int)

    var onCursor: ((Double?) -> Unit)? = null

    private var traces: List<Trace> = emptyList()
    private var cands: List<Cand> = emptyList()
    private var lengthM = 1.0
    var cursorM: Double? = null
        private set
    /** vertical exaggeration per metre panel as last drawn (for the readout) */
    val lastVe = LinkedHashMap<String, Double>()

    private val d = resources.displayMetrics.density
    private val leftPad = 44f * d
    private val rightPad = 8f * d

    private val axisPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(150, 150, 150); strokeWidth = 1f * d }
    private val gridPaint = Paint().apply { color = Color.argb(60, 150, 150, 150); strokeWidth = 1f }
    private val tracePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { strokeWidth = 1.8f * d; style = Paint.Style.STROKE }
    private val text = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(200, 200, 200); textSize = 10f * d }
    private val title = Paint(text).apply { textSize = 11f * d; isFakeBoldText = true }
    private val vePaint = Paint(text).apply { color = Color.rgb(255, 120, 110); textSize = 11f * d; isFakeBoldText = true; textAlign = Paint.Align.RIGHT }
    private val candPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        strokeWidth = 1.2f * d; style = Paint.Style.STROKE; pathEffect = DashPathEffect(floatArrayOf(5f * d, 4f * d), 0f)
    }
    private val candText = Paint(text).apply { textSize = 9f * d }
    private val cursorPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; strokeWidth = 1.2f * d }
    private val path = Path()

    fun setProfile(p: JSONObject, satLabel: String?) {
        lengthM = p.getDouble("length_m").coerceAtLeast(1e-6)
        val dem = p.getJSONObject("dem")
        val ea = p.getJSONArray("elevation_axis"); val ra = p.getJSONArray("relief_axis")
        val list = mutableListOf(
            Trace(arr(dem.getJSONArray("d0")), arr(dem.getJSONArray("d1")), nul(dem.getJSONArray("elevation")),
                ea.getDouble(0), ea.getDouble(1), "Elevation (m)", Color.rgb(110, 160, 255), true),
            Trace(arr(dem.getJSONArray("d0")), arr(dem.getJSONArray("d1")), nul(dem.getJSONArray("relief")),
                ra.getDouble(0), ra.getDouble(1),
                String.format(Locale.US, "Relief (m vs surroundings, r=%.0f m)", p.optDouble("relief_radius_m", 300.0)),
                Color.rgb(255, 150, 60), true))
        p.optJSONObject("sat")?.let { s ->
            val st = s.getJSONObject("steps"); val ax = s.getJSONArray("axis")
            val unit = s.optString("units").takeIf { it.isNotBlank() && it != "null" }?.let { " ($it)" } ?: ""
            list += Trace(arr(st.getJSONArray("d0")), arr(st.getJSONArray("d1")), nul(st.getJSONArray("value")),
                ax.getDouble(0), ax.getDouble(1),
                "${satLabel ?: s.optString("product")}$unit \u00B7 scene ${s.optString("scene_date", "-")} \u00B7 own cells",
                Color.rgb(90, 210, 120), false)
        }
        traces = list
        val c = p.getJSONArray("candidates")
        cands = (0 until c.length()).map { i ->
            val o = c.getJSONObject(i)
            Cand(o.getDouble("d_m"), o.getString("label") + (o.optString("confidence_label").takeIf { it.isNotBlank() && it != "null" }?.let { " $it" } ?: ""),
                FinalImageView.styleColour(o.optString("style", "unrated")))
        }
        cursorM = null
        invalidate()
    }

    fun clear() { traces = emptyList(); cands = emptyList(); cursorM = null; invalidate() }

    private fun arr(a: JSONArray) = DoubleArray(a.length()) { a.getDouble(it) }
    private fun nul(a: JSONArray) = Array(a.length()) { if (a.isNull(it)) null else a.getDouble(it) }

    private fun xOf(dm: Double) = leftPad + (dm / lengthM * (width - leftPad - rightPad)).toFloat()

    override fun onTouchEvent(e: MotionEvent): Boolean {
        if (traces.isEmpty()) return false
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> {
                parent?.requestDisallowInterceptTouchEvent(true)
                val f = ((e.x - leftPad) / (width - leftPad - rightPad)).coerceIn(0f, 1f)
                cursorM = f * lengthM
                onCursor?.invoke(cursorM); invalidate()
            }
        }
        return true
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (traces.isEmpty()) return
        val bottomAxis = 16f * d
        val panelH = (height - bottomAxis) / traces.size
        val plotW = width - leftPad - rightPad
        lastVe.clear()
        traces.forEachIndexed { i, t ->
            val top = i * panelH
            val py0 = top + 15f * d
            val ph = panelH - 19f * d
            val span = (t.hi - t.lo).takeIf { it > 0 } ?: 1e-9
            fun y(v: Double) = py0 + ph - ((v - t.lo) / span * ph).toFloat()
            canvas.drawText(t.title, leftPad, top + 11f * d, title)
            for (tk in ticks(t.lo, t.hi, 3)) {
                val yy = y(tk)
                canvas.drawLine(leftPad, yy, width - rightPad, yy, gridPaint)
                canvas.drawText(fmt(tk), 2f * d, yy + 3f * d, text)
            }
            for (c in cands) {
                candPaint.color = c.colour
                val x = xOf(c.d)
                canvas.drawLine(x, py0, x, py0 + ph, candPaint)
                if (i == 0) canvas.drawText(c.label, x + 2f * d, py0 + 9f * d, candText.apply { color = c.colour })
            }
            // exact steps; a gap (no data) breaks the line
            path.reset()
            var open = false
            for (k in t.v.indices) {
                val v = t.v[k]
                if (v == null) { open = false; continue }
                val yy = y(v)
                if (!open) { path.moveTo(xOf(t.d0[k]), yy); open = true } else path.lineTo(xOf(t.d0[k]), yy)
                path.lineTo(xOf(t.d1[k]), yy)
            }
            tracePaint.color = t.colour
            canvas.drawPath(path, tracePaint)
            canvas.drawLine(leftPad, py0, leftPad, py0 + ph, axisPaint)
            canvas.drawLine(leftPad, py0 + ph, width - rightPad, py0 + ph, axisPaint)
            if (t.metres) {
                val ve = (lengthM / plotW) / (span / ph)
                lastVe[if (i == 0) "elevation" else "relief"] = ve
                canvas.drawText(String.format(Locale.US, "VE \u00D7%.1f", ve), width - rightPad, top + 11f * d, vePaint)
            }
        }
        val yb = height - 4f * d
        for (tk in ticks(0.0, lengthM, 6)) {
            val x = xOf(tk)
            canvas.drawLine(x, yb - 12f * d, x, yb - 9f * d, axisPaint)
            canvas.drawText(fmt(tk), x - text.measureText(fmt(tk)) / 2, yb, text)
        }
        val unit = "m from A"
        canvas.drawText(unit, width - rightPad - text.measureText(unit), yb, text)
        cursorM?.let { canvas.drawLine(xOf(it), 0f, xOf(it), height - bottomAxis, cursorPaint) }
    }

    private fun ticks(lo: Double, hi: Double, n: Int): List<Double> {
        val span = hi - lo
        if (span <= 0) return listOf(lo)
        val raw = span / n
        val mag = 10.0.pow(floor(log10(raw)))
        val step = listOf(1.0, 2.0, 2.5, 5.0, 10.0).map { it * mag }.first { it >= raw }
        val out = ArrayList<Double>()
        var t = ceil(lo / step) * step
        while (t <= hi + 1e-9) { out += t; t += step }
        return out
    }

    private fun fmt(v: Double): String =
        if (kotlin.math.abs(v) >= 100 || v == floor(v)) String.format(Locale.US, "%.0f", v)
        else String.format(Locale.US, "%.2f", v).trimEnd('0').trimEnd('.')
}
