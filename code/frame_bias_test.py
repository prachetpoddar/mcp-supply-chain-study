#!/usr/bin/env python3
"""
Measure the npm search-frame bias directly instead of bounding it.

THE PROBLEM
    Our MCP frame is 5,250 of 8,227 packages, 63.8% coverage, drawn in search
    score order. Section 6 shows such a frame is a top-slice and Section 8
    downgrades four rows to bounds because of it. Worst-case identification
    bounds are uselessly wide: assuming every out-of-frame package is bad puts
    the population license-file-absence rate anywhere in [14.2, 50.4], which
    spans both control values. Hedging cannot settle this. Measurement can.

THE TEST
    Query partitioning reached 6,540 packages, 79.5% coverage. 1,289 of those
    are absent from the score-ordered frame. They are, by construction, packages
    the top-slice missed. If they look like the in-frame sample, the top-slice
    bias on these metrics is small and the four bounded rows become estimates.
    If they are worse, the size of the gap gives a correction rather than a
    guess.

    This is not a perfect test. The partitioned frame is itself 79.5%, not
    100%, so the remaining 1,687 packages are unobserved by both. But it moves
    the unidentified mass from 36.2 points to 20.5, and it measures the part
    that was previously only assumed.

    python3 frame_bias_test.py fetch [seconds]
    python3 frame_bias_test.py report
"""
import io, json, math, os, random, sys, tarfile, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = "/tmp/mcpres/frame_bias_state.json"
UA = {"User-Agent": "mcp-supply-chain-study/0.2 (research)"}
N = 250
SEED = 20260907


def increment():
    """Names in the partitioned frame but not in the score-ordered one."""
    wide = set(json.load(open(os.path.join(HERE, "npm_frame_wide_6540.json"))))
    seen = set()

    def collect(o):
        if isinstance(o, dict):
            for v in o.values():
                collect(v)
        elif isinstance(o, list):
            for x in o:
                if isinstance(x, str):
                    seen.add(x)
                elif isinstance(x, dict) and "name" in x:
                    seen.add(x["name"])
                else:
                    collect(x)

    collect(json.load(open(os.path.join(HERE, "mcp-substitutability.json"))))
    inc = sorted(wide - seen)
    random.Random(SEED).shuffle(inc)
    return inc[:N]


def load():
    return json.load(open(STATE)) if os.path.exists(STATE) else {}


def fetch(budget):
    s, t0 = load(), time.time()
    todo = [n for n in increment() if n not in s]
    print(f"out-of-frame sample: {len(todo)} remaining of {N}")
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
            tm = d.get("time", {})
            vers = [v for v in d.get("versions", {})]
            last = max((tm[v] for v in vers if v in tm), default=None)
            import datetime as dt
            last_days = None
            if last:
                last_days = (dt.datetime.now(dt.timezone.utc)
                             - dt.datetime.fromisoformat(last.replace("Z", "+00:00"))).days
            url = (meta.get("dist") or {}).get("tarball")
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
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
    print(f"done: {ok} ok, {len(s)-ok} errors, {len(s)} total")


def pm(k, n):
    p = k / n
    return 1.96 * math.sqrt(p * (1 - p) / n) * 100


def z2(a, na, b, nb):
    p1, p2 = a / na, b / nb
    p = (a + b) / (na + nb)
    return (p1 - p2) / math.sqrt(p * (1 - p) * (1 / na + 1 / nb))


def report():
    s = load()
    rows = [v for v in s.values() if "error" not in v]
    n = len(rows)
    v2 = json.load(open(os.path.join(HERE, "mcp-study-v2-data.json")))
    tb = v2["npm_tarballs"]
    tb = list(tb.values()) if isinstance(tb, dict) else tb
    meta = v2["npm_stage1_metadata"]

    tests = {
        "no license file": (sum(1 for r in tb if not r.get("license_files")), len(tb),
                            sum(1 for r in rows if not r["license_files"]), n),
        "declares, no text": (sum(1 for r in tb if r.get("declared") and not r.get("license_files")), len(tb),
                              sum(1 for r in rows if r["declared"] and not r["license_files"]), n),
        "exactly one version": (sum(1 for r in meta if r.get("n_versions") == 1), len(meta),
                                sum(1 for r in rows if r["n_versions"] == 1), n),
        "released last 30 days": (sum(1 for r in meta if r.get("rel30", 0) > 0), len(meta),
                                  sum(1 for r in rows if r["last_days"] is not None and r["last_days"] <= 30), n),
    }
    out = {}
    print(f"\n{'metric':24s} {'in-frame':>16s} {'out-of-frame':>18s} {'z':>7s}")
    print("-" * 70)
    for k, (a, na, b, nb) in tests.items():
        z = z2(a, na, b, nb)
        print(f"{k:24s} {100*a/na:6.1f}% ±{pm(a,na):.1f} (n={na}) "
              f"{100*b/nb:6.1f}% ±{pm(b,nb):.1f} (n={nb}) {z:+7.2f}")
        out[k] = {"in_frame": [a, na, round(100*a/na, 1)],
                  "out_of_frame": [b, nb, round(100*b/nb, 1)], "z": round(z, 2)}
    json.dump(out, open(os.path.join(HERE, "frame_bias_result.json"), "w"), indent=1)
    print("\nwrote frame_bias_result.json")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    if mode == "fetch":
        fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 480)
    else:
        report()
