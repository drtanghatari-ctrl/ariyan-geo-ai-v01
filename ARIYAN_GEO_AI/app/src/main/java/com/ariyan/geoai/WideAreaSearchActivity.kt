package com.ariyan.geoai

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.util.TypedValue
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.ariyan.geoai.databinding.ActivityWideAreaSearchBinding
import com.chaquo.python.Kwarg
import com.chaquo.python.PyException
import com.chaquo.python.Python
import com.google.android.material.button.MaterialButton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * WideAreaSearchActivity -- per the user's own explicit architectural
 * instruction (given before any of this was built), a NEW KIND of
 * investigation the user launches (province-wide, tiled, potentially
 * long-running), deliberately SEPARATE from GrandProjectActivity's own
 * retrospective browse screen ("review what already happened"). This
 * screen is only responsible for configuring, launching, and
 * monitoring wide-area search jobs -- once a job's tiles are processed,
 * their resulting candidates show up in GrandProjectActivity's existing
 * Candidates tab like any other investigation, exactly like any other
 * investigation this app has ever run; this screen never re-displays
 * results itself.
 *
 * TWO TABS, mirroring GrandProjectActivity.kt's own button-switch
 * pattern: "New Search" (configure and create a job -- a real place-
 * name lookup via Nominatim, or a manually typed bounding box, feeding
 * the same tile-grid creation either way) and "Jobs" (a flat list of
 * every job created for this project; tapping one opens a detail dialog
 * with its real, live tile progress and a Start/Resume button). All new
 * content is built entirely in Kotlin code into two empty XML
 * containers (containerNewSearch/containerJobs), same discipline as
 * GrandProjectActivity.kt's own containerCandidateRows/
 * containerHypotheses -- see this app's own real history of a real bug
 * (a literal "--" inside an XML comment breaking Android's data-binding
 * parser, twice) for why new form/list content is built in code rather
 * than new XML.
 *
 * JOB EXECUTION runs in WideAreaSearchService.kt, a real foreground
 * service (mirrors OfflineDownloadService.kt's own structure) --
 * independent of this Activity's own lifecycle, so a real job (which
 * can mean dozens to hundreds of real HTTP calls across many tiles)
 * keeps running if the user leaves this screen. This Activity's own
 * job-detail dialog polls wide_area_search_status_<job_id>.json (the
 * SAME real per-job progress file wide_area_search_mobile.py's own
 * _write_wide_area_status() writes) while it is open, mirroring
 * MainActivity.kt's own readInvestigationProgressText() polling
 * convention exactly, just scoped to one job and to the dialog's own
 * lifetime rather than the whole Activity's -- a simple, self-contained
 * first pass; the service itself is the actual source of truth and
 * keeps running regardless of whether this dialog is open.
 *
 * PROJECT SCOPE: uses the SAME interim stopgap MainActivity.kt's and
 * GrandProjectActivity.kt's own Grand Project persistence already use --
 * grand_project_sync.get_or_create_default_grand_project() -- since no
 * real Grand Project selection UI exists yet (same note as those two
 * files' own doc comments).
 *
 * NOT BUILT IN THIS PASS: AOI input mechanism (c) -- creating a job
 * directly from a reviewed geographic_suggestion row (Phase 2.5's
 * Historical Research & Probable-Area Engine) -- since no UI exists yet
 * to pick a suggestion from; see wide_area_search_mobile.py's own module
 * doc for why this is expected to be a thin addition once that picker
 * UI exists, not a new geocoding/geometry capability. Also not built: a
 * radius_m/grid_size override per job (uses this app's existing single-
 * point investigation defaults, 500m/96, for every tile).
 */
class WideAreaSearchActivity : AppCompatActivity() {

    private lateinit var binding: ActivityWideAreaSearchBinding
    private lateinit var python: Python
    private lateinit var credentialStore: SecureCredentialStore

    // Same real path convention as MainActivity.kt's/GrandProjectActivity.kt's
    // own offlineDataRoot -- see their class doc comments for why this
    // exact value; this is also the `data_root` wide_area_search_mobile.py
    // expects.
    private val offlineDataRoot: String by lazy { ExternalStorageAccess.offlineDataRoot().absolutePath }

    // New-search form state remembered across a successful Look Up
    // call, so Create Job can label the new job accurately.
    // Deliberately simple for a first pass: typing directly into the
    // bounding-box fields afterward does NOT reset this back to
    // MANUAL_BBOX (that would need a TextWatcher on all four fields for
    // marginal benefit -- input_kind is purely a display label on the
    // job list, it has zero effect on the real tile geometry, which
    // always comes from whatever numbers are in the four fields at the
    // moment Create Job is tapped).
    private var lastInputKind: String = "MANUAL_BBOX"
    private var lastPlaceName: String? = null

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* no-op either way, mirrors OfflineDataActivity.kt's own launcher */ }

    private val jobResultReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                WideAreaSearchService.ACTION_JOB_FINISHED -> {
                    Toast.makeText(this@WideAreaSearchActivity, "Wide-area search job finished.", Toast.LENGTH_LONG).show()
                    if (binding.containerJobs.visibility == View.VISIBLE) loadJobsTab()
                }
                WideAreaSearchService.ACTION_JOB_FAILED -> {
                    val err = intent.getStringExtra(WideAreaSearchService.EXTRA_ERROR_MESSAGE) ?: "Unknown error"
                    Toast.makeText(
                        this@WideAreaSearchActivity,
                        "Wide-area search job failed: ${cleanErrorMessage(err)}",
                        Toast.LENGTH_LONG
                    ).show()
                    if (binding.containerJobs.visibility == View.VISIBLE) loadJobsTab()
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityWideAreaSearchBinding.inflate(layoutInflater)
        setContentView(binding.root)

        python = Python.getInstance()
        credentialStore = SecureCredentialStore(this)

        val filter = IntentFilter().apply {
            addAction(WideAreaSearchService.ACTION_JOB_FINISHED)
            addAction(WideAreaSearchService.ACTION_JOB_FAILED)
        }
        ContextCompat.registerReceiver(this, jobResultReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }

        binding.buttonShowNewSearch.setOnClickListener { showNewSearchTab() }
        binding.buttonShowJobs.setOnClickListener { loadJobsTab() }

        showNewSearchTab()
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(jobResultReceiver)
    }

    // =========================== NEW SEARCH TAB ===========================

    private fun showNewSearchTab() {
        binding.containerJobs.visibility = View.GONE
        binding.containerNewSearch.visibility = View.VISIBLE
        binding.containerNewSearch.removeAllViews()
        renderNewSearchForm()
    }

    /** Builds the entire New Search form in code: job title, a place-
     * name lookup (fills the four bounding-box fields below on a real
     * match), the four bounding-box fields themselves (always editable
     * directly, regardless of whether Look Up was used), a tile-size
     * field, and the Create Job button. Rebuilt from scratch each time
     * the New Search tab is shown (same removeAllViews() convention as
     * GrandProjectActivity.kt's own render*() functions). */
    private fun renderNewSearchForm() {
        val density = resources.displayMetrics.density

        fun sectionLabel(text: String): TextView = TextView(this).apply {
            this.text = text
            setTextColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_text_secondary))
            textSize = 12f
            setPadding(0, (12 * density).toInt(), 0, (4 * density).toInt())
        }

        fun field(hintText: String, prefill: String = ""): EditText = EditText(this).apply {
            hint = hintText
            setText(prefill)
            setTextColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_text_primary))
            setHintTextColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_text_secondary))
            setPadding((12 * density).toInt(), (10 * density).toInt(), (12 * density).toInt(), (10 * density).toInt())
        }

        binding.containerNewSearch.addView(sectionLabel("Job title"))
        val inputTitle = field("e.g. Fars Province survey")
        binding.containerNewSearch.addView(inputTitle)

        binding.containerNewSearch.addView(sectionLabel("Look up a place name (fills in the bounding box below)"))
        val inputPlaceName = field("e.g. Fars Province, Iran")
        binding.containerNewSearch.addView(inputPlaceName)

        // Declared before the Look Up button so its click listener can
        // fill them; added to the container further below, after the
        // section label that introduces them, so the ON-SCREEN order
        // stays Title -> Place lookup -> Look Up button -> Bounding box
        // label -> the four fields -> Tile size -> Create Job.
        val inputMinLat = field("min_lat")
        val inputMaxLat = field("max_lat")
        val inputMinLon = field("min_lon")
        val inputMaxLon = field("max_lon")

        val buttonLookUp = MaterialButton(this).apply {
            text = "Look Up Place"
            setBackgroundColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_surface))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = (4 * density).toInt() }
            setOnClickListener {
                val placeName = inputPlaceName.text.toString().trim()
                if (placeName.isEmpty()) {
                    Toast.makeText(this@WideAreaSearchActivity, "Enter a place name first.", Toast.LENGTH_SHORT).show()
                } else {
                    lookUpPlace(placeName, inputMinLat, inputMaxLat, inputMinLon, inputMaxLon)
                }
            }
        }
        binding.containerNewSearch.addView(buttonLookUp)

        binding.containerNewSearch.addView(sectionLabel("Bounding box (edit directly, or use Look Up above)"))
        binding.containerNewSearch.addView(inputMinLat)
        binding.containerNewSearch.addView(inputMaxLat)
        binding.containerNewSearch.addView(inputMinLon)
        binding.containerNewSearch.addView(inputMaxLon)

        binding.containerNewSearch.addView(sectionLabel("Tile size (meters)"))
        val inputTileSize = field("tile size in meters", "1000")
        binding.containerNewSearch.addView(inputTileSize)

        val buttonCreate = MaterialButton(this).apply {
            text = "Create Job"
            setBackgroundColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_accent))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = (16 * density).toInt() }
            setOnClickListener {
                createJob(
                    inputTitle.text.toString().trim(),
                    inputMinLat.text.toString().trim(),
                    inputMaxLat.text.toString().trim(),
                    inputMinLon.text.toString().trim(),
                    inputMaxLon.text.toString().trim(),
                    inputTileSize.text.toString().trim(),
                )
            }
        }
        binding.containerNewSearch.addView(buttonCreate)
    }

    /** Calls the real, live Nominatim lookup (via
     * wide_area_search_mobile.geocode_place_to_bbox_json(), unchanged
     * geocoding logic reused from this project's existing
     * geocoding_source_mobile_nominatim.py) and fills the four
     * bounding-box fields on a real match. A genuine "not found" or a
     * real network/HTTP failure is shown as a plain Toast with the real
     * message -- an ordinary, expected outcome here, not a crash. */
    private fun lookUpPlace(
        placeName: String,
        minLat: EditText, maxLat: EditText, minLon: EditText, maxLon: EditText
    ) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("wide_area_search_mobile")
                        .callAttr("geocode_place_to_bbox_json", placeName)
                        .toString()
                }
                val result = JSONObject(jsonText)
                if (result.optBoolean("found", false)) {
                    val bbox = result.getJSONObject("bounding_box")
                    minLat.setText(bbox.optDouble("min_lat").toString())
                    maxLat.setText(bbox.optDouble("max_lat").toString())
                    minLon.setText(bbox.optDouble("min_lon").toString())
                    maxLon.setText(bbox.optDouble("max_lon").toString())
                    lastInputKind = "PLACE_NAME"
                    lastPlaceName = placeName
                    Toast.makeText(
                        this@WideAreaSearchActivity,
                        "Found: ${result.optString("resolved_name", placeName)}",
                        Toast.LENGTH_LONG
                    ).show()
                } else {
                    Toast.makeText(
                        this@WideAreaSearchActivity,
                        result.optString("error", "Place not found."),
                        Toast.LENGTH_LONG
                    ).show()
                }
            } catch (e: PyException) {
                Toast.makeText(this@WideAreaSearchActivity, "Look-up failed: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            } finally {
                setLoading(false)
            }
        }
    }

    /** Validates the form's four bounding-box fields and tile size as
     * real numbers (an ordinary, expected user-input mistake is caught
     * here with a plain Toast, not a crash), then calls
     * create_wide_area_search_job_json() -- which itself real-tile-grid-
     * generates and persists the job, or returns a real {"error": ...}
     * (e.g. the tile-count cap was exceeded) that this function also
     * surfaces as a plain Toast rather than treating as a hard failure. */
    private fun createJob(
        title: String,
        minLatText: String, maxLatText: String, minLonText: String, maxLonText: String,
        tileSizeText: String,
    ) {
        if (title.isEmpty()) {
            Toast.makeText(this, "Enter a job title first.", Toast.LENGTH_SHORT).show()
            return
        }
        val minLat = minLatText.toDoubleOrNull()
        val maxLat = maxLatText.toDoubleOrNull()
        val minLon = minLonText.toDoubleOrNull()
        val maxLon = maxLonText.toDoubleOrNull()
        val tileSize = tileSizeText.toDoubleOrNull()
        if (minLat == null || maxLat == null || minLon == null || maxLon == null || tileSize == null) {
            Toast.makeText(this, "Fill in all four bounding-box fields and a tile size, all as real numbers.", Toast.LENGTH_LONG).show()
            return
        }

        setLoading(true)
        lifecycleScope.launch {
            try {
                val grandProjectId = getGrandProjectId()
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("wide_area_search_mobile").callAttr(
                        "create_wide_area_search_job_json",
                        offlineDataRoot, grandProjectId, title, lastInputKind,
                        minLat, maxLat, minLon, maxLon, tileSize,
                        Kwarg("place_name", if (lastInputKind == "PLACE_NAME") lastPlaceName else null),
                    ).toString()
                }
                val result = JSONObject(jsonText)
                if (result.has("error")) {
                    Toast.makeText(this@WideAreaSearchActivity, result.optString("error"), Toast.LENGTH_LONG).show()
                } else {
                    Toast.makeText(
                        this@WideAreaSearchActivity,
                        "Job created with ${result.optInt("n_tiles")} tiles.",
                        Toast.LENGTH_LONG
                    ).show()
                    loadJobsTab()
                }
            } catch (e: PyException) {
                Toast.makeText(this@WideAreaSearchActivity, "Failed to create job: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            } finally {
                setLoading(false)
            }
        }
    }

    // =========================== JOBS TAB ===========================

    private fun loadJobsTab() {
        setLoading(true)
        lifecycleScope.launch {
            try {
                val grandProjectId = getGrandProjectId()
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("wide_area_search_mobile")
                        .callAttr("list_wide_area_search_jobs_json", offlineDataRoot, grandProjectId)
                        .toString()
                }
                renderJobRows(jsonText)
            } catch (e: PyException) {
                binding.containerNewSearch.visibility = View.GONE
                binding.containerJobs.visibility = View.VISIBLE
                binding.containerJobs.removeAllViews()
                binding.containerJobs.addView(plainText("Failed to load jobs: ${cleanErrorMessage(e.message)}"))
            } finally {
                setLoading(false)
            }
        }
    }

    private fun plainText(text: String): TextView {
        val density = resources.displayMetrics.density
        return TextView(this).apply {
            this.text = text
            typeface = Typeface.MONOSPACE
            textSize = 12f
            setTextColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_text_secondary))
            setPadding(0, (10 * density).toInt(), 0, (10 * density).toInt())
        }
    }

    /** Real fields per row, exactly as
     * wide_area_search_mobile.list_wide_area_search_jobs_json() (a thin
     * wrapper over grand_project_db.list_wide_area_search_jobs_for_project())
     * returns them -- nothing fabricated, nothing renamed. Tapping a row
     * opens showJobDetail() -- mirrors GrandProjectActivity.kt's own
     * renderCandidateRows()/showCandidateDetail() pattern exactly. */
    private fun renderJobRows(jsonText: String) {
        binding.containerNewSearch.visibility = View.GONE
        binding.containerJobs.visibility = View.VISIBLE
        binding.containerJobs.removeAllViews()

        val array = try {
            JSONArray(jsonText)
        } catch (e: Exception) {
            binding.containerJobs.addView(plainText("Could not parse results."))
            return
        }
        if (array.length() == 0) {
            binding.containerJobs.addView(plainText("No wide-area search jobs created yet -- use the New Search tab."))
            return
        }

        val tapBackground = TypedValue()
        theme.resolveAttribute(android.R.attr.selectableItemBackground, tapBackground, true)
        val density = resources.displayMetrics.density

        for (i in 0 until array.length()) {
            val row = array.getJSONObject(i)
            val jobId = row.optString("id")
            val rowText = buildString {
                append("#").append(i + 1).append("  ").append(row.optString("title")).append("\n")
                append("  ").append(row.optString("input_kind")).append("   ").append(row.optInt("n_tiles")).append(" tiles\n")
                append("  status: ").append(row.optString("status")).append("\n")
                append("  created: ").append(row.optString("created_at")).append("\n")
                append("(tap to view progress / start)")
            }
            val rowView = TextView(this).apply {
                text = rowText
                typeface = Typeface.MONOSPACE
                textSize = 12f
                setTextColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_text_secondary))
                setPadding((12 * density).toInt(), (10 * density).toInt(), (12 * density).toInt(), (10 * density).toInt())
                isClickable = true
                isFocusable = true
                setBackgroundResource(tapBackground.resourceId)
                setOnClickListener { showJobDetail(jobId, row.optString("title")) }
            }
            binding.containerJobs.addView(rowView)
        }
    }

    /** Shows one job's real, live progress in a dialog (built entirely
     * in code, same reasoning as GrandProjectActivity.kt's own
     * showDetailDialog()), plus a "Start / Resume" button that starts
     * WideAreaSearchService for this job_id.
     *
     * Polls wide_area_search_status_<job_id>.json (the real per-job
     * progress file the running job writes) once a second WHILE THIS
     * DIALOG IS OPEN, falling back to a fresh real DB read
     * (get_wide_area_search_job_status_json) whenever that file doesn't
     * exist yet (e.g. the job has never been started, or was started
     * and finished in a previous app session so no live file is being
     * written right now) -- so the dialog always shows something real,
     * whether or not a run is currently in progress. Polling is
     * cancelled the moment the dialog is dismissed; the service itself
     * (if running) is entirely unaffected and keeps going regardless --
     * this is a display convenience, not the job's own control
     * mechanism. */
    private fun showJobDetail(jobId: String, title: String) {
        val density = resources.displayMetrics.density
        val progressText = TextView(this).apply {
            text = "Loading…"
            typeface = Typeface.MONOSPACE
            textSize = 12f
            setTextIsSelectable(true)
            setTextColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_text_secondary))
            val pad = (16 * density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        val scrollView = ScrollView(this).apply { addView(progressText) }

        val dialog = AlertDialog.Builder(this)
            .setTitle(title)
            .setView(scrollView)
            .setPositiveButton("Close", null)
            .setNeutralButton("Start / Resume") { _, _ -> startJob(jobId) }
            .create()

        val statusFile = File(offlineDataRoot, "wide_area_search_status_$jobId.json")
        val pollingJob: Job = lifecycleScope.launch {
            while (isActive) {
                val liveText = readWideAreaStatusText(statusFile)
                if (liveText != null) {
                    progressText.text = liveText
                } else {
                    refreshJobDetailTextFromDb(jobId, progressText)
                }
                delay(1000)
            }
        }
        dialog.setOnDismissListener { pollingJob.cancel() }
        dialog.show()
    }

    /** Real fallback used by showJobDetail()'s polling loop whenever no
     * live status file exists yet -- reads the job's real current
     * status row plus its real tile-progress counts directly from the
     * database via get_wide_area_search_job_status_json(), rather than
     * showing a blank/stale dialog before the job has ever run. */
    private suspend fun refreshJobDetailTextFromDb(jobId: String, target: TextView) {
        try {
            val jsonText = withContext(Dispatchers.Default) {
                python.getModule("wide_area_search_mobile")
                    .callAttr("get_wide_area_search_job_status_json", offlineDataRoot, jobId)
                    .toString()
            }
            val result = JSONObject(jsonText)
            val job = result.optJSONObject("job")
            val progress = result.optJSONObject("progress")
            target.text = buildString {
                if (job != null) {
                    append("status: ").append(job.optString("status")).append("\n")
                }
                if (progress != null) {
                    append("tiles: ").append(progress.optInt("done")).append(" done, ")
                    append(progress.optInt("failed")).append(" failed, ")
                    append(progress.optInt("pending")).append(" pending, ")
                    append(progress.optInt("total")).append(" total")
                }
            }
        } catch (e: PyException) {
            target.text = "Failed to load progress: ${cleanErrorMessage(e.message)}"
        }
    }

    /** Reads wide_area_search_status_<job_id>.json -- the SAME real
     * progress file wide_area_search_mobile.py's
     * _write_wide_area_status() writes while a job is actively running
     * -- best-effort, returns null on any missing/malformed file
     * (e.g. before the job has ever run, or a permission/IO failure),
     * mirroring MainActivity.kt's own readInvestigationProgressText()
     * exactly, just against this project's per-job status shape
     * (phase/done/total/detail) instead of the single-investigation
     * one. */
    private fun readWideAreaStatusText(file: File): String? {
        if (!file.exists()) return null
        return try {
            val obj = JSONObject(file.readText())
            "phase: ${obj.optString("phase", "?")}\n" +
                "done: ${obj.optInt("done", 0)} / ${obj.optInt("total", 0)}\n" +
                obj.optString("detail", "")
        } catch (e: Exception) {
            null
        }
    }

    /** Starts WideAreaSearchService for one job, passing this device's
     * real saved credentials (SecureCredentialStore, the SAME store
     * MainActivity.kt already persists into) -- resumable by design,
     * see wide_area_search_mobile.run_wide_area_search_job()'s own
     * docstring: calling this again for a job with tiles already DONE
     * simply continues with whatever is still PENDING. Refuses to start
     * a second job while WideAreaSearchService.isRunning is already
     * true (mirrors OfflineDataActivity.kt's own single-download-at-a-
     * time check for OfflineDownloadService), with a plain Toast rather
     * than silently queuing or racing two jobs against the same shared
     * Copernicus token/rate limits. */
    private fun startJob(jobId: String) {
        if (WideAreaSearchService.isRunning) {
            Toast.makeText(this, "A wide-area search job is already running -- let it finish first.", Toast.LENGTH_LONG).show()
            return
        }
        val serviceIntent = Intent(this, WideAreaSearchService::class.java).apply {
            putExtra(WideAreaSearchService.EXTRA_JOB_ID, jobId)
            putExtra(WideAreaSearchService.EXTRA_DATA_ROOT, offlineDataRoot)
            putExtra(WideAreaSearchService.EXTRA_API_KEY, credentialStore.openTopographyApiKey)
            putExtra(WideAreaSearchService.EXTRA_DEMTYPE, credentialStore.demType.ifEmpty { "SRTMGL1" })
            putExtra(WideAreaSearchService.EXTRA_NDVI_CLIENT_ID, credentialStore.copernicusClientId)
            putExtra(WideAreaSearchService.EXTRA_NDVI_CLIENT_SECRET, credentialStore.copernicusClientSecret)
        }
        ContextCompat.startForegroundService(this, serviceIntent)
        Toast.makeText(this, "Wide-area search started in the background.", Toast.LENGTH_LONG).show()
    }

    // =========================== SHARED ===========================

    /** Resolves the (one, stopgap) Grand Project's id -- same real
     * stopgap and same suspend-helper pattern as
     * GrandProjectActivity.kt's own getGrandProjectId(). */
    private suspend fun getGrandProjectId(): String = withContext(Dispatchers.Default) {
        python.getModule("grand_project_sync")
            .callAttr("get_or_create_default_grand_project", offlineDataRoot)
            .toString()
    }

    /** Same "first line only" convention as MainActivity.kt's/
     * GrandProjectActivity.kt's own cleanErrorMessage(). */
    private fun cleanErrorMessage(raw: String?): String {
        if (raw.isNullOrBlank()) return "Unknown Python error"
        return raw.substringBefore("\n\n").trim()
    }

    private fun setLoading(loading: Boolean) {
        binding.progressBarWideAreaSearch.visibility = if (loading) View.VISIBLE else View.GONE
        binding.buttonShowNewSearch.isEnabled = !loading
        binding.buttonShowJobs.isEnabled = !loading
    }
}
