#!/usr/bin/env python3
"""
Resolve the study corpus into a CRA-shaped component inventory.

WHY THIS EXISTS
    The frame study counts packages. The CRA question is about COMPONENTS a
    product ingests, which is a different unit: a package present in one tree and
    a package present in two hundred are one row each in a package-level table
    and are completely different exposures to a manufacturer. This builds the
    inventory the group's question actually needs, keyed on the component and
    carrying how often it is ingested, how deep it sits, how long since its
    project last shipped anything, and whether an advisory against it has a fix.

WHAT IS FIXED AND WHY
    Tree membership is read from the published resolved trees and is NOT
    re-resolved. Re-resolving against a later registry would change the corpus
    and the question in the same step, and the published corpus is the one every
    released figure refers to.

    Staleness is measured on the most recent release of ANY version of the
    package, not the installed version. A package pinned at an old version but
    still publishing is maintained; the installed version being old is a property
    of the depender, not of the project.

    Depth is the shortest edge distance from a tree's root, computed by
    breadth-first traversal over the published node set using each installed
    version's declared dependencies. Edges pointing outside the published set are
    counted and reported rather than dropped silently.

    Thresholds are 180, 365 and 730 days, all three reported together, per
    PREREGISTRATION-2.md. This script does not select among them.

    python3 cra_components.py fetch [seconds]
    python3 cra_components.py build
"""
import collections, datetime as dt, json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TREES = os.path.join(HERE, "..", "data", "nested_gap.json")
if not os.path.exists(TREES):
    TREES = "/tmp/mcpres/nested_gap.json"
STATE = "/tmp/mcpres/component_packuments_full.json"
OUT = os.path.join(HERE, "cra_components.json")
# The abbreviated packument (application/vnd.npm.install-v1+json) is smaller and
# carries dependency data, but it has NO `time` field, so every release date came
# back null on the first run and the inventory reported 2,373 of 2,373 names
# without a release date. Staleness is the whole point of this table, so the full
# document is fetched and immediately reduced to the two things needed.
UA = {"User-Agent": "mcp-supply-chain-study/0.6 (academic research)"}
THRESHOLDS = (180, 365, 730)


def split(e):
    i = e.rfind("@@")
    return e[:i], e[i + 2:]


def corpus():
    """name -> (root pair, [(name, version), ...]). The root is the server
    package itself, taken from the tree record rather than guessed."""
    s = json.load(open(TREES))
    trees = {}
    for name, v in s.items():
        arr = v.get("installed") or []
        if arr:
            trees[name] = ((name, v.get("root_version")), [split(e) for e in arr])
    return trees


def fetch(budget):
    trees = corpus()
    names = sorted({n for _, rows in trees.values() for n, _ in rows})
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    todo = [n for n in names if n not in s]
    print(f"{len(names)} distinct component names, {len(todo)} to fetch")
    t0 = time.time()
    for i, n in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        url = "https://registry.npmjs.org/" + urllib.parse.quote(n, safe="")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=30) as r:
                d = json.load(r)
            # keep only what the inventory needs
            vers = d.get("versions") or {}
            tm = d.get("time") or {}
            s[n] = {
                "latest_release": max((t for k, t in tm.items()
                                       if k not in ("created", "modified")), default=None),
                "deps": {v: {"d": (m.get("dependencies") or {}),
                             "o": (m.get("optionalDependencies") or {}),
                             "p": {k: r_ for k, r_ in (m.get("peerDependencies") or {}).items()
                                   if not ((m.get("peerDependenciesMeta") or {}).get(k) or {}).get("optional")}}
                         for v, m in vers.items()},
                "deprecated": sorted(v for v, m in vers.items() if (m or {}).get("deprecated")),
            }
        except Exception as e:
            s[n] = {"error": type(e).__name__}
        if i % 100 == 0:
            json.dump(s, open(STATE, "w"))
            print(f"  {i}/{len(todo)}", flush=True)
        time.sleep(0.05)
    json.dump(s, open(STATE, "w"))
    ok = sum(1 for v in s.values() if "error" not in v)
    print(f"\nhave {ok} of {len(s)} ({sum(1 for v in s.values() if 'error' in v)} errors)")


def depths(rows, pk, root):
    """Shortest edge distance from the root over the published node set.

    The root is passed in. An earlier version took rows[0], but the published
    node lists are sorted alphabetically rather than root-first, so the traversal
    started from an arbitrary package and left 18,337 of 22,943 nodes
    unreachable. The unreachable counter is what surfaced it.
    """
    have = {(n, v) for n, v in rows}
    byname = collections.defaultdict(set)
    for n, v in rows:
        byname[n].add(v)
    if root not in have:
        return {}, 0, len(have)
    d = {root: 0}
    q = collections.deque([root])
    external = 0
    while q:
        cur = q.popleft()
        n, v = cur
        meta = ((pk.get(n) or {}).get("deps") or {}).get(v) or {}
        for grp in ("d", "o", "p"):
            for dn in (meta.get(grp) or {}):
                cands = byname.get(dn)
                if not cands:
                    external += 1
                    continue
                for dv in cands:
                    if (dn, dv) not in d:
                        d[(dn, dv)] = d[cur] + 1
                        q.append((dn, dv))
    unreached = len(have) - len(d)
    return d, external, unreached


def build():
    trees = corpus()
    pk = json.load(open(STATE))
    now = dt.datetime.now(dt.timezone.utc)
    age = {}
    for n, v in pk.items():
        t = v.get("latest_release")
        if t:
            try:
                age[n] = (now - dt.datetime.fromisoformat(t.replace("Z", "+00:00"))).days
            except Exception:
                pass
    ingest = collections.Counter()
    node_rows = []
    ext_total = unreach_total = 0
    for root, (rootpair, rows) in trees.items():
        for n, _ in {(n, None) for n, _ in rows}:
            ingest[n] += 1
        dmap, ext, unre = depths(rows, pk, rootpair)
        ext_total += ext
        unreach_total += unre
        for (n, v) in rows:
            node_rows.append({"tree": root, "name": n, "version": v,
                              "depth": dmap.get((n, v)), "age": age.get(n)})
    out = {"trees": len(trees), "node_instances": len(node_rows),
           "distinct_names": len(ingest),
           "names_without_release_date": sum(1 for n in ingest if n not in age),
           "edges_outside_published_set": ext_total,
           "nodes_unreachable_from_root": unreach_total,
           "thresholds_days": list(THRESHOLDS),
           "ingestion": dict(ingest.most_common())}
    json.dump({"summary": out, "nodes": node_rows}, open(OUT, "w"))
    print(json.dumps(out, indent=1)[:800])
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "build"
    fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 600) if m == "fetch" else build()
