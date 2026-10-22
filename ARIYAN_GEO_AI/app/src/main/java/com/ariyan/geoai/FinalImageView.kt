package com.ariyan.geoai

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapShader
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
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
    /** All markers under the finger, nearest first (a cluster can hold several). */
    var onMarkersTapped: ((List<Marker>) -> Unit)? = null
    /** Labels skipped on the last frame because they would have overlapped. */
    var hiddenLabelCount = 0
        private set

    // fa-v1 (2026-10-21): Profile A-A'. In pick mode a single tap reports its
    // grid-pixel point instead of opening a marker.
    var pickMode = false
    var onGridTapped: ((Float, Float) -> Unit)? = null
    /** line ends and the trace cursor, grid-pixel coordinates */
    var profileA: FloatArray? = null
    var profileB: FloatArray? = null
    var profileCursor: FloatArray? = null
    private val profileLine = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; strokeWidth = 2.5f * resources.displayMetrics.density }
    private val profileShadow = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.BLACK; strokeWidth = 4.5f * resources.displayMetrics.density }

    private var bitmap: Bitmap? = null
    private var cellDxM = 30.0
    var levels: List<Level> = emptyList()
    var utmLines: List<UtmLine> = emptyList()
    var markers: List<Marker> = emptyList()

    var smooth = false
        set(v) { field = v; bmpPaint.isFilterBitmap = v; overlayPaint.isFilterBitmap = v; invalidate() }

    // fi-v2 (2026-10-21): one satellite layer drawn over the DEM image with
    // its OWN cells. Placement is in DEM-cell units: image pixel (0,0) sits
    // at (overlayX0, overlayY0) and each image pixel spans (overlaySx, overlaySy)
    // DEM cells. Empty image cells (cloud, NODATA, radar below noise) are
    // drawn as a dark hatch so the coloured relief never shows through and
    // gets mistaken for data (2026-10-21).
    private var overlay: Bitmap? = null
    private var emptyMask: Bitmap? = null          // ALPHA_8: 255 where the cell is empty
    private val hatchSize = 10
    private val hatchShader: BitmapShader = run {
        val n = hatchSize
        val px = IntArray(n * n) { i ->
            val x = i % n; val y = i / n
            if ((x + y) % n < 2) Color.rgb(150, 150, 150) else Color.rgb(34, 34, 38)
        }
        BitmapShader(Bitmap.createBitmap(px, n, n, Bitmap.Config.ARGB_8888),
            Shader.TileMode.REPEAT, Shader.TileMode.REPEAT)
    }
    private val hatchMatrix = Matrix()
    private val emptyPaint = Paint().apply {
        isFilterBitmap = false; isAntiAlias = false; isDither = false; shader = hatchShader
    }
    private var overlayX0 = 0f
    private var overlayY0 = 0f
    private var overlaySx = 1f
    private var overlaySy = 1f
    private val overlayPaint = Paint().apply { isFilterBitmap = false; isAntiAlias = false; isDither = false }
    var overlayOpacity = 1f
        set(v) {
            field = v.coerceIn(0f, 1f)
            overlayPaint.alpha = (field * 255).toInt(); emptyPaint.alpha = overlayPaint.alpha
            invalidate()
        }

    /** Fraction of overlay cells that are empty (0 when there is no overlay). */
    var overlayEmptyFraction = 0f
        private set

    fun setOverlay(bmp: Bitmap?, x0: Float, y0: Float, sx: Float, sy: Float) {
        val old = overlay
        overlay = bmp
        overlayX0 = x0; overlayY0 = y0; overlaySx = sx; overlaySy = sy
        if (old != null && old !== bmp) old.recycle()
        emptyMask?.recycle(); emptyMask = null
        overlayEmptyFraction = 0f
        if (bmp != null) buildEmptyMask(bmp)
        invalidate()
    }

    private fun buildEmptyMask(bmp: Bitmap) {
        val w = bmp.width; val h = bmp.height
        val px = IntArray(w * h)
        bmp.getPixels(px, 0, w, 0, 0, w, h)
        var empty = 0
        // reuse the array: opaque where the cell is empty, clear where it has data
        for (i in px.indices) {
            if ((px[i] ushr 24) == 0) { px[i] = -0x1000000; empty++ } else px[i] = 0
        }
        overlayEmptyFraction = if (px.isEmpty()) 0f else empty.toFloat() / px.size
        if (empty == 0) return
        val m = try { Bitmap.createBitmap(w, h, Bitmap.Config.ALPHA_8) } catch (e: OutOfMemoryError) { return }
        m.setPixels(px, 0, w, 0, 0, w, h)        // ALPHA_8 keeps only the alpha byte; handles row padding
        emptyMask = m
    }

    val hasOverlay: Boolean get() = overlay != null
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

    fun clearImage() {
        bitmap?.recycle(); bitmap = null
        overlay?.recycle(); overlay = null
        emptyMask?.recycle(); emptyMask = null
        overlayEmptyFraction = 0f
        invalidate()
    }

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

    // fa-v1.1: while a profile is open the map is framed on its line. The map
    // shrinks when the profile panel opens, so the framing is re-applied on
    // every size change until the user pans or zooms by hand.
    private var lineFit: FloatArray? = null

    /** Frame the segment (grid pixels) with room for its end labels. */
    fun fitLine(x0: Float, y0: Float, x1: Float, y1: Float) {
        lineFit = floatArrayOf(x0, y0, x1, y1)
        if (width > 0 && height > 0) applyLineFit()
        post { if (lineFit != null) applyLineFit() }
    }

    fun clearLineFit() { lineFit = null }

    private fun applyLineFit() {
        val f = lineFit ?: return
        if (width == 0 || height == 0) return
        val pad = 20f * d
        val w = max(abs(f[2] - f[0]), 1f); val h = max(abs(f[3] - f[1]), 1f)
        // never zoom out below MIN_LINE_FIT dp per cell: when the short map
        // can't hold the whole line at that size, the ends go off-screen and
        // get edge tags instead of the map shrinking to a thumbnail
        scale = clampScale(max(min((width - 2 * pad) / w, (height - 2 * pad) / h), MIN_LINE_FIT * d))
        tx = width / 2f - (f[0] + f[2]) / 2f * scale
        ty = height / 2f - (f[1] + f[3]) / 2f * scale
        fitted = true
        clampPan(); onViewChanged?.invoke(); invalidate()
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        if (lineFit != null) applyLineFit()
        else if (!fitted) fitToScreen() else { clampPan(); invalidate() }
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
            lineFit = null
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
            lineFit = null
            tx -= dx; ty -= dy
            clampPan(); onViewChanged?.invoke(); invalidate(); return true
        }
        override fun onDoubleTap(e: MotionEvent): Boolean {
            lineFit = null
            val ns = clampScale(scale * 2f)
            val f = ns / scale
            tx = e.x - (e.x - tx) * f; ty = e.y - (e.y - ty) * f; scale = ns
            clampPan(); onViewChanged?.invoke(); invalidate(); return true
        }
        override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
            if (pickMode) { onGridTapped?.invoke((e.x - tx) / scale, (e.y - ty) / scale); return true }
            if (!showCandidates) return false
            val hitR = 22f * d
            val hits = markers.filter { dist2(e.x, e.y, it) <= hitR * hitR }.sortedBy { dist2(e.x, e.y, it) }
            if (hits.isNotEmpty()) { onMarkersTapped?.invoke(hits); return true }
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
        overlay?.let { ov ->
            canvas.save()
            canvas.translate(overlayX0, overlayY0)
            canvas.scale(overlaySx, overlaySy)
            emptyMask?.let { m ->
                // keep the hatch a fixed size on screen whatever the zoom
                hatchMatrix.setScale(1f / (scale * overlaySx), 1f / (scale * overlaySy))
                hatchShader.setLocalMatrix(hatchMatrix)
                canvas.drawBitmap(m, 0f, 0f, emptyPaint)
            }
            canvas.drawBitmap(ov, 0f, 0f, overlayPaint)
            canvas.restore()
        }
        canvas.restore()
        matrix.reset(); matrix.postScale(scale, scale); matrix.postTranslate(tx, ty)

        if (showContours) for (lv in levels) {
            if (scratch.size < lv.pts.size) scratch = FloatArray(lv.pts.size)
            matrix.mapPoints(scratch, 0, lv.pts, 0, lv.pts.size / 2)
            canvas.drawLines(scratch, 0, lv.pts.size, if (lv.index) contourIndexPaint else contourPaint)
        }
        // Shapes first, then every text label in priority order. A label that
        // would overlap one already drawn, a marker, the north arrow or the
        // scale bar is skipped rather than piled on top.
        placed.clear(); hiddenLabelCount = 0
        if (showUtm) drawUtm(canvas)
        if (showCandidates) drawMarkers(canvas)
        drawScaleBar(canvas)
        drawNorth(canvas)
        if (showLabels) drawLabels(canvas)
        drawProfile(canvas)
    }

    private fun drawProfile(canvas: Canvas) {
        val a = profileA ?: return
        val ax = tx + a[0] * scale; val ay = ty + a[1] * scale
        markerFill.color = Color.WHITE; markerStroke.color = Color.BLACK
        val m = 18f * d
        val inside = { x: Float, y: Float -> x in m..(width - m) && y in m..(height - m) }
        profileB?.let { b ->
            val bx = tx + b[0] * scale; val by = ty + b[1] * scale
            canvas.drawLine(ax, ay, bx, by, profileShadow)
            canvas.drawLine(ax, ay, bx, by, profileLine)
            // fa-v1.1: an end outside the view gets an edge tag where the line
            // leaves the screen, with an arrow pointing to the real end.
            // a line hugging the edge misses the inset box; then clip to the
            // whole view and pull the tag in from the edge
            val t = clipSegment(ax, ay, bx, by, m, m, width - m, height - m)
                ?: clipSegment(ax, ay, bx, by, 0f, 0f, width.toFloat(), height.toFloat())
            if (t != null) {
                fun cx(u: Float) = (ax + (bx - ax) * u).coerceIn(m, width - m)
                fun cy(u: Float) = (ay + (by - ay) * u).coerceIn(m, height - m)
                if (!inside(ax, ay)) edgeTag(canvas, "A", cx(t[0]), cy(t[0]), ax, ay)
                if (!inside(bx, by)) edgeTag(canvas, "A\u2032", cx(t[1]), cy(t[1]), bx, by)
            }
            if (inside(bx, by)) endLabel(canvas, "A\u2032", bx, by)
        }
        if (inside(ax, ay) || profileB == null) endLabel(canvas, "A", ax, ay)
        profileCursor?.let { c ->
            val cx = tx + c[0] * scale; val cy = ty + c[1] * scale
            markerStroke.color = Color.YELLOW
            canvas.drawCircle(cx, cy, 8f * d, markerStroke)
            canvas.drawLine(cx - 12f * d, cy, cx + 12f * d, cy, markerStroke)
            canvas.drawLine(cx, cy - 12f * d, cx, cy + 12f * d, markerStroke)
            markerStroke.color = Color.BLACK
        }
    }

    /** End dot plus its letter, letter kept inside the view. */
    private fun endLabel(canvas: Canvas, t: String, x: Float, y: Float) {
        markerFill.color = Color.WHITE; markerStroke.color = Color.BLACK
        canvas.drawCircle(x, y, 5f * d, markerFill); canvas.drawCircle(x, y, 5f * d, markerStroke)
        val w = labelText.measureText(t); val ts = labelText.textSize
        val spots = listOf(x + 7f * d to y - 7f * d, x - 7f * d - w to y - 7f * d,
                           x + 7f * d to y + 7f * d + ts, x - 7f * d - w to y + 7f * d + ts)
            .map { (lx, ly) -> lx.coerceIn(2f * d, width - w - 2f * d) to ly.coerceIn(ts + 2f * d, height - 2f * d) }
        place(canvas, t, labelText, spots, force = true)
    }

    /** Arrow at (x, y) pointing toward the off-screen end (ex, ey), letter beside it. */
    private fun edgeTag(canvas: Canvas, t: String, x: Float, y: Float, ex: Float, ey: Float) {
        val dx = ex - x; val dy = ey - y
        val len = kotlin.math.hypot(dx, dy).takeIf { it > 1e-3f } ?: return
        val ux = dx / len; val uy = dy / len
        val s = 9f * d
        path.reset()
        path.moveTo(x + ux * s, y + uy * s)
        path.lineTo(x - uy * s * 0.6f, y + ux * s * 0.6f)
        path.lineTo(x + uy * s * 0.6f, y - ux * s * 0.6f)
        path.close()
        markerFill.color = Color.WHITE; markerStroke.color = Color.BLACK
        canvas.drawPath(path, markerFill); canvas.drawPath(path, markerStroke)
        // letter on the side of the line, pulled back toward the view centre
        val w = labelText.measureText(t); val ts = labelText.textSize
        val spots = listOf(-1f, 1f).map { side ->
            (x - ux * 4f * d - side * uy * 12f * d - w / 2).coerceIn(2f * d, width - w - 2f * d) to
                (y - uy * 4f * d + side * ux * 12f * d + ts / 3).coerceIn(ts + 2f * d, height - 2f * d)
        }
        place(canvas, t, labelText, spots, force = true)
    }

    /** Liang-Barsky: parameters [t0, t1] of segment (x0,y0)-(x1,y1) inside the
     *  rectangle, or null when it misses it. */
    internal fun clipSegment(x0: Float, y0: Float, x1: Float, y1: Float,
                             l: Float, t: Float, r: Float, b: Float): FloatArray? {
        val dx = x1 - x0; val dy = y1 - y0
        var a = 0f; var z = 1f
        val p = floatArrayOf(-dx, dx, -dy, dy)
        val q = floatArrayOf(x0 - l, r - x0, y0 - t, b - y0)
        for (k in 0 until 4) {
            if (p[k] == 0f) { if (q[k] < 0f) return null; continue }
            val u = q[k] / p[k]
            if (p[k] < 0f) { if (u > z) return null; if (u > a) a = u }
            else { if (u < a) return null; if (u < z) z = u }
        }
        return floatArrayOf(a, z)
    }

    private val placed = ArrayList<RectF>()
    private val utmLabels = ArrayList<Pair<String, FloatArray>>()   // text, (x, baseline, axis 0=E 1=N)
    private val tmp = RectF()

    private fun textRect(t: String, x: Float, baseline: Float, p: Paint, out: RectF): RectF {
        val fm = p.fontMetrics
        val pad = 2f * d
        out.set(x - pad, baseline + fm.ascent - pad, x + p.measureText(t) + pad, baseline + fm.descent + pad)
        return out
    }

    private fun free(r: RectF): Boolean {
        if (r.right < 0 || r.bottom < 0 || r.left > width || r.top > height) return false
        for (q in placed) if (RectF.intersects(q, r)) return false
        return true
    }

    /** Try each spot in turn; draw at the first free one, else count it hidden. */
    private fun place(canvas: Canvas, t: String, p: Paint, spots: List<Pair<Float, Float>>, force: Boolean = false): Boolean {
        for ((x, y) in spots) {
            textRect(t, x, y, p, tmp)
            if (free(tmp)) { placed.add(RectF(tmp)); canvas.drawText(t, x, y, p); return true }
        }
        if (force && spots.isNotEmpty()) {
            val (x, y) = spots[0]
            placed.add(RectF(textRect(t, x, y, p, tmp))); canvas.drawText(t, x, y, p); return true
        }
        hiddenLabelCount++
        return false
    }

    private fun markerLabel(m: Marker) = m.id.take(6) + (m.confidenceLabel?.let { " $it" } ?: "")

    private fun markerSpots(m: Marker, t: String): List<Pair<Float, Float>> {
        val sx = tx + m.x * scale; val sy = ty + m.y * scale
        val r = (if (m.focus) 12f else 7f) * d
        val w = labelText.measureText(t)
        return listOf(
            (sx + r + 4 * d) to (sy + 4 * d),          // right
            (sx - r - 4 * d - w) to (sy + 4 * d),      // left
            (sx - w / 2) to (sy - r - 4 * d),          // above
            (sx - w / 2) to (sy + r + 14 * d),         // below
        )
    }

    private fun rank(m: Marker) = when (m.style) {
        "high" -> 0; "moderate" -> 1; "low" -> 2; "rejected" -> 4; else -> 3
    }

    private fun drawLabels(canvas: Canvas) {
        val focus = if (showCandidates) markers.firstOrNull { it.focus } else null
        // 1. the candidate this image is about always gets its label
        if (focus != null) markerLabel(focus).let { place(canvas, it, labelText, markerSpots(focus, it), force = true) }
        // 2. grid labels: eastings along the top first, then northings down the left
        for ((t, a) in utmLabels.sortedBy { it.second[2] }) {
            val spots = if (a[2] == 0f) listOf(a[0] to a[1])
                else listOf(a[0] to a[1], a[0] to (a[1] + 16 * d), a[0] to (a[1] + 30 * d))
            place(canvas, t, utmText, spots)
        }
        // 3. other candidates: higher confidence first, then nearest to the focus
        if (!showCandidates) return
        val fx = focus?.x ?: 0f; val fy = focus?.y ?: 0f
        val rest = markers.filter { !it.focus && onScreen(it) }
            .sortedWith(compareBy<Marker>({ rank(it) }, { (it.x - fx) * (it.x - fx) + (it.y - fy) * (it.y - fy) }))
        for (m in rest) markerLabel(m).let { place(canvas, it, labelText, markerSpots(m, it)) }
    }

    private fun onScreen(m: Marker): Boolean {
        val sx = tx + m.x * scale; val sy = ty + m.y * scale
        return sx >= 0 && sy >= 0 && sx <= width && sy <= height
    }

    private fun drawUtm(canvas: Canvas) {
        val margin = 14f * d
        utmLabels.clear()
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
                // collected here, placed later by drawLabels so they cannot collide
                if (ln.axis == "easting") utmLabels.add(t to floatArrayOf(sx + 3 * d, max(sy, margin), 0f))
                else utmLabels.add(t to floatArrayOf(max(sx, 2 * d) + 3 * d, sy - 3 * d, 1f))
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
            // the disc itself is an obstacle: no label may be written over a marker
            val rr = if (m.focus) r + 6 * d else r
            placed.add(RectF(sx - rr, sy - rr, sx + rr, sy + rr))
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
        placed.add(RectF(x0 - 4 * d, y0 - 24 * d, x0 + max(len, labelText.measureText(t)) + 4 * d, y0 + 8 * d))
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
        placed.add(RectF(cx - 12 * d, cy - 16 * d, cx + 12 * d, cy + 26 * d))
    }

    private fun trim(v: Double) = if (v == floor(v)) v.toLong().toString() else v.toString()

    companion object {
        /** Zoom limit: 64 dp per DEM cell, already far past native. */
        const val MAX_PX_PER_CELL = 64f
        /** fa-v1.3: smallest zoom used when framing a profile line, dp per cell */
        const val MIN_LINE_FIT = 3f

        fun styleColour(style: String): Int = when (style) {
            "high" -> Color.rgb(229, 72, 77)
            "moderate" -> Color.rgb(217, 130, 43)
            "low" -> Color.rgb(240, 200, 60)
            "rejected" -> Color.rgb(160, 160, 160)
            else -> Color.rgb(90, 160, 230)
        }
    }
}
