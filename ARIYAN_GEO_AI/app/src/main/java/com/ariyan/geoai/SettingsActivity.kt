package com.ariyan.geoai

import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.widget.FrameLayout
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
 * mc-v1.3 (2026-11-02): Settings, the last tab of the mock-up. Read-only, in
 * one place: storage access, API keys (only "set" / "not set"; they are typed
 * on the Investigation screen, which this links to), the Grand Project
 * database with its guard and daily backups (db-safe-v1), crash reports, the
 * offline libraries and the app version. Nothing here deletes, moves or
 * changes a file (mission_control.settings_json).
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var python: Python
    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }
    private lateinit var content: LinearLayout
    private val d by lazy { resources.displayMetrics.density }
    private fun px(v: Int) = (v * d).toInt()
    private fun col(id: Int) = ContextCompat.getColor(this, id)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        python = Python.getInstance()
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(px(12), px(10), px(12), px(24)) }
        setContentView(ScrollView(this).apply { setBackgroundColor(col(R.color.ariyan_bg)); addView(content) })
    }

    override fun onResume() {
        super.onResume()
        load()
    }

    private fun load() {
        content.removeAllViews()
        header()
        storage()
        keys()
        val loading = text("Reading the offline_data folder\u2026", 13f, col(R.color.ariyan_text_secondary))
        content.addView(loading)
        lifecycleScope.launch {
            val o = withContext(Dispatchers.Default) {
                try {
                    JSONObject(python.getModule("mission_control").callAttr("settings_json", offlineDataRoot).toString())
                } catch (e: PyException) {
                    JSONObject().put("error", e.message)
                }
            }
            content.removeView(loading)
            if (o.has("error")) {
                content.addView(panel("COULD NOT READ offline_data", "data", AriyanDecor.ROSE).apply { line(this, o.optString("error"), true) })
            } else {
                database(o)
                folders(o)
            }
            app()
        }
    }

    private fun header() {
        val frame = FrameLayout(this)
        frame.addView(AriyanDecor.HeaderBanner(this), FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(px(16), px(14), px(16), px(14)) }
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        row.addView(AriyanDecor.Glyph(this, "steward", AriyanDecor.ACCENT), LinearLayout.LayoutParams(px(28), px(28)))
        row.addView(text("Settings", 22f, col(R.color.ariyan_text_primary), bold = true).apply { setPadding(px(10), 0, 0, 0) })
        box.addView(row)
        box.addView(text("Storage, keys, database safety and backups. Read-only: nothing here deletes or changes a file.",
            13f, AriyanDecor.ACCENT).apply { setPadding(0, px(6), 0, 0) })
        frame.addView(box)
        content.addView(frame, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { bottomMargin = px(8) })
    }

    private fun storage() {
        val ok = ExternalStorageAccess.isGranted(this)
        content.addView(panel("STORAGE", "data", AriyanDecor.VIOLET).apply {
            row(this, ok, "All files access", if (ok) "granted" else "not granted: nothing can be read or saved")
            line(this, "Folder: " + offlineDataRoot)
            if (!ok) addView(pill("Grant access", AriyanDecor.ROSE) {
                try {
                    startActivity(if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R)
                        ExternalStorageAccess.manageAllFilesSettingsIntent(this@SettingsActivity)
                    else Intent(Settings.ACTION_APPLICATION_SETTINGS))
                } catch (e: ActivityNotFoundException) {
                    startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                }
            })
        })
    }

    private fun keys() {
        val creds = SecureCredentialStore(this)
        val ot = creds.activeOpenTopographyApiKey().isNotEmpty()
        val cp = creds.activeCopernicusClientId().isNotEmpty()
        content.addView(panel("API KEYS", "steward", AriyanDecor.TEAL).apply {
            row(this, ot, "OpenTopography key", if (ot) "set" else "not set (live DEM unavailable)")
            row(this, cp, "Copernicus login", if (cp) "set" else "not set (satellite evidence unavailable)")
            line(this, "Values are never shown here. Keys are typed and saved on the Investigation screen.")
            addView(pill("Edit keys on the Investigation screen", AriyanDecor.TEAL) {
                startActivity(Intent(this@SettingsActivity, MainActivity::class.java))
            })
        })
    }

    private fun database(o: JSONObject) {
        val dbo = o.optJSONObject("database") ?: JSONObject()
        val guard = o.optJSONObject("guard")
        val b = o.optJSONObject("backups") ?: JSONObject()
        val files = b.optJSONArray("files")
        val crash = o.optJSONObject("crash_reports") ?: JSONObject()
        content.addView(panel("DATABASE SAFETY (db-safe-v1)", "data", AriyanDecor.AMBER).apply {
            row(this, dbo.optBoolean("exists"), "grand_project.db",
                if (dbo.optBoolean("exists")) mb(dbo.optLong("bytes")) else "missing")
            row(this, guard != null, "Size guard",
                if (guard != null) "last seen " + mb(guard.optLong("last_seen_size")) + ", " +
                    guard.optString("last_seen_at").take(16).replace("T", " ") + " UTC"
                else "no guard file yet")
            row(this, !o.optBoolean("allow_new_flag"), "ALLOW_NEW_GRAND_PROJECT_DB",
                if (o.optBoolean("allow_new_flag")) "PRESENT: the next start may create an empty database. Remove it unless you meant this."
                else "absent (normal)")
            val n = files?.length() ?: 0
            row(this, n > 0, "Daily backups", String.format(Locale.US, "%d kept in db_backups (%s)", n, b.optString("keep_rule")))
            if (files != null) for (i in 0 until minOf(n, 12)) {
                val f = files.getJSONObject(i)
                line(this, "   " + f.optString("name") + "  \u00B7  " + mb(f.optLong("bytes")))
            }
            line(this, "To restore: copy a backup over grand_project.db while the app is closed. The app never deletes your copies.")
            val cn = crash.optInt("count")
            row(this, cn == 0, "Crash reports", if (cn == 0) "none" else
                String.format(Locale.US, "%d, newest %s (offline_data/crash_reports)", cn, crash.optString("newest")))
        })
    }

    private fun folders(o: JSONObject) {
        val f = o.optJSONArray("folders") ?: return
        content.addView(panel("OFFLINE LIBRARIES", "layers", AriyanDecor.BLUE).apply {
            if (f.length() == 0) line(this, "No library folders yet.", true)
            for (i in 0 until f.length()) {
                val x = f.getJSONObject(i)
                row(this, x.optInt("files") > 0, x.optString("name"),
                    String.format(Locale.US, "%,d files, %s", x.optInt("files"), mb(x.optLong("bytes"))))
            }
            line(this, "Bulk COP30 country tiles and their sizes are listed on Mission Control under Data Sources.")
        })
    }

    private fun app() {
        val vn = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "?"
        } catch (e: Exception) { "?" }
        content.addView(panel("APP", "target", AriyanDecor.ACCENT).apply {
            line(this, "ARIYAN GEO AI $vn", true)
            line(this, "Package $packageName \u00B7 Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
        })
    }

    // ---------------------------------------------------------------- widgets

    private fun mb(b: Long): String = if (b >= 1_000_000_000L) String.format(Locale.US, "%.1f GB", b / 1e9)
        else String.format(Locale.US, "%.0f MB", b / 1e6)

    private fun text(s: String, size: Float, colour: Int, bold: Boolean = false) = TextView(this).apply {
        text = s; textSize = size; setTextColor(colour)
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun line(box: LinearLayout, s: String, primary: Boolean = false) {
        box.addView(text(s, 13f, col(if (primary) R.color.ariyan_text_primary else R.color.ariyan_text_secondary)).apply {
            setPadding(0, px(6), 0, 0)
        })
    }

    private fun row(box: LinearLayout, ok: Boolean, name: String, detail: String) {
        val c = if (ok) AriyanDecor.ACCENT else AriyanDecor.ORANGE
        val r = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(px(8), px(7), px(8), px(7))
            background = AriyanDecor.pill(d, AriyanDecor.withAlpha(c, 16)).apply { cornerRadius = 8 * d }
        }
        val t = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        t.addView(text(name, 13f, col(R.color.ariyan_text_primary), bold = true))
        t.addView(text(detail, 12f, col(R.color.ariyan_text_secondary)))
        r.addView(t, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        r.addView(text(if (ok) "\u2713" else "\u2717", 16f, c, bold = true))
        box.addView(r, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(6) })
    }

    private fun panel(title: String, glyph: String, tint: Int): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(px(14), px(12), px(14), px(14))
        background = AriyanDecor.panel(d, tint)
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { setMargins(0, px(6), 0, px(6)) }
        val head = LinearLayout(this@SettingsActivity).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        head.addView(AriyanDecor.Glyph(this@SettingsActivity, glyph, tint), LinearLayout.LayoutParams(px(20), px(20)))
        head.addView(text(title, 13f, tint, bold = true).apply { setPadding(px(8), 0, 0, 0); letterSpacing = 0.06f })
        addView(head)
    }

    private fun pill(label: String, c: Int, action: () -> Unit) = text(label, 14f, col(R.color.ariyan_bg), bold = true).apply {
        gravity = Gravity.CENTER
        setPadding(px(16), px(10), px(16), px(10))
        background = AriyanDecor.pill(d, c)
        isClickable = true
        setOnClickListener { action() }
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(12) }
    }
}
