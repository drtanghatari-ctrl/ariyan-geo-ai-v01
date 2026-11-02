package com.ariyan.geoai

import android.content.Context
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.View
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

/**
 * mc-v1.1 (2026-11-02): the decorative pieces of the mock-up, shared by
 * Mission Control and the AI Debate Engine. Drawing only: no data is made up
 * here. The header pattern is an ornament (it carries no labels and is not a
 * map); the gauge and bars draw exactly the numbers they are given.
 */
object AriyanDecor {

    const val ACCENT = 0xFF3FB68B.toInt()
    const val TEAL = 0xFF2FA6B8.toInt()
    const val BLUE = 0xFF4C8DFF.toInt()
    const val VIOLET = 0xFF9A7BFF.toInt()
    const val AMBER = 0xFFD9A62B.toInt()
    const val ORANGE = 0xFFD9822B.toInt()
    const val ROSE = 0xFFE0607E.toInt()
    const val LINE = 0xFF30363D.toInt()
    const val SURFACE = 0xFF161B22.toInt()

    val BAND_COLOURS = mapOf(
        "SUBSTANTIAL" to 0xFF2E7D32.toInt(), "HIGH" to ACCENT, "MODERATE" to AMBER, "LOW" to ORANGE,
        "NO_DATA" to 0xFF6E7681.toInt(), "NOT_RATED" to 0xFF3A414A.toInt()
    )
    val PERSPECTIVE_COLOURS = listOf(TEAL, AMBER, ROSE, ACCENT, VIOLET, BLUE)
    val AGREEMENT_COLOURS = mapOf(
        "LEADING_INTERPRETATION" to ACCENT, "CONTESTED" to ROSE, "WEAK_SIGNAL" to ORANGE, "NO_DATA" to 0xFF6E7681.toInt()
    )

    fun withAlpha(c: Int, a: Int) = (c and 0x00FFFFFF) or (a.coerceIn(0, 255) shl 24)

    /** Rounded panel with a soft top-to-bottom gradient and a hairline edge. */
    fun panel(d: Float, tint: Int = ACCENT, radiusDp: Float = 14f) = GradientDrawable(
        GradientDrawable.Orientation.TOP_BOTTOM, intArrayOf(withAlpha(tint, 26), SURFACE)
    ).apply { cornerRadius = radiusDp * d; setStroke(maxOf(1, d.toInt()), withAlpha(tint, 70)) }

    fun pill(d: Float, fill: Int, stroke: Int? = null) = GradientDrawable().apply {
        cornerRadius = 40 * d; setColor(fill)
        if (stroke != null) setStroke(maxOf(1, d.toInt()), stroke)
    }

    /** Header banner: dark teal gradient with an ornamental contour pattern. */
    class HeaderBanner(ctx: Context) : View(ctx) {
        private val p = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
        private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
        override fun onDraw(c: Canvas) {
            val w = width.toFloat(); val h = height.toFloat()
            val r = 18f * resources.displayMetrics.density
            fill.shader = LinearGradient(0f, 0f, w, h, 0xFF0F2A2A.toInt(), 0xFF101722.toInt(), Shader.TileMode.CLAMP)
            c.drawRoundRect(RectF(0f, 0f, w, h), r, r, fill)
            c.save()
            val clip = Path().apply { addRoundRect(RectF(0f, 0f, w, h), r, r, Path.Direction.CW) }
            c.clipPath(clip)
            p.strokeWidth = 1.2f * resources.displayMetrics.density
            for ((cx, cy, k) in listOf(Triple(0.82f, 0.30f, 9), Triple(0.18f, 1.05f, 7))) {
                for (i in 1..k) {
                    p.color = withAlpha(ACCENT, 22 + 6 * (k - i))
                    val base = i * h * 0.11f
                    val path = Path()
                    for (s in 0..72) {
                        val t = s / 72.0 * 2 * PI
                        val rr = base * (1 + 0.10 * sin(3 * t + i) + 0.05 * cos(5 * t - i))
                        val x = (cx * w + rr * cos(t) * 1.35).toFloat()
                        val y = (cy * h + rr * sin(t)).toFloat()
                        if (s == 0) path.moveTo(x, y) else path.lineTo(x, y)
                    }
                    path.close()
                    c.drawPath(path, p)
                }
            }
            c.restore()
        }
    }

    /**
     * Semicircular confidence gauge on the Steward's 0-1 scale. Arc segments are
     * the real band ceilings (LOW 0.35, MODERATE 0.55, HIGH 0.75, SUBSTANTIAL 0.90);
     * bands above the highest one reached are drawn dim. The needle sits on the
     * value passed in (the highest stored confidence), never on a made-up number.
     */
    class Gauge(ctx: Context, private val value: Double?, private val band: String?) : View(ctx) {
        private val arc = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeCap = Paint.Cap.BUTT }
        private val pen = Paint(Paint.ANTI_ALIAS_FLAG)
        private val segs = listOf(
            Triple(0.0, 0.35, "LOW"), Triple(0.35, 0.55, "MODERATE"), Triple(0.55, 0.75, "HIGH"),
            Triple(0.75, 0.90, "SUBSTANTIAL"), Triple(0.90, 1.0, "")
        )
        private val order = listOf("LOW", "MODERATE", "HIGH", "SUBSTANTIAL")

        override fun onMeasure(wSpec: Int, hSpec: Int) {
            val w = MeasureSpec.getSize(wSpec)
            setMeasuredDimension(w, (w * 0.68f).toInt())
        }

        override fun onDraw(c: Canvas) {
            val d = resources.displayMetrics.density
            val w = width.toFloat(); val h = height.toFloat()
            val stroke = 16f * d
            val rad = min(w / 2f - stroke / 2 - 30 * d, h - 22 * d - stroke / 2 - 52 * d)
            val cx = w / 2f; val cy = 22 * d + stroke / 2 + rad
            val box = RectF(cx - rad, cy - rad, cx + rad, cy + rad)
            arc.strokeWidth = stroke
            val reached = order.indexOf(band ?: "")
            for ((a, b, name) in segs) {
                val idx = order.indexOf(name)
                val base = BAND_COLOURS[name] ?: 0xFF3A414A.toInt()
                arc.color = if (name.isEmpty()) 0xFF2A3038.toInt() else if (idx <= reached) base else withAlpha(base, 60)
                c.drawArc(box, (180 + a * 180).toFloat() + 0.6f, ((b - a) * 180).toFloat() - 1.2f, false, arc)
            }
            pen.textAlign = Paint.Align.CENTER
            pen.textSize = 10f * d
            pen.color = 0xFF8B949E.toInt()
            for (t in listOf(0.0, 0.35, 0.55, 0.75, 0.90)) {
                val ang = PI + t * PI
                val rx = cx + (rad + stroke / 2 + 9 * d) * cos(ang).toFloat()
                val ry = cy + (rad + stroke / 2 + 9 * d) * sin(ang).toFloat()
                c.drawText(if (t == 0.0) "0" else String.format(java.util.Locale.US, "%.2f", t), rx, ry + 3 * d, pen)
            }
            if (value != null) {
                val ang = PI + value.coerceIn(0.0, 1.0) * PI
                pen.color = 0xFFE6EDF3.toInt()
                pen.strokeWidth = 3f * d
                pen.strokeCap = Paint.Cap.ROUND
                c.drawLine(cx, cy, cx + (rad - stroke * 0.2f) * cos(ang).toFloat(),
                    cy + (rad - stroke * 0.2f) * sin(ang).toFloat(), pen)
                c.drawCircle(cx, cy, 6 * d, pen)
            }
            pen.textSize = 26f * d
            pen.typeface = Typeface.DEFAULT_BOLD
            pen.color = BAND_COLOURS[band ?: ""] ?: 0xFFE6EDF3.toInt()
            c.drawText(if (value != null) String.format(java.util.Locale.US, "%.2f", value) else "\u2014", cx, cy + 32 * d, pen)
            pen.textSize = 12f * d
            pen.typeface = Typeface.DEFAULT
            pen.color = 0xFF8B949E.toInt()
            c.drawText(band ?: "not rated", cx, cy + 49 * d, pen)
        }
    }

    /** Simple line glyphs for tiles and chips (24-unit design box). */
    class Glyph(ctx: Context, private val kind: String, private val colour: Int) : View(ctx) {
        private val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
        }
        override fun onDraw(c: Canvas) {
            val s = min(width, height) / 24f
            p.color = colour
            p.strokeWidth = 1.8f * s
            c.save()
            c.translate((width - 24 * s) / 2, (height - 24 * s) / 2)
            c.scale(s, s)
            p.strokeWidth = 1.8f
            when (kind) {
                "target" -> { c.drawCircle(12f, 12f, 8f, p); c.drawCircle(12f, 12f, 3f, p)
                    c.drawLine(12f, 1f, 12f, 5f, p); c.drawLine(12f, 19f, 12f, 23f, p)
                    c.drawLine(1f, 12f, 5f, 12f, p); c.drawLine(19f, 12f, 23f, 12f, p) }
                "grid" -> for (i in 0..2) for (j in 0..2) c.drawRect(3f + i * 6.5f, 3f + j * 6.5f, 8f + i * 6.5f, 8f + j * 6.5f, p)
                "stack" -> { c.drawRoundRect(RectF(3f, 7f, 21f, 20f), 2f, 2f, p)
                    c.drawLine(3f, 7f, 9f, 7f, p); c.drawLine(9f, 7f, 11f, 4f, p); c.drawLine(11f, 4f, 21f, 4f, p); c.drawLine(21f, 4f, 21f, 7f, p) }
                "layers" -> for (k in 0..2) { val y = 6f + k * 5f
                    c.drawPath(Path().apply { moveTo(12f, y - 4f); lineTo(21f, y); lineTo(12f, y + 4f); lineTo(3f, y); close() }, p) }
                "book" -> { c.drawPath(Path().apply { moveTo(12f, 6f); lineTo(3f, 4f); lineTo(3f, 19f); lineTo(12f, 21f); close() }, p)
                    c.drawPath(Path().apply { moveTo(12f, 6f); lineTo(21f, 4f); lineTo(21f, 19f); lineTo(12f, 21f) }, p) }
                "debate" -> { c.drawRoundRect(RectF(2f, 3f, 15f, 12f), 3f, 3f, p); c.drawLine(5f, 12f, 4f, 16f, p); c.drawLine(4f, 16f, 8f, 12f, p)
                    c.drawRoundRect(RectF(9f, 10f, 22f, 19f), 3f, 3f, p); c.drawLine(19f, 19f, 20f, 23f, p); c.drawLine(20f, 23f, 16f, 19f, p) }
                "mountain" -> { c.drawRoundRect(RectF(2f, 3f, 22f, 21f), 2f, 2f, p)
                    c.drawPath(Path().apply { moveTo(4f, 18f); lineTo(10f, 9f); lineTo(14f, 14f); lineTo(16f, 11f); lineTo(20f, 18f) }, p) }
                "steward" -> { c.drawPath(Path().apply { moveTo(12f, 2f); lineTo(20f, 5f); lineTo(20f, 12f)
                    quadTo(20f, 19f, 12f, 22f); quadTo(4f, 19f, 4f, 12f); lineTo(4f, 5f); close() }, p)
                    c.drawPath(Path().apply { moveTo(8f, 12f); lineTo(11f, 15f); lineTo(16f, 9f) }, p) }
                "data" -> { c.drawOval(RectF(4f, 2f, 20f, 7f), p); c.drawLine(4f, 4.5f, 4f, 19.5f, p); c.drawLine(20f, 4.5f, 20f, 19.5f, p)
                    c.drawArc(RectF(4f, 9f, 20f, 14f), 0f, 180f, false, p); c.drawArc(RectF(4f, 17f, 20f, 22f), 0f, 180f, false, p) }
                else -> c.drawCircle(12f, 12f, 8f, p)
            }
            c.restore()
        }
    }

    /** Horizontal proportional bar of real counts. */
    class CountBar(ctx: Context, private val segs: List<Pair<Int, Int>>) : View(ctx) {
        private val p = Paint(Paint.ANTI_ALIAS_FLAG)
        override fun onDraw(c: Canvas) {
            val r = height / 2f
            val clip = Path().apply { addRoundRect(RectF(0f, 0f, width.toFloat(), height.toFloat()), r, r, Path.Direction.CW) }
            c.save(); c.clipPath(clip)
            p.color = LINE
            c.drawRect(0f, 0f, width.toFloat(), height.toFloat(), p)
            val total = segs.sumOf { it.second }
            if (total > 0) {
                var x = 0f
                for ((col, n) in segs) {
                    if (n <= 0) continue
                    val w = maxOf(3f, width * n.toFloat() / total)
                    p.shader = LinearGradient(0f, 0f, 0f, height.toFloat(), col, withAlpha(col, 170), Shader.TileMode.CLAMP)
                    c.drawRect(x, 0f, minOf(width.toFloat(), x + w), height.toFloat(), p)
                    p.shader = null
                    x += w
                }
            }
            c.restore()
        }
    }
}
