"""
GRAND PROJECT and HISTORICAL RESEARCH tabs (win-w4d, 2026-11-03), the phone's
GrandProjectActivity and HistoricalResearchActivity on the laptop, calling the
same Python (grand_project_query_mobile, grand_project_review, provenance_check,
terrain_context_labels, grand_project_calibration, calib_profile, calib_bench,
single_point_jobs, historical_research_mobile, wide_area_search_mobile).

Grand Project: dashboard of every job (trust, target, candidates by status,
calib-v1 strong, evidence and provenance rows); per job: set trust (Trusted /
Unverified / Corrupted) and target (Mound or tell / Other / Not set) with a
reason, provenance check, terrain labels, calibration report; hypotheses
(create, link a candidate); single-point investigations turned into one-tile
jobs; the full timeline; calib-v1 profile report, bench, adopt / revoke.
Historical Research: the hs-v1 search (English + Persian Wikipedia, Wikidata,
Pleiades, OpenAlex) with every source count and error, located findings (tier,
Iran flag, caveat, links), Save, and a wide-area job from a saved finding.
No confidence percentage anywhere; a finding is a place to look, not evidence.
"""
from __future__ import annotations

import json
import webbrowser
from typing import Any, Dict, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ariyan_win import qtwork

ACCENT, TEAL, GOLD, ORANGE, ROSE, MUTED = "#3FB68B", "#2FA6B8", "#F2C14E", "#D9822B", "#E0607E", "#8B9BB0"


def _gid(root):
    import grand_project_sync as gps
    return str(gps.get_or_create_default_grand_project(root))


def _show_result(parent, title: str, text: str):
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(760, 560)
    v = QtWidgets.QVBoxLayout(dlg)
    t = QtWidgets.QPlainTextEdit(text)
    t.setReadOnly(True)
    v.addWidget(t)
    b = QtWidgets.QPushButton("Close")
    b.clicked.connect(dlg.accept)
    v.addWidget(b)
    dlg.exec()


def _pretty(obj) -> str:
    if isinstance(obj, dict) and obj.get("summary_text"):
        return str(obj["summary_text"]) + "\n\n" + json.dumps(obj, indent=1, ensure_ascii=False, default=str)
    return json.dumps(obj, indent=1, ensure_ascii=False, default=str)


class GrandProject(QtWidgets.QTabWidget):
    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root
        # --- dashboard + job tools
        dash = QtWidgets.QWidget()
        dv = QtWidgets.QVBoxLayout(dash)
        self.dash_note = QtWidgets.QLabel("Reading\u2026")
        self.dash_note.setWordWrap(True)
        dv.addWidget(self.dash_note)
        self.jobs = QtWidgets.QTableWidget(0, 10)
        self.jobs.setHorizontalHeaderLabels(["Job", "Trust", "Target", "Candidates", "Open", "Supported", "Rejected",
                                             "Inconclusive", "calib strong", "Evidence rows"])
        self.jobs.verticalHeader().setVisible(False)
        self.jobs.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.jobs.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.jobs.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        dv.addWidget(self.jobs, 1)
        row = QtWidgets.QHBoxLayout()
        for name, fn in (("Set trust\u2026", self._trust), ("Set target\u2026", self._target),
                         ("Check provenance", lambda: self._tool("check_job_provenance_json", "Provenance check")),
                         ("Terrain labels", lambda: self._tool("label_job_terrain_json", "Terrain labels (f3-v2)")),
                         ("Calibration report", lambda: self._tool("calibrate_job_json", "Calibration")),
                         ("Refresh", self.load)):
            b = QtWidgets.QPushButton(name)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        dv.addLayout(row)
        self.addTab(dash, "Dashboard && jobs")
        # --- hypotheses
        hyp = QtWidgets.QWidget()
        hv = QtWidgets.QVBoxLayout(hyp)
        self.hyps = QtWidgets.QListWidget()
        hv.addWidget(self.hyps, 1)
        hr = QtWidgets.QHBoxLayout()
        nb = QtWidgets.QPushButton("New hypothesis\u2026")
        nb.clicked.connect(self._new_hyp)
        lb = QtWidgets.QPushButton("Link a candidate to the selected hypothesis\u2026")
        lb.clicked.connect(self._link_hyp)
        hr.addWidget(nb)
        hr.addWidget(lb)
        hr.addStretch(1)
        hv.addLayout(hr)
        hv.addWidget(QtWidgets.QLabel("A hypothesis is your own stated idea about the place; linking a candidate to it "
                                      "changes no status or confidence."))
        self.addTab(hyp, "Hypotheses")
        # --- single points
        sp = QtWidgets.QWidget()
        sv = QtWidgets.QVBoxLayout(sp)
        self.singles = QtWidgets.QListWidget()
        self.singles.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        sv.addWidget(self.singles, 1)
        mb = QtWidgets.QPushButton("Make one-tile jobs from the selected investigations")
        mb.clicked.connect(self._make_singles)
        sv.addWidget(mb)
        sv.addWidget(QtWidgets.QLabel("Older single-point investigations become one-tile jobs so they can be refined "
                                      "(Pass 2) or auto-run, as on the phone (sp-v1)."))
        self.addTab(sp, "Single points")
        # --- timeline
        tl = QtWidgets.QWidget()
        tv = QtWidgets.QVBoxLayout(tl)
        self.timeline = QtWidgets.QTableWidget(0, 3)
        self.timeline.setHorizontalHeaderLabels(["When (UTC)", "Event", "Description"])
        self.timeline.verticalHeader().setVisible(False)
        self.timeline.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        tv.addWidget(self.timeline, 1)
        self.addTab(tl, "Timeline")
        # --- calibration
        cal = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(cal)
        self.calib = QtWidgets.QPlainTextEdit()
        self.calib.setReadOnly(True)
        cv.addWidget(self.calib, 1)
        cr = QtWidgets.QHBoxLayout()
        for name, fn in (("Refresh the calib-v1 report", self._calib_report), ("Run the calibration bench", self._bench),
                         ("Adopt calib-v1\u2026", self._adopt), ("Revoke calib-v1\u2026", self._revoke)):
            b = QtWidgets.QPushButton(name)
            b.clicked.connect(fn)
            cr.addWidget(b)
        cr.addStretch(1)
        cv.addLayout(cr)
        cv.addWidget(QtWidgets.QLabel("calib-v1 only labels and sorts (|z| threshold); it never changes a status, "
                                      "review or confidence. Adopting or revoking needs your note and is recorded."))
        self.addTab(cal, "Calibration")
        self.load()

    # ------------------------------------------------------------------ load
    def load(self):
        import grand_project_query_mobile as q
        import single_point_jobs as spj

        def get():
            gid = _gid(self.root)
            return {"dash": json.loads(q.project_dashboard_json(self.root, gid)),
                    "hyps": json.loads(q.list_hypotheses_json(self.root, gid)),
                    "singles": json.loads(spj.list_single_points_json(self.root)),
                    "timeline": json.loads(q.list_timeline_json(self.root, gid))}
        qtwork.run_async(get, self._loaded)
        self._calib_report()

    def _loaded(self, r):
        if "error" in r:
            self.dash_note.setText(r["error"])
            return
        d = r["dash"]
        if isinstance(d, dict) and "error" in d:
            self.dash_note.setText(d["error"])
        else:
            self.dash_note.setText("%s candidates in %d jobs \u00b7 calib-v1 %s \u00b7 report %s" % (
                "{:,}".format(d.get("candidates_total", 0)), len(d.get("jobs", [])),
                "active" if d.get("calib_active") else "not adopted", d.get("report_version")))
            self.jobs.setRowCount(0)
            for i, j in enumerate(d.get("jobs", [])):
                self.jobs.insertRow(i)
                bs = j.get("by_status") or {}
                vals = [j.get("title") or j.get("job_id", "")[:8], j.get("trust") or "not set", (j.get("target") or "").replace("_", " ").lower(),
                        j.get("candidates", 0), bs.get("GENERATED", 0), bs.get("SUPPORTED", 0), bs.get("REJECTED", 0),
                        bs.get("INCONCLUSIVE", 0), j.get("calib_strong", 0), j.get("evidence_rows", 0)]
                for k, val in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem("{:,}".format(val) if isinstance(val, int) else str(val))
                    it.setData(QtCore.Qt.UserRole, j.get("job_id"))
                    self.jobs.setItem(i, k, it)
            self.jobs.resizeColumnsToContents()
        self.hyps.clear()
        for h in (r["hyps"] if isinstance(r["hyps"], list) else []):
            it = QtWidgets.QListWidgetItem("%s \u00b7 %s \u00b7 %s" % (h.get("statement"), h.get("status") or "",
                                                                     (h.get("created_at") or "")[:10]))
            it.setData(QtCore.Qt.UserRole, h["id"])
            self.hyps.addItem(it)
        if not self.hyps.count():
            self.hyps.addItem("No hypotheses yet.")
        self.singles.clear()
        s = r["singles"] if isinstance(r["singles"], dict) else {}
        for x in s.get("items", []):
            it = QtWidgets.QListWidgetItem("%s \u00b7 %.5f, %.5f \u00b7 %s candidate(s) \u00b7 %s" % (
                str(x.get("investigation_id", ""))[:8], x.get("lat") or 0, x.get("lon") or 0, x.get("n_candidates", ""),
                (x.get("created_at") or "")[:10]))
            it.setData(QtCore.Qt.UserRole, x.get("investigation_id"))
            self.singles.addItem(it)
        if not self.singles.count():
            self.singles.addItem("No single-point investigation waiting to become a job.")
        rows = r["timeline"] if isinstance(r["timeline"], list) else []
        self.timeline.setRowCount(0)
        for i, e in enumerate(reversed(rows[-500:])):
            self.timeline.insertRow(i)
            for k, val in enumerate(((e.get("occurred_at") or "")[:16].replace("T", " "),
                                     (e.get("event_type") or "").replace("_", " ").title(), e.get("description") or "")):
                self.timeline.setItem(i, k, QtWidgets.QTableWidgetItem(val))
        self.timeline.resizeColumnsToContents()
        self.timeline.horizontalHeader().setStretchLastSection(True)

    # -------------------------------------------------------------- job tools
    def _job(self) -> Optional[str]:
        it = self.jobs.selectedItems()
        if not it:
            QtWidgets.QMessageBox.information(self, "Choose a job", "Select a job in the table first.")
            return None
        return it[0].data(QtCore.Qt.UserRole)

    def _choose(self, title, options):
        item, ok = QtWidgets.QInputDialog.getItem(self, title, "Choose:", [o[1] for o in options], 0, False)
        if not ok:
            return None, None
        key = dict((o[1], o[0]) for o in options)[item]
        reason, ok = QtWidgets.QInputDialog.getText(self, title, "Your reason (kept on record):")
        if not ok or not reason.strip():
            return None, None
        return key, reason.strip()

    def _trust(self):
        jid = self._job()
        if not jid:
            return
        key, reason = self._choose("Job trust", [("TRUSTED", "Trusted"), ("UNVERIFIED", "Unverified"),
                                                 ("CORRUPTED", "Corrupted")])
        if key:
            import grand_project_query_mobile as q
            r = json.loads(q.set_job_trust_json(self.root, jid, key, reason))
            if "error" in r:
                QtWidgets.QMessageBox.warning(self, "Not set", r["error"])
            self.load()

    def _target(self):
        jid = self._job()
        if not jid:
            return
        key, reason = self._choose("Job target", [("MOUND_TELL", "Mound or tell (switches on the Hillside rule)"),
                                                  ("OTHER", "Other"), ("NOT_SET", "Not set")])
        if key:
            import grand_project_query_mobile as q
            r = json.loads(q.set_job_target_json(self.root, jid, key, reason))
            if "error" in r:
                QtWidgets.QMessageBox.warning(self, "Not set", r["error"])
            self.load()

    def _tool(self, fn_name: str, title: str):
        jid = self._job()
        if not jid:
            return
        import grand_project_query_mobile as q
        qtwork.run_async(lambda: json.loads(getattr(q, fn_name)(self.root, jid)),
                         lambda r: _show_result(self, title, _pretty(r)))

    # ------------------------------------------------------------ hypotheses
    def _new_hyp(self):
        text, ok = QtWidgets.QInputDialog.getMultiLineText(self, "New hypothesis", "Your statement:")
        if not ok or not text.strip():
            return
        import grand_project_query_mobile as q
        r = json.loads(q.create_hypothesis_json(self.root, _gid(self.root), text.strip()))
        if isinstance(r, dict) and "error" in r:
            QtWidgets.QMessageBox.warning(self, "Not created", r["error"])
        self.load()

    def _link_hyp(self):
        it = self.hyps.currentItem()
        hid = it.data(QtCore.Qt.UserRole) if it else None
        if not hid:
            return
        cid, ok = QtWidgets.QInputDialog.getText(self, "Link a candidate", "Full candidate id:")
        if not ok or not cid.strip():
            return
        import grand_project_query_mobile as q
        r = json.loads(q.link_candidate_to_hypothesis_json(self.root, cid.strip(), hid))
        if isinstance(r, dict) and "error" in r:
            QtWidgets.QMessageBox.warning(self, "Not linked", r["error"])
        else:
            QtWidgets.QMessageBox.information(self, "Linked", "Candidate linked to the hypothesis.")

    def _make_singles(self):
        ids = [i.data(QtCore.Qt.UserRole) for i in self.singles.selectedItems() if i.data(QtCore.Qt.UserRole)]
        if not ids:
            return
        import single_point_jobs as spj
        r = json.loads(spj.make_single_point_jobs_json(self.root, json.dumps(ids)))
        _show_result(self, "One-tile jobs", _pretty(r))
        self.load()

    # ----------------------------------------------------------- calibration
    def _calib_report(self):
        import grand_project_query_mobile as q
        qtwork.run_async(lambda: json.loads(q.calib_profile_report_json(self.root, _gid(self.root))),
                         lambda r: self.calib.setPlainText(_pretty(r)))

    def _bench(self):
        import grand_project_query_mobile as q
        self.calib.setPlainText("Running the calibration bench on the frozen test areas\u2026")
        qtwork.run_async(lambda: json.loads(q.run_calib_bench_json(self.root)),
                         lambda r: self.calib.setPlainText(_pretty(r)))

    def _adopt(self):
        note, ok = QtWidgets.QInputDialog.getText(self, "Adopt calib-v1", "Your approval note (kept on record):")
        if ok and note.strip():
            import grand_project_query_mobile as q
            self.calib.setPlainText(_pretty(json.loads(q.calib_profile_adopt_json(self.root, _gid(self.root),
                                                                                   note.strip()))))

    def _revoke(self):
        reason, ok = QtWidgets.QInputDialog.getText(self, "Revoke calib-v1", "Your reason (kept on record):")
        if ok and reason.strip():
            import grand_project_query_mobile as q
            self.calib.setPlainText(_pretty(json.loads(q.calib_profile_revoke_json(self.root, _gid(self.root),
                                                                                    reason.strip()))))


class HistoricalResearch(QtWidgets.QTabWidget):
    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root
        self.search_json: Optional[str] = None
        s = QtWidgets.QWidget()
        sv = QtWidgets.QVBoxLayout(s)
        row = QtWidgets.QHBoxLayout()
        self.query = QtWidgets.QLineEdit()
        self.query.setPlaceholderText("a historical place, site or event (English or Persian), e.g. Hasanlu, \u062a\u067e\u0647 \u062d\u0633\u0646\u0644\u0648")
        self.query.returnPressed.connect(self._search)
        go = QtWidgets.QPushButton("Search")
        go.clicked.connect(self._search)
        row.addWidget(self.query, 1)
        row.addWidget(go)
        sv.addLayout(row)
        self.sources = QtWidgets.QLabel("Sources: English + Persian Wikipedia, Wikidata, Pleiades, OpenAlex (online).")
        self.sources.setWordWrap(True)
        sv.addWidget(self.sources)
        self.found = QtWidgets.QListWidget()
        sv.addWidget(self.found, 1)
        br = QtWidgets.QHBoxLayout()
        sb = QtWidgets.QPushButton("Save the selected finding")
        sb.clicked.connect(self._save)
        ob = QtWidgets.QPushButton("Open its links")
        ob.clicked.connect(self._links)
        br.addWidget(sb)
        br.addWidget(ob)
        br.addStretch(1)
        sv.addLayout(br)
        self.other = QtWidgets.QTextBrowser()
        self.other.setMaximumHeight(170)
        sv.addWidget(self.other)
        self.addTab(s, "Search")
        sv2 = QtWidgets.QWidget()
        v2 = QtWidgets.QVBoxLayout(sv2)
        self.saved = QtWidgets.QListWidget()
        v2.addWidget(self.saved, 1)
        wb = QtWidgets.QPushButton("Start a wide-area job around the selected saved finding\u2026")
        wb.clicked.connect(self._job_from_saved)
        v2.addWidget(wb)
        v2.addWidget(QtWidgets.QLabel("Only located findings can start a job; the radius is always yours, never "
                                      "taken from the text. A finding is a place to look, not evidence."))
        self.addTab(sv2, "Saved")
        self.load_saved()

    def _search(self):
        q = self.query.text().strip()
        if not q:
            return
        self.found.clear()
        self.other.setHtml("")
        self.sources.setText("Searching\u2026 (online; about half a minute)")
        import historical_research_mobile as hr
        qtwork.run_async(lambda: hr.run_historical_search_json(q), self._found)

    def _found(self, text):
        if isinstance(text, dict):
            self.sources.setText(text.get("error", "?"))
            return
        self.search_json = text
        r = json.loads(text)
        if "error" in r:
            self.sources.setText(r["error"])
            return
        counts, errors = r.get("source_counts") or {}, r.get("source_errors") or {}
        self.sources.setText("Sources: " + " \u00b7 ".join("%s %s%s" % (k, v, " (error)" if errors.get(k) else "")
                                                           for k, v in counts.items()) +
                             ("".join("\nError %s: %s" % (k, v) for k, v in errors.items() if v)))
        for i, f in enumerate(r.get("located_findings") or []):
            iran = "not recorded" if f.get("in_iran") is None else ("yes" if f["in_iran"] else "NO")
            co = "; ".join("%s %s %.5f, %.5f" % (c.get("tier"), c.get("source"), c.get("lat"), c.get("lon"))
                           for c in f.get("coordinates") or [])
            title = f.get("title_en") or f.get("title") or ""
            it = QtWidgets.QListWidgetItem("#%d [%s] %s \u00b7 Iran: %s \u00b7 %s%s" % (
                i + 1, f.get("best_tier"), title, iran, co, ("\n      " + f["caveat"]) if f.get("caveat") else ""))
            it.setData(QtCore.Qt.UserRole, f)
            self.found.addItem(it)
        if not self.found.count():
            self.found.addItem("No located findings.")
        html = []
        un = r.get("unlocated_findings") or []
        if un:
            html.append("<b>Found, but no coordinate (%d)</b><ul>%s</ul>" % (len(un), "".join(
                "<li>%s \u2014 %s</li>" % (f.get("title_en") or f.get("title"), f.get("caveat") or "") for f in un[:20])))
        lit = r.get("literature") or []
        if lit:
            html.append("<b>Literature (OpenAlex, title match only, %d)</b><ul>%s</ul>" % (len(lit), "".join(
                "<li>%s (%s) <a href='%s'>%s</a></li>" % (w.get("title"), w.get("year") or "", w.get("url") or "",
                                                         w.get("url") or "") for w in lit[:20])))
        self.other.setHtml("".join(html))
        self.other.setOpenExternalLinks(True)

    def _sel(self) -> Optional[Dict[str, Any]]:
        it = self.found.currentItem()
        return it.data(QtCore.Qt.UserRole) if it else None

    def _links(self):
        f = self._sel()
        if not f:
            return
        for k in ("wikidata", "pleiades", "wikipedia_en", "wikipedia_fa"):
            u = (f.get("links") or {}).get(k)
            if u:
                webbrowser.open(u)

    def _save(self):
        f = self._sel()
        if not f or not self.search_json:
            return
        import historical_research_mobile as hr
        r = json.loads(hr.save_located_finding_json(self.root, _gid(self.root), self.search_json, f.get("key")))
        if isinstance(r, dict) and "error" in r:
            QtWidgets.QMessageBox.warning(self, "Not saved", r["error"])
            return
        QtWidgets.QMessageBox.information(self, "Saved", "Saved to the project (saving the same finding twice does "
                                          "not duplicate it).")
        self.load_saved()

    def load_saved(self):
        import historical_research_mobile as hr
        qtwork.run_async(lambda: json.loads(hr.list_geographic_suggestions_json(self.root, _gid(self.root))),
                         self._saved)

    def _saved(self, rows):
        self.saved.clear()
        if isinstance(rows, dict):
            self.saved.addItem(rows.get("error", "?"))
            return
        for s in rows:
            pos = "" if s.get("lat") is None else " \u00b7 %.5f, %.5f" % (s["lat"], s["lon"])
            it = QtWidgets.QListWidgetItem("%s \u00b7 %s%s \u00b7 %s \u00b7 %s" % (
                s.get("kind"), s.get("resolved_name") or s.get("place_name") or "", pos, s.get("status"),
                (s.get("created_at") or "")[:10]))
            it.setData(QtCore.Qt.UserRole, s)
            self.saved.addItem(it)
        if not self.saved.count():
            self.saved.addItem("No saved findings yet. Run a search and save a located result.")

    def _job_from_saved(self):
        it = self.saved.currentItem()
        s = it.data(QtCore.Qt.UserRole) if it else None
        if not s or s.get("kind") != "LOCATED_FINDING" or s.get("lat") is None:
            QtWidgets.QMessageBox.information(self, "Not startable", "Choose a saved LOCATED finding with a coordinate.")
            return
        r_km, ok = QtWidgets.QInputDialog.getDouble(self, "Wide-area job", "Radius around the finding (km):", 2.0, 0.2,
                                                    50.0, 1)
        if not ok:
            return
        import wide_area_search_mobile as wa
        name = s.get("resolved_name") or s.get("place_name") or "historical finding"
        r = json.loads(wa.create_wide_area_search_job_from_suggestion_json(
            self.root, _gid(self.root), "hist: " + name, float(s["lat"]), float(s["lon"]), r_km,
            geographic_suggestion_id=s["id"]))
        if "error" in r:
            QtWidgets.QMessageBox.warning(self, "Not created", r["error"])
            return
        QtWidgets.QMessageBox.information(self, "Job created", "%s tiles. Run it on INVESTIGATION \u2192 Wide-area jobs "
                                          "(download its terrain on Data & Evidence first)." % r.get("n_tiles"))
