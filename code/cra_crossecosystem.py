#!/usr/bin/env python3
"""
Does the top-level SBOM gap generalise beyond npm?

THE QUESTION
    The npm finding is that a top-level SBOM names a median 2.2% of what an
    install materialises. The first challenge anyone will make is that deep
    transitive trees are an npm pathology. This tests that directly across the
    ecosystems deps.dev covers.

WHY THE ANSWER IS NOT AUTOMATICALLY COMPARABLE, AND MUST BE STATED
    Each ecosystem resolves differently, and the differences are not cosmetic:

      npm     nests conflicting versions, so one name can appear twice
      Maven   "nearest wins" conflict mediation, one version per coordinate
      PyPI    a flat environment; two versions of a package CANNOT coexist
      Go      minimal version selection; takes the lowest version satisfying all
      Cargo   allows semver-incompatible majors side by side, like npm

    So a raw ratio comparison across ecosystems compares different objects. PyPI
    physically cannot produce npm's duplicate structure. Go deliberately picks
    low where npm picks high.

    The honest output is therefore per-ecosystem, with the resolution model
    named, and NOT a single cross-ecosystem number. If the ratios turn out
    similar despite the models differing, that is a stronger result than any
    average would be.

CALIBRATION REQUIREMENT
    For npm we validated deps.dev against a real `npm install`: the advisory
    verdict differed on 0.8% of servers. We have no equivalent check for the
    other ecosystems, so their figures are deps.dev's view, not a validated
    install. Report them as such. Anyone quoting a Maven number as "what
    installs" without a `mvn dependency:tree` check is repeating our own mistake
    in a new ecosystem.

    python3 cra_crossecosystem.py sample     pick packages per ecosystem
    python3 cra_crossecosystem.py fetch [s]  query deps.dev, resumable
    python3 cra_crossecosystem.py report
"""
import json, os, statistics, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
STATE = os.path.join(DATA, "crossecosystem_state.json")
SAMPLE = os.path.join(DATA, "crossecosystem_sample.json")
API = "https://api.deps.dev/v3alpha"
UA = {"User-Agent": "mcp-supply-chain-study/0.5 (academic research)"}
PAUSE = 0.35

MODELS = {"npm": "nests conflicting versions", "maven": "nearest-wins, one per coordinate",
          "pypi": "flat environment, no duplicates possible",
          "go": "minimal version selection", "cargo": "majors coexist",
          "nuget": "nearest-wins"}


def get(path):
    for a in range(4):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(API + path, headers=UA), timeout=45) as r:
                return json.load(r)
        except Exception as e:
            if getattr(e, "code", None) == 404:
                return None
            if a == 3:
                raise
            time.sleep(2 ** a)


def enc(s):
    return urllib.parse.quote(s, safe="")


def fetch(budget):
    samp = json.load(open(SAMPLE))
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    todo = [(e, n, v) for e, rows in samp.items() for n, v in rows
            if f"{e}|{n}|{v}" not in s]
    print(f"deps.dev: {len(todo)} package versions to query")
    t0 = time.time()
    for i, (eco, name, ver) in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        key = f"{eco}|{name}|{ver}"
        try:
            dep = get(f"/systems/{eco}/packages/{enc(name)}/versions/{enc(ver)}:dependencies")
            if dep is None:
                s[key] = {"ok": False, "reason": "404"}
            else:
                nodes = [(nd.get("versionKey") or {}) for nd in dep.get("nodes", [])]
                pairs = [(k.get("name"), k.get("version")) for k in nodes
                         if k.get("name") and k.get("version")]
                # direct edges are those from the root node, index 0 by convention
                direct = {e.get("toNode") for e in dep.get("edges", [])
                          if e.get("fromNode") == 0}
                s[key] = {"ok": True, "n_nodes": len(pairs),
                          "n_direct": len(direct),
                          "distinct_names": len({p[0] for p in pairs})}
        except Exception as e:
            s[key] = {"ok": False, "reason": type(e).__name__}
        if i % 25 == 0:
            json.dump(s, open(STATE, "w"))
            print(f"  {i}/{len(todo)}", flush=True)
        time.sleep(PAUSE)
    json.dump(s, open(STATE, "w"))
    print(f"done: {sum(1 for v in s.values() if v.get('ok'))} resolved of {len(s)}")


def report():
    s = json.load(open(STATE))
    by = {}
    for key, v in s.items():
        if not v.get("ok") or not v.get("n_nodes"):
            continue
        eco = key.split("|", 1)[0]
        by.setdefault(eco, []).append(v)
    print(f"{'ecosystem':10s} {'n':>5s} {'direct':>7s} {'nodes':>7s} {'share named':>12s}  resolution model")
    print("-" * 88)
    out = {}
    for eco, rows in sorted(by.items()):
        share = [100 * r["n_direct"] / r["n_nodes"] for r in rows if r["n_nodes"]]
        if not share:
            continue
        share.sort()
        d = statistics.median([r["n_direct"] for r in rows])
        n = statistics.median([r["n_nodes"] for r in rows])
        print(f"{eco:10s} {len(rows):5d} {d:7.0f} {n:7.0f} {statistics.median(share):11.1f}%  "
              f"{MODELS.get(eco,'?')}")
        out[eco] = {"n": len(rows), "median_direct": d, "median_nodes": n,
                    "median_share_pct": round(statistics.median(share), 1),
                    "mean_share_pct": round(statistics.mean(share), 1),
                    "resolution_model": MODELS.get(eco),
                    "validated_against_real_install": eco == "npm"}
    out["_caveat"] = ("deps.dev's published graph. Validated against a real install for "
                      "npm only. Other ecosystems are deps.dev's view and must not be "
                      "described as what installs until each is checked against its own "
                      "package manager.")
    json.dump(out, open(os.path.join(DATA, "cra_crossecosystem.json"), "w"), indent=1)
    print("\nwrote data/cra_crossecosystem.json")
    print("\nREAD THIS BEFORE QUOTING: only the npm row is validated against a real")
    print("install. The others are deps.dev's resolution and each ecosystem resolves")
    print("differently; PyPI cannot nest at all and Go picks minimum versions.")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    if m == "fetch":
        fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 600)
    elif m == "report":
        report()
    else:
        print("run `sample` yourself: put {ecosystem: [[name, version], ...]} in")
        print(f"{SAMPLE}\nEcosystems deps.dev supports: {', '.join(MODELS)}")
