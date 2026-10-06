package com.ariyan.geoai

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.util.TypedValue
import android.view.View
import android.widget.CheckBox
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
 * RUN MODE + IN-TILE PROGRESS: tapping "Start / Resume" in the job-detail
 * dialog first asks how to run -- a full run, or a DEM-ONLY SWEEP (no
 * Copernicus calls, no stability re-fetches; roughly 2 OpenTopography
 * calls per tile instead of up to 10). The choice is per start, passed
 * to the service as EXTRA_DEM_ONLY; nothing about it is stored on the
 * job. A third choice, "DEM-only sweep, offline library first", also sets
 * EXTRA_DEM_OFFLINE_FIRST (offline DEM library read first, cross-check
 * skipped); it is never the default -- plain DEM-only and full runs stay
 * online first. While a tile is running, the dialog also shows which stage of
 * that tile the pipeline is in (DEM / stability / NDVI / thermal /
 * optical / SAR / persistence / cross-check, with candidate counts) by
 * reading investigation_status.json -- the file
 * investigation_multi_mobile.py already writes at every stage. That file
 * is shared with single-point runs, so it is only trusted when it was
 * written AFTER the job's own status file's last write (i.e. during the
 * tile now running); otherwise the stage line is hidden rather than risk
 * showing a stale stage from some earlier run.
 *
 * PASS 2 (REFINEMENT): the job-detail dialog also has a "Refine top N"
 * button. It asks how many (3 / 5 / 10), shows a read-only preview of
 * exactly which candidates would be refined (grand_project_refinement.
 * preview_refinement_selection_json -- no network, no writes) with the
 * real API cost and any missing-credential warning, and only then starts
 * WideAreaSearchService with EXTRA_REFINE_TOP_N. The refinement writes its
 * own progress file (wide_area_refine_status_<job_id>.json); the dialog
 * shows whichever of the two status files was written most recently, with
 * a heading when it is the refinement's.
 *
 * LAND-COVER FILTER (Pass 2): the raw top candidates of a DEM sweep are
 * mostly palm groves and buildings, because the public terrain data is a
 * surface model. Before the preview, "Refine top N" therefore first makes
 * sure the job's candidates have been land-cover checked
 * (land_cover_flags.ensure_job_land_cover_json: a small public download
 * the first time, nothing after that, needs internet). Candidates flagged
 * as trees / buildings / open water are left out of Pass 2's selection.
 * NOTHING is deleted: the confirmation dialog says how many were skipped,
 * and its middle button ("Include flagged" / "Use filter") switches the
 * filter off or on for that run. If the check cannot run (offline), the
 * dialog says so and nothing is filtered. See land_cover_flags.py for the
 * rule and its honest limits.
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
 * radius_m/grid_size override per job -- the analysis window is derived
 * from each job's tile size by wide_area_search_mobile.derive_analysis_window()
 * (e.g. 1 km tiles -> 750 m radius, 144x144 grid, 10.4 m cells).
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
                    val isRefinement = intent.getBooleanExtra(WideAreaSearchService.EXTRA_IS_REFINEMENT, false)
                    val resultObj = try {
                        JSONObject(intent.getStringExtra(WideAreaSearchService.EXTRA_RESULT_JSON) ?: "{}")
                    } catch (e: Exception) {
                        JSONObject()
                    }
                    if (isRefinement && !isFinishing && !isDestroyed) {
                        // Pass 2: a dialog with the per-candidate outcome and
                        // DEM source (a toast cannot hold it).
                        AlertDialog.Builder(this@WideAreaSearchActivity)
                            .setTitle("Pass 2 refinement finished")
                            .setView(scrollableText(formatRefinementResult(resultObj)))
                            .setPositiveButton("OK", null)
                            .show()
                        if (binding.containerJobs.visibility == View.VISIBLE) loadJobsTab()
                        return
                    }
                    val finishedMessage = if (isRefinement) {
                        // Pass 2 result: counts straight from
                        // run_refinement_pass() -- "not reproduced" is a
                        // finding about the candidate, not a failure.
                        val failed = resultObj.optInt("failed", 0)
                        "Pass 2 refinement finished: ${resultObj.optInt("refined")} of " +
                            "${resultObj.optInt("attempted")} candidates refined " +
                            "(${resultObj.optInt("reproduced")} reproduced the DEM anomaly, " +
                            "${resultObj.optInt("not_reproduced")} did not)" +
                            (if (failed > 0) ", $failed failed and stay eligible for a retry." else ".")
                    } else {
                        // The job's result JSON carries a one-line "health_summary"
                        // (e.g. why tiles used the offline DEM library) -- see
                        // wide_area_search_mobile.py. Best-effort: an absent or
                        // unreadable summary just gives the plain message.
                        val healthSummary = resultObj.optString("health_summary", "")
                        if (healthSummary.isNotEmpty()) {
                            "Wide-area search job finished. $healthSummary"
                        } else {
                            "Wide-area search job finished."
                        }
                    }
                    Toast.makeText(this@WideAreaSearchActivity, finishedMessage, Toast.LENGTH_LONG).show()
                    if (binding.containerJobs.visibility == View.VISIBLE) loadJobsTab()
                }
                WideAreaSearchService.ACTION_JOB_FAILED -> {
                    val err = intent.getStringExtra(WideAreaSearchService.EXTRA_ERROR_MESSAGE) ?: "Unknown error"
                    val failedWhat = if (intent.getBooleanExtra(WideAreaSearchService.EXTRA_IS_REFINEMENT, false)) {
                        "Pass 2 refinement"
                    } else {
                        "Wide-area search job"
                    }
                    Toast.makeText(
                        this@WideAreaSearchActivity,
                        "$failedWhat failed: ${cleanErrorMessage(err)}",
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
            setTextColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_text_primary))
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
                append("#").append(i + 1).append(" ").append(row.optString("title")).append("\n")
                // Short job id (first 6 characters) so near-identical titles
                // can be told apart -- the same short form used when
                // identifying a job in a database query.
                append(" id: ").append(jobId.take(6)).append("\n")
                append(" ").append(row.optString("input_kind")).append(" ").append(row.optInt("n_tiles")).append(" tiles\n")
                append(" status: ").append(row.optString("status")).append("\n")
                append(" created: ").append(row.optString("created_at")).append("\n")
                append("(tap to view progress / start / refine)")
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
        // The in-tile stage line lives in its OWN TextView, above the
        // selectable text: it changes every few seconds while a tile runs,
        // and re-assigning the selectable text that often would clear any
        // text the user is selecting/copying.
        val stageText = TextView(this).apply {
            typeface = Typeface.MONOSPACE
            textSize = 12f
            setTextColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_text_primary))
            val pad = (16 * density).toInt()
            setPadding(pad, pad, pad, 0)
            visibility = View.GONE
        }
        // Failed-tile tools (added 2026-09-29). Buttons inside the dialog
        // body, because its three button slots (Close / Start / Refine) are
        // already taken. "Why did tiles fail?" is read-only; "Retry failed
        // tiles…" asks for confirmation first and never starts a run itself.
        val buttonWhyFailed = MaterialButton(this).apply {
            text = "Why did tiles fail?"
            setAllCaps(false)
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        val buttonRetryFailed = MaterialButton(this).apply {
            text = "Retry failed tiles…"
            setAllCaps(false)
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                leftMargin = (8 * density).toInt()
            }
        }
        val failedTileRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            val pad = (16 * density).toInt()
            setPadding(pad, pad, pad, 0)
            addView(buttonWhyFailed)
            addView(buttonRetryFailed)
        }
        // Offline DEM library (libfill-v1, 2026-10-05): shows which 1-degree
        // tiles Pass 2 needs for this job and downloads only the missing
        // ones, so Pass 2 can cut its windows from disk (0 live calls).
        val buttonDemLibrary = MaterialButton(this).apply {
            text = "DEM library…"
            setAllCaps(false)
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }
        val demLibraryRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            val pad = (16 * density).toInt()
            setPadding(pad, (8 * density).toInt(), pad, 0)
            addView(buttonDemLibrary)
        }
        // ap-v1 (2026-10-05): whole-job automation (auto_pipeline.py +
        // AutoPipelineWorker). Shows the current run if there is one.
        val buttonAutoRun = MaterialButton(this).apply {
            text = "Auto run…"
            setAllCaps(false)
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }
        val autoRunRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            val pad = (16 * density).toInt()
            setPadding(pad, (8 * density).toInt(), pad, 0)
            addView(buttonAutoRun)
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(failedTileRow)
            addView(demLibraryRow)
            addView(autoRunRow)
            addView(stageText)
            addView(progressText)
        }
        val scrollView = ScrollView(this).apply { addView(content) }

        val dialog = AlertDialog.Builder(this)
            .setTitle(title)
            .setView(scrollView)
            .setPositiveButton("Close", null)
            .setNeutralButton("Start / Resume") { _, _ -> chooseRunMode(jobId) }
            .setNegativeButton("Refine top N…") { _, _ -> chooseRefineCount(jobId) }
            .create()
        buttonWhyFailed.setOnClickListener { showTileFailures(jobId, title) }
        buttonDemLibrary.setOnClickListener { showDemLibraryPlan(jobId, title) }
        buttonAutoRun.setOnClickListener { showAutoRun(jobId, title) }
        buttonRetryFailed.setOnClickListener {
            // Closed first so that, when reopened, it re-reads the true
            // counts instead of the pre-retry numbers.
            dialog.dismiss()
            confirmRetryFailedTiles(jobId, title)
        }

        val statusFile = File(offlineDataRoot, "wide_area_search_status_$jobId.json")
        // Pass 2 writes its own file (see grand_project_refinement.py); show
        // whichever of the two was written most recently, so a refinement in
        // progress -- or the last one that finished -- is visible here.
        val refineStatusFile = File(offlineDataRoot, "wide_area_refine_status_$jobId.json")
        val pollingJob: Job = lifecycleScope.launch {
            while (isActive) {
                val showRefine = refineStatusFile.exists() &&
                    (!statusFile.exists() || refineStatusFile.lastModified() >= statusFile.lastModified())
                val activeFile = if (showRefine) refineStatusFile else statusFile
                val stageLine = readCurrentTileStageText(activeFile, if (showRefine) "candidate" else "tile") ?: ""
                if (stageText.text.toString() != stageLine) stageText.text = stageLine
                stageText.visibility = if (stageLine.isEmpty()) View.GONE else View.VISIBLE
                val liveText = readWideAreaStatusText(
                    activeFile, if (showRefine) "Pass 2 (refinement of the top candidates)" else null
                )
                if (liveText != null) {
                    // Only assign when changed: re-assigning identical text every
                    // second would clear any text the user is selecting/copying.
                    if (progressText.text.toString() != liveText) progressText.text = liveText
                } else {
                    refreshJobDetailTextFromDb(jobId, progressText)
                }
                delay(1000)
            }
        }
        dialog.setOnDismissListener { pollingJob.cancel() }
        dialog.show()
    }

    // =========================== FAILED TILES (ADDED 2026-09-29) ===========================

    /** Formats wide_area_search_mobile's grouped failure reasons. Groups are
     * formed with numbers ignored; each shows one real, unmodified stored
     * message as its example. */
    private fun formatFailureGroups(groups: JSONArray?): String = buildString {
        if (groups == null) return@buildString
        for (i in 0 until groups.length()) {
            val g = groups.optJSONObject(i) ?: continue
            val count = g.optInt("count")
            append(count).append(if (count == 1) " tile" else " tiles")
            append(" (tile ").append(g.optString("tiles")).append("):\n")
            append(g.optString("example")).append("\n\n")
        }
    }

    /** Formats summarize_tile_failures_json()'s "dem_check": the offline
     * DEM files the failed tiles need and each file's state at the moment
     * of the check (present / absent / unreadable with the OS error).
     * Empty string when there is no check to show. */
    private fun formatDemCheck(check: JSONObject?): String = buildString {
        if (check == null) return@buildString
        val files = check.optJSONArray("files")
        val noCountry = check.optString("no_country_tiles")
        val errors = check.optJSONArray("errors")
        if ((files == null || files.length() == 0) && noCountry.isEmpty() &&
            (errors == null || errors.length() == 0)) return@buildString
        append("OFFLINE DEM FILES THESE TILES NEED\n")
        append("(checked just now -- the library may have changed since the tiles ran)\n")
        val folder = check.optString("folder")
        if (folder.isNotEmpty()) append("folder: ").append(folder).append("\n")
        append("\n")
        if (files != null) {
            for (i in 0 until files.length()) {
                val f = files.optJSONObject(i) ?: continue
                append(f.optString("file")).append(" -- ").append(f.optString("status")).append("\n")
                append("   needed by tile ").append(f.optString("tiles")).append("\n")
            }
        }
        if (noCountry.isNotEmpty()) {
            append("No registered offline country covers tile ").append(noCountry).append("\n")
        }
        if (errors != null) {
            for (i in 0 until errors.length()) {
                append("Check could not be computed for ").append(errors.optString(i)).append("\n")
            }
        }
    }

    /** "Why did tiles fail?" -- read-only. Shows every FAILED tile's real
     * stored error message (wide_area_search_tile.error_message), grouped
     * by summarize_tile_failures_json(). Changes nothing. */
    private fun showTileFailures(jobId: String, title: String) {
        lifecycleScope.launch {
            try {
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("wide_area_search_mobile")
                        .callAttr("summarize_tile_failures_json", offlineDataRoot, jobId)
                        .toString()
                }
                val result = JSONObject(jsonText)
                val progress = result.optJSONObject("progress")
                val failed = result.optInt("failed")
                val total = progress?.optInt("total") ?: 0
                val body = buildString {
                    if (progress != null) {
                        append("tiles: ").append(progress.optInt("done")).append(" done, ")
                        append(failed).append(" failed, ")
                        append(progress.optInt("pending")).append(" pending, ")
                        append(total).append(" total\n\n")
                    }
                    if (failed == 0) {
                        append("No tile of this job is FAILED, so there is no failure reason to show.")
                    } else {
                        append("Why the ").append(failed).append(" FAILED tile")
                        append(if (failed == 1) "" else "s").append(" failed, grouped.\n")
                        append("Messages that differ only in numbers are grouped together; ")
                        append("each group shows one real stored message.\n\n")
                        append(formatFailureGroups(result.optJSONArray("groups")).trimEnd())
                        val demCheck = formatDemCheck(result.optJSONObject("dem_check")).trimEnd()
                        if (demCheck.isNotEmpty()) append("\n\n").append(demCheck)
                    }
                }
                AlertDialog.Builder(this@WideAreaSearchActivity)
                    .setTitle("Why did tiles fail? -- $title")
                    .setView(scrollableText(body))
                    .setPositiveButton("Close", null)
                    .show()
            } catch (e: PyException) {
                Toast.makeText(
                    this@WideAreaSearchActivity,
                    "Could not read tile failures: ${cleanErrorMessage(e.message)}",
                    Toast.LENGTH_LONG
                ).show()
            }
        }
    }

    /** "Retry failed tiles…" -- the explicit, human-requested retry.
     * Refuses while any job is running (a running job only works through
     * the PENDING list it read at start, so tiles reset mid-run would be
     * left PENDING and misreported). Reads the current failures, asks for
     * confirmation, then calls retry_failed_tiles_json(). Never starts a
     * run: afterwards it offers Start / Resume, which goes through the
     * usual run-mode choice. */
    private fun confirmRetryFailedTiles(jobId: String, title: String) {
        if (WideAreaSearchService.isRunning) {
            Toast.makeText(this, "A wide-area search job is running -- let it finish before retrying failed tiles.", Toast.LENGTH_LONG).show()
            return
        }
        lifecycleScope.launch {
            try {
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("wide_area_search_mobile")
                        .callAttr("summarize_tile_failures_json", offlineDataRoot, jobId)
                        .toString()
                }
                val result = JSONObject(jsonText)
                val failed = result.optInt("failed")
                if (failed == 0) {
                    AlertDialog.Builder(this@WideAreaSearchActivity)
                        .setTitle("Retry failed tiles -- $title")
                        .setMessage("No tile of this job is FAILED. Nothing to retry.")
                        .setPositiveButton("OK", null)
                        .show()
                    return@launch
                }
                val body = buildString {
                    append("Put ").append(failed).append(" FAILED tile")
                    append(if (failed == 1) "" else "s").append(" back to PENDING?\n\n")
                    append("- Nothing runs until you tap Start / Resume.\n")
                    append("- DONE tiles and their candidates are not touched; the job keeps its id.\n")
                    append("- The failure reasons below are saved in the project timeline before ")
                    append("they are cleared from the tiles.\n")
                    append("- If the cause is not fixed first, the same tiles will simply fail again.\n\n")
                    append(formatFailureGroups(result.optJSONArray("groups")).trimEnd())
                    val demCheck = formatDemCheck(result.optJSONObject("dem_check")).trimEnd()
                    if (demCheck.isNotEmpty()) append("\n\n").append(demCheck)
                }
                AlertDialog.Builder(this@WideAreaSearchActivity)
                    .setTitle("Retry failed tiles -- $title")
                    .setView(scrollableText(body))
                    .setPositiveButton("Retry $failed") { _, _ -> retryFailedTiles(jobId, title) }
                    .setNegativeButton("Cancel", null)
                    .show()
            } catch (e: PyException) {
                Toast.makeText(
                    this@WideAreaSearchActivity,
                    "Could not read tile failures: ${cleanErrorMessage(e.message)}",
                    Toast.LENGTH_LONG
                ).show()
            }
        }
    }

    /** Read-only: which library tiles this job's bbox needs, per DEM
     * type, which are present (with SHA-256) and which are missing, plus
     * the rolling 24 h live-call budget. Offers the download only when
     * something is missing. */
    private fun showDemLibraryPlan(jobId: String, title: String) {
        lifecycleScope.launch {
            try {
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("dem_library_mobile")
                        .callAttr("dem_library_plan_json", offlineDataRoot, jobId)
                        .toString()
                }
                val plan = JSONObject(jsonText)
                if (plan.has("error")) {
                    Toast.makeText(this@WideAreaSearchActivity, "DEM library: ${plan.optString("error")}", Toast.LENGTH_LONG).show()
                    return@launch
                }
                val missing = plan.optInt("missing_total")
                val budget = plan.optInt("budget_left_24h")
                val nDemTypes = plan.optJSONObject("demtypes")?.length() ?: 0
                val body = buildString {
                    append(formatDemLibraryPlan(plan))
                    append("\nLive-call budget left (rolling 24 h): ").append(budget)
                    append(" of ").append(plan.optInt("daily_cap")).append("\n\n")
                    if (missing == 0) {
                        append("All tiles are in the library. Pass 2 will cut its DEM windows from disk.")
                    } else {
                        append("Download uses ").append(missing).append(" live call")
                        append(if (missing == 1) "" else "s")
                        append(" (one per tile) plus up to ").append(nDemTypes)
                        append(" for the spot-check (one small live window per DEM type, compared ")
                        append("cell-by-cell with the library). Present tiles are never re-downloaded.\n\n")
                        append("Keep this screen open until it finishes; each tile can take a minute or two.")
                    }
                }
                val b = AlertDialog.Builder(this@WideAreaSearchActivity)
                    .setTitle("DEM library -- $title")
                    .setView(scrollableText(body))
                    .setPositiveButton("Close", null)
                if (missing > 0 && budget > 0) {
                    b.setNegativeButton("Download $missing") { _, _ -> fillDemLibrary(jobId, title) }
                }
                b.show()
            } catch (e: PyException) {
                Toast.makeText(this@WideAreaSearchActivity, "DEM library: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun formatDemLibraryPlan(plan: JSONObject): String = buildString {
        val dts = plan.optJSONObject("demtypes") ?: return@buildString
        val keys = dts.keys()
        while (keys.hasNext()) {
            val dt = keys.next()
            val o = dts.getJSONObject(dt)
            append(dt).append(": ").append(o.optInt("needed")).append(" tile(s) needed\n")
            val present = o.optJSONArray("present")
            if (present != null) for (i in 0 until present.length()) {
                val t = present.getJSONObject(i)
                append("  ✓ ").append(t.optString("tile")).append("  sha ")
                append(t.optString("sha256").take(12)).append("…\n")
            }
            val miss = o.optJSONArray("missing")
            if (miss != null) for (i in 0 until miss.length()) {
                append("  ✗ ").append(miss.optString(i)).append("  missing\n")
            }
        }
    }

    private fun fillDemLibrary(jobId: String, title: String) {
        val progress = AlertDialog.Builder(this)
            .setTitle("DEM library -- $title")
            .setMessage("Downloading missing tiles… keep this screen open.")
            .setCancelable(false)
            .show()
        lifecycleScope.launch {
            try {
                val jsonText = withContext(Dispatchers.IO) {
                    python.getModule("dem_library_mobile").callAttr(
                        "fill_dem_library_json", offlineDataRoot, jobId,
                        credentialStore.openTopographyApiKey, 10, true
                    ).toString()
                }
                progress.dismiss()
                val r = JSONObject(jsonText)
                val body = buildString {
                    if (r.has("error")) {
                        append("Error: ").append(r.optString("error"))
                        return@buildString
                    }
                    val spotCalls = (0 until (r.optJSONArray("spot_checks")?.length() ?: 0)).count {
                        val c = r.getJSONArray("spot_checks").getJSONObject(it)
                        !c.has("skipped")
                    }
                    append("Live calls used: ").append(r.optInt("calls") + spotCalls)
                    append(" (").append(r.optInt("calls")).append(" tile, ")
                    append(spotCalls).append(" spot-check)\n")
                    val dl = r.optJSONArray("downloaded")
                    append("Downloaded: ").append(dl?.length() ?: 0).append("\n")
                    if (dl != null) for (i in 0 until dl.length()) {
                        val t = dl.getJSONObject(i)
                        append("  ").append(t.optString("demtype")).append("/").append(t.optString("tile"))
                        append("  ").append(t.optLong("bytes") / 1024).append(" KB  sha ")
                        append(t.optString("sha256").take(12)).append("…\n")
                    }
                    val failed = r.optJSONArray("failed")
                    if (failed != null && failed.length() > 0) {
                        append("Failed:\n")
                        for (i in 0 until failed.length()) {
                            val f = failed.getJSONObject(i)
                            append("  ").append(f.optString("tile")).append(": ").append(f.optString("error")).append("\n")
                        }
                    }
                    if (!r.isNull("stopped")) {
                        append("Stopped early: ").append(r.optString("stopped")).append("\n")
                    }
                    val checks = r.optJSONArray("spot_checks")
                    if (checks != null && checks.length() > 0) {
                        append("\nSpot-check (live window vs library):\n")
                        for (i in 0 until checks.length()) {
                            val c = checks.getJSONObject(i)
                            append("  ").append(c.optString("demtype")).append(": ")
                            when {
                                c.has("skipped") -> append("skipped -- ").append(c.optString("skipped"))
                                c.has("error") -> append("ERROR -- ").append(c.optString("error"))
                                c.optBoolean("ok") -> append("IDENTICAL (0 mismatches)")
                                else -> append("DIFFERENT -- mismatches ").append(c.opt("mismatches"))
                                    .append(", origin match ").append(c.optBoolean("origin_match"))
                            }
                            append("\n")
                        }
                    }
                    val after = r.optJSONObject("plan_after")
                    if (after != null) {
                        append("\n").append(formatDemLibraryPlan(after))
                        append("\nBudget left (24 h): ").append(after.optInt("budget_left_24h"))
                    }
                    append("\nTime: ").append(r.optDouble("seconds")).append(" s")
                }
                AlertDialog.Builder(this@WideAreaSearchActivity)
                    .setTitle("DEM library -- $title")
                    .setView(scrollableText(body))
                    .setPositiveButton("Close", null)
                    .show()
            } catch (e: PyException) {
                progress.dismiss()
                Toast.makeText(this@WideAreaSearchActivity, "DEM library download failed: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun autoPipeline() = python.getModule("auto_pipeline")

    /** ap-v1: shows the newest automatic run of this job (with its 10
     * steps) or offers to start one. */
    private fun showAutoRun(jobId: String, title: String) {
        lifecycleScope.launch {
            try {
                val runs = JSONArray(withContext(Dispatchers.Default) {
                    autoPipeline().callAttr("list_auto_runs_json", offlineDataRoot, jobId).toString()
                }.let { if (it.trimStart().startsWith("{")) "[]" else it })
                val latest = if (runs.length() > 0) runs.getJSONObject(0) else null
                if (latest == null) { offerAutoRunStart(jobId, title); return@launch }
                val runId = latest.getString("run_id")
                val st = JSONObject(withContext(Dispatchers.Default) {
                    autoPipeline().callAttr("auto_run_status_json", offlineDataRoot, runId).toString()
                })
                val state = st.optString("state")
                val body = buildString {
                    append("Run ").append(runId.take(8)).append(" -- ").append(state)
                    if (st.optInt("paused_for_s") > 0) {
                        append(" (paused, resumes in ~").append(st.optInt("paused_for_s") / 60).append(" min)")
                    }
                    append("\nStarted ").append(st.optString("created_at").take(19)).append(" UTC\n\n")
                    val steps = st.optJSONArray("steps") ?: JSONArray()
                    for (i in 0 until steps.length()) {
                        val s = steps.getJSONObject(i)
                        val mark = when (s.optString("status")) {
                            "DONE" -> "✓"; "SKIPPED" -> "–"; "PAUSED" -> "⏸"; "FAILED" -> "✗"; else -> "·"
                        }
                        append(mark).append(" ").append(i + 1).append(". ").append(s.optString("step"))
                        append("  ").append(s.optString("status")).append("\n")
                        val d = s.optJSONObject("detail")
                        if (d != null && d.length() > 0) append(autoStepLine(s.optString("step"), d))
                    }
                }
                val b = AlertDialog.Builder(this@WideAreaSearchActivity)
                    .setTitle("Auto run -- $title")
                    .setView(scrollableText(body))
                    .setPositiveButton("Close", null)
                if (state == "RUNNING") {
                    b.setNegativeButton("Stop run") { _, _ -> confirmCancelAutoRun(runId) }
                    b.setNeutralButton("Resume now") { _, _ ->
                        AutoPipelineWorker.enqueue(this@WideAreaSearchActivity, runId, offlineDataRoot)
                        Toast.makeText(this@WideAreaSearchActivity, "Automatic run resumed.", Toast.LENGTH_SHORT).show()
                    }
                } else {
                    b.setNeutralButton("New run…") { _, _ -> offerAutoRunStart(jobId, title) }
                }
                b.show()
            } catch (e: PyException) {
                Toast.makeText(this@WideAreaSearchActivity, "Auto run: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun autoStepLine(step: String, d: JSONObject): String = buildString {
        fun line(t: String) { append("     ").append(t).append("\n") }
        when {
            d.has("reason") -> line(d.optString("reason"))
            d.has("error") -> line(d.optString("error").take(160))
            d.has("skipped") -> line(d.optString("skipped"))
            step == "pass2" && d.has("refined_total") -> {
                line("refined ${d.optInt("refined_total")}, failed ${d.optInt("failed_total")}, " +
                     "strong left ${d.optInt("remaining_strong")}")
                // display fix 2026-10-06: where the DEM windows came from
                if (d.has("library_cuts_total")) {
                    line("DEM: ${d.optInt("library_cuts_total")} cut from library, " +
                         "${d.optInt("live_dem_calls_total")} live call(s)")
                    val extra = mutableListOf<String>()
                    if (d.optInt("window_cache_hits_total") > 0) extra.add("${d.optInt("window_cache_hits_total")} from saved windows")
                    if (d.optInt("tiles_promoted_total") > 0) extra.add("${d.optInt("tiles_promoted_total")} tile(s) added to library")
                    if (d.optInt("windows_saved_total") > 0) extra.add("${d.optInt("windows_saved_total")} window(s) saved")
                    if (extra.isNotEmpty()) line("(" + extra.joinToString(", ") + ")")
                }
                val errs = d.optJSONArray("errors")
                if (errs != null) for (i in 0 until errs.length()) {
                    val e = errs.optJSONObject(i) ?: continue
                    line("✗ ${e.optString("candidate")}: ${e.optString("error").take(120)}")
                }
            }
            step == "provenance" -> line("${d.optString("verdict")} (${d.optInt("candidates_verified")}/${d.optInt("candidates")})")
            step == "trust" -> {
                line(d.optString("decision") + (if (d.has("note")) " -- " + d.optString("note") else ""))
                val rs = d.optJSONArray("reasons")
                if (rs != null) for (i in 0 until rs.length()) line("• " + rs.optString(i))
            }
            step == "report" -> line("${d.optInt("rows_shown")} rows -> " + d.optString("html_path").substringAfterLast('/'))
            d.has("note") -> line(d.optString("note"))
        }
    }

    private fun offerAutoRunStart(jobId: String, title: String) {
        val body = "Runs the whole job automatically, in the background, in this order:\n\n" +
            "1. DEM library (download the 1-degree tiles, spot-check)\n" +
            "2. Pass 1 sweep: DEM-only, offline-first, COP30\n" +
            "3. Land-cover flags\n4. Terrain labels\n5. Auto-review\n" +
            "6. Pass 2 on every calib-v1 strong, non-rejected candidate, strongest first " +
            "(library-first; max 40 live DEM calls per rolling 24 h; up to 50 candidates)\n" +
            "7. Auto-review again\n8. Provenance check\n" +
            "9. Automatic trust: TRUSTED only if provenance VERIFIED, 0 failed tiles, no offline-guard " +
            "pause, no Pass 2 failures and identical spot-checks. A trust mark you set is never changed; " +
            "nothing is ever marked Corrupted.\n" +
            "10. Report (top 50, rounded coordinates)\n\n" +
            "Quota, throttling and no-internet pause the run and it resumes by itself. It survives " +
            "the app being closed and the phone restarting. Every step is logged."
        AlertDialog.Builder(this)
            .setTitle("Auto run -- $title")
            .setView(scrollableText(body))
            .setPositiveButton("Start automatic run") { _, _ -> startAutoRun(jobId) }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun startAutoRun(jobId: String) {
        lifecycleScope.launch {
            try {
                val r = JSONObject(withContext(Dispatchers.Default) {
                    autoPipeline().callAttr("start_auto_run_json", offlineDataRoot, jobId, "").toString()
                })
                if (r.has("error")) {
                    Toast.makeText(this@WideAreaSearchActivity, "Auto run: ${r.optString("error")}", Toast.LENGTH_LONG).show()
                    return@launch
                }
                val runId = r.getString("run_id")
                AutoPipelineWorker.enqueue(this@WideAreaSearchActivity, runId, offlineDataRoot)
                Toast.makeText(this@WideAreaSearchActivity,
                    "Automatic run ${runId.take(8)} started. Tap Auto run… to follow it.", Toast.LENGTH_LONG).show()
            } catch (e: PyException) {
                Toast.makeText(this@WideAreaSearchActivity, "Auto run: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun confirmCancelAutoRun(runId: String) {
        AlertDialog.Builder(this)
            .setTitle("Stop automatic run ${runId.take(8)}?")
            .setMessage("Steps already done stay done and recorded. The run cannot be resumed; you can start a new one later (it will skip finished work).")
            .setPositiveButton("Stop run") { _, _ ->
                AutoPipelineWorker.cancel(this, runId)
                lifecycleScope.launch {
                    withContext(Dispatchers.Default) {
                        autoPipeline().callAttr("cancel_auto_run_json", offlineDataRoot, runId, "stopped by user").toString()
                    }
                    Toast.makeText(this@WideAreaSearchActivity, "Automatic run stopped.", Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("Keep running", null)
            .show()
    }

    private fun retryFailedTiles(jobId: String, title: String) {
        // Checked again: a job could have been started while the
        // confirmation dialog was open.
        if (WideAreaSearchService.isRunning) {
            Toast.makeText(this, "A wide-area search job is running -- let it finish before retrying failed tiles.", Toast.LENGTH_LONG).show()
            return
        }
        lifecycleScope.launch {
            try {
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("wide_area_search_mobile")
                        .callAttr("retry_failed_tiles_json", offlineDataRoot, jobId)
                        .toString()
                }
                val result = JSONObject(jsonText)
                val reset = result.optInt("reset")
                val progress = result.optJSONObject("progress")
                val body = buildString {
                    append(reset).append(" tile").append(if (reset == 1) "" else "s")
                    append(" put back to PENDING.\n\n")
                    if (progress != null) {
                        append("tiles: ").append(progress.optInt("done")).append(" done, ")
                        append(progress.optInt("failed")).append(" failed, ")
                        append(progress.optInt("pending")).append(" pending, ")
                        append(progress.optInt("total")).append(" total\n\n")
                    }
                    append("Tap Start / Resume to run them.")
                }
                AlertDialog.Builder(this@WideAreaSearchActivity)
                    .setTitle("Retry failed tiles -- $title")
                    .setMessage(body)
                    .setPositiveButton("Close", null)
                    .setNeutralButton("Start / Resume") { _, _ -> chooseRunMode(jobId) }
                    .show()
                loadJobsTab()
            } catch (e: PyException) {
                Toast.makeText(
                    this@WideAreaSearchActivity,
                    "Retry failed: ${cleanErrorMessage(e.message)}",
                    Toast.LENGTH_LONG
                ).show()
            }
        }
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
     * one. Also shows the optional "health" text the job writes -- the
     * run-health report (why tiles used the offline DEM library, which
     * satellite checks were unavailable, live rate-limit/quota pause
     * state) -- and, while running, the time of the last update, so a
     * slow tile (rate-limit retry waits can take minutes) is
     * distinguishable from a job that has stopped. */
    private fun readWideAreaStatusText(file: File, heading: String? = null): String? {
        if (!file.exists()) return null
        return try {
            val obj = JSONObject(file.readText())
            val phase = obj.optString("phase", "?")
            val health = obj.optString("health", "")
            buildString {
                if (heading != null) append(heading).append("\n")
                append("phase: ").append(phase).append("\n")
                append("done: ").append(obj.optInt("done", 0))
                append(" / ").append(obj.optInt("total", 0)).append("\n")
                append(obj.optString("detail", ""))
                if (phase == "running") {
                    // Absolute time (not "N s ago") so the text only changes when
                    // the job writes a new update, which keeps selection/copy usable.
                    val updated = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.US)
                        .format(java.util.Date(file.lastModified()))
                    append("\n(last update ").append(updated).append(")")
                }
                if (health.isNotEmpty()) {
                    append("\n\n")
                    append(health)
                }
            }
        } catch (e: Exception) {
            null
        }
    }

    /** One line describing which stage of the tile that is running RIGHT
     * NOW the pipeline is in, e.g. "in this tile: thermal checks, 12 of 26
     * candidates done (updated 10:42:17)" -- read from
     * investigation_status.json, which investigation_multi_mobile.py's own
     * _write_investigation_status() writes at every stage (phase / done /
     * total). Returns null (line hidden) unless ALL of these hold: the job
     * file says "running"; investigation_status.json exists; it was last
     * written at or after the job file's last write (the job file is
     * rewritten when a tile starts and when it ends, so this means "written
     * during the current tile", and rules out a stale file left by a
     * single-point run or an earlier tile); and its phase is not "done".
     * Any read/parse problem also gives null. The candidate counts are only
     * meaningful for the per-candidate stages; the DEM stage is shown
     * without a count. */
    private fun readCurrentTileStageText(jobStatusFile: File, unit: String = "tile"): String? {
        try {
            if (!jobStatusFile.exists()) return null
            val jobObj = JSONObject(jobStatusFile.readText())
            if (jobObj.optString("phase", "") != "running") return null

            val stageFile = File(offlineDataRoot, "investigation_status.json")
            if (!stageFile.exists()) return null
            if (stageFile.lastModified() < jobStatusFile.lastModified()) return null

            val obj = JSONObject(stageFile.readText())
            val phase = obj.optString("phase", "")
            if (phase.isEmpty() || phase == "done") return null
            val done = obj.optInt("done", 0)
            val total = obj.optInt("total", 0)

            val label = when (phase) {
                "dem" -> "reading the DEM"
                "stability" -> "stability re-checks"
                "ndvi" -> "NDVI checks"
                "thermal" -> "thermal checks"
                "optical" -> "optical checks"
                "sar" -> "SAR checks"
                "persistence" -> "temporal persistence checks"
                "dem_cross_check" -> "second-DEM cross-check"
                else -> phase
            }
            val updated = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.US)
                .format(java.util.Date(stageFile.lastModified()))
            return if (phase == "dem") {
                "in this $unit: $label (updated $updated)"
            } else {
                "in this $unit: $label, $done of $total candidates done (updated $updated)"
            }
        } catch (e: Exception) {
            return null
        }
    }

    /** Asks how to run before starting: a full run, or a DEM-only sweep.
     * Refuses up front (same rule and same Toast as startJob()) if a job is
     * already running, so the user is not asked a question whose answer
     * cannot be used. */
    private fun chooseRunMode(jobId: String) {
        if (WideAreaSearchService.isRunning) {
            Toast.makeText(this, "A wide-area search job is already running -- let it finish first.", Toast.LENGTH_LONG).show()
            return
        }
        val options = arrayOf(
            "Full run: DEM + all satellite checks",
            "DEM-only sweep: skips satellite checks and stability re-fetches " +
                "(about 2 OpenTopography calls per tile instead of up to 10, " +
                "and no Copernicus calls)",
            "DEM-only sweep, offline library first: as above, but reads elevation " +
                "from the offline library first (live OpenTopography only where the " +
                "library has no coverage) and skips the second-DEM cross-check -- " +
                "saves the OpenTopography quota",
        )
        AlertDialog.Builder(this)
            .setTitle("How should this run?")
            .setItems(options) { _, which ->
                startJob(jobId, demOnly = (which >= 1), demOfflineFirst = (which == 2))
            }
            .setNegativeButton("Cancel", null)
            .show()
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
    private fun startJob(jobId: String, demOnly: Boolean, demOfflineFirst: Boolean = false) {
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
            putExtra(WideAreaSearchService.EXTRA_DEM_ONLY, demOnly)
            putExtra(WideAreaSearchService.EXTRA_DEM_OFFLINE_FIRST, demOnly && demOfflineFirst)
        }
        ContextCompat.startForegroundService(this, serviceIntent)
        Toast.makeText(
            this,
            if (demOnly && demOfflineFirst) "Wide-area search (DEM-only sweep, offline library first) started in the background."
            else if (demOnly) "Wide-area search (DEM-only sweep) started in the background."
            else "Wide-area search started in the background.",
            Toast.LENGTH_LONG
        ).show()
    }

    // =========================== PASS 2 (REFINEMENT) ===========================

    /** First step of "Refine top N": how many candidates. Refuses up front
     * if a job is already running (the service allows one at a time, and
     * a refinement shares the same OpenTopography quota and Copernicus
     * token). The counts are deliberately small: each refinement is a full
     * multi-source investigation, not a cheap DEM read. */
    private fun chooseRefineCount(jobId: String) {
        if (WideAreaSearchService.isRunning) {
            Toast.makeText(this, "A wide-area search job is already running -- let it finish first.", Toast.LENGTH_LONG).show()
            return
        }
        val counts = intArrayOf(3, 5, 10)
        val labels = arrayOf(
            "Top 3 (a good first try)",
            "Top 5",
            "Top 10 (uses the most API budget)",
            "Specific candidates (enter IDs)…",
        )
        AlertDialog.Builder(this)
            .setTitle("Refine how many top candidates?")
            .setItems(labels) { _, which ->
                if (which < counts.size) previewRefinement(jobId, counts[which], true)
                else askCandidateIds(jobId)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /** Second step: the preview of exactly which candidates a Pass 2 of
     * this size would refine, so the user confirms real API spend against
     * real candidates rather than a number.
     *
     * LAND-COVER FILTER: when skipFlagged is true (the normal path), this
     * FIRST makes sure every candidate of the job has been land-cover
     * checked (land_cover_flags.ensure_job_land_cover_json: one small
     * public download the first time, nothing after that; it writes only
     * the app's own candidate_land_cover table). A problem there (offline,
     * no tile) never blocks the refinement: it is shown in the
     * confirmation and the unchecked candidates are simply not filtered.
     * The preview itself is then read-only. */
    private fun previewRefinement(jobId: String, n: Int, skipFlagged: Boolean) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                var landCoverNote: String? = null
                if (skipFlagged) {
                    Toast.makeText(
                        this@WideAreaSearchActivity,
                        "Checking land cover (needs internet, can take a little while)…",
                        Toast.LENGTH_SHORT
                    ).show()
                    landCoverNote = withContext(Dispatchers.Default) {
                        try {
                            val lc = JSONObject(
                                python.getModule("land_cover_flags")
                                    .callAttr("ensure_job_land_cover_json", offlineDataRoot, jobId)
                                    .toString()
                            )
                            // "problem" is ABSENT (not null) when all went well.
                            if (lc.has("problem")) lc.getString("problem") else null
                        } catch (e: Exception) {
                            "The land-cover check failed: ${cleanErrorMessage(e.message)}"
                        }
                    }
                }
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("grand_project_refinement")
                        .callAttr(
                            "preview_refinement_selection_json", offlineDataRoot, jobId, n,
                            Kwarg("skip_flagged", skipFlagged)
                        )
                        .toString()
                }
                showRefinementConfirmation(jobId, n, JSONObject(jsonText), skipFlagged, landCoverNote)
            } catch (e: PyException) {
                Toast.makeText(this@WideAreaSearchActivity, "Could not preview the refinement: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            } catch (e: org.json.JSONException) {
                Toast.makeText(this@WideAreaSearchActivity, "Could not read the refinement preview: ${e.message}", Toast.LENGTH_LONG).show()
            } finally {
                setLoading(false)
            }
        }
    }

    /** Third step: the confirmation. Lists the real selected candidates,
     * the real cost, what the land-cover filter skipped, and -- only when
     * they apply -- the two missing-credential consequences (both real: no
     * OpenTopography key means the live DEM path cannot run; no Copernicus
     * credentials means the satellite checks are recorded as "not run",
     * never fabricated). The middle button flips the land-cover filter for
     * this run and re-previews. */
    private fun showRefinementConfirmation(
        jobId: String, n: Int, preview: JSONObject,
        skipFlagged: Boolean, landCoverNote: String?
    ) {
        val selected = preview.optJSONArray("selected") ?: JSONArray()
        val jobCandidates = preview.optInt("job_candidates", 0)
        val alreadyRefined = preview.optInt("already_refined", 0)
        val skippedDuplicates = preview.optInt("skipped_near_duplicates", 0)
        val skippedFlagged = preview.optInt("skipped_flagged", 0)
        val landCoverUnchecked = preview.optInt("land_cover_unchecked", 0)
        val byReason = preview.optJSONObject("skipped_flagged_by_reason")
        val flaggedTreesOrBuildings = byReason?.optInt("tree_or_built", 0) ?: 0
        val flaggedWater = byReason?.optInt("water", 0) ?: 0

        if (selected.length() == 0) {
            val flaggedText = if (skipFlagged && skippedFlagged > 0) {
                " $skippedFlagged skipped by the land-cover filter."
            } else {
                ""
            }
            Toast.makeText(
                this,
                "Nothing to refine: this job has $jobCandidates candidates, " +
                    "$alreadyRefined already refined, $skippedDuplicates skipped as near-duplicates.$flaggedText",
                Toast.LENGTH_LONG
            ).show()
            return
        }

        val message = buildString {
            append("Pass 2 will refine ").append(selected.length())
            append(" of this job's ").append(jobCandidates).append(" Pass 1 candidates, highest DEM z-score first.\n")
            if (selected.length() < n) {
                append("(You asked for ").append(n).append("; only ").append(selected.length()).append(" are eligible.)\n")
            }
            if (alreadyRefined > 0) append(alreadyRefined).append(" already refined earlier.\n")
            if (skippedDuplicates > 0) append(skippedDuplicates).append(" skipped as near-duplicates of another candidate.\n")
            if (skipFlagged && skippedFlagged > 0) {
                append(skippedFlagged).append(" skipped by the land-cover filter (trees or buildings: ")
                append(flaggedTreesOrBuildings).append(", open water: ").append(flaggedWater)
                append("). They stay in the database; nothing is deleted.\n")
            }
            if (skipFlagged && landCoverUnchecked > 0) {
                append(landCoverUnchecked).append(" candidates could not be land-cover checked, so they are NOT filtered.\n")
            }
            if (skipFlagged && !landCoverNote.isNullOrBlank()) {
                append("Land-cover note: ").append(landCoverNote).append("\n")
            }
            if (!skipFlagged) {
                append("The land-cover filter is OFF for this run: trees, buildings and water candidates can be included.\n")
            }
            append("\n")
            for (i in 0 until selected.length()) {
                val c = selected.getJSONObject(i)
                val scoreText = if (c.isNull("score")) "n/a"
                else String.format(java.util.Locale.US, "%+.2f", c.optDouble("score"))
                append(i + 1).append(". ")
                append(String.format(java.util.Locale.US, "%.5f, %.5f", c.optDouble("lat"), c.optDouble("lon")))
                append(" z=").append(scoreText)
                append(" (").append(reliefText(c)).append(")\n")
            }
            append("\nz = how unusual the bump/dip is; m = its peak height or depth ")
            append("against the smoothed ground (from Pass 1).\n")
            append("\nEach refinement makes about 2 live OpenTopography calls, up to about 8 ")
            append("stability re-fetches, and Copernicus calls -- not cheap while the daily ")
            append("OpenTopography cap applies.")
            if (credentialStore.openTopographyApiKey.isNullOrBlank()) {
                append("\n\nNo OpenTopography API key is saved on this device: refinements ")
                append("outside the offline DEM library's coverage will fail.")
            }
            if (credentialStore.copernicusClientId.isNullOrBlank() || credentialStore.copernicusClientSecret.isNullOrBlank()) {
                append("\n\nNo Copernicus credentials are saved: satellite checks will be ")
                append("recorded as not run.")
            }
        }

        val builder = AlertDialog.Builder(this)
            .setTitle("Refine ${selected.length()} candidate(s)?")
            .setMessage(message)
            .setPositiveButton("Start refinement") { _, _ -> startRefinement(jobId, selected.length(), skipFlagged) }
            .setNegativeButton("Cancel", null)
        if (skipFlagged) {
            builder.setNeutralButton("Include flagged") { _, _ -> previewRefinement(jobId, n, false) }
        } else {
            builder.setNeutralButton("Use filter") { _, _ -> previewRefinement(jobId, n, true) }
        }
        builder.show()
    }

    /** Starts WideAreaSearchService in Pass 2 mode (EXTRA_REFINE_TOP_N)
     * with this device's real saved credentials, same as startJob(). Safe to
     * run again: refined candidates carry a marker row and are skipped;
     * failed ones stay eligible. skipFlagged is passed through as
     * EXTRA_REFINE_SKIP_FLAGGED so the run selects exactly what the
     * confirmation showed. */
    private fun startRefinement(jobId: String, n: Int, skipFlagged: Boolean) {
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
            putExtra(WideAreaSearchService.EXTRA_REFINE_TOP_N, n)
            putExtra(WideAreaSearchService.EXTRA_REFINE_SKIP_FLAGGED, skipFlagged)
        }
        ContextCompat.startForegroundService(this, serviceIntent)
        Toast.makeText(this, "Pass 2 refinement of $n candidate(s) started in the background.", Toast.LENGTH_LONG).show()
    }

    // ====================== PASS 2: SELECTED CANDIDATES ======================

    /** "Refine selected candidates": the user types candidate ids (or unique
     * prefixes of at least 6 characters, e.g. the 8-character ids used in
     * notes), separated by spaces, commas or new lines. Python resolves them
     * against THIS job only (grand_project_refinement.resolve_candidate_refs),
     * so an id from another job is refused, never refined. Repeats of
     * already-refined candidates are allowed here on purpose (live re-checks).
     * "Require live DEM" (default on) discards and stops rather than record
     * an offline-library refinement. */
    private fun askCandidateIds(jobId: String, prefill: String = "", requireLivePrefill: Boolean = true) {
        if (WideAreaSearchService.isRunning) {
            Toast.makeText(this, "A wide-area search job is already running -- let it finish first.", Toast.LENGTH_LONG).show()
            return
        }
        val density = resources.displayMetrics.density
        val pad = (20 * density).toInt()
        val input = EditText(this).apply {
            hint = "e.g. eaef8a95 55f6d053 a3bf3758"
            setText(prefill)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE or
                InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            minLines = 2
            typeface = Typeface.MONOSPACE
        }
        val requireLive = CheckBox(this).apply {
            text = "Require live-quality DEM (the verified 1-degree DEM library counts; stop instead of falling back to cached/synthetic data)"
            isChecked = requireLivePrefill
        }
        val note = TextView(this).apply {
            text = "Only candidates of this job are accepted. Candidates refined before " +
                "can be refined again; earlier results are kept."
            textSize = 12f
            setTextColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_text_secondary))
        }
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad / 2, pad, 0)
            addView(input)
            addView(requireLive)
            addView(note)
        }
        AlertDialog.Builder(this)
            .setTitle("Refine selected candidates")
            .setView(layout)
            .setPositiveButton("Preview") { _, _ ->
                val text = input.text?.toString().orEmpty()
                if (text.isBlank()) {
                    Toast.makeText(this, "No candidate ids entered.", Toast.LENGTH_SHORT).show()
                } else {
                    previewSelectedRefinement(jobId, text, requireLive.isChecked)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /** Read-only preview (grand_project_refinement.
     * preview_selected_refinement_json): the resolved candidates, each with
     * its earlier refinements and their DEM source, plus every reference
     * that could not be used and why. */
    private fun previewSelectedRefinement(jobId: String, refsText: String, requireLive: Boolean) {
        setLoading(true)
        lifecycleScope.launch {
            try {
                val jsonText = withContext(Dispatchers.Default) {
                    python.getModule("grand_project_refinement")
                        .callAttr("preview_selected_refinement_json", offlineDataRoot, jobId, refsText)
                        .toString()
                }
                showSelectedRefinementConfirmation(jobId, refsText, requireLive, JSONObject(jsonText))
            } catch (e: PyException) {
                Toast.makeText(this@WideAreaSearchActivity, "Could not preview the refinement: ${cleanErrorMessage(e.message)}", Toast.LENGTH_LONG).show()
            } catch (e: org.json.JSONException) {
                Toast.makeText(this@WideAreaSearchActivity, "Could not read the refinement preview: ${e.message}", Toast.LENGTH_LONG).show()
            } finally {
                setLoading(false)
            }
        }
    }

    private fun showSelectedRefinementConfirmation(
        jobId: String, refsText: String, requireLive: Boolean, preview: JSONObject
    ) {
        val selected = preview.optJSONArray("selected") ?: JSONArray()
        val problems = preview.optJSONArray("problems") ?: JSONArray()
        val ids = ArrayList<String>()
        val message = buildString {
            if (selected.length() == 0) {
                append("None of the entered ids can be refined.\n")
            } else {
                append("Pass 2 will refine these ").append(selected.length()).append(" candidate(s), in this order:\n\n")
            }
            for (i in 0 until selected.length()) {
                val c = selected.getJSONObject(i)
                val id = c.optString("candidate_id")
                ids.add(id)
                val scoreText = if (c.isNull("score")) "n/a"
                else String.format(java.util.Locale.US, "%+.2f", c.optDouble("score"))
                append(i + 1).append(". ").append(id.take(8)).append(" z=").append(scoreText)
                append(" (").append(reliefText(c)).append(")")
                if (!c.isNull("confidence_band")) append(" ").append(c.optString("confidence_band"))
                append("\n ")
                append(String.format(java.util.Locale.US, "%.5f, %.5f", c.optDouble("lat"), c.optDouble("lon")))
                append("\n")
                val history = c.optJSONArray("previous_refinements") ?: JSONArray()
                if (history.length() == 0) {
                    append(" never refined\n")
                } else {
                    for (h in 0 until history.length()) {
                        val e = history.getJSONObject(h)
                        append(" earlier: ")
                        append(if (e.optBoolean("reproduced", false)) "reproduced" else "not reproduced")
                        append(", DEM ").append(demSourceLabel(e.optString("dem_source")))
                        append("\n")
                    }
                }
            }
            if (problems.length() > 0) {
                append("\nNot used:\n")
                for (i in 0 until problems.length()) {
                    val p = problems.getJSONObject(i)
                    append(" ").append(p.optString("ref")).append(": ").append(p.optString("problem")).append("\n")
                }
            }
            if (selected.length() > 0) {
                append("\n")
                if (requireLive) {
                    append("Live DEM required: windows are cut from the verified DEM library when ")
                    append("its tiles are present (same cells as live, no API call); otherwise fetched ")
                    append("live. If neither is available, that ")
                    append("candidate's results are discarded (nothing recorded) and the run stops; ")
                    append("the rest stay as they are.")
                    if (credentialStore.openTopographyApiKey.isNullOrBlank()) {
                        append("\n\nNo OpenTopography API key is saved on this device, so this run ")
                        append("cannot start with live DEM required.")
                    }
                } else {
                    append("Live DEM NOT required: if the live fetch fails, the offline library is used ")
                    append("and recorded as such (it is the same data the sweep was built from).")
                }
                append("\n\nEach refinement makes about 2 live OpenTopography calls, up to about 8 ")
                append("stability re-fetches, and Copernicus calls.")
                if (credentialStore.copernicusClientId.isNullOrBlank() || credentialStore.copernicusClientSecret.isNullOrBlank()) {
                    append("\n\nNo Copernicus credentials are saved: satellite checks will be recorded as not run.")
                }
            }
        }
        val builder = AlertDialog.Builder(this)
            .setTitle(if (ids.isEmpty()) "Nothing to refine" else "Refine ${ids.size} selected candidate(s)?")
            .setView(scrollableText(message))
            .setNeutralButton("Edit ids") { _, _ -> askCandidateIds(jobId, refsText, requireLive) }
            .setNegativeButton("Cancel", null)
        if (ids.isNotEmpty()) {
            builder.setPositiveButton("Start refinement") { _, _ ->
                startSelectedRefinement(jobId, ids, requireLive)
            }
        }
        builder.show()
    }

    /** Starts WideAreaSearchService with the RESOLVED full ids from the
     * preview (so the run refines exactly what was confirmed), same
     * credentials as startRefinement(). */
    private fun startSelectedRefinement(jobId: String, ids: List<String>, requireLive: Boolean) {
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
            putExtra(WideAreaSearchService.EXTRA_REFINE_CANDIDATE_IDS, ids.joinToString("\n"))
            putExtra(WideAreaSearchService.EXTRA_REFINE_REQUIRE_LIVE_DEM, requireLive)
        }
        ContextCompat.startForegroundService(this, serviceIntent)
        Toast.makeText(this, "Pass 2 refinement of ${ids.size} selected candidate(s) started in the background.", Toast.LENGTH_LONG).show()
    }

    /** Plain-language label for a stored dem_source value (see
     * grand_project_refinement.py's DEM_SOURCE_* constants). */
    private fun demSourceLabel(raw: String?): String = when (raw) {
        "LIVE" -> "live"
        "OFFLINE_FALLBACK" -> "offline library (live failed)"
        "OFFLINE_FIRST" -> "offline library (by choice)"
        "OFFLINE_FALLBACK_INFERRED" -> "offline library (from old record)"
        "OFFLINE_FIRST_INFERRED" -> "offline library, by choice (from old record)"
        "NOT_RECORDED" -> "source not recorded"
        null, "" -> "source not recorded"
        else -> raw?.lowercase(java.util.Locale.US) ?: "source not recorded"
    }

    /** The finished-dialog text for any Pass 2 run (top N or selected),
     * straight from run_refinement_pass()/run_selected_refinement(). Keys
     * that an older result lacks simply do not appear. */
    private fun formatRefinementResult(r: JSONObject): String = buildString {
        append(r.optInt("refined")).append(" of ").append(r.optInt("attempted")).append(" refined: ")
        append(r.optInt("reproduced")).append(" reproduced the DEM anomaly, ")
        append(r.optInt("not_reproduced")).append(" did not.\n")
        // lib-v1: where the DEM cells physically came from (the offline
        // library or the network). Absent when the library was not armed.
        val lib = r.optJSONObject("dem_library")
        if (lib != null) {
            append("DEM library: ").append(lib.optInt("library_cuts")).append(" window(s) cut from disk")
            val misses = lib.optJSONObject("library_misses")
            var nMiss = 0
            if (misses != null) { val k = misses.keys(); while (k.hasNext()) nMiss += misses.optInt(k.next()) }
            append(", ").append(nMiss).append(" fetched live")
            if (misses != null && misses.length() > 0) {
                append(" (")
                val k = misses.keys(); var first = true
                while (k.hasNext()) { val key = k.next(); if (!first) append(", "); first = false
                    append(key).append(" ").append(misses.optInt(key)) }
                append(")")
            }
            append("\n")
        }
        val results = r.optJSONArray("results") ?: JSONArray()
        if (results.length() > 0) append("\n")
        for (i in 0 until results.length()) {
            val x = results.getJSONObject(i)
            append(x.optString("candidate_id").take(8)).append(" ")
            if (x.optString("status") != "REFINED") {
                append(x.optString("status")).append("\n")
                continue
            }
            if (x.optBoolean("reproduced", false)) {
                append("reproduced")
                if (!x.isNull("match_distance_m")) {
                    append(String.format(java.util.Locale.US, " (%.0f m)", x.optDouble("match_distance_m")))
                }
            } else {
                append("not reproduced")
            }
            append("\n DEM ").append(demSourceLabel(x.optString("dem_source")))
            if (!x.isNull("dem_origin") && x.has("dem_origin")) {
                append(if (x.optString("dem_origin") == "LIBRARY") " (from library)" else " (from network)")
            }
            if (x.optBoolean("repeat_refinement", false)) append(", repeat")
            val sats = x.optJSONArray("satellite_sources_recorded")
            if (sats != null && sats.length() > 0) {
                append("\n + ")
                for (j in 0 until sats.length()) {
                    if (j > 0) append(", ")
                    append(sats.optString(j))
                }
            }
            if (!x.isNull("confidence_band")) append("\n confidence ").append(x.optString("confidence_band"))
            append("\n")
        }
        val failures = r.optJSONArray("failures") ?: JSONArray()
        if (failures.length() > 0) {
            append("\nFailed (stay eligible for a retry):\n")
            for (i in 0 until failures.length()) {
                val f = failures.getJSONObject(i)
                append(" ").append(f.optString("candidate_id").take(8)).append(": ")
                append(cleanErrorMessage(f.optString("error"))).append("\n")
            }
        }
        if (!r.isNull("stopped_no_live_dem") && r.optString("stopped_no_live_dem").isNotEmpty()) {
            append("\nSTOPPED: live DEM unavailable -- ").append(r.optString("stopped_no_live_dem")).append("\n")
            val notStarted = r.optJSONArray("not_started") ?: JSONArray()
            if (notStarted.length() > 0) {
                append("Not refined this time (nothing recorded, unchanged):\n")
                for (i in 0 until notStarted.length()) {
                    append(" ").append(notStarted.getJSONObject(i).optString("candidate_id").take(8)).append("\n")
                }
            }
        }
        val problems = r.optJSONArray("reference_problems") ?: JSONArray()
        if (problems.length() > 0) {
            append("\nIds not used:\n")
            for (i in 0 until problems.length()) {
                val p = problems.getJSONObject(i)
                append(" ").append(p.optString("ref")).append(": ").append(p.optString("problem")).append("\n")
            }
        }
    }

    /** A selectable monospace text in a ScrollView, for long dialog bodies. */
    private fun scrollableText(text: String): ScrollView {
        val density = resources.displayMetrics.density
        val pad = (20 * density).toInt()
        val tv = TextView(this).apply {
            this.text = text
            typeface = Typeface.MONOSPACE
            textSize = 12f
            setTextIsSelectable(true)
            setTextColor(ContextCompat.getColor(this@WideAreaSearchActivity, R.color.ariyan_text_primary))
            setPadding(pad, pad / 2, pad, 0)
        }
        return ScrollView(this).apply { addView(tv) }
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

    /** RELIEF-IN-PREVIEW (ADDED 2026-10-06): "+2.4 m" / "-1.1 m" (raised /
     * sunken) from the preview's relief_m (Pass 1 peak DEM residual), or
     * "? m" when it was not recorded. A non-breaking space keeps the
     * number and "m" on one line in large-font dialogs. */
    private fun reliefText(c: JSONObject): String =
        if (!c.has("relief_m") || c.isNull("relief_m")) "?\u00A0m"
        else String.format(java.util.Locale.US, "%+.1f\u00A0m", c.optDouble("relief_m"))
}
