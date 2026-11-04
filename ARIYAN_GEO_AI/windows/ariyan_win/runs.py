"""
Running work on the laptop (win-w4b, 2026-11-03) -- the phone's own code:

  INVESTIGATION   investigation_multi_mobile.run_investigation_multi_json (DEM +
                  NDVI / thermal / optical / SAR correlation; live OpenTopography
                  first, offline tiles as fallback) or investigation_mobile (DEM
                  only), then debate_mobile.run_debate_json, then
                  grand_project_sync.record_investigation_results (saved to the
                  project; a run with candidates also becomes a one-tile job so it
                  can be refined or auto-run, as on the phone, sp-v1).
  WIDE-AREA JOBS  wide_area_search_mobile: create (box or place name), run
                  (full / DEM-only sweep / DEM-only offline first), retry failed
                  tiles; one runner per job (job-lease-v1); progress from the
                  job's own status file. A run cannot be stopped half-way; closing
                  the program stops it and the next run resumes at the first
                  unfinished tile.
  AUTOMATIC RUN   auto_pipeline (ap-v1): start, then slices of work until done;
                  "Stop after this step" ends between steps; cancel records why.

Only one run at a time on this computer. Keys come from Settings (DPAPI).
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ariyan_win import keys, qtwork

ACCENT, TEAL, GOLD, ORANGE, ROSE, MUTED = "#3FB68B", "#2FA6B8", "#F2C14E", "#D9822B", "#E0607E", "#8B9BB0"
_RUN_LOCK = threading.Lock()                       # one run at a time on this computer


def _lab(text="", colour=None, bold=False, wrap=True):
    w = QtWidgets.QLabel(text)
    w.setWordWrap(wrap)
    css = ("color:%s;" % colour if colour else "") + ("font-weight:700;" if bold else "")
    if css:
        w.setStyleSheet(css)
    return w


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def handed_off(root: str) -> Optional[str]:
    """One device works on the project at a time: if this computer SENT the project
    (and has not received it back), running work here is refused."""
    try:
        import project_bundle as pb
        h = pb.handoff(root)
    except Exception:
        return None
    if h.get("state") == "SENT":
        return ("This computer sent the project to the %s on %s UTC. Work there, then send it back and use "
                "\u201cReceive from phone\u201d before running anything here." % (
                    h.get("to") or "phone", str(h.get("at") or "")[:16].replace("T", " ")))
    return None


def _gid(root: str) -> str:
    import grand_project_sync as gps
    return str(gps.get_or_create_default_grand_project(root))


# ---------------------------------------------------------------------------
# background work
# ---------------------------------------------------------------------------

def run_investigation(root: str, lat: float, lon: float, radius_m: float, grid: int, demtype: str,
                      with_satellite: bool) -> Dict[str, Any]:
    if not _RUN_LOCK.acquire(blocking=False):
        return {"error": "Another run is already going on this computer; wait for it to finish."}
    try:
        if handed_off(root):
            return {"error": handed_off(root)}
        ot = keys.opentopography()
        cid, sec = keys.copernicus()
        if with_satellite:
            import investigation_multi_mobile as imm
            text = imm.run_investigation_multi_json(lat, lon, radius_m, grid, api_key=ot, demtype=demtype,
                                                    ndvi_client_id=cid, ndvi_client_secret=sec,
                                                    offline_data_root=root)
        else:
            import investigation_mobile as im
            text = im.run_investigation_json(lat, lon, radius_m, grid, api_key=ot, demtype=demtype,
                                             offline_data_root=root)
        rec = json.loads(text)
        if "error" in rec:
            return rec
        import debate_mobile as dm
        debate_text = dm.run_debate_json(text)
        saved, save_error = None, None
        try:
            import grand_project_sync as gps
            saved = gps.record_investigation_results(root, _gid(root), text, debate_json=debate_text,
                                                     register_single_point_job=True)
        except Exception as e:                    # saving must never hide a result already computed
            save_error = "%s: %s" % (type(e).__name__, e)
        return {"record": rec, "debate": json.loads(debate_text), "saved": saved, "save_error": save_error}
    finally:
        _RUN_LOCK.release()


def run_job(root: str, job_id: str, mode: str) -> Dict[str, Any]:
    if not _RUN_LOCK.acquire(blocking=False):
        return {"error": "Another run is already going on this computer; wait for it to finish."}
    try:
        if handed_off(root):
            return {"error": handed_off(root)}
        import wide_area_search_mobile as wa
        cid, sec = keys.copernicus()
        text = wa.run_wide_area_search_job(root, job_id, api_key=keys.opentopography(), demtype="SRTMGL1",
                                           ndvi_client_id=cid, ndvi_client_secret=sec,
                                           dem_only=(mode != "full"), dem_offline_first=(mode == "dem_offline"))
        try:
            return json.loads(text)
        except ValueError:
            return {"report": text}
    finally:
        _RUN_LOCK.release()


class AutoRunner:
    """Runs an automatic run in slices; stop() takes effect between steps."""

    def __init__(self):
        self.stop_flag = False

    def run(self, root: str, run_id: str, on_tick) -> Dict[str, Any]:
        if not _RUN_LOCK.acquire(blocking=False):
            return {"error": "Another run is already going on this computer; wait for it to finish."}
        try:
            if handed_off(root):
                return {"error": handed_off(root)}
            import auto_pipeline as ap
            cid, sec = keys.copernicus()
            while True:
                r = json.loads(ap.run_slice_json(root, run_id, keys.opentopography(), cid, sec, 120))
                on_tick(r)
                if "error" in r or r.get("state") not in ("RUNNING",):
                    return r
                if self.stop_flag:
                    return dict(r, stopped_by_user=True)
        finally:
            _RUN_LOCK.release()


# ---------------------------------------------------------------------------
# INVESTIGATION tab
# ---------------------------------------------------------------------------

class InvestigationTab(QtWidgets.QWidget):
    def __init__(self, root: str, open_final_image, selected_coords, parent=None):
        super().__init__(parent)
        self.root, self.open_final_image, self.selected_coords = root, open_final_image, selected_coords
        v = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QFormLayout()
        self.lat = QtWidgets.QDoubleSpinBox()
        self.lon = QtWidgets.QDoubleSpinBox()
        for s, lo, hi in ((self.lat, -85, 85), (self.lon, -180, 180)):
            s.setDecimals(6)
            s.setRange(lo, hi)
        self.radius = QtWidgets.QDoubleSpinBox()
        self.radius.setRange(100, 5000)
        self.radius.setValue(500)
        self.radius.setSuffix(" m")
        self.grid = QtWidgets.QSpinBox()
        self.grid.setRange(8, 256)
        self.grid.setValue(96)
        self.dem = QtWidgets.QComboBox()
        self.dem.addItems(["SRTMGL1", "COP30"])
        self.sat = QtWidgets.QCheckBox("Correlate with satellite evidence (NDVI, thermal, optical, radar)")
        self.sat.setChecked(True)
        paste = QtWidgets.QLineEdit()
        paste.setPlaceholderText("or paste \u201clat, lon\u201d (e.g. from Google Maps) and press Enter")
        paste.returnPressed.connect(lambda: self._paste(paste))
        usesel = QtWidgets.QPushButton("Use the candidate selected on Mission Control")
        usesel.clicked.connect(self._use_selected)
        left.addRow("Latitude", self.lat)
        left.addRow("Longitude", self.lon)
        left.addRow(paste)
        left.addRow(usesel)
        left.addRow("Radius", self.radius)
        left.addRow("Grid cells", self.grid)
        left.addRow("Live DEM", self.dem)
        left.addRow(self.sat)
        self.run_btn = QtWidgets.QPushButton("Run investigation")
        self.run_btn.clicked.connect(self._run)
        left.addRow(self.run_btn)
        self.keys_note = _lab("", colour=MUTED)
        left.addRow(self.keys_note)
        lw = QtWidgets.QWidget()
        lw.setLayout(left)
        lw.setMaximumWidth(460)
        v.addWidget(lw)
        right = QtWidgets.QVBoxLayout()
        self.progress = _lab("", colour=GOLD)
        right.addWidget(self.progress)
        self.result = QtWidgets.QTextBrowser()
        right.addWidget(self.result, 1)
        self.cands = QtWidgets.QListWidget()
        self.cands.currentItemChanged.connect(lambda it, _p: it and __import__("ariyan_win.stewardui", fromlist=["x"])
                                              .focus_candidate(it.data(QtCore.Qt.UserRole)))
        self.cands.setMaximumHeight(160)
        self.cands.itemDoubleClicked.connect(lambda it: it.data(QtCore.Qt.UserRole) and
                                             self.open_final_image(it.data(QtCore.Qt.UserRole)))
        right.addWidget(_lab("Candidates saved to the project (double-click for the Final Image):", colour=MUTED))
        right.addWidget(self.cands)
        v.addLayout(right, 1)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._poll)
        self._refresh_keys()

    def _refresh_keys(self):
        st = keys.status()
        self.keys_note.setText("Keys: OpenTopography %s (without it, offline tiles only) \u00b7 Copernicus %s "
                               "(without it, no satellite correlation). Change them in Settings." % (
                                   "set" if st["opentopography"] else "not set", "set" if st["copernicus"] else "not set"))

    def _paste(self, e):
        try:
            a, b = [float(x) for x in e.text().replace(";", ",").split(",")[:2]]
            self.lat.setValue(a)
            self.lon.setValue(b)
            e.clear()
        except ValueError:
            e.setText("")
            e.setPlaceholderText("not understood \u2014 type it as 36.95323, 45.52454")

    def _use_selected(self):
        c = self.selected_coords()
        if c:
            self.lat.setValue(c[0])
            self.lon.setValue(c[1])

    def _run(self):
        self._refresh_keys()
        if self.lat.value() == 0 and self.lon.value() == 0:
            return
        self.run_btn.setEnabled(False)
        self.result.setHtml("")
        self.cands.clear()
        self.progress.setText("Starting\u2026")
        try:
            os.remove(os.path.join(self.root, "investigation_status.json"))
        except OSError:
            pass
        self.timer.start(1500)
        qtwork.run_async(run_investigation, self._done, self.root, self.lat.value(), self.lon.value(),
                         self.radius.value(), self.grid.value(), self.dem.currentText(), self.sat.isChecked())

    def _poll(self):
        st = _read_json(os.path.join(self.root, "investigation_status.json"))
        if st:
            self.progress.setText("%s \u00b7 %s/%s \u00b7 %s" % (st.get("phase"), st.get("done"), st.get("total"),
                                                              st.get("detail", "")))

    def _done(self, r):
        self.timer.stop()
        self.run_btn.setEnabled(True)
        if "error" in r:
            self.progress.setText("")
            self.result.setHtml("<p style='color:%s'><b>Not run:</b> %s</p>" % (ROSE, r["error"]))
            return
        rec, deb, saved = r["record"], r.get("debate") or {}, r.get("saved") or {}
        ev = rec.get("evidence") or []
        html = ["<h3>Investigation at %.5f, %.5f</h3>" % (self.lat.value(), self.lon.value()),
                "<p><b>%s</b></p>" % (rec.get("confidence_statement") or ""),
                "<p>Evidence:</p><ul>%s</ul>" % "".join("<li>%s</li>" % e.get("source", "?") for e in ev),
                "<p>Anomalies found: %d</p>" % len(rec.get("anomalies") or [])]
        for d in (deb.get("debates") or [])[:5]:
            syn = d.get("synthesis") or {}
            conf = (((d.get("steward") or {}).get("reasoning_trace") or {}).get("confidence") or {})
            html.append("<p><b>%s</b> \u00b7 %s \u00b7 leading: %s \u00b7 Steward %s %s</p>" % (
                d.get("candidate_id"), (syn.get("agreement_level") or "").replace("_", " ").title(),
                syn.get("leading_position") or "none", conf.get("band") or "", conf.get("clamped_confidence") or ""))
        if r.get("save_error"):
            html.append("<p style='color:%s'>Shown here but NOT saved to the project: %s</p>" % (ROSE, r["save_error"]))
        else:
            html.append("<p style='color:%s'>Saved to the project (investigation %s).</p>" % (
                ACCENT, str(saved.get("investigation_id") or "")[:8]))
        self.result.setHtml("".join(html))
        self.progress.setText("Finished.")
        for cid in (saved.get("candidate_ids") or []):
            it = QtWidgets.QListWidgetItem(str(cid)[:8])
            it.setData(QtCore.Qt.UserRole, cid)
            self.cands.addItem(it)
        if saved.get("candidate_ids"):
            from ariyan_win.stewardui import focus_candidate
            focus_candidate(saved["candidate_ids"][0], self)


# ---------------------------------------------------------------------------
# WIDE-AREA JOBS (inside the Investigation tab's second page)
# ---------------------------------------------------------------------------

class JobsTab(QtWidgets.QWidget):
    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root
        self.runner: Optional[AutoRunner] = None
        self._running_job: Optional[str] = None
        v = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        row = QtWidgets.QHBoxLayout()
        nb = QtWidgets.QPushButton("New job\u2026")
        nb.clicked.connect(self._new_job)
        rb = QtWidgets.QPushButton("Refresh")
        rb.clicked.connect(self.load)
        row.addWidget(nb)
        row.addWidget(rb)
        row.addStretch(1)
        left.addLayout(row)
        self.jobs = QtWidgets.QListWidget()
        self.jobs.currentItemChanged.connect(lambda *_: self._show_job())
        self.jobs.currentItemChanged.connect(lambda *_: self.cand_search.edit.text().strip() and self.cand_search.run())
        left.addWidget(self.jobs, 2)
        from ariyan_win.candidates import CandidateSearch        # u2: find a candidate in the job
        self.open_final_image = None
        self.cand_search = CandidateSearch(root, job_id=self._job_id)
        self.cand_search.picked.connect(self._candidate)
        self.cand_search.opened.connect(lambda c: self.open_final_image and self.open_final_image(c))
        left.addWidget(self.cand_search, 3)
        lw = QtWidgets.QWidget()
        lw.setLayout(left)
        lw.setMaximumWidth(460)
        v.addWidget(lw)
        right = QtWidgets.QVBoxLayout()
        from ariyan_win.stewardui import StewardGuide             # sm-v1: the Steward leads the job
        self.steward_go = None
        self.guide = StewardGuide(root, lambda a, j: self.steward_go and self.steward_go(a, j))
        right.addWidget(self.guide)
        self.detail = QtWidgets.QTextBrowser()
        self.detail.setMaximumHeight(170)
        right.addWidget(self.detail, 1)
        b1 = QtWidgets.QHBoxLayout()
        self.b_full = QtWidgets.QPushButton("Run (full evidence)")
        self.b_dem = QtWidgets.QPushButton("DEM-only sweep")
        self.b_off = QtWidgets.QPushButton("DEM-only, offline first")
        self.b_retry = QtWidgets.QPushButton("Retry failed tiles")
        for b, mode in ((self.b_full, "full"), (self.b_dem, "dem"), (self.b_off, "dem_offline")):
            b.clicked.connect(lambda _=False, m=mode: self._run(m))
            b1.addWidget(b)
        self.b_retry.clicked.connect(self._retry)
        b1.addWidget(self.b_retry)
        right.addLayout(b1)
        b2 = QtWidgets.QHBoxLayout()
        self.b_auto = QtWidgets.QPushButton("Automatic run (library, sweep, land cover, labels, review, Pass 2, report)")
        self.b_auto.clicked.connect(self._auto)
        self.b_stop = QtWidgets.QPushButton("Stop after this step")
        self.b_stop.clicked.connect(self._stop)
        self.b_stop.setEnabled(False)
        b2.addWidget(self.b_auto)
        b2.addWidget(self.b_stop)
        right.addLayout(b2)
        self.progress = _lab("", colour=GOLD)
        right.addWidget(self.progress)
        right.addWidget(_lab("A job run cannot be stopped half-way: closing the program stops it, and the next run "
                             "carries on at the first unfinished tile. One run at a time on this computer.",
                             colour=MUTED))
        v.addLayout(right, 1)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.load()

    # -- list
    def load(self):
        import wide_area_search_mobile as wa
        qtwork.run_async(lambda: json.loads(wa.list_wide_area_search_jobs_json(self.root, _gid(self.root))),
                         self._listed)

    def _listed(self, rows):
        cur = self._job_id()
        self.jobs.clear()
        if isinstance(rows, dict):
            self.jobs.addItem(rows.get("error", "?"))
            return
        for j in rows:
            it = QtWidgets.QListWidgetItem("%s \u00b7 %s \u00b7 %d tiles \u00b7 %s" % (
                j["title"], j["status"].lower(), j["n_tiles"], (j.get("created_at") or "")[:10]))
            it.setData(QtCore.Qt.UserRole, j["id"])
            self.jobs.addItem(it)
            if j["id"] == cur:
                self.jobs.setCurrentItem(it)
        if self.jobs.currentItem() is None and self.jobs.count():
            self.jobs.setCurrentRow(0)               # u3d: a job is always selected, so the Steward can guide it

    def _candidate(self, cid: str):
        from ariyan_win.candidates import CandidateDialog
        CandidateDialog(self.root, cid, self.open_final_image, self, steward_go=self.steward_go).show()

    def _job_id(self) -> Optional[str]:
        it = self.jobs.currentItem()
        return it.data(QtCore.Qt.UserRole) if it else None

    def _show_job(self):
        jid = self._job_id()
        if not jid:
            return
        self.guide.load(jid)
        from ariyan_win.stewardui import focus_job
        focus_job(jid, self)
        import auto_pipeline as ap
        import wide_area_search_mobile as wa

        def get():
            st = json.loads(wa.get_wide_area_search_job_status_json(self.root, jid))
            fails = json.loads(wa.summarize_tile_failures_json(self.root, jid))
            runs = json.loads(ap.list_auto_runs_json(self.root, jid))
            return {"st": st, "fails": fails, "runs": runs}
        qtwork.run_async(get, lambda r, j=jid: self._render(j, r))

    def _render(self, jid, r):
        if jid != self._job_id():
            return
        if "error" in r:
            self.detail.setPlainText(r["error"])
            return
        j, p = (r["st"].get("job") or {}), (r["st"].get("progress") or {})
        html = ["<h3>%s</h3>" % j.get("title"),
                "<p>%s \u00b7 box %.4f\u2013%.4f N, %.4f\u2013%.4f E \u00b7 tiles of %.0f m</p>" % (
                    j.get("status"), j.get("min_lat", 0), j.get("max_lat", 0), j.get("min_lon", 0), j.get("max_lon", 0),
                    j.get("tile_size_m", 0)),
                "<p><b>Tiles:</b> %s total \u00b7 %s done \u00b7 %s pending \u00b7 %s failed</p>" % (
                    p.get("total"), p.get("done"), p.get("pending"), p.get("failed"))]
        f = r["fails"]
        if isinstance(f, dict) and f.get("groups"):
            html.append("<p><b>Failures:</b></p><ul>%s</ul>" % "".join(
                "<li>%d tile(s): %s \u2014 tiles %s</li>" % (g.get("count", 0), g.get("example"), g.get("tiles"))
                for g in f["groups"][:8]))
        runs = r["runs"].get("runs") if isinstance(r["runs"], dict) else r["runs"]
        if runs:
            html.append("<p><b>Automatic runs:</b></p><ul>%s</ul>" % "".join(
                "<li>%s \u00b7 %s \u00b7 next: %s</li>" % ((x.get("created_at") or "")[:16].replace("T", " "), x.get("state"),
                                                       x.get("next_step")) for x in runs[:6]))
        self.detail.setHtml("".join(html))

    # -- create
    def _new_job(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("New wide-area job")
        f = QtWidgets.QFormLayout(dlg)
        title = QtWidgets.QLineEdit()
        place = QtWidgets.QLineEdit()
        place.setPlaceholderText("a place name (looked up once, online) \u2014 or fill the box below")
        boxes = [QtWidgets.QDoubleSpinBox() for _ in range(4)]
        for b, (lo, hi) in zip(boxes, ((-85, 85), (-85, 85), (-180, 180), (-180, 180))):
            b.setDecimals(5)
            b.setRange(lo, hi)
        size = QtWidgets.QDoubleSpinBox()
        size.setRange(250, 5000)
        size.setValue(1000)
        size.setSuffix(" m")
        look = QtWidgets.QPushButton("Look up the place")
        note = _lab("", colour=MUTED)

        def lookup():
            import wide_area_search_mobile as wa
            g = json.loads(wa.geocode_place_to_bbox_json(place.text()))
            if not g.get("found"):
                note.setText(g.get("error") or "not found")
                return
            bb = g["bounding_box"]
            for b, k in zip(boxes, ("min_lat", "max_lat", "min_lon", "max_lon")):
                b.setValue(float(bb[k]))
            note.setText("Found: %s" % g.get("resolved_name"))
            if not title.text():
                title.setText(place.text())
        look.clicked.connect(lookup)
        f.addRow("Title", title)
        f.addRow("Place", place)
        f.addRow(look)
        f.addRow(note)
        for b, name in zip(boxes, ("South (min lat)", "North (max lat)", "West (min lon)", "East (max lon)")):
            f.addRow(name, b)
        f.addRow("Tile size", size)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        import wide_area_search_mobile as wa
        s, n, w, e = (b.value() for b in boxes)
        r = json.loads(wa.create_wide_area_search_job_json(
            self.root, _gid(self.root), title.text().strip() or "job", "place" if place.text().strip() else "bbox",
            s, n, w, e, size.value(), None, place.text().strip() or None))
        if "error" in r:
            QtWidgets.QMessageBox.warning(self, "Not created", r["error"])
            return
        QtWidgets.QMessageBox.information(self, "Job created", "%d tiles. Download their terrain on Data & Evidence, then "
                                          "run the job here." % r["n_tiles"])
        self.load()

    # -- run
    def _busy(self, on: bool):
        for b in (self.b_full, self.b_dem, self.b_off, self.b_retry, self.b_auto):
            b.setEnabled(not on)

    def _run(self, mode):
        jid = self._job_id()
        if not jid:
            return
        self._running_job = jid
        self._busy(True)
        self.progress.setText("Starting\u2026")
        self.timer.start(2000)
        qtwork.run_async(run_job, self._run_done, self.root, jid, mode)

    def _poll(self):
        if not self._running_job:
            return
        st = _read_json(os.path.join(self.root, "wide_area_search_status_%s.json" % self._running_job))
        if st:
            self.progress.setText("%s \u00b7 tile %s of %s \u00b7 %s" % (st.get("phase"), st.get("done"), st.get("total"),
                                                                     (st.get("detail") or "")[:160]))

    def _run_done(self, r):
        self.guide.load(self._job_id())
        self.timer.stop()
        self._busy(False)
        self._running_job = None
        if "error" in r:
            msg = "Not run: " + str(r["error"])
        elif "total" in r:
            msg = "Finished: %s of %s tiles done, %s failed, %s still pending%s." % (
                r.get("done"), r.get("total"), r.get("failed"), r.get("pending"),
                " (paused: %s)" % r.get("pause_reason") if r.get("paused") else "")
        else:
            msg = "Finished: " + str(r.get("report") or r.get("summary") or json.dumps(r, default=str))[:300]
        self.progress.setText(msg)
        self._show_job()
        self.load()

    def _retry(self):
        jid = self._job_id()
        if not jid:
            return
        import wide_area_search_mobile as wa
        r = json.loads(wa.retry_failed_tiles_json(self.root, jid))
        self.progress.setText(r.get("error") or "%s failed tile(s) set to pending again. Run the job to retry them."
                              % r.get("reset"))
        self._show_job()

    def _auto(self):
        jid = self._job_id()
        if not jid:
            return
        import auto_pipeline as ap
        r = json.loads(ap.start_auto_run_json(self.root, jid, ""))
        if "error" in r:
            QtWidgets.QMessageBox.warning(self, "Not started", r["error"])
            return
        self.runner = AutoRunner()
        self._busy(True)
        self.b_stop.setEnabled(True)
        rid = r["run_id"]
        self.progress.setText("Automatic run %s started\u2026" % rid[:8])

        def tick(s):
            QtCore.QMetaObject.invokeMethod(self, "_tick", QtCore.Qt.QueuedConnection,
                                            QtCore.Q_ARG(str, json.dumps(s, default=str)))
        qtwork.run_async(self.runner.run, self._auto_done, self.root, rid, tick)

    @QtCore.Slot(str)
    def _tick(self, text):
        s = json.loads(text)
        self.progress.setText("Automatic run: %s \u00b7 next step %s" % (s.get("state"), s.get("next_step")))

    def _stop(self):
        if self.runner:
            self.runner.stop_flag = True
            self.b_stop.setEnabled(False)
            self.progress.setText(self.progress.text() + " \u2014 stopping after this step\u2026")

    def _auto_done(self, r):
        self.guide.load(self._job_id())
        self._busy(False)
        self.b_stop.setEnabled(False)
        if "error" in r:
            self.progress.setText("Automatic run error: " + r["error"])
        elif r.get("stopped_by_user"):
            self.progress.setText("Stopped by you before step %s. Start the automatic run again to continue." % r.get(
                "next_step"))
        else:
            self.progress.setText("Automatic run %s%s." % (r.get("state"), (" \u2014 paused for about %d min: %s" % (
                (r.get("retry_after_s") or 0) // 60, r.get("reason") or "")) if r.get("state") == "PAUSED" else ""))
        self._show_job()
        self.load()
