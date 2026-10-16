package com.ariyan.geoai

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import kotlin.math.abs
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

/**
 * fi-v1 (2026-10-16): pinch-zoom / pan canvas for the Final Image screen.
 *
 * The bitmap holds exactly one pixel per real DEM cell (straight from
 * final_image_mobile.image_rgba). It is never pre-stretched: every frame
 * draws it through the current view transform, with bitmap filtering OFF
 * in "Exact cells" mode (each cell a crisp square at any zoom, no invented
 * detail) or ON in "Smooth" mode (labelled as interpolated). Contours, the
 * UTM grid, candidate markers, the scale bar and the north arrow are
 * vectors drawn on top at screen resolution, so they stay sharp.
 *
 * Coordinates: grid-pixel space, cell (r, c) covers [c, c+1) x [r, r+1),
 * the same convention final_image.py uses for every vector layer.
 */
class FinalImageView(context: Context) : View(context) {

    class Level(val levelM: Double, val index: Boolean, val pts: FloatArray)
    class UtmLine(val axis: String, val value: Int, val pts: FloatArray)
    class Marker(
        val id: String, val x: Float, val y: Float, val style: String,
        val status: String, val confidenceLabel: String?, val focus: Boolean,
    )

    var onViewChanged: (() -> Unit)? = null
    var onMarkerTapped: ((Marker) -> Unit)? = null

    private var bitmap: Bitmap? = null
    private var cellDxM = 30.0
    var levels: List<Level> = emptyList()
    var utmLines: List<UtmLine> = emptyList()
    var markers: List<Marker> = emptyList()

    var smooth = false
        set(v) { field = v; bmpPaint.isFilterBitmap = v; invalidate() }
    var showContours = true
        set(v) { field = v; invalidate() }
    var showUtm = true
        set(v) { field = v; invalidate() }
    var showCandidates = true
        set(v) { field = v; invalidate() }
    var showLabels = true
        set(v) { field = v; invalidate() }

    /** Screen pixels per DEM cell, and the screen position of grid (0,0). */
    var scale = 1f
        private set
    private var tx = 0f
    private var ty = 0f
    private var fitted = false

    private val d = resources.displayMetrics.density
    private val bmpPaint = Paint().apply { isFilterBitmap = false; isAntiAlias = false; isDither = false }
    private val contourPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(150, 20, 20, 20); strokeWidth = 1f * d; style = Paint.Style.STROKE
    }
    private val contourIndexPaint = Paint(contourPaint).apply { strokeWidth = 1.8f * d; color = Color.argb(200, 10, 10, 10) }
    private val utmPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(170, 255, 255, 255); strokeWidth = 1f * d; style = Paint.Style.STROKE
    }
    private val utmText = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE; textSize = 10f * d; setShadowLayer(2f * d, 0f, 0f, Color.BLACK)
    }
    private val markerFill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val markerStroke = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = 2f * d }
    private val labelText = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE; textSize = 11f * d; setShadowLayer(2.5f * d, 0f, 0f, Color.BLACK)
    }
    private val barPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; strokeWidth = 3f * d }
    private val barShadow = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.BLACK; strokeWidth = 5f * d }
    private val path = Path()
    private val matrix = Matrix()
    private var scratch = FloatArray(0)

    init { setBackgroundColor(Color.rgb(14, 17, 22)) }

    fun setImage(bmp: Bitmap, cellDx: Double, keepView: Boolean) {
        val old = bitmap
        bitmap = bmp
        cellDxM = cellDx
        if (!keepView || old == null || old.width != bmp.width || old.height != bmp.height) fitted = false
        if (old != null && old !== bmp) old.recycle()
        requestLayout(); invalidate()
    }

    fun clearImage() { bitmap?.recycle(); bitmap = null; invalidate() }

    fun fitToScreen() {
        val b = bitmap ?: return
        if (width == 0 || height == 0) return
        scale = min(width.toFloat() / b.width, height.toFloat() / b.height)
        tx = (width - b.width * scale) / 2f
        ty = (height - b.height * scale) / 2f
        fitted = true
        onViewChanged?.invoke(); invalidate()
    }

    /** Grid-pixel window currently on screen: x0, y0, x1, y1. */
    fun visibleWindow(): FloatArray =
        floatArrayOf(-tx / scale, -ty / scale, (width - tx) / scale, (height - ty) / scale)

    fun focusOn(gx: Float, gy: Float, pxPerCell: Float) {
        scale = clampScale(pxPerCell)
        tx = width / 2f - gx * scale
        ty = height / 2f - gy * scale
        clampPan(); onViewChanged?.invoke(); invalidate()
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        if (!fitted) fitToScreen() else { clampPan(); invalidate() }
    }

    private fun minScale(): Float {
        val b = bitmap ?: return 0.1f
        return 0.5f * min(width.toFloat() / b.width, height.toFloat() / b.height)
    }

    private fun clampScale(s: Float) = s.coerceIn(minScale(), MAX_PX_PER_CELL * d)

    /** Keep at least a quarter of the view covered by the image. */
    private fun clampPan() {
        val b = bitmap ?: return
        val iw = b.width * scale; val ih = b.height * scale
        tx = tx.coerceIn(width * 0.25f - iw, width * 0.75f)
        ty = ty.coerceIn(height * 0.25f - ih, height * 0.75f)
    }

    private val scaler = ScaleGestureDetector(context, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScale(det: ScaleGestureDetector): Boolean {
            val ns = clampScale(scale * det.scaleFactor)
            val f = ns / scale
            tx = det.focusX - (det.focusX - tx) * f
            ty = det.focusY - (det.focusY - ty) * f
            scale = ns
            clampPan(); onViewChanged?.invoke(); invalidate()
            return true
        }
    })

    private val gestures = GestureDetector(context, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDown(e: MotionEvent) = true
        override fun onScroll(e1: MotionEvent?, e2: MotionEvent, dx: Float, dy: Float): Boolean {
            tx -= dx; ty -= dy
            clampPan(); onViewChanged?.invoke(); invalidate(); return true
        }
        override fun onDoubleTap(e: MotionEvent): Boolean {
            val ns = clampScale(scale * 2f)
            val f = ns / scale
            tx = e.x - (e.x - tx) * f; ty = e.y - (e.y - ty) * f; scale = ns
            clampPan(); onViewChanged?.invoke(); invalidate(); return true
        }
        override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
            if (!showCandidates) return false
            val hitR = 22f * d
            val hit = markers.minByOrNull { dist2(e.x, e.y, it) }
            if (hit != null && dist2(e.x, e.y, hit) <= hitR * hitR) { onMarkerTapped?.invoke(hit); return true }
            return false
        }
    })

    private fun dist2(x: Float, y: Float, m: Marker): Float {
        val sx = tx + m.x * scale - x; val sy = ty + m.y * scale - y
        return sx * sx + sy * sy
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        scaler.onTouchEvent(event)
        if (!scaler.isInProgress) gestures.onTouchEvent(event)
        if (event.actionMasked == MotionEvent.ACTION_DOWN) parent?.requestDisallowInterceptTouchEvent(true)
        return true
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val b = bitmap ?: return
        canvas.save()
        canvas.translate(tx, ty)
        canvas.scale(scale, scale)
        canvas.drawBitmap(b, 0f, 0f, bmpPaint)
        canvas.restore()
        matrix.reset(); matrix.postScale(scale, scale); matrix.postTranslate(tx, ty)

        if (showContours) for (lv in levels) {
            if (scratch.size < lv.pts.size) scratch = FloatArray(lv.pts.size)
            matrix.mapPoints(scratch, 0, lv.pts, 0, lv.pts.size / 2)
            canvas.drawLines(scratch, 0, lv.pts.size, if (lv.index) contourIndexPaint else contourPaint)
        }
        if (showUtm) drawUtm(canvas)
        if (showCandidates) drawMarkers(canvas)
        drawScaleBar(canvas)
        drawNorth(canvas)
    }

    private fun drawUtm(canvas: Canvas) {
        val margin = 14f * d
        for (ln in utmLines) {
            if (ln.pts.size < 4) continue
            path.reset()
            var best = -1; var bestD = Float.MAX_VALUE
            var i = 0
            while (i < ln.pts.size) {
                val sx = tx + ln.pts[i] * scale; val sy = ty + ln.pts[i + 1] * scale
                if (i == 0) path.moveTo(sx, sy) else path.lineTo(sx, sy)
                // easting labels along the top edge, northing labels along the left edge
                val dd = if (ln.axis == "easting") abs(sy - margin) else abs(sx - margin)
                if (sx in 0f..width.toFloat() && sy in 0f..height.toFloat() && dd < bestD) { bestD = dd; best = i }
                i += 2
            }
            canvas.drawPath(path, utmPaint)
            if (best >= 0 && showLabels) {
                val sx = tx + ln.pts[best] * scale; val sy = ty + ln.pts[best + 1] * scale
                val t = if (ln.axis == "easting") "E ${ln.value}" else "N ${ln.value}"
                if (ln.axis == "easting") canvas.drawText(t, sx + 3 * d, max(sy, margin), utmText)
                else canvas.drawText(t, max(sx, 2 * d) + 3 * d, sy - 3 * d, utmText)
            }
        }
    }

    private fun drawMarkers(canvas: Canvas) {
        val r = 7f * d
        for (m in markers.sortedBy { it.focus }) {
            val sx = tx + m.x * scale; val sy = ty + m.y * scale
            if (sx < -40 * d || sy < -40 * d || sx > width + 40 * d || sy > height + 40 * d) continue
            val col = styleColour(m.style)
            if (m.style == "rejected") {
                markerStroke.color = col
                canvas.drawCircle(sx, sy, r, markerStroke)
                canvas.drawLine(sx - r * 0.7f, sy - r * 0.7f, sx + r * 0.7f, sy + r * 0.7f, markerStroke)
            } else {
                markerFill.color = col
                canvas.drawCircle(sx, sy, r, markerFill)
                markerStroke.color = Color.BLACK
                canvas.drawCircle(sx, sy, r, markerStroke)
            }
            if (m.focus) {
                markerStroke.color = Color.WHITE
                canvas.drawCircle(sx, sy, r + 5 * d, markerStroke)
            }
            if (showLabels) {
                val t = m.id.take(6) + (m.confidenceLabel?.let { " $it" } ?: "")
                canvas.drawText(t, sx + r + 4 * d, sy + 4 * d, labelText)
            }
        }
    }

    private fun drawScaleBar(canvas: Canvas) {
        val mPerPx = cellDxM / scale
        val target = width * 0.28 * mPerPx
        val p = 10.0.pow(floor(log10(target)))
        val nice = listOf(1.0, 2.0, 5.0, 10.0).map { it * p }.last { it <= target }
        val len = (nice / mPerPx).toFloat()
        val x0 = 16f * d; val y0 = height - 18f * d
        canvas.drawLine(x0, y0, x0 + len, y0, barShadow)
        canvas.drawLine(x0, y0, x0 + len, y0, barPaint)
        canvas.drawLine(x0, y0 - 5 * d, x0, y0 + 5 * d, barPaint)
        canvas.drawLine(x0 + len, y0 - 5 * d, x0 + len, y0 + 5 * d, barPaint)
        val t = if (nice >= 1000) "${trim(nice / 1000)} km" else "${trim(nice)} m"
        canvas.drawText(t, x0, y0 - 8 * d, labelText)
    }

    private fun drawNorth(canvas: Canvas) {
        val cx = width - 22f * d; val cy = 30f * d
        path.reset()
        path.moveTo(cx, cy - 12 * d); path.lineTo(cx - 7 * d, cy + 8 * d); path.lineTo(cx, cy + 4 * d); path.lineTo(cx + 7 * d, cy + 8 * d); path.close()
        markerFill.color = Color.WHITE
        canvas.drawPath(path, markerFill)
        markerStroke.color = Color.BLACK
        canvas.drawPath(path, markerStroke)
        canvas.drawText("N", cx - 4 * d, cy + 22 * d, labelText)
    }

    private fun trim(v: Double) = if (v == floor(v)) v.toLong().toString() else v.toString()

    companion object {
        /** Zoom limit: 64 dp per DEM cell, already far past native. */
        const val MAX_PX_PER_CELL = 64f

        fun styleColour(style: String): Int = when (style) {
            "high" -> Color.rgb(229, 72, 77)
            "moderate" -> Color.rgb(217, 130, 43)
            "low" -> Color.rgb(240, 200, 60)
            "rejected" -> Color.rgb(160, 160, 160)
            else -> Color.rgb(90, 160, 230)
        }
    }
}
