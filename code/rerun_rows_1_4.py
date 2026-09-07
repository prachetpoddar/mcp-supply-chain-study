#!/usr/bin/env python3
"""
Re-measure paper rows 1 to 4 against the COVERAGE-MATCHED control frames.

WHY THIS EXISTS
    Rows 1 to 4 of the published v1.0.0 table were measured against a
    `keywords:cli` + `keywords:server` frame drawn from the top 2,500 npm
    search results. Section 6 of the paper establishes that such a frame is a
    score-ordered top-slice covering 2.4% of a 104,818-package population, and
    that comparing it against 64% coverage of the MCP population produces
    false positives. Rows 5 to 7 were re-run against coverage-matched frames;
    rows 1 to 4 were not. This script closes that gap.

    The two matched frames are the ones already used for rows 5 to 7:
      keywords:eslint-plugin   7,075 population,  250 sampled,  74% coverage
      keywords:langchain       1,973 population,  250 sampled, 100% coverage

METHOD
    Mirrors mcp_controls.py exactly so the arms remain comparable:
      row 1  ships no license file   tarball contains no path matching
                                     'licen' or 'copying', case-insensitive
      row 2  declares, ships no text manifest `license` set AND no such file
      row 3  deprecated in tree      any node in the resolved install graph
                                     carries a `deprecated` field
      row 4  released in last 30d    last publish within 30 days

    Resumable. State in /tmp/mcpres/rerun_state.json, written after every
    package, so an interrupted run costs nothing.

    python3 rerun_rows_1_4.py tarballs [seconds]
    python3 rerun_rows_1_4.py walks    [seconds]
    python3 rerun_rows_1_4.py report
"""
import io, json, os, sys, tarfile, time, urllib.request, collections, math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib

CONFOUND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp-confound-tests.json")
STATE = "/tmp/mcpres/rerun_state.json"
UA = {"User-Agent": "mcp-supply-chain-study/0.2 (research)"}


def frames():
    c3 = json.load(open(CONFOUND))["control3"]
    return {k: [r["name"] for r in v] for k, v in c3.items()}


def load():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"tarballs": {}, "walks": {}}


def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w"))


def do_tarballs(budget):
    s, t0 = load(), time.time()
    todo = [(f, n) for f, names in frames().items() for n in names if n not in s["tarballs"]]
    print(f"tarballs: {len(todo)} remaining")
    for i, (frame, n) in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}"); break
        try:
            d = mcplib.npm_packument(n)
            lat = d["dist-tags"]["latest"]
            meta = d["versions"][lat]
            lic = meta.get("license")
            if isinstance(lic, dict):
                lic = lic.get("type")
            if isinstance(lic, list):
                lic = " OR ".join(str(x.get("type", x)) for x in lic)
            url = (meta.get("dist") or {}).get("tarball")
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
            with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
                fn = tf.getnames()
            s["tarballs"][n] = {
                "frame": frame, "declared": lic, "files": len(fn),
                "license_files": [x for x in fn if "licen" in x.lower() or "copying" in x.lower()],
            }
        except Exception as e:
            s["tarballs"][n] = {"frame": frame, "error": type(e).__name__}
        if i % 20 == 0:
            save(s); print(f"  {i}/{len(todo)}", flush=True)
    save(s)
    ok = sum(1 for v in s["tarballs"].values() if "error" not in v)
    print(f"tarballs done: {ok} ok, {len(s['tarballs'])-ok} errors, {len(s['tarballs'])} total")


def do_walks(budget):
    s, t0 = load(), time.time()
    todo = [(f, n) for f, names in frames().items() for n in names if n not in s["walks"]]
    print(f"walks: {len(todo)} remaining")
    for i, (frame, n) in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}"); break
        try:
            nodes, st = mcplib.npm_walk(n, "latest")
            s["walks"][n] = {
                "frame": frame, "nodes": len(nodes),
                "deprecated": sum(1 for v in nodes.values() if v.get("deprecated")),
            }
        except Exception as e:
            s["walks"][n] = {"frame": frame, "error": type(e).__name__}
        if i % 10 == 0:
            save(s); print(f"  {i}/{len(todo)}  cache={mcplib.STATS['cache_hit']} net={mcplib.STATS['net']}", flush=True)
    save(s)
    ok = sum(1 for v in s["walks"].values() if "error" not in v)
    print(f"walks done: {ok} ok, {len(s['walks'])-ok} errors, {len(s['walks'])} total")


def wilson_pm(k, n):
    """Half-width of the normal-approximation interval, as the paper reports it."""
    p = k / n
    return 1.96 * math.sqrt(p * (1 - p) / n) * 100


def z2(a, na, b, nb):
    p1, p2 = a / na, b / nb
    p = (a + b) / (na + nb)
    return (p1 - p2) / math.sqrt(p * (1 - p) * (1 / na + 1 / nb))


def report():
    s = load()
    v2 = json.load(open(os.path.join(os.path.dirname(CONFOUND), "mcp-study-v2-data.json")))
    cf = json.load(open(CONFOUND))
    out = {}

    # --- MCP arms, recomputed from raw so the comparison is like for like ---
    tb = v2["npm_tarballs"]
    tb = list(tb.values()) if isinstance(tb, dict) else tb
    m_no_file = sum(1 for r in tb if not r.get("license_files"))
    m_decl_no = sum(1 for r in tb if r.get("declared") and not r.get("license_files"))
    n_tb = len(tb)

    trees = v2["npm_trees"]
    # Per-tree deprecation needs package-level attribution, which the summary
    # rows in mcp-study-v2-data.json do not carry. walk250.jsonl does, and is
    # added to the release alongside this script for exactly that reason.
    WALK = "/tmp/mcpres/walk250.jsonl"
    walk_src = WALK if os.path.exists(WALK) else os.path.join(
        os.path.dirname(CONFOUND), "walk250.jsonl")
    wrows = [json.loads(l) for l in open(walk_src)]
    m_dep = sum(1 for r in wrows if any(v.get("deprecated") for v in r["pkgs"].values()))

    m30 = sum(1 for r in cf["age_profiles"]["mcp"] if r.get("last_days") is not None and r["last_days"] <= 30)

    rows = {}
    for frame in frames():
        tbs = [v for v in s["tarballs"].values() if v.get("frame") == frame and "error" not in v]
        wks = [v for v in s["walks"].values() if v.get("frame") == frame and "error" not in v]
        c30 = sum(1 for r in cf["control3"][frame] if r.get("last_days") is not None and r["last_days"] <= 30)
        rows[frame] = {
            "row1_no_license_file": [sum(1 for v in tbs if not v["license_files"]), len(tbs)],
            "row2_declares_no_text": [sum(1 for v in tbs if v["declared"] and not v["license_files"]), len(tbs)],
            "row3_deprecated_in_tree": [sum(1 for v in wks if v["deprecated"] > 0), len(wks)],
            "row4_released_30d": [c30, len(cf["control3"][frame])],
            "median_tree": sorted(v["nodes"] for v in wks)[len(wks) // 2] if wks else None,
        }

    mcp = {
        "row1_no_license_file": [m_no_file, n_tb],
        "row2_declares_no_text": [m_decl_no, n_tb],
        "row3_deprecated_in_tree": [m_dep, len(trees)],
        "row4_released_30d": [m30, len(cf["age_profiles"]["mcp"])],
    }

    print(f"\n{'row':26s} {'MCP':>18s} {'eslint-plugin':>20s} {'langchain':>20s}")
    print("-" * 88)
    for r in ["row1_no_license_file", "row2_declares_no_text", "row3_deprecated_in_tree", "row4_released_30d"]:
        a, na = mcp[r]
        line = f"{r:26s} {a:4d}/{na:<4d}{100*a/na:6.1f}%  "
        zs = {}
        for frame in ["keywords:eslint-plugin", "keywords:langchain"]:
            b, nb = rows[frame][r]
            z = z2(a, na, b, nb) if nb else float("nan")
            zs[frame] = round(z, 2)
            line += f"{b:4d}/{nb:<4d}{100*b/nb:6.1f}% z={z:+5.2f} "
        print(line)
        out[r] = {"mcp": [a, na, round(100 * a / na, 1), round(wilson_pm(a, na), 1)],
                  "eslint_plugin": rows["keywords:eslint-plugin"][r],
                  "langchain": rows["keywords:langchain"][r],
                  "z": zs}
    out["median_tree"] = {f: rows[f]["median_tree"] for f in rows}
    out["mcp_median_tree"] = sorted(t["nodes"] for t in trees)[len(trees) // 2]
    json.dump(out, open("/mnt/user-data/outputs/rows_1_4_rematched.json", "w"), indent=1)
    print("\nwrote rows_1_4_rematched.json")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else 480
    {"tarballs": lambda: do_tarballs(budget),
     "walks": lambda: do_walks(budget),
     "report": report}[mode]()
