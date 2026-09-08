#!/usr/bin/env python3
"""
Re-fetch every packument the study touches, once, so the whole corpus resolves
against a single dated registry snapshot.

WHY
    mcplib's on-disk cache never expires. Over a multi-day study that means the
    resolver silently answers from a snapshot that drifts further from the
    registry every day, and the drift is uneven: packages looked up early are
    staler than packages looked up late. Measured on 60 corpus packages, 3.3%
    had a newer `latest` than the cache held, all one patch version behind.

    That is small but it is not nothing, and worse, it is not reproducible: a
    reader re-running the study gets different numbers for reasons nothing
    records. Validating against a live `npm install` also charges the staleness
    to the resolver, where it shows up as a bug that is not one.

    This pass re-fetches each distinct package exactly once and stamps the run,
    so downstream walks read a consistent snapshot and the paper can state an
    as-of date.

    python3 refresh_cache.py collect     list the names, no network
    python3 refresh_cache.py run [secs]  re-fetch, resumable
"""
import datetime as dt, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["MCPRES_REFRESH"] = "1"
import mcplib

HERE = os.path.dirname(os.path.abspath(__file__))
DONE = "/tmp/mcpres/refresh_done.json"
STAMP = os.path.join(HERE, "registry_snapshot.json")


def names():
    out = set()

    def add(x):
        if isinstance(x, str) and x:
            out.add(x)

    try:
        ng = json.load(open("/tmp/mcpres/nested_gap.json"))
        for root, g in ng.items():
            add(root)
            if "skip" in g:
                continue
            for k in ("published", "installed"):
                for x in g.get(k, []):
                    add(x.rpartition("@@")[0])
    except Exception:
        pass
    for f, key in (("/tmp/mcpres/rerun_strata.json", None),
                   ("/tmp/mcpres/rerun_tree_rows.json", "arm")):
        try:
            d = json.load(open(f))
            if key:
                for arm, rows in d.items():
                    for n in rows:
                        add(n)
            else:
                for n in d:
                    add(n)
        except Exception:
            pass
    try:
        for t in json.load(open(os.path.join(HERE, "resolved_trees_for_depsdev.json"))):
            add(t["root_name"])
            for n in (t.get("resolved") or {}):
                add(n)
    except Exception:
        pass
    return sorted(out)


def run(budget):
    todo_all = names()
    done = set(json.load(open(DONE))) if os.path.exists(DONE) else set()
    todo = [n for n in todo_all if n not in done]
    print(f"{len(todo_all)} distinct packages, {len(todo)} still to refresh")
    t0 = time.time()
    for i, n in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        try:
            mcplib.npm_packument(n)
        except Exception:
            pass
        done.add(n)
        if i % 200 == 0:
            json.dump(sorted(done), open(DONE, "w"))
            print(f"  {i}/{len(todo)}  net={mcplib.STATS['net']} "
                  f"{time.time()-t0:.0f}s", flush=True)
    json.dump(sorted(done), open(DONE, "w"))
    left = len([n for n in todo_all if n not in done])
    print(f"refreshed {len(done)} of {len(todo_all)}; {left} remaining")
    if left == 0:
        json.dump({"registry_snapshot_utc": dt.datetime.utcnow().isoformat() + "Z",
                   "packages_refreshed": len(done),
                   "note": "every packument in the corpus re-fetched in one pass; "
                           "all downstream resolution reads this snapshot"},
                  open(STAMP, "w"), indent=1)
        print(f"wrote {STAMP}")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "collect"
    if m == "collect":
        n = names()
        print(f"{len(n)} distinct packages")
    else:
        run(float(sys.argv[2]) if len(sys.argv) > 2 else 540)
