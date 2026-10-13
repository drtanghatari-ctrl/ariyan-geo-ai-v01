"""
t2_cc_v1_test.py -- ARIYAN GEO AI, test T2 for the cc-v1 HIGH gate.

FROZEN RULES (approved by the user 2026-10-13 BEFORE this script was run;
any change is T2-v2, never an edit of this file)

QUESTION
  Among Pass 2 refined candidates, do those near recorded sites pass the
  cc-v1 rule more often than the rest?

POPULATION
  Candidates of the trusted bench jobs 32c858, 32d423, f43d36 (a job
  marked CORRUPTED is refused) that have at least one Pass 2 marker row
  (evidence_link relation 'refinement_dem_check') carrying
  cc_fields_version ccf-v1 or ccf-v2. Each candidate counts ONCE, using
  its latest such row. Rows were produced in the app's calib-v1 order
  (Refine top N); this script does no hand-picking.

cc-v1 PASS = all seven checks hold; "untested" always counts as FAIL
  1 reproduced   reproduced == true AND dem_source == LIVE AND
                 dem_type == SRTMGL1 (independent of the COP30 Pass 1;
                 windows cut from the SRTM library tile count as LIVE).
                 OFFLINE_FALLBACK is not independent -> fail.
  2 cop30        dem_cross_check tested AND confirmed.
  3 stability    stability present, >= 1 window fetched, detected in
                 every fetched window.
  4 landcover    candidate_land_cover_v2 row exists, centre has >= 5
                 valid px, and the lc-v2 rule does not reject it.
  5 hillside     only for MOUND_TELL jobs: newest f3-v2 TERRAIN_CONTEXT
                 row says Hillside "No". Not a mound job -> passes.
  6 steward      steward_gate present (ccf-v2), effective_sources >= 2.0
                 AND avg_quality >= 0.8 (the Steward's own HIGH inputs).
  7 industrial   industrial_index.check (ind-v1, 300 m) status CLEAR.
                 OUTSIDE_COVERAGE is untested -> fail.

NEAR A SITE
  known_sites.annotate(lat, lon)["label"] == "NEAR_KNOWN_SITE"
  (recorded site point or outline within 1000 m), at the candidate's
  stored position.

STATISTIC AND VERDICT
  One-sided Fisher exact test on the 2 x 2 table near/rest x pass/fail
  (P of at least the observed near-site passes, hypergeometric).
  NOT ENOUGH DATA  if fewer than 5 near-site candidates in the
                   population, or 0 passes overall.
  PASS             if near-site pass rate > rest pass rate and p < 0.05.
  FAIL             otherwise.
  Every check's block count is reported so a FAIL is explained.

NETWORK / SAFETY
  Downloads the app code from GitHub once (into ariyan_src_t2 beside
  this script). The database is opened READ-ONLY. No OpenTopography,
  Copernicus or WorldCover calls. Writes nothing to the database.

USAGE
  python t2_cc_v1_test.py
"""
import hashlib
import io
import json
import math
import os
import sqlite3
import sys
import tarfile
import urllib.request

VERSION = "t2-ccv1-v1"
DB_PATH = "/storage/emulated/0/ARIYAN_GEO_AI/offline_data/grand_project.db"
TARBALL = ("https://codeload.github.com/drtanghatari-ctrl/ariyan-geo-ai-v01/"
           "tar.gz/refs/heads/main")
HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(HERE, "ariyan_src_t2")
PY_SUBDIR = "ARIYAN_GEO_AI/app/src/main/python/"

JOB_PREFIXES = ("32c858", "32d423", "f43d36")
CCF_VERSIONS = ("ccf-v1", "ccf-v2")
MIN_NEAR = 5
ALPHA = 0.05
EFFECTIVE_SOURCES_MIN = 2.0
AVG_QUALITY_MIN = 0.8
TERRAIN_TYPE = "TERRAIN_CONTEXT"
TERRAIN_METHOD = "f3-v2"
MOUND_TELL = "MOUND_TELL"
CHECKS = ("reproduced", "cop30", "stability", "landcover", "hillside",
          "steward", "industrial")


def own_hashes():
    with open(os.path.abspath(__file__), "rb") as f:
        b = f.read()
    return hashlib.md5(b).hexdigest(), hashlib.sha256(b).hexdigest()


def fetch_code():
    need = ("known_sites.py", "industrial_index.py", "land_cover_flags.py")
    if all(os.path.exists(os.path.join(SRC_DIR, n)) for n in need):
        return
    print("Downloading app code from GitHub (read-only, once)...")
    os.makedirs(SRC_DIR, exist_ok=True)
    data = urllib.request.urlopen(TARBALL, timeout=120).read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for m in tf.getmembers():
            i = m.name.find(PY_SUBDIR)
            if i < 0 or not m.isfile():
                continue
            rel = m.name[i + len(PY_SUBDIR):]
            if "/" in rel or not rel.endswith(".py"):
                continue
            with open(os.path.join(SRC_DIR, rel), "wb") as out:
                out.write(tf.extractfile(m).read())


def file_md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def fisher_one_sided(a, b, c, d):
    """P(X >= a) for X ~ hypergeometric: a/b = near pass/fail,
    c/d = rest pass/fail."""
    n1, k, n = a + b, a + c, a + b + c + d
    denom = math.comb(n, n1)
    hi = min(n1, k)
    return sum(math.comb(k, x) * math.comb(n - k, n1 - x)
               for x in range(a, hi + 1)) / denom


def resolve_job(conn, prefix):
    rows = conn.execute("SELECT id, title FROM wide_area_search_job WHERE id LIKE ?",
                        (prefix + "%",)).fetchall()
    if len(rows) != 1:
        raise SystemExit(f"job prefix {prefix}: {len(rows)} matches, expected 1")
    return rows[0]["id"], rows[0]["title"]


def job_is_corrupted(conn, job_id):
    try:
        r = conn.execute("SELECT trust FROM job_trust WHERE job_id = ? "
                         "ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    except sqlite3.OperationalError:
        return False
    return bool(r) and r["trust"] == "CORRUPTED"


def job_target(conn, job_id):
    try:
        r = conn.execute("SELECT target FROM job_target WHERE job_id = ? "
                         "ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return r["target"] if r else None


def main():
    md5, sha = own_hashes()
    print(f"{VERSION}  script md5 {md5}")
    print(f"script sha256 {sha}")
    fetch_code()
    sys.path.insert(0, SRC_DIR)
    try:
        import numpy  # noqa: F401  (land_cover_flags needs it)
    except ImportError:
        print("numpy missing: run  pkg install python-numpy  and try again.")
        return 1
    import industrial_index
    import known_sites
    import land_cover_flags as lcf
    for n in ("known_sites.py", "industrial_index.py", "land_cover_flags.py"):
        print(f"app code {n} md5 {file_md5(os.path.join(SRC_DIR, n))}")

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row

    pop = []
    for prefix in JOB_PREFIXES:
        job_id, title = resolve_job(conn, prefix)
        if job_is_corrupted(conn, job_id):
            raise SystemExit(f"job {prefix} is marked CORRUPTED; T2 refuses it.")
        target = job_target(conn, job_id)
        cands = conn.execute(
            "SELECT c.id, c.lat, c.lon FROM candidate c "
            "JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
            "WHERE t.job_id = ?", (job_id,)).fetchall()
        cmap = {r["id"]: r for r in cands}
        latest = {}
        for r in conn.execute(
                "SELECT e.candidate_id, e.detail_json FROM evidence_link e "
                "JOIN candidate c ON c.id = e.candidate_id "
                "JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
                "WHERE t.job_id = ? AND e.relation = 'refinement_dem_check' "
                "ORDER BY e.recorded_at, e.id", (job_id,)):
            try:
                d = json.loads(r["detail_json"] or "{}")
            except ValueError:
                continue
            if d.get("cc_fields_version") in CCF_VERSIONS:
                latest[r["candidate_id"]] = d
        print(f"job {prefix} ({title}): target {target or 'NOT_SET'}, "
              f"{len(cands)} candidates, {len(latest)} with a ccf Pass 2 row")
        for cid, d in latest.items():
            c = cmap[cid]
            pop.append({"id": cid, "job": prefix, "lat": c["lat"], "lon": c["lon"],
                        "target": target, "d": d})

    # newest f3-v2 terrain row per candidate, and lc-v2 rows
    ids = [p["id"] for p in pop]
    terrain, lc = {}, {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"SELECT candidate_id, detail_json FROM evidence_link "
                f"WHERE evidence_type = ? AND candidate_id IN ({q}) ORDER BY id",
                [TERRAIN_TYPE] + chunk):
            try:
                d = json.loads(r["detail_json"] or "{}")
            except ValueError:
                continue
            if d.get("method_version") == TERRAIN_METHOD:
                terrain[r["candidate_id"]] = d
        try:
            for r in conn.execute(
                    f"SELECT * FROM candidate_land_cover_v2 WHERE candidate_id IN ({q})",
                    chunk):
                lc[r["candidate_id"]] = r
        except sqlite3.OperationalError:
            pass
    conn.close()

    blocked = {k: 0 for k in CHECKS}
    for p in pop:
        d, res = p["d"], {}
        res["reproduced"] = (d.get("reproduced") is True
                             and d.get("dem_source") == "LIVE"
                             and d.get("dem_type") == "SRTMGL1")
        xc = d.get("dem_cross_check") or {}
        res["cop30"] = xc.get("tested") is True and xc.get("confirmed") is True
        st = d.get("stability") or {}
        fet, det = st.get("n_windows_fetched"), st.get("n_windows_detected")
        res["stability"] = (isinstance(fet, int) and fet >= 1 and det == fet)
        row = lc.get(p["id"])
        res["landcover"] = (row is not None
                            and (row["centre_valid"] or 0) >= lcf.CENTRE_MIN_VALID
                            and lcf.flag_reason_v2(row) is None)
        if p["target"] == MOUND_TELL:
            res["hillside"] = (terrain.get(p["id"]) or {}).get("hillside") == "No"
        else:
            res["hillside"] = True
        sg = d.get("steward_gate") or {}
        es, aq = sg.get("effective_sources"), sg.get("avg_quality")
        res["steward"] = (isinstance(es, (int, float)) and isinstance(aq, (int, float))
                          and es >= EFFECTIVE_SOURCES_MIN and aq >= AVG_QUALITY_MIN)
        ind = industrial_index.check(p["lat"], p["lon"])
        res["industrial"] = ind["status"] == industrial_index.STATUS_CLEAR
        p["ind_text"] = ind["text"]
        for k in CHECKS:
            if not res[k]:
                blocked[k] += 1
        p["res"] = res
        p["pass"] = all(res.values())
        ks = known_sites.annotate(p["lat"], p["lon"])
        p["near"] = ks.get("label") == known_sites.LABEL_NEAR
        p["site_text"] = ks.get("text", "")

    near = [p for p in pop if p["near"]]
    rest = [p for p in pop if not p["near"]]
    a = sum(p["pass"] for p in near)
    b = len(near) - a
    c = sum(p["pass"] for p in rest)
    dd = len(rest) - c
    total_pass = a + c

    print(f"\nPopulation: {len(pop)} refined candidates "
          f"(near a recorded site: {len(near)}, rest: {len(rest)})")
    print(f"cc-v1 passes: near {a} of {len(near)}   rest {c} of {len(rest)}")
    print("\nBlocked by each check (a candidate can fail several):")
    for k in CHECKS:
        print(f"  {k:<11} {blocked[k]}")

    print("\nPer candidate (R=reproduced C=cop30 S=stability L=landcover "
          "H=hillside W=steward I=industrial; + pass, - fail):")
    for p in sorted(pop, key=lambda x: (not x["near"], x["job"], x["id"])):
        flags = "".join(("+" if p["res"][k] else "-") for k in CHECKS)
        tag = "NEAR" if p["near"] else "    "
        print(f"  {p['id'][:8]} {p['job']} {tag} {flags} "
              f"{'PASS' if p['pass'] else 'fail'}  {p['lat']:.5f},{p['lon']:.5f}")
        if p["near"] or p["pass"]:
            print(f"      site: {p['site_text']}")
        if not p["res"]["industrial"]:
            print(f"      industrial: {p['ind_text']}")

    if len(near) < MIN_NEAR or total_pass == 0:
        why = (f"only {len(near)} near-site refined candidates (need {MIN_NEAR})"
               if len(near) < MIN_NEAR else "0 candidates pass cc-v1")
        verdict = f"NOT ENOUGH DATA ({why})"
    else:
        pval = fisher_one_sided(a, b, c, dd)
        rate_near, rate_rest = a / len(near), (c / len(rest) if rest else 0.0)
        print(f"\nPass rate near {rate_near:.1%}  rest {rate_rest:.1%}  "
              f"one-sided Fisher p = {pval:.4g}")
        verdict = "PASS" if (rate_near > rate_rest and pval < ALPHA) else "FAIL"
    print(f"\nVERDICT T2: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
