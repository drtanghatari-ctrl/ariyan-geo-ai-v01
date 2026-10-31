package com.ariyan.geoai

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.opengl.GLES20
import android.opengl.GLSurfaceView
import android.opengl.GLUtils
import android.opengl.Matrix
import android.os.Handler
import android.os.Looper
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.nio.ShortBuffer
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * s3d-v1 (2026-10-31): 3D Visualization tab of the Final Image screen.
 *
 * Draws the stored DEM window as a 3D surface with OpenGL ES 2.0 (built into
 * Android, no extra library):
 *   - one vertex per stored DEM cell centre; flat triangles only between four
 *     neighbouring cells that ALL have a value, so a cell without a value
 *     leaves a hole. Nothing is filled, smoothed or invented.
 *   - the drape is whatever the 2D map shows (terrain colour, a satellite
 *     layer or a filter), sampled with NEAREST filtering so every image pixel
 *     stays a sharp square at any zoom. Empty layer pixels are drawn dark.
 *   - height exaggeration is set by the activity and always printed there.
 *   - candidate pins and the profile line A-A' come from the 2D map.
 *
 * One finger: rotate (left/right) and tilt (up/down). Two fingers: pinch to
 * zoom. Double tap: reset the view. Display only: nothing is written.
 *
 * cut-v1 (2026-10-31): cutaway along the profile line A-A'. The straight line
 * through A and A' (across the whole window) cuts the surface; one side is
 * kept. The cut face is a grey hatched wall from the stored cell heights along
 * the line down to a drawing base: NOTHING below the ground line is measured
 * (no GPR, no ERT), and the wall's depth is a drawing aid, not a depth.
 * Whole triangles are kept or removed by their centre, so the cut edge follows
 * the cells; the wall breaks where cells have no value.
 *
 * cut-v2 (2026-10-31): the face has three bands, all from stored DEM cells:
 *   orange  = DERIVED raised material: ground above its local base level
 *             (mean ground within the relief radius); make-up unknown
 *   blue    = DERIVED hollow: translucent band from the ground up to the base
 *   grey    = UNKNOWN below the lower of ground and base (no measurement)
 * Nothing is drawn that the DEM does not give; no layer, wall or chamber.
 *
 * cut-v2 part 2 (2026-10-31): the user's own HYPOTHESIZED shapes (stored by
 * section_hypothesis.py) are drawn on the face in purple with a bright outline:
 * from..to metres along A->A', top..bottom metres below the ground line (times
 * the height exaggeration, like everything else). Only the user creates them.
 *
 * ef-v4b (2026-10-31): MEASURED ERT sections (field_data.py) are drawn on the cut
 * face as a picture: distance along the line -> across the face, depth below the
 * stored ground line -> down (times the height exaggeration), NEAREST sampling so
 * each model cell stays a sharp block; empty cells are dark. Drawn just in front
 * of the face, behind the user's purple hypotheses.
 */
class Surface3DView(context: Context) : GLSurfaceView(context) {

    class Pin(val x: Float, val y: Float, val colour: Int, val focus: Boolean)

    /** a draped image: grid x (DEM cells) -> image pixel = (x - x0) / sx */
    class Drape(val bitmap: Bitmap, val x0: Float, val y0: Float, val sx: Float, val sy: Float)

    private val r = Renderer3D()
    private val main = Handler(Looper.getMainLooper())

    /** camera changed (degrees, metres); called on the UI thread */
    var onCamera: ((az: Float, tilt: Float, dist: Float) -> Unit)? = null

    /** a shader failed to build on this phone; called once on the UI thread */
    var onGlError: ((String) -> Unit)? = null

    init {
        r.errorSink = { msg -> main.post { onGlError?.invoke(msg) } }
        setEGLContextClientVersion(2)
        setEGLConfigChooser(8, 8, 8, 8, 16, 0)
        preserveEGLContextOnPause = true
        setRenderer(r)
        renderMode = RENDERMODE_WHEN_DIRTY
    }

    // ---------------------------------------------------------------- data in

    /** heights: row-major H*W, metres relative to the window median, NaN = no value */
    fun setSurface(heights: FloatArray, w: Int, h: Int, dx: Float, dy: Float, ve: Float,
                   drape: Drape, pins: List<Pin>, line: FloatArray?, resetCamera: Boolean, cut: Int = 0,
                   base: FloatArray? = null) {
        queueEvent {
            r.setData(heights, w, h, dx, dy, ve, drape, pins, line, cut, base)
            if (resetCamera) r.resetCamera()
        }
        requestRender()
        if (resetCamera) post { reportCamera() }
    }

    fun setExaggeration(ve: Float) { queueEvent { r.setVe(ve) }; requestRender() }

    /** cut-v2 part 2: one user hypothesis on the open line (metres along A->A', metres below ground) */
    class Hyp(val fromM: Float, val toM: Float, val topM: Float, val bottomM: Float)

    /** ef-v4b: one measured ERT section on the open line. fromM..toM = distance along
     *  its line (outer edges of its first and last bins), topM..bottomM = depth below
     *  ground; reversed = its distance 0 is at A' instead of A */
    class Section(val bitmap: Bitmap, val lengthM: Float, val fromM: Float, val toM: Float,
                  val topM: Float, val bottomM: Float, val reversed: Boolean)

    fun setSections(list: List<Section>) { queueEvent { r.setSections(list) }; requestRender() }

    /** lengthM = the real length of the open line A-A' in metres */
    fun setHypotheses(list: List<Hyp>, lengthM: Float) { queueEvent { r.setHyps(list, lengthM) }; requestRender() }

    /** cut-v1: 0 = no cut, +1 = keep the left side of A->A', -1 = keep the right side */
    fun setCut(side: Int) { queueEvent { r.setCut(side) }; requestRender() }

    fun resetView() { queueEvent { r.resetCamera() }; requestRender(); post { reportCamera() } }

    /** renders one frame into a bitmap; the callback runs on the UI thread */
    fun snapshot(cb: (Bitmap?) -> Unit) {
        queueEvent { r.shotCallback = { b -> main.post { cb(b) } } }
        requestRender()
    }

    fun camera(): FloatArray = floatArrayOf(r.az, r.tilt, r.dist)

    private fun reportCamera() { onCamera?.invoke(r.az, r.tilt, r.dist) }

    // ---------------------------------------------------------------- touch

    private var lastX = 0f
    private var lastY = 0f
    private var dragging = false

    private val scaler = ScaleGestureDetector(context, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScale(d: ScaleGestureDetector): Boolean {
            val f = d.scaleFactor
            if (f > 0f) {
                r.dist = (r.dist / f).coerceIn(r.minDist, r.maxDist)
                requestRender(); reportCamera()
            }
            return true
        }
    })

    private val gestures = GestureDetector(context, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDoubleTap(e: MotionEvent): Boolean { resetView(); return true }
    })

    override fun onTouchEvent(e: MotionEvent): Boolean {
        parent?.requestDisallowInterceptTouchEvent(true)
        gestures.onTouchEvent(e)
        scaler.onTouchEvent(e)
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> { lastX = e.x; lastY = e.y; dragging = true }
            MotionEvent.ACTION_POINTER_DOWN -> dragging = false
            MotionEvent.ACTION_MOVE -> if (dragging && e.pointerCount == 1 && !scaler.isInProgress) {
                val ddx = e.x - lastX
                val ddy = e.y - lastY
                lastX = e.x; lastY = e.y
                val d = resources.displayMetrics.density
                r.az = ((r.az - ddx / d * 0.4f) % 360f + 360f) % 360f
                r.tilt = (r.tilt + ddy / d * 0.3f).coerceIn(5f, 89f)
                requestRender(); reportCamera()
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> dragging = false
        }
        return true
    }

    // ---------------------------------------------------------------- renderer

    private class Band(val verts: FloatBuffer, val idx: ShortBuffer, val count: Int)

    private class Renderer3D : GLSurfaceView.Renderer {
        @Volatile var az = 200f
        @Volatile var tilt = 40f
        @Volatile var dist = 3000f
        var minDist = 100f
        var maxDist = 20000f
        var shotCallback: ((Bitmap?) -> Unit)? = null
        var errorSink: ((String) -> Unit)? = null

        private var heights: FloatArray? = null
        private var w = 0
        private var h = 0
        private var dx = 30f
        private var dy = 30f
        private var ve = 1f
        private var drape: Drape? = null
        private var pins: List<Pin> = emptyList()
        private var line: FloatArray? = null
        private var cut = 0
        private var wallStrips: List<FloatBuffer> = emptyList()
        private var raisedStrips: List<FloatBuffer> = emptyList()   // cut-v2 orange
        private var hollowStrips: List<FloatBuffer> = emptyList()   // cut-v2 blue
        private var baseArr: FloatArray? = null
        private var hyps: List<Hyp> = emptyList()
        private var hypLenM = 0f
        private var hypFill: List<FloatBuffer> = emptyList()      // purple fill strips (stride 5)
        private var hypOutline: List<FloatBuffer> = emptyList()   // outline line strips (stride 3)
        // ef-v4b: measured ERT sections on the face
        private var sections: List<Section> = emptyList()
        private var secStrips: List<Pair<Int, FloatBuffer>> = emptyList()   // (section index, strip stride 8)
        private var secTex = IntArray(0)
        private var secDirty = false
        private var wallProg = 0

        private var bands: List<Band> = emptyList()
        private var pinBuf: FloatBuffer? = null
        private var lineStrips: List<FloatBuffer> = emptyList()
        private var texId = 0
        private var texDirty = false
        private var meshProg = 0
        private var flatProg = 0
        private var vw = 1
        private var vh = 1
        private val proj = FloatArray(16)
        private val viewM = FloatArray(16)
        private val mvp = FloatArray(16)

        fun setData(hg: FloatArray, w0: Int, h0: Int, dx0: Float, dy0: Float, ve0: Float,
                    dr: Drape, p: List<Pin>, ln: FloatArray?, ct: Int, bs: FloatArray?) {
            heights = hg; w = w0; h = h0; dx = dx0; dy = dy0; ve = ve0
            baseArr = bs?.takeIf { it.size == hg.size }
            drape = dr; pins = p; line = ln
            cut = if (ln == null) 0 else ct
            texDirty = true
            rebuild()
        }

        fun setVe(v: Float) { ve = v; rebuild() }

        fun setCut(side: Int) { cut = if (line == null) 0 else side; rebuild() }

        fun setHyps(list: List<Hyp>, lengthM: Float) { hyps = list; hypLenM = lengthM; rebuild() }

        fun setSections(list: List<Section>) { sections = list; secDirty = true; rebuild() }

        /** cut-v1: is a grid point on the side that is kept? */
        private fun kept(gx: Float, gy: Float): Boolean {
            val ln = line
            if (cut == 0 || ln == null) return true
            return CutGeometry.keep(ln, cut, gx, gy)
        }

        fun resetCamera() {
            val across = max(w * dx, h * dy).coerceAtLeast(100f)
            az = 200f; tilt = 40f; dist = across * 1.3f
            minDist = across * 0.08f; maxDist = across * 6f
        }

        private fun at(c: Int, rr: Int): Float = heights!![rr * w + c]

        private fun wx(c: Float) = (c - w / 2f) * dx
        private fun wz(rr: Float) = (rr - h / 2f) * dy

        /** height of the nearest stored cell to a grid point, or NaN */
        private fun cellHeight(gx: Float, gy: Float): Float {
            val c = floor(gx).toInt().coerceIn(0, w - 1)
            val rr = floor(gy).toInt().coerceIn(0, h - 1)
            return at(c, rr)
        }

        private fun rebuild() {
            val hg = heights ?: return
            if (w < 2 || h < 2) return
            val dr = drape ?: return
            val tw = dr.bitmap.width.toFloat()
            val th = dr.bitmap.height.toFloat()
            // bands so that each band has at most 65535 vertices (16-bit indices)
            val rowsPerBand = max(2, 65535 / w)
            val out = ArrayList<Band>()
            var r0 = 0
            while (r0 < h - 1) {
                val r1 = min(h - 1, r0 + rowsPerBand - 1)
                val rows = r1 - r0 + 1
                val vb = ByteBuffer.allocateDirect(rows * w * 8 * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()
                for (rr in r0..r1) for (c in 0 until w) {
                    val z = hg[rr * w + c]
                    val ok = !z.isNaN()
                    val gx = c + 0.5f
                    val gy = rr + 0.5f
                    // normal from neighbouring cells (display lighting only)
                    val zl = if (c > 0) hg[rr * w + c - 1] else Float.NaN
                    val zr = if (c < w - 1) hg[rr * w + c + 1] else Float.NaN
                    val zu = if (rr > 0) hg[(rr - 1) * w + c] else Float.NaN
                    val zd = if (rr < h - 1) hg[(rr + 1) * w + c] else Float.NaN
                    val gxv = slope(zl, z, zr, dx) * ve
                    val gzv = slope(zu, z, zd, dy) * ve
                    var nx = -gxv; var ny = 1f; var nz = -gzv
                    val nl = sqrt(nx * nx + ny * ny + nz * nz)
                    nx /= nl; ny /= nl; nz /= nl
                    vb.put(wx(gx)); vb.put(if (ok) z * ve else 0f); vb.put(wz(gy))
                    vb.put(((gx - dr.x0) / dr.sx) / tw); vb.put(((gy - dr.y0) / dr.sy) / th)
                    vb.put(nx); vb.put(ny); vb.put(nz)
                }
                vb.position(0)
                val idxList = ArrayList<Short>()
                for (rr in r0 until r1) for (c in 0 until w - 1) {
                    if (hg[rr * w + c].isNaN() || hg[rr * w + c + 1].isNaN() ||
                        hg[(rr + 1) * w + c].isNaN() || hg[(rr + 1) * w + c + 1].isNaN()) continue
                    val a = (rr - r0) * w + c
                    val b = a + 1
                    val cc = a + w
                    val d = cc + 1
                    // cut-v1: keep or drop each whole triangle by its centre (grid units)
                    val x0 = c + 0.5f; val y0 = rr + 0.5f
                    if (kept(x0 + 1f / 3f, y0 + 1f / 3f)) {
                        idxList.add(a.toShort()); idxList.add(cc.toShort()); idxList.add(b.toShort())
                    }
                    if (kept(x0 + 2f / 3f, y0 + 2f / 3f)) {
                        idxList.add(b.toShort()); idxList.add(cc.toShort()); idxList.add(d.toShort())
                    }
                }
                val ib = ByteBuffer.allocateDirect(max(1, idxList.size) * 2).order(ByteOrder.nativeOrder()).asShortBuffer()
                for (s in idxList) ib.put(s)
                ib.position(0)
                out.add(Band(vb, ib, idxList.size))
                r0 = r1
            }
            bands = out

            // pins: a vertical stick from the surface, plus a dot on top
            val across = max(w * dx, h * dy)
            val stick = across * 0.06f
            val pb = ByteBuffer.allocateDirect(max(1, pins.size) * 2 * 7 * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()
            var n = 0
            for (p in pins) {
                if (!kept(p.x, p.y)) continue          // cut-v1: no pins floating over the removed side
                val z = cellHeight(p.x, p.y)
                if (z.isNaN()) continue
                val cr = Color.red(p.colour) / 255f; val cg = Color.green(p.colour) / 255f; val cb = Color.blue(p.colour) / 255f
                val base = z * ve
                val top = base + if (p.focus) stick * 1.4f else stick
                pb.put(wx(p.x)); pb.put(base); pb.put(wz(p.y)); pb.put(cr); pb.put(cg); pb.put(cb); pb.put(if (p.focus) 1f else 0f)
                pb.put(wx(p.x)); pb.put(top); pb.put(wz(p.y)); pb.put(cr); pb.put(cg); pb.put(cb); pb.put(if (p.focus) 1f else 0f)
                n++
            }
            pb.position(0)
            pinBuf = if (n > 0) pb else null
            pinCount = n

            // profile line draped on the surface; breaks where cells have no value
            val strips = ArrayList<FloatBuffer>()
            line?.let { ln ->
                val len = sqrt((ln[2] - ln[0]) * (ln[2] - ln[0]) + (ln[3] - ln[1]) * (ln[3] - ln[1]))
                val steps = max(2, (len * 4).toInt())
                val lift = across * 0.004f
                var cur = ArrayList<Float>()
                for (i in 0..steps) {
                    val f = i.toFloat() / steps
                    val gx = ln[0] + f * (ln[2] - ln[0])
                    val gy = ln[1] + f * (ln[3] - ln[1])
                    val z = cellHeight(gx, gy)
                    if (z.isNaN()) {
                        if (cur.size >= 6) strips.add(toBuf(cur))
                        cur = ArrayList()
                    } else { cur.add(wx(gx)); cur.add(z * ve + lift); cur.add(wz(gy)) }
                }
                if (cur.size >= 6) strips.add(toBuf(cur))
            }
            lineStrips = strips

            // cut-v1/v2: the cut face along the whole line. For every sample (nearest stored cell):
            //   ground g, local base b (cut-v2), drawing floor f.
            //   grey  (UNKNOWN)  from min(g, b) down to f
            //   orange (DERIVED raised) from g down to b where g > b
            //   blue  (DERIVED hollow)  from b down to g where b > g (translucent)
            val walls = ArrayList<FloatBuffer>()
            val raised = ArrayList<FloatBuffer>()
            val hollow = ArrayList<FloatBuffer>()
            val ln = line
            val bArr = baseArr
            if (cut != 0 && ln != null) {
                var lo = Float.MAX_VALUE
                for (v in hg) if (!v.isNaN() && v < lo) lo = v
                if (bArr != null) for (v in bArr) if (!v.isNaN() && v < lo) lo = v
                val floorY = lo * ve - across * 0.08f
                val seg = CutGeometry.clipToWindow(ln, w.toFloat(), h.toFloat())
                if (seg != null) {
                    val len = sqrt((seg[2] - seg[0]) * (seg[2] - seg[0]) + (seg[3] - seg[1]) * (seg[3] - seg[1]))
                    val steps = max(2, (len * 4).toInt())
                    var g1 = ArrayList<Float>(); var o1 = ArrayList<Float>(); var b1 = ArrayList<Float>()
                    var along = 0f
                    val stepM = len / steps * sqrt(dx * dy)   // approximate metres per step, for the hatch only
                    fun flush() {
                        if (g1.size >= 20) walls.add(toBuf(g1))
                        if (o1.size >= 20) raised.add(toBuf(o1))
                        if (b1.size >= 20) hollow.add(toBuf(b1))
                        g1 = ArrayList(); o1 = ArrayList(); b1 = ArrayList()
                    }
                    fun put(list: ArrayList<Float>, x: Float, top: Float, bottom: Float, zz: Float, a: Float) {
                        list.add(x); list.add(top); list.add(zz); list.add(a); list.add(top - floorY)
                        list.add(x); list.add(bottom); list.add(zz); list.add(a); list.add(bottom - floorY)
                    }
                    for (i in 0..steps) {
                        val f = i.toFloat() / steps
                        val gx = seg[0] + f * (seg[2] - seg[0])
                        val gy = seg[1] + f * (seg[3] - seg[1])
                        val z = cellHeight(gx, gy)
                        if (z.isNaN()) { flush() } else {
                            val g = z * ve
                            val bc = if (bArr != null) {
                                val c = floor(gx).toInt().coerceIn(0, w - 1)
                                val rr = floor(gy).toInt().coerceIn(0, h - 1)
                                bArr[rr * w + c]
                            } else Float.NaN
                            val x = wx(gx); val zz = wz(gy)
                            if (bc.isNaN()) {
                                put(g1, x, g, floorY, zz, along)
                                put(o1, x, g, g, zz, along)          // zero-height: keeps strips aligned
                                put(b1, x, g, g, zz, along)
                            } else {
                                val b = bc * ve
                                put(g1, x, min(g, b), floorY, zz, along)
                                put(o1, x, g, min(g, b), zz, along)  // zero height where g <= b
                                put(b1, x, max(g, b), g, zz, along)  // zero height where g >= b
                            }
                        }
                        along += stepM
                    }
                    flush()
                }
            }
            wallStrips = walls
            raisedStrips = raised
            hollowStrips = hollow

            // cut-v2 part 2: user HYPOTHESIZED shapes on the face, only while the face is shown.
            // Each sample sits on the A->A' segment, nudged a little toward the removed side so
            // the shape is drawn just in front of the face instead of fighting with it.
            val fills = ArrayList<FloatBuffer>()
            val outlines = ArrayList<FloatBuffer>()
            if (cut != 0 && ln != null && hyps.isNotEmpty() && hypLenM > 0f) {
                val ldx = ln[2] - ln[0]; val ldy = ln[3] - ln[1]
                val ll = sqrt(ldx * ldx + ldy * ldy).coerceAtLeast(1e-6f)
                // right of A->A' (y down) is (-ldy, ldx); the removed side is right when keeping left
                val side = if (cut > 0) 1f else -1f
                val nx = -ldy / ll * side * 0.15f
                val ny = ldx / ll * side * 0.15f
                for (hp in hyps) {
                    val f0 = (hp.fromM / hypLenM).coerceIn(0f, 1f)
                    val f1 = (hp.toM / hypLenM).coerceIn(0f, 1f)
                    if (f1 <= f0) continue
                    val n = max(2, ((f1 - f0) * ll * 4).toInt())
                    var fill = ArrayList<Float>(); val tops = ArrayList<Float>(); val bots = ArrayList<Float>()
                    fun close() {
                        if (fill.size >= 20) fills.add(toBuf(fill))
                        if (tops.size >= 6) {
                            val o = ArrayList<Float>()
                            o.addAll(tops)
                            var i = bots.size - 3
                            while (i >= 0) { o.add(bots[i]); o.add(bots[i + 1]); o.add(bots[i + 2]); i -= 3 }
                            o.add(tops[0]); o.add(tops[1]); o.add(tops[2])
                            outlines.add(toBuf(o))
                        }
                        fill = ArrayList(); tops.clear(); bots.clear()
                    }
                    for (i in 0..n) {
                        val f = f0 + (f1 - f0) * i / n
                        val gx = ln[0] + f * ldx
                        val gy = ln[1] + f * ldy
                        val z = cellHeight(gx, gy)
                        if (z.isNaN()) { close(); continue }
                        val g = z * ve
                        val top = g - hp.topM * ve
                        val bot = g - hp.bottomM * ve
                        val x = wx(gx + nx); val zz = wz(gy + ny)
                        fill.add(x); fill.add(top); fill.add(zz); fill.add(0f); fill.add(0f)
                        fill.add(x); fill.add(bot); fill.add(zz); fill.add(0f); fill.add(0f)
                        tops.add(x); tops.add(top); tops.add(zz)
                        bots.add(x); bots.add(bot); bots.add(zz)
                    }
                    close()
                }
            }
            hypFill = fills
            hypOutline = outlines

            // ef-v4b: measured ERT sections on the face (slightly nearer the face than hypotheses)
            val sstrips = ArrayList<Pair<Int, FloatBuffer>>()
            if (cut != 0 && ln != null && sections.isNotEmpty()) {
                val ldx = ln[2] - ln[0]; val ldy = ln[3] - ln[1]
                val ll = sqrt(ldx * ldx + ldy * ldy).coerceAtLeast(1e-6f)
                val side = if (cut > 0) 1f else -1f
                val nx = -ldy / ll * side * 0.08f
                val ny = ldx / ll * side * 0.08f
                sections.forEachIndexed { si, sc ->
                    if (sc.lengthM <= 0f || sc.toM <= sc.fromM) return@forEachIndexed
                    val n = max(2, ((sc.toM - sc.fromM) / sc.lengthM * ll * 4).toInt())
                    var cur = ArrayList<Float>()
                    fun flush() { if (cur.size >= 32) sstrips.add(Pair(si, toBuf(cur))); cur = ArrayList() }
                    for (i in 0..n) {
                        val dM = sc.fromM + (sc.toM - sc.fromM) * i / n
                        val along = (dM / sc.lengthM).coerceIn(0f, 1f)
                        val f = if (sc.reversed) 1f - along else along
                        val gx = ln[0] + f * ldx
                        val gy = ln[1] + f * ldy
                        val z = cellHeight(gx, gy)
                        if (z.isNaN()) { flush(); continue }
                        val g = z * ve
                        val u = i.toFloat() / n
                        val x = wx(gx + nx); val zz = wz(gy + ny)
                        // top vertex then bottom vertex: pos, uv, normal (up)
                        cur.add(x); cur.add(g - sc.topM * ve); cur.add(zz); cur.add(u); cur.add(0f); cur.add(0f); cur.add(1f); cur.add(0f)
                        cur.add(x); cur.add(g - sc.bottomM * ve); cur.add(zz); cur.add(u); cur.add(1f); cur.add(0f); cur.add(1f); cur.add(0f)
                    }
                    flush()
                }
            }
            secStrips = sstrips
        }
        private var pinCount = 0

        private fun toBuf(a: List<Float>): FloatBuffer {
            val b = ByteBuffer.allocateDirect(a.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()
            for (v in a) b.put(v)
            b.position(0)
            return b
        }

        private fun slope(a: Float, m: Float, b: Float, step: Float): Float = when {
            !a.isNaN() && !b.isNaN() -> (b - a) / (2 * step)
            !b.isNaN() && !m.isNaN() -> (b - m) / step
            !a.isNaN() && !m.isNaN() -> (m - a) / step
            else -> 0f
        }

        // ------------------------------------------------------------ GL

        override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
            GLES20.glClearColor(14 / 255f, 17 / 255f, 22 / 255f, 1f)
            GLES20.glEnable(GLES20.GL_DEPTH_TEST)
            meshProg = program(MESH_VS, MESH_FS)
            flatProg = program(FLAT_VS, FLAT_FS)
            wallProg = program(WALL_VS, WALL_FS)
            texId = 0
            texDirty = true
            secTex = IntArray(0)          // ef-v4b: textures are gone with the old context
            secDirty = true
        }

        override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
            vw = max(1, width); vh = max(1, height)
            GLES20.glViewport(0, 0, vw, vh)
        }

        override fun onDrawFrame(gl: GL10?) {
            GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT or GLES20.GL_DEPTH_BUFFER_BIT)
            if (texDirty) uploadTexture()
            if (bands.isNotEmpty() && texId != 0) {
                val across = max(w * dx, h * dy)
                Matrix.perspectiveM(proj, 0, 45f, vw.toFloat() / vh, max(1f, dist * 0.01f), dist * 4f + across * 2f)
                val a = Math.toRadians(az.toDouble()); val t = Math.toRadians(tilt.toDouble())
                val ex = (dist * cos(t) * sin(a)).toFloat()
                val ey = (dist * sin(t)).toFloat()
                val ez = (-dist * cos(t) * cos(a)).toFloat()
                Matrix.setLookAtM(viewM, 0, ex, ey, ez, 0f, 0f, 0f, 0f, 1f, 0f)
                Matrix.multiplyMM(mvp, 0, proj, 0, viewM, 0)
                drawMesh()
                drawPins()
                drawLine()
                drawWall()
                drawSections()
                drawHypOutline()
            }
            shotCallback?.let { cb ->
                shotCallback = null
                cb(readPixels())
            }
        }

        private fun drawMesh() {
            GLES20.glUseProgram(meshProg)
            val uMvp = GLES20.glGetUniformLocation(meshProg, "uMvp")
            val uLight = GLES20.glGetUniformLocation(meshProg, "uLight")
            val uTex = GLES20.glGetUniformLocation(meshProg, "uTex")
            val aPos = GLES20.glGetAttribLocation(meshProg, "aPos")
            val aUv = GLES20.glGetAttribLocation(meshProg, "aUv")
            val aN = GLES20.glGetAttribLocation(meshProg, "aN")
            GLES20.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
            // light from the north-west, 45 degrees up (the map's own hillshade convention)
            GLES20.glUniform3f(uLight, -0.5f, 0.7071f, -0.5f)
            GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texId)
            GLES20.glUniform1i(uTex, 0)
            for (b in bands) {
                if (b.count == 0) continue
                b.verts.position(0)
                GLES20.glVertexAttribPointer(aPos, 3, GLES20.GL_FLOAT, false, 32, b.verts)
                GLES20.glEnableVertexAttribArray(aPos)
                b.verts.position(3)
                GLES20.glVertexAttribPointer(aUv, 2, GLES20.GL_FLOAT, false, 32, b.verts)
                GLES20.glEnableVertexAttribArray(aUv)
                b.verts.position(5)
                GLES20.glVertexAttribPointer(aN, 3, GLES20.GL_FLOAT, false, 32, b.verts)
                GLES20.glEnableVertexAttribArray(aN)
                b.verts.position(0)
                b.idx.position(0)
                GLES20.glDrawElements(GLES20.GL_TRIANGLES, b.count, GLES20.GL_UNSIGNED_SHORT, b.idx)
            }
            GLES20.glDisableVertexAttribArray(aPos)
            GLES20.glDisableVertexAttribArray(aUv)
            GLES20.glDisableVertexAttribArray(aN)
        }

        private fun drawPins() {
            val pb = pinBuf ?: return
            GLES20.glUseProgram(flatProg)
            val uMvp = GLES20.glGetUniformLocation(flatProg, "uMvp")
            val uSize = GLES20.glGetUniformLocation(flatProg, "uSize")
            val aPos = GLES20.glGetAttribLocation(flatProg, "aPos")
            val aCol = GLES20.glGetAttribLocation(flatProg, "aCol")
            GLES20.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
            pb.position(0)
            GLES20.glVertexAttribPointer(aPos, 3, GLES20.GL_FLOAT, false, 28, pb)
            GLES20.glEnableVertexAttribArray(aPos)
            pb.position(3)
            GLES20.glVertexAttribPointer(aCol, 4, GLES20.GL_FLOAT, false, 28, pb)
            GLES20.glEnableVertexAttribArray(aCol)
            pb.position(0)
            GLES20.glLineWidth(3f)
            GLES20.glUniform1f(uSize, 1f)
            GLES20.glDrawArrays(GLES20.GL_LINES, 0, pinCount * 2)
            GLES20.glUniform1f(uSize, 16f)
            // tops only: every second vertex
            for (i in 0 until pinCount) GLES20.glDrawArrays(GLES20.GL_POINTS, 2 * i + 1, 1)
            GLES20.glDisableVertexAttribArray(aPos)
            GLES20.glDisableVertexAttribArray(aCol)
        }

        private fun drawWall() {
            if (wallStrips.isEmpty() && raisedStrips.isEmpty() && hollowStrips.isEmpty()) return
            GLES20.glUseProgram(wallProg)
            val uMvp = GLES20.glGetUniformLocation(wallProg, "uMvp")
            val uPeriod = GLES20.glGetUniformLocation(wallProg, "uPeriod")
            val uColour = GLES20.glGetUniformLocation(wallProg, "uColour")
            val uHatch = GLES20.glGetUniformLocation(wallProg, "uHatch")
            val aPos = GLES20.glGetAttribLocation(wallProg, "aPos")
            val aW = GLES20.glGetAttribLocation(wallProg, "aW")
            GLES20.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
            GLES20.glUniform1f(uPeriod, max(w * dx, h * dy) * 0.02f)
            fun strips(list: List<FloatBuffer>) {
                for (s in list) {
                    s.position(0)
                    GLES20.glVertexAttribPointer(aPos, 3, GLES20.GL_FLOAT, false, 20, s)
                    GLES20.glEnableVertexAttribArray(aPos)
                    s.position(3)
                    GLES20.glVertexAttribPointer(aW, 2, GLES20.GL_FLOAT, false, 20, s)
                    GLES20.glEnableVertexAttribArray(aW)
                    s.position(0)
                    GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, s.capacity() / 5)
                }
            }
            // UNKNOWN: grey, hatched
            GLES20.glUniform4f(uColour, 0.55f, 0.55f, 0.58f, 1f)
            GLES20.glUniform1f(uHatch, 1f)
            strips(wallStrips)
            // DERIVED raised material: solid orange
            GLES20.glUniform4f(uColour, 0.93f, 0.55f, 0.18f, 1f)
            GLES20.glUniform1f(uHatch, 0f)
            strips(raisedStrips)
            // cut-v2 part 2: HYPOTHESIZED (user): purple, in front of the face
            if (hypFill.isNotEmpty()) {
                GLES20.glEnable(GLES20.GL_BLEND)
                GLES20.glBlendFunc(GLES20.GL_SRC_ALPHA, GLES20.GL_ONE_MINUS_SRC_ALPHA)
                GLES20.glUniform4f(uColour, 0.62f, 0.32f, 0.95f, 0.65f)
                GLES20.glUniform1f(uHatch, 0f)
                strips(hypFill)
                GLES20.glDisable(GLES20.GL_BLEND)
            }
            // DERIVED hollow: translucent blue, drawn last without writing depth
            if (hollowStrips.isNotEmpty()) {
                GLES20.glEnable(GLES20.GL_BLEND)
                GLES20.glBlendFunc(GLES20.GL_SRC_ALPHA, GLES20.GL_ONE_MINUS_SRC_ALPHA)
                GLES20.glDepthMask(false)
                GLES20.glUniform4f(uColour, 0.30f, 0.55f, 0.98f, 0.45f)
                strips(hollowStrips)
                GLES20.glDepthMask(true)
                GLES20.glDisable(GLES20.GL_BLEND)
            }
            GLES20.glDisableVertexAttribArray(aPos)
            GLES20.glDisableVertexAttribArray(aW)
        }

        private fun uploadSections() {
            if (secTex.isNotEmpty()) GLES20.glDeleteTextures(secTex.size, secTex, 0)
            secTex = IntArray(sections.size)
            if (sections.isNotEmpty()) GLES20.glGenTextures(sections.size, secTex, 0)
            sections.forEachIndexed { i, sc ->
                GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, secTex[i])
                GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_NEAREST)
                GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_NEAREST)
                GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
                GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
                if (!sc.bitmap.isRecycled) GLUtils.texImage2D(GLES20.GL_TEXTURE_2D, 0, sc.bitmap, 0)
            }
            secDirty = false
        }

        /** ef-v4b: measured sections, textured with the mesh program (same layout: pos, uv, normal) */
        private fun drawSections() {
            if (secDirty) uploadSections()
            if (secStrips.isEmpty() || secTex.isEmpty()) return
            GLES20.glUseProgram(meshProg)
            val uMvp = GLES20.glGetUniformLocation(meshProg, "uMvp")
            val uLight = GLES20.glGetUniformLocation(meshProg, "uLight")
            val uTex = GLES20.glGetUniformLocation(meshProg, "uTex")
            val aPos = GLES20.glGetAttribLocation(meshProg, "aPos")
            val aUv = GLES20.glGetAttribLocation(meshProg, "aUv")
            val aN = GLES20.glGetAttribLocation(meshProg, "aN")
            GLES20.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
            GLES20.glUniform3f(uLight, 0f, 1f, 0f)           // flat, full light: colours stay true
            GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
            GLES20.glUniform1i(uTex, 0)
            for ((si, b) in secStrips) {
                if (si >= secTex.size) continue
                GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, secTex[si])
                b.position(0)
                GLES20.glVertexAttribPointer(aPos, 3, GLES20.GL_FLOAT, false, 32, b)
                GLES20.glEnableVertexAttribArray(aPos)
                b.position(3)
                GLES20.glVertexAttribPointer(aUv, 2, GLES20.GL_FLOAT, false, 32, b)
                GLES20.glEnableVertexAttribArray(aUv)
                b.position(5)
                GLES20.glVertexAttribPointer(aN, 3, GLES20.GL_FLOAT, false, 32, b)
                GLES20.glEnableVertexAttribArray(aN)
                b.position(0)
                GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, b.capacity() / 8)
            }
            GLES20.glDisableVertexAttribArray(aPos)
            GLES20.glDisableVertexAttribArray(aUv)
            GLES20.glDisableVertexAttribArray(aN)
        }

        private fun drawHypOutline() {
            if (hypOutline.isEmpty()) return
            GLES20.glUseProgram(flatProg)
            val uMvp = GLES20.glGetUniformLocation(flatProg, "uMvp")
            val uSize = GLES20.glGetUniformLocation(flatProg, "uSize")
            val aPos = GLES20.glGetAttribLocation(flatProg, "aPos")
            val aCol = GLES20.glGetAttribLocation(flatProg, "aCol")
            GLES20.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
            GLES20.glUniform1f(uSize, 1f)
            GLES20.glDisableVertexAttribArray(aCol)
            GLES20.glVertexAttrib4f(aCol, 0.86f, 0.66f, 1f, 0f)
            GLES20.glLineWidth(3f)
            for (s in hypOutline) {
                s.position(0)
                GLES20.glVertexAttribPointer(aPos, 3, GLES20.GL_FLOAT, false, 12, s)
                GLES20.glEnableVertexAttribArray(aPos)
                GLES20.glDrawArrays(GLES20.GL_LINE_STRIP, 0, s.capacity() / 3)
            }
            GLES20.glDisableVertexAttribArray(aPos)
        }

        private fun drawLine() {
            if (lineStrips.isEmpty()) return
            GLES20.glUseProgram(flatProg)
            val uMvp = GLES20.glGetUniformLocation(flatProg, "uMvp")
            val uSize = GLES20.glGetUniformLocation(flatProg, "uSize")
            val aPos = GLES20.glGetAttribLocation(flatProg, "aPos")
            val aCol = GLES20.glGetAttribLocation(flatProg, "aCol")
            GLES20.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
            GLES20.glUniform1f(uSize, 1f)
            GLES20.glDisableVertexAttribArray(aCol)
            GLES20.glVertexAttrib4f(aCol, 1f, 0.92f, 0.2f, 0f)
            GLES20.glLineWidth(4f)
            for (s in lineStrips) {
                s.position(0)
                GLES20.glVertexAttribPointer(aPos, 3, GLES20.GL_FLOAT, false, 12, s)
                GLES20.glEnableVertexAttribArray(aPos)
                GLES20.glDrawArrays(GLES20.GL_LINE_STRIP, 0, s.capacity() / 3)
            }
            GLES20.glDisableVertexAttribArray(aPos)
        }

        private fun uploadTexture() {
            val dr = drape ?: return
            if (dr.bitmap.isRecycled) return
            if (texId == 0) {
                val ids = IntArray(1)
                GLES20.glGenTextures(1, ids, 0)
                texId = ids[0]
            }
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texId)
            // NEAREST: each image pixel stays a sharp square at any zoom (Exact cells)
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_NEAREST)
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_NEAREST)
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
            GLUtils.texImage2D(GLES20.GL_TEXTURE_2D, 0, dr.bitmap, 0)
            texDirty = false
        }

        private fun readPixels(): Bitmap? = try {
            val buf = ByteBuffer.allocateDirect(vw * vh * 4).order(ByteOrder.nativeOrder())
            GLES20.glReadPixels(0, 0, vw, vh, GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, buf)
            val raw = Bitmap.createBitmap(vw, vh, Bitmap.Config.ARGB_8888)
            buf.position(0)
            raw.copyPixelsFromBuffer(buf)
            // GL rows start at the bottom: flip
            val m = android.graphics.Matrix().apply { preScale(1f, -1f) }
            val flipped = Bitmap.createBitmap(raw, 0, 0, vw, vh, m, false)
            if (flipped !== raw) raw.recycle()
            flipped
        } catch (e: Throwable) { null }

        private fun program(vs: String, fs: String): Int {
            fun shader(type: Int, src: String): Int {
                val s = GLES20.glCreateShader(type)
                GLES20.glShaderSource(s, src)
                GLES20.glCompileShader(s)
                val ok = IntArray(1)
                GLES20.glGetShaderiv(s, GLES20.GL_COMPILE_STATUS, ok, 0)
                if (ok[0] == 0) errorSink?.invoke("3D shader did not compile on this phone: " + GLES20.glGetShaderInfoLog(s))
                return s
            }
            val p = GLES20.glCreateProgram()
            GLES20.glAttachShader(p, shader(GLES20.GL_VERTEX_SHADER, vs))
            GLES20.glAttachShader(p, shader(GLES20.GL_FRAGMENT_SHADER, fs))
            GLES20.glLinkProgram(p)
            val ok = IntArray(1)
            GLES20.glGetProgramiv(p, GLES20.GL_LINK_STATUS, ok, 0)
            if (ok[0] == 0) errorSink?.invoke("3D shader did not link on this phone: " + GLES20.glGetProgramInfoLog(p))
            return p
        }

        companion object {
            const val MESH_VS = """
                uniform mat4 uMvp;
                uniform vec3 uLight;
                attribute vec3 aPos;
                attribute vec2 aUv;
                attribute vec3 aN;
                varying vec2 vUv;
                varying float vL;
                void main() {
                    gl_Position = uMvp * vec4(aPos, 1.0);
                    vUv = aUv;
                    vL = max(dot(normalize(aN), normalize(uLight)), 0.0);
                }"""
            // empty layer pixels (alpha 0) and places the layer does not cover are drawn dark grey
            const val MESH_FS = """
                precision mediump float;
                uniform sampler2D uTex;
                varying vec2 vUv;
                varying float vL;
                void main() {
                    vec4 c = texture2D(uTex, vUv);
                    bool outside = vUv.x < 0.0 || vUv.x > 1.0 || vUv.y < 0.0 || vUv.y > 1.0;
                    vec3 rgb = (outside || c.a < 0.5) ? vec3(0.17, 0.17, 0.19) : c.rgb;
                    float k = 0.6 + 0.4 * vL;
                    gl_FragColor = vec4(rgb * k, 1.0);
                }"""
            const val FLAT_VS = """
                uniform mat4 uMvp;
                uniform float uSize;
                attribute vec3 aPos;
                attribute vec4 aCol;
                varying vec4 vCol;
                varying float vTop;
                void main() {
                    gl_Position = uMvp * vec4(aPos, 1.0);
                    gl_PointSize = uSize * (1.0 + 0.5 * aCol.a);
                    vCol = aCol;
                    vTop = (uSize > 2.0 && aCol.a > 0.5) ? 1.0 : 0.0;
                }"""
            // a focus pin (aCol.a = 1) gets a white top
            // cut-v1: grey face with diagonal hatch = NO subsurface measurement
            const val WALL_VS = """
                uniform mat4 uMvp;
                attribute vec3 aPos;
                attribute vec2 aW;
                varying vec2 vW;
                void main() {
                    gl_Position = uMvp * vec4(aPos, 1.0);
                    vW = aW;
                }"""
            // cut-v2: one colour per band; uHatch = 1 adds the diagonal "no measurement" hatch
            const val WALL_FS = """
                precision mediump float;
                uniform float uPeriod;
                uniform float uHatch;
                uniform vec4 uColour;
                varying vec2 vW;
                void main() {
                    float t = mod(vW.x + vW.y, uPeriod) / uPeriod;
                    vec3 c = (uHatch > 0.5 && t < 0.18) ? uColour.rgb * 0.55 : uColour.rgb;
                    gl_FragColor = vec4(c, uColour.a);
                }"""
            const val FLAT_FS = """
                precision mediump float;
                varying vec4 vCol;
                varying float vTop;
                void main() {
                    vec3 c = vTop > 0.5 ? vec3(1.0) : vCol.rgb;
                    gl_FragColor = vec4(c, 1.0);
                }"""
        }
    }
}

/** cut-v1: pure geometry for the cutaway (grid units: x right, y down; north up on the map) */
object CutGeometry {
    /** +1 = keep the left side of A->A' (as seen on the north-up map), -1 = keep the right side */
    fun keep(line: FloatArray, side: Int, gx: Float, gy: Float): Boolean {
        val cross = (line[2] - line[0]) * (gy - line[1]) - (line[3] - line[1]) * (gx - line[0])
        // with y pointing down, cross > 0 means the point is to the RIGHT of A->A'
        return if (side > 0) cross <= 0f else cross >= 0f
    }

    /** the straight line through A and A', clipped to the window [0,w] x [0,h]; null if it misses */
    fun clipToWindow(line: FloatArray, w: Float, h: Float): FloatArray? {
        val ax = line[0]; val ay = line[1]
        val ddx = line[2] - ax; val ddy = line[3] - ay
        if (ddx == 0f && ddy == 0f) return null
        var t0 = -1e9f; var t1 = 1e9f
        fun clip(p: Float, q: Float): Boolean {
            if (p == 0f) return q >= 0f
            val t = q / p
            if (p < 0f) { if (t > t1) return false; if (t > t0) t0 = t }
            else { if (t < t0) return false; if (t < t1) t1 = t }
            return true
        }
        if (!clip(-ddx, ax) || !clip(ddx, w - ax) || !clip(-ddy, ay) || !clip(ddy, h - ay)) return null
        if (t1 <= t0) return null
        return floatArrayOf(ax + t0 * ddx, ay + t0 * ddy, ax + t1 * ddx, ay + t1 * ddy)
    }
}
