#!/usr/bin/env python3
"""Warm mcplib's packument cache in parallel.

The walk is serial and each registry request costs a couple of seconds through
a proxy, so a 250-root re-walk spends hours waiting rather than resolving. This
fetches the packuments the walk will need, concurrently, through mcplib's own
cache and its own rate limiter, so nothing about resolution changes: afterwards
the walk reads the same files it would have fetched itself.

    python3 code/prefetch_packuments.py <names-file> [workers] [budget-seconds]

A budget is supported because the shell this runs in cannot keep a background
process alive between calls, so the warm-up proceeds in slices. Re-running with
the same list is cheap: cached names return without a request.

The name list comes from the released corpus walk, which names every package in
the 250 trees. The frozen arm can still miss, since a tree's older state may
contain packages the live tree does not, and those are fetched by the walk.
"""
import concurrent.futures as cf
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib

DEADLINE = None


def one(name):
    if DEADLINE and time.time() > DEADLINE:
        return None                      # out of budget, leave it for the next slice
    try:
        mcplib.npm_packument(name)
        return True
    except Exception:
        return False

def main():
    path = sys.argv[1]
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    global DEADLINE
    if len(sys.argv) > 3:
        DEADLINE = time.time() + float(sys.argv[3])
    names = [n.strip() for n in open(path) if n.strip()]
    print(f"{len(names)} names, {workers} workers, cache {mcplib.CACHE}", flush=True)
    ok = bad = skipped = 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, got in enumerate(ex.map(one, names)):
            if got is None:
                skipped += 1
                continue
            ok += got
            bad += not got
            if i % 200 == 0:
                el = time.time() - t0
                print(f"  {i}/{len(names)}  ok={ok} failed={bad}  "
                      f"{i/max(el,1e-9):.1f}/s  net={mcplib.STATS['net']} "
                      f"hits={mcplib.STATS['cache_hit']}", flush=True)
    print(f"done: {ok} fetched or cached, {bad} failed, {skipped} left for the "
          f"next slice, {time.time()-t0:.0f}s, net={mcplib.STATS['net']}, "
          f"cache hits={mcplib.STATS['cache_hit']}")

if __name__ == "__main__":
    main()
