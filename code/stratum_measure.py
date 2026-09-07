#!/usr/bin/env python3
"""
Measure a sample of the packages the maintainer crawl reached, so the third
stratum of the population has an observed rate rather than a bound.

STRATA, after enumeration reached 95.1%
    A  score-ordered search frame        5,250   63.8%   measured, n=400
    B  free-text term expansion          1,290   15.7%   measured, n=250
    C  maintainer partition crawl        1,293   15.7%   this script, n=250
    D  reached by nothing                  405    4.9%   bounded

    python3 stratum_measure.py fetch [seconds]
    python3 stratum_measure.py report
"""
import datetime as dt, io, json, math, os, random, sys, tarfile, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = "/tmp/mcpres/stratum_c_state.json"
UA = {"User-Agent": "mcp-supply-chain-study/0.4 (research)"}
N, SEED = 250, 20260907


def stratum_c():
    complete = set(json.load(open(os.path.join(HERE, "npm_frame_complete.json"))))
    wide = set(json.load(open(os.path.join(HERE, "npm_frame_wide_6540.json"))))
    c = sorted(complete - wide)
    random.Random(SEED).shuffle(c)
    return c[:N]


def load():
    return json.load(open(STATE)) if os.path.exists(STATE) else {}


def fetch(budget):
    s, t0 = load(), time.time()
    todo = [n for n in stratum_c() if n not in s]
    print(f"stratum C sample: {len(todo)} remaining of {N}")
    for i, n in enumerate(todo):
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
            tm, vers = d.get("time", {}), list(d.get("versions", {}))
            last = max((tm[v] for v in vers if v in tm), default=None)
            last_days = None
            if last:
                last_days = (dt.datetime.now(dt.timezone.utc)
                             - dt.datetime.fromisoformat(last.replace("Z", "+00:00"))).days
            raw = urllib.request.urlopen(urllib.request.Request(
                (meta.get("dist") or {}).get("tarball"), headers=UA), timeout=60).read()
            with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
                fn = tf.getnames()
            s[n] = {"declared": lic, "n_versions": len(vers), "last_days": last_days,
                    "license_files": [x for x in fn if "licen" in x.lower() or "copying" in x.lower()]}
        except Exception as e:
            s[n] = {"error": type(e).__name__}
        if i % 25 == 0:
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            json.dump(s, open(STATE, "w")); print(f"  {i}/{len(todo)}", flush=True)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w"))
    ok = sum(1 for v in s.values() if "error" not in v)
    print(f"done: {ok} ok, {len(s)-ok} errors")


def pm(k, n):
    p = k / n
    return 1.96 * math.sqrt(p * (1 - p) / n) * 100


def z2(a, na, b, nb):
    p1, p2 = a / na, b / nb
    p = (a + b) / (na + nb)
    return (p1 - p2) / math.sqrt(p * (1 - p) * (1 / na + 1 / nb))


def report():
    POP = 8238
    complete = set(json.load(open(os.path.join(HERE, "npm_frame_complete.json"))))
    wide = set(json.load(open(os.path.join(HERE, "npm_frame_wide_6540.json"))))
    NA, NB, NC = 5250, len(wide) - 5250, len(complete - wide)
    ND = POP - NA - NB - NC

    v2 = json.load(open(os.path.join(HERE, "mcp-study-v2-data.json")))
    tb = v2["npm_tarballs"]; tb = list(tb.values()) if isinstance(tb, dict) else tb
    meta = v2["npm_stage1_metadata"]
    B = [v for v in json.load(open("/tmp/mcpres/frame_bias_state.json")).values() if "error" not in v]
    C = [v for v in load().values() if "error" not in v]

    metrics = {
        "no license file": (
            sum(1 for r in tb if not r.get("license_files")), len(tb),
            sum(1 for r in B if not r["license_files"]), len(B),
            sum(1 for r in C if not r["license_files"]), len(C), (36.4, 50.0)),
        "declares, no text": (
            sum(1 for r in tb if r.get("declared") and not r.get("license_files")), len(tb),
            sum(1 for r in B if r["declared"] and not r["license_files"]), len(B),
            sum(1 for r in C if r["declared"] and not r["license_files"]), len(C), (36.0, 49.2)),
        "exactly one version": (
            sum(1 for r in meta if r.get("n_versions") == 1), len(meta),
            sum(1 for r in B if r["n_versions"] == 1), len(B),
            sum(1 for r in C if r["n_versions"] == 1), len(C), (26.4, 21.2)),
        "released last 30 days": (
            sum(1 for r in meta if r.get("rel30", 0) > 0), len(meta),
            sum(1 for r in B if r["last_days"] is not None and r["last_days"] <= 30), len(B),
            sum(1 for r in C if r["last_days"] is not None and r["last_days"] <= 30), len(C), (11.6, 16.4)),
    }

    print(f"strata  A={NA} ({100*NA/POP:.1f}%)  B={NB} ({100*NB/POP:.1f}%)  "
          f"C={NC} ({100*NC/POP:.1f}%)  D={ND} ({100*ND/POP:.1f}%)\n")
    print(f"{'metric':23s} {'A':>7s} {'B':>7s} {'C':>7s} {'corrected':>10s} "
          f"{'bounds':>16s} {'eslint':>7s} {'langchain':>10s}")
    print("-" * 96)
    out = {"strata": {"A": NA, "B": NB, "C": NC, "D": ND, "population": POP}}
    for k, (a, na, b, nb, c, nc, ctl) in metrics.items():
        pA, pB, pC = a / na, b / nb, c / nc
        obs = NA * pA + NB * pB + NC * pC
        corrected = obs / (NA + NB + NC)
        lo, hi = obs / POP, (obs + ND) / POP
        print(f"{k:23s} {100*pA:6.1f}% {100*pB:6.1f}% {100*pC:6.1f}% {100*corrected:9.1f}% "
              f"[{100*lo:5.1f},{100*hi:5.1f}] {ctl[0]:7.1f}% {ctl[1]:9.1f}%")
        out[k] = {"A": [a, na], "B": [b, nb], "C": [c, nc],
                  "corrected": round(100 * corrected, 1),
                  "bounds": [round(100 * lo, 1), round(100 * hi, 1)],
                  "eslint": ctl[0], "langchain": ctl[1],
                  "z_C_vs_A": round(z2(a, na, c, nc), 2)}
    json.dump(out, open(os.path.join(HERE, "frame_corrected_95.json"), "w"), indent=1)
    print("\nwrote frame_corrected_95.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 480) if m == "fetch" else report()
