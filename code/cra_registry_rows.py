#!/usr/bin/env python3
"""
CRA rows measurable from the npm registry alone, on the study's stratified frame.

WHAT THIS MEASURES
    Annex I Part II(7), distribute security updates securely:
        - registry signature present (npm applies these by default)
        - SLSA build provenance attestation present
          (dist.attestations.provenance.predicateType = slsa.dev/provenance/v1,
           verified by hand against sigstore, zod and the MCP SDK)
      The gap between the two is the finding: a naive check on "is it signed"
      reports near-total compliance, while provenance, which is what actually
      establishes where an artefact came from, is a minority.

    Article 13(8), defined support period, by proxy:
        - age of the latest release
      A registry cannot show a declared support period, so recency of
      maintenance is the available proxy and is labelled as one.

WHY STRATIFIED
    An earlier pilot drew packages at random from the enumerated frame. That
    carries no coverage correction, so it could not be compared with the
    paper's other rows. This uses the same strata as everything else:

        A  score-ordered search frame      5,250
        B  free-text term expansion        1,290
        C  maintainer partition crawl      1,293
        D  reached by nothing                400   bounded, never observed

    and the same estimator: a stratified point estimate over the observed
    strata, with Manski bounds putting stratum D at both extremes.

    python3 cra_registry_rows.py fetch [seconds]
    python3 cra_registry_rows.py report
"""
import datetime as dt, json, os, random, statistics, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = "/tmp/mcpres/cra_registry_rows.json"
SEED = 20260908
NA, POP = 5250, 8238
SLSA = "https://slsa.dev/provenance/v1"


def strata():
    comp = set(json.load(open(os.path.join(HERE, "npm_frame_complete.json"))))
    wide = set(json.load(open(os.path.join(HERE, "npm_frame_wide_6540.json"))))
    orig = set()

    def collect(o):
        if isinstance(o, dict):
            for v in o.values():
                collect(v)
        elif isinstance(o, list):
            for x in o:
                if isinstance(x, str):
                    orig.add(x)
                elif isinstance(x, dict) and "name" in x:
                    orig.add(x["name"])
                else:
                    collect(x)
    collect(json.load(open(os.path.join(HERE, "mcp-substitutability.json"))))
    A = sorted(orig & comp)
    B = sorted((wide - orig) & comp)
    C = sorted(comp - wide)
    r = random.Random(SEED)
    for x in (A, B, C):
        r.shuffle(x)
    NAS=int(os.environ.get("CRA_NA","400")); NBS=int(os.environ.get("CRA_NB","250")); NCS=int(os.environ.get("CRA_NC","250"))
    return {"A": A[:NAS], "B": B[:NBS], "C": C[:NCS]}, (len(A), len(B), len(C))


def measure(name):
    d = mcplib.npm_packument(name)
    lat = (d.get("dist-tags") or {}).get("latest")
    if not lat:
        return None
    m = (d.get("versions") or {}).get(lat, {}) or {}
    dist = m.get("dist") or {}
    att = dist.get("attestations") or {}
    pred = ((att.get("provenance") or {}).get("predicateType")) if att else None
    t = (d.get("time") or {}).get(lat)
    age = None
    if t:
        try:
            age = (dt.datetime.now(dt.timezone.utc)
                   - dt.datetime.fromisoformat(t.replace("Z", "+00:00"))).days
        except Exception:
            pass
    return {"signed": bool(dist.get("signatures")),
            "provenance": pred == SLSA,
            "attestation_other": bool(att) and pred != SLSA,
            "age_days": age}


def fetch(budget):
    samp, sizes = strata()
    print(f"stratum sizes in frame: A={sizes[0]} B={sizes[1]} C={sizes[2]}")
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    todo = [(st, n) for st, rows in samp.items() for n in rows if n not in s]
    print(f"{len(todo)} packages to read")
    t0 = time.time()
    for i, (st, n) in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        try:
            r = measure(n)
            s[n] = ({"stratum": st, **r} if r else {"stratum": st, "skip": "no latest"})
        except Exception as e:
            s[n] = {"stratum": st, "skip": type(e).__name__}
        if i % 100 == 0:
            json.dump(s, open(STATE, "w"))
            print(f"  {i}/{len(todo)}  net={mcplib.STATS['net']}", flush=True)
    json.dump(s, open(STATE, "w"))
    ok = sum(1 for v in s.values() if "skip" not in v)
    print(f"\nread {ok} of {len(s)}")


def report():
    s = json.load(open(STATE))
    _, sizes = strata()
    NB, NC = 1290, 1293
    ND = POP - (NA + NB + NC)
    by = {"A": [], "B": [], "C": []}
    for v in s.values():
        if "skip" in v:
            continue
        by[v["stratum"]].append(v)
    print(f"strata: A={NA} B={NB} C={NC} unreached={ND} of {POP}")
    print(f"samples: A n={len(by['A'])}  B n={len(by['B'])}  C n={len(by['C'])}\n")
    out = {"strata": {"A": NA, "B": NB, "C": NC, "D": ND, "population": POP},
           "n": {k: len(v) for k, v in by.items()}}

    def row(label, pred):
        p = {k: (sum(1 for v in by[k] if pred(v)) / len(by[k]) if by[k] else 0.0)
             for k in by}
        obs = NA * p["A"] + NB * p["B"] + NC * p["C"]
        corr = obs / (NA + NB + NC)
        lo, hi = obs / POP, (obs + ND) / POP
        print(f"{label:38s} A {100*p['A']:5.1f}%  B {100*p['B']:5.1f}%  C {100*p['C']:5.1f}%"
              f"   corrected {100*corr:5.1f}%  [{100*lo:.1f}, {100*hi:.1f}]")
        out[label] = {"A_pct": round(100*p["A"], 1), "B_pct": round(100*p["B"], 1),
                      "C_pct": round(100*p["C"], 1), "corrected_pct": round(100*corr, 1),
                      "bounds": [round(100*lo, 1), round(100*hi, 1)]}

    print("Annex I Part II(7), secure distribution")
    row("  registry signature present", lambda v: v["signed"])
    row("  SLSA build provenance present", lambda v: v["provenance"])
    print("\nArticle 13(8) proxy, maintenance recency")
    row("  no release in over 6 months", lambda v: (v["age_days"] or 0) > 182)
    row("  no release in over 12 months", lambda v: (v["age_days"] or 0) > 365)
    ages = [v["age_days"] for v in sum(by.values(), []) if v["age_days"] is not None]
    if ages:
        print(f"\n  median age of latest release, pooled sample: "
              f"{statistics.median(ages):.0f} days")
        out["median_age_days_pooled"] = statistics.median(ages)
    out["_note"] = ("stratified over observed strata A/B/C with Manski bounds over the "
                    "unreached stratum D, the same estimator as the paper's other rows. "
                    "Provenance is dist.attestations.provenance.predicateType == "
                    "slsa.dev/provenance/v1. Support period is a proxy: a registry "
                    "cannot show a declared support period.")
    json.dump(out, open(os.path.join(HERE, "cra_registry_rows.json"), "w"), indent=1)
    print("\nwrote cra_registry_rows.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 600) if m == "fetch" else report()
