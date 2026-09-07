#!/usr/bin/env python3
"""
Enumerate the npm `mcp-server` keyword population as completely as the public
search API allows, by partitioning on maintainer.

WHY
    The score-ordered frame reaches 5,250 of ~8,230 packages (63.8%) because
    pagination stops near 5,000 results. Free-text term expansion lifted that to
    6,540 (79.5%) and then saturated: the last ten of a hundred terms added 26
    packages. The residual 20.5% is what forces every comparison in the paper
    into partial-identification bounds.

    `maintainer:` is a real partition. `keywords:mcp-server maintainer:cyanheads`
    returns total=121 against the unrestricted 8,238, so the qualifier is
    applied rather than ignored. Every package has at least one maintainer, so
    complete maintainer coverage implies complete package coverage, and each
    maintainer's slice is far below the 5,000 pagination cap.

    NOTE, and this is the point of Section 6 of the paper: `scope:` is NOT a
    real partition. `keywords:mcp-server scope:pipeworx` returns total=8238,
    identical to the unrestricted query. npm accepts the qualifier and ignores
    it. Anything built on it would be a frame that looks partitioned and is not.

METHOD
    1. Seed: paginate the unrestricted query to the cap, recording each
       package's publisher.
    2. Snowball: for every maintainer seen, run `keywords:mcp-server
       maintainer:<user>`, paginate it to its own `total`, and add any new
       maintainers found to the queue.
    3. Stop when the queue empties.

    Resumable. State written after every query.

    python3 frame_complete.py seed
    python3 frame_complete.py crawl [seconds]
    python3 frame_complete.py report
"""
import json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = "/tmp/mcpres/frame_complete.json"
UA = {"User-Agent": "mcp-supply-chain-study/0.4 (academic research)"}
PAUSE = 1.1


def search(text, frm=0, size=250):
    u = ("https://registry.npmjs.org/-/v1/search?text="
         + urllib.parse.quote(text) + f"&size={size}&from={frm}")
    for a in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45) as r:
                return json.load(r)
        except Exception:
            if a == 3:
                raise
            time.sleep(2 ** a)


def load():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"names": {}, "users_done": [], "users_todo": [], "population": None}


def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w"))


def absorb(s, objs):
    """Record names and queue any unseen maintainers. Returns new-name count."""
    new = 0
    done, todo = set(s["users_done"]), set(s["users_todo"])
    for o in objs:
        p = o["package"]
        n = p["name"]
        if n not in s["names"]:
            s["names"][n] = (p.get("publisher") or {}).get("username")
            new += 1
        u = (p.get("publisher") or {}).get("username")
        if u and u not in done and u not in todo:
            todo.add(u)
    s["users_todo"] = sorted(todo)
    return new


def seed():
    s = load()
    d = search("keywords:mcp-server", 0, 1)
    s["population"] = d.get("total")
    print(f"population reported by the API: {s['population']}")
    for frm in range(0, 5000, 250):
        d = search("keywords:mcp-server", frm, 250)
        objs = d.get("objects", [])
        if not objs:
            break
        n = absorb(s, objs)
        print(f"  from={frm:4d}  +{n:3d}  names={len(s['names'])}  users queued={len(s['users_todo'])}", flush=True)
        save(s)
        if len(objs) < 250:
            break
        time.sleep(PAUSE)
    # fold in the frames we already have, so the crawl starts from 6,540
    wide = json.load(open(os.path.join(HERE, "npm_frame_wide_6540.json")))
    for n in wide:
        s["names"].setdefault(n, None)
    save(s)
    print(f"seeded: {len(s['names'])} names, {len(s['users_todo'])} maintainers queued")


def crawl(budget):
    s, t0 = load(), time.time()
    print(f"start: {len(s['names'])} names, {len(s['users_todo'])} queued, {len(s['users_done'])} done")
    while s["users_todo"] and time.time() - t0 < budget:
        u = s["users_todo"].pop(0)
        try:
            d = search(f"keywords:mcp-server maintainer:{u}", 0, 250)
        except Exception as e:
            print(f"  {u}: {type(e).__name__}, requeued at tail")
            s["users_todo"].append(u); save(s); continue
        total = d.get("total", 0)
        new = absorb(s, d.get("objects", []))
        frm = 250
        while frm < min(total, 5000) and time.time() - t0 < budget:
            time.sleep(PAUSE)
            d2 = search(f"keywords:mcp-server maintainer:{u}", frm, 250)
            o2 = d2.get("objects", [])
            if not o2:
                break
            new += absorb(s, o2)
            frm += 250
        s["users_done"].append(u)
        save(s)
        if new:
            print(f"  {u:28s} total={total:5d}  +{new:4d}  names={len(s['names'])}  "
                  f"queued={len(s['users_todo'])}", flush=True)
        time.sleep(PAUSE)
    pop = s.get("population") or 8238
    print(f"\nnames={len(s['names'])} of {pop} = {100*len(s['names'])/pop:.1f}% coverage")
    print(f"maintainers done={len(s['users_done'])} queued={len(s['users_todo'])}")


def report():
    s = load()
    pop = s.get("population") or 8238
    names = sorted(s["names"])
    json.dump(names, open(os.path.join(HERE, "npm_frame_complete.json"), "w"))
    print(f"coverage: {len(names)}/{pop} = {100*len(names)/pop:.1f}%")
    print(f"maintainers: {len(s['users_done'])} done, {len(s['users_todo'])} queued")
    wide = set(json.load(open(os.path.join(HERE, "npm_frame_wide_6540.json"))))
    print(f"new since the 6,540 frame: {len(set(names) - wide)}")
    print("wrote npm_frame_complete.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    if m == "seed":
        seed()
    elif m == "crawl":
        crawl(float(sys.argv[2]) if len(sys.argv) > 2 else 480)
    else:
        report()
