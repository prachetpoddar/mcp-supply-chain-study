#!/usr/bin/env python3
"""
Break the maintainer crawl's blind spot.

THE BLIND SPOT
    frame_complete.py discovers maintainers from search results, and search
    results are score-ordered. A maintainer every one of whose packages sits
    below the pagination cutoff is never seen, so their packages are never
    reached, so the crawl cannot converge on the full population from the
    search API alone.

THE FIX
    A packument lists every maintainer of a package, not just the one who
    published the version search happened to surface. Co-maintainers are an
    entry point into exactly the region search cannot reach. So: fetch the
    packument for every package already known, take the full `maintainers`
    array, and feed any unseen usernames back into the crawl queue.

    Packuments are cached on disk by mcplib, and most of the frame was already
    walked during the study, so most of this is free.

    python3 maintainer_harvest.py [seconds]

    Then re-run: python3 frame_complete.py crawl <seconds>
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib

STATE = "/tmp/mcpres/frame_complete.json"
SEEN = "/tmp/mcpres/harvest_seen.json"


def main(budget):
    s = json.load(open(STATE))
    seen = set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()
    names = [n for n in s["names"] if n not in seen]
    done, todo = set(s["users_done"]), set(s["users_todo"])
    print(f"packuments to read: {len(names)}   maintainers known: {len(done | todo)}")

    t0, added, read = time.time(), 0, 0
    for i, n in enumerate(names):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(names)}"); break
        try:
            d = mcplib.npm_packument(n)
        except Exception:
            seen.add(n); continue
        read += 1
        for m in d.get("maintainers", []) or []:
            u = m.get("name") if isinstance(m, dict) else None
            if u and u not in done and u not in todo:
                todo.add(u); added += 1
        seen.add(n)
        if i % 250 == 0:
            s["users_todo"] = sorted(todo)
            json.dump(s, open(STATE, "w")); json.dump(sorted(seen), open(SEEN, "w"))
            print(f"  {i}/{len(names)}  read={read}  new maintainers={added}  "
                  f"cache={mcplib.STATS['cache_hit']} net={mcplib.STATS['net']}", flush=True)

    s["users_todo"] = sorted(todo)
    json.dump(s, open(STATE, "w"))
    json.dump(sorted(seen), open(SEEN, "w"))
    print(f"\nread {read} packuments, found {added} maintainers search never surfaced")
    print(f"queue is now {len(s['users_todo'])}; re-run frame_complete.py crawl")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 480)
