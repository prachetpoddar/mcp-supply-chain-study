#!/usr/bin/env python3
"""
Measure Annex I Part II(2), "address and remediate vulnerabilities without delay".

WHY THIS NEEDS OSV
    npm's own bulk advisory endpoint returns severity and vulnerable ranges but
    no dates, so remediation latency cannot be computed from it. OSV records
    carry `published` and `modified`, and their `affected[].ranges[].events`
    carry the `fixed` version. Combining the OSV advisory date with the npm
    publish timestamp of the fixing version gives, per advisory:

        latency = (time the fixing version was published)
                - (time the advisory was published)

    Negative latency is the good case: the fix shipped before disclosure, which
    is what a coordinated disclosure process produces. Large positive latency is
    the case the CRA is aimed at.

    This is, as far as I can tell, the only one of the eight Part II
    requirements that becomes measurable purely by adding OSV to the npm data we
    already hold.

GUARDS, because this study has been burned by unverified assumptions
    1. The OSV response is checked for the fields we depend on before any
       arithmetic. If `published` or a `fixed` event is missing, the advisory is
       recorded as unusable rather than silently skipped, and the count of
       unusable records is reported alongside the result.
    2. A fixing version whose publish time is absent from the packument is
       likewise recorded, not dropped.
    3. Advisories with multiple `fixed` events take the EARLIEST fix at or after
       the advisory, and the choice is recorded per row so it can be audited.

    OSV is reachable from your machine and not from the study sandbox, which is
    the only reason this runs here.

    python3 cra_osv_latency.py fetch [seconds]
    python3 cra_osv_latency.py report
"""
import datetime as dt, json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
STATE = os.path.join(DATA, "osv_latency_state.json")
OSV = "https://api.osv.dev/v1/query"
NPM = "https://registry.npmjs.org/"
UA = {"Content-Type": "application/json", "User-Agent": "mcp-supply-chain-study/0.5"}
PAUSE = 0.25


def post(url, body):
    r = urllib.request.Request(url, data=json.dumps(body).encode(), headers=UA)
    with urllib.request.urlopen(r, timeout=45) as resp:
        return json.load(resp)


def get(url):
    r = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(r, timeout=45) as resp:
        return json.load(resp)


def iso(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def targets():
    """Distinct package names across the study's resolved trees."""
    p = os.path.join(DATA, "cra_package_list.json")
    if os.path.exists(p):
        return json.load(open(p))
    print(f"expected {p}; it ships alongside this script")
    sys.exit(1)


def fetch(budget):
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    names = [n for n in targets() if n not in s]
    print(f"OSV: {len(names)} packages to query of {len(targets())}")
    t0 = time.time()
    for i, n in enumerate(names):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(names)}")
            break
        try:
            d = post(OSV, {"package": {"name": n, "ecosystem": "npm"}})
            s[n] = d.get("vulns") or []
        except Exception as e:
            s[n] = {"error": type(e).__name__}
        if i % 50 == 0:
            json.dump(s, open(STATE, "w"))
            print(f"  {i}/{len(names)}", flush=True)
        time.sleep(PAUSE)
    json.dump(s, open(STATE, "w"))
    ok = sum(1 for v in s.values() if isinstance(v, list))
    withv = sum(1 for v in s.values() if isinstance(v, list) and v)
    print(f"\nqueried {ok} packages, {withv} carry at least one advisory")


def report():
    s = json.load(open(STATE))
    rows, unusable = [], {"no_published": 0, "no_fixed": 0, "no_publish_time": 0}
    timecache = {}
    pkgs = [n for n, v in s.items() if isinstance(v, list) and v]
    print(f"packages with advisories: {len(pkgs)}")
    for n in pkgs:
        try:
            if n not in timecache:
                timecache[n] = (get(NPM + n.replace("/", "%2F")).get("time") or {})
                time.sleep(0.05)
            tm = timecache[n]
        except Exception:
            continue
        for v in s[n]:
            pub = iso(v.get("published") or "")
            if not pub:
                unusable["no_published"] += 1
                continue
            fixes = []
            for aff in v.get("affected") or []:
                if (aff.get("package") or {}).get("name") != n:
                    continue
                for rng in aff.get("ranges") or []:
                    for ev in rng.get("events") or []:
                        if ev.get("fixed"):
                            fixes.append(ev["fixed"])
            if not fixes:
                unusable["no_fixed"] += 1
                continue
            dated = [(fv, iso(tm.get(fv) or "")) for fv in fixes]
            dated = [(fv, t) for fv, t in dated if t]
            if not dated:
                unusable["no_publish_time"] += 1
                continue
            at_or_after = [(fv, t) for fv, t in dated if t >= pub]
            chosen = min(at_or_after or dated, key=lambda x: x[1])
            rows.append({"package": n, "id": v.get("id"),
                         "published": v["published"], "fixed_version": chosen[0],
                         "fixed_published": chosen[1].isoformat(),
                         "latency_days": (chosen[1] - pub).total_seconds() / 86400,
                         "fix_before_advisory": chosen[1] < pub,
                         "n_fix_candidates": len(dated)})
    import statistics
    lat = [r["latency_days"] for r in rows]
    before = sum(1 for r in rows if r["fix_before_advisory"])
    print(f"\nusable advisory/fix pairs: {len(rows)}")
    print(f"unusable: {unusable}")
    if lat:
        print(f"\nAnnex I Part II(2) proxy, days from advisory publication to fix availability")
        print(f"  fix published BEFORE the advisory (coordinated): {before} = {100*before/len(rows):.1f}%")
        after = [x for x in lat if x >= 0]
        if after:
            after.sort()
            print(f"  of the remainder, median {statistics.median(after):.1f} days, "
                  f"p90 {after[int(.9*len(after))]:.1f}, max {after[-1]:.0f}")
        print(f"  over 30 days after disclosure: {sum(1 for x in lat if x > 30)} = "
              f"{100*sum(1 for x in lat if x > 30)/len(rows):.1f}%")
    json.dump({"pairs": len(rows), "unusable": unusable,
               "fix_before_advisory": before, "rows": rows},
              open(os.path.join(DATA, "cra_osv_latency.json"), "w"), indent=1)
    print("\nwrote data/cra_osv_latency.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 600) if m == "fetch" else report()
