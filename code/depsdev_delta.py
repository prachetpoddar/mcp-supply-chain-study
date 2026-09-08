#!/usr/bin/env python3
"""
Measure the gap Adam Dudley described: the published dependency graph that
deps.dev answers for, against the tree that actually resolves at install time.

RUN THIS ON YOUR OWN MACHINE. The cloud container's egress denies
api.deps.dev; your Terminal reaches it.

    cd ~/Documents/MCPSupplyChainStudy
    python3 code/depsdev_delta.py fetch     # ~250 requests, resumable
    python3 code/depsdev_delta.py report

WHAT IT COMPARES
    Left  deps.dev's graph for the exact (name, version) of each MCP server
          root. This is what `mcp-audit sbom` and `scan --check-vulns` see.
    Right the tree produced by resolving every semver range against the live
          registry, from data/resolved_trees_for_depsdev.json, which is the
          250-server corpus already walked for the study.

    Both sides are dependency graphs of the same root at the same version, so
    the difference isolates resolution behaviour rather than sampling.

WHAT THE DIFFERENCE MEANS
    Three kinds, reported separately because they have different causes:

    missing_in_depsdev   packages the live resolution installs and deps.dev
                         does not list. Optional and platform-specific
                         dependencies live here, and so does anything added
                         to a range's satisfying set since deps.dev crawled.
    extra_in_depsdev     packages deps.dev lists that the live resolution
                         does not install. Optional deps deps.dev includes
                         unconditionally live here.
    version_differs      packages both sides install at different versions.
                         This is pure range-resolution drift.

    A scanner that queries the published graph is answering about the left
    side while its user is running the right side. This measures how far
    apart they are.

LIMITS, stated because the question deserves it
    This isolates resolution. It does not model lockfile state, since none of
    the 250 configs pins anything, and it does not model postinstall side
    effects, which are counted separately in the study as install hooks.
    Platform-specific behaviour is only partly captured: the walk includes
    optional dependencies without evaluating their os/cpu constraints, so
    what it produces is the union over platforms rather than one machine's
    install.
"""
import json, os, sys, time, urllib.request

API = "https://api.deps.dev/v3alpha/systems/npm/packages/{}/versions/{}:dependencies"
UA = {"User-Agent": "mcp-supply-chain-study/0.5 (academic research)"}
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
STATE = os.path.join(DATA, "depsdev_state.json")
PAUSE = 0.35


def enc(n):
    return urllib.parse.quote(n, safe="") if "/" in n or "@" in n else n


import urllib.parse


def fetch():
    trees = json.load(open(os.path.join(DATA, "resolved_trees_for_depsdev.json")))
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    todo = [t for t in trees if t["server"] not in s]
    print(f"deps.dev: {len(todo)} roots to query of {len(trees)}")
    for i, t in enumerate(todo):
        url = API.format(enc(t["root_name"]), urllib.parse.quote(t["root_version"], safe=""))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                d = json.load(r)
            nodes = {}
            for n in d.get("nodes", []):
                vk = n.get("versionKey") or {}
                if vk.get("name"):
                    nodes[vk["name"]] = vk.get("version")
            s[t["server"]] = {"ok": True, "nodes": nodes, "n": len(nodes)}
        except Exception as e:
            code = getattr(e, "code", None)
            s[t["server"]] = {"ok": False, "error": type(e).__name__, "code": code}
        if i % 25 == 0:
            json.dump(s, open(STATE, "w"))
            print(f"  {i}/{len(todo)}", flush=True)
        time.sleep(PAUSE)
    json.dump(s, open(STATE, "w"))
    ok = sum(1 for v in s.values() if v.get("ok"))
    print(f"done: {ok} resolved, {len(s)-ok} failed")


def report():
    trees = {t["server"]: t for t in json.load(open(os.path.join(DATA, "resolved_trees_for_depsdev.json")))}
    s = json.load(open(STATE))
    rows, agree = [], 0
    for name, dd in s.items():
        if not dd.get("ok") or name not in trees:
            continue
        live = trees[name]["resolved"]
        ddn = dd["nodes"]
        miss = [k for k in live if k not in ddn]
        extra = [k for k in ddn if k not in live]
        vdiff = [k for k in live if k in ddn and ddn[k] and live[k] != ddn[k]]
        if not miss and not extra and not vdiff:
            agree += 1
        rows.append({"server": name, "live_n": len(live), "depsdev_n": len(ddn),
                     "missing_in_depsdev": len(miss), "extra_in_depsdev": len(extra),
                     "version_differs": len(vdiff)})
    n = len(rows)
    if not n:
        print("no comparable rows"); return
    def med(f): return sorted(f(r) for r in rows)[n // 2]
    def pct(f): return 100 * sum(1 for r in rows if f(r)) / n
    print(f"comparable servers: {n}   graphs identical on both sides: {agree} = {100*agree/n:.1f}%\n")
    print(f"  median nodes, live resolution : {med(lambda r: r['live_n'])}")
    print(f"  median nodes, deps.dev        : {med(lambda r: r['depsdev_n'])}")
    print(f"  servers where deps.dev lists FEWER packages : {pct(lambda r: r['depsdev_n'] < r['live_n']):.1f}%")
    print(f"  servers with >=1 package deps.dev misses    : {pct(lambda r: r['missing_in_depsdev'] > 0):.1f}%")
    print(f"  servers with >=1 version disagreement       : {pct(lambda r: r['version_differs'] > 0):.1f}%")
    tot_live = sum(r["live_n"] for r in rows); tot_dd = sum(r["depsdev_n"] for r in rows)
    print(f"\n  total package instances, live {tot_live}, deps.dev {tot_dd}, "
          f"delta {100*(tot_live-tot_dd)/max(tot_dd,1):+.1f}%")
    json.dump(rows, open(os.path.join(DATA, "depsdev_delta.json"), "w"), indent=1)
    print("\nwrote data/depsdev_delta.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    fetch() if m == "fetch" else report()
