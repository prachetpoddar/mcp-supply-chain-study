#!/usr/bin/env python3
"""
Validate the resolver against real `npm install` trees, across all three arms.

WHY ALL THREE ARMS
    Two resolver bugs (deprecated-version preference, missing peerDependencies)
    were invisible until a real install was run, and the second moved a control
    arm's median tree from 8 nodes to 79. A validation that covers only the MCP
    arm cannot catch a bug whose effect is arm-specific, which is exactly the
    failure that just occurred: peers matter enormously for eslint plugins and
    barely at all for MCP servers.

METHOD
    For each sampled package: npm install the exact resolved root version into a
    throwaway directory with --ignore-scripts, read the resulting
    package-lock.json, and compare its (name, version) set against the set the
    resolver computes. Install scripts are never executed; these are arbitrary
    third-party packages.

    Each tree is deleted immediately after measurement. 90 node_modules trees
    do not fit in the session's disk allowance otherwise.

    Agreement is reported as the share of npm's own nodes that the resolver
    reproduces. The resolver is expected to be a slight superset, because it
    includes optionalDependencies without evaluating os/cpu, so platform
    binaries for other systems appear in it and not in the install.

    python3 validate_installs.py run [seconds]
    python3 validate_installs.py report
"""
import json, os, random, shutil, statistics, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib
import install_gap as IG
import nested_gap as NG

STATE = os.environ.get("MCPRES_VSTATE", "/tmp/mcpres/validate_installs.json")
WORK = "/tmp/mcpres/vwork"
N_PER_ARM = int(os.environ.get("MCPRES_VN", "30"))


def sample():
    random.seed(int(os.environ.get("MCPRES_VSEED", "97531")))
    out = {}
    trees = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "resolved_trees_for_depsdev.json")))
    ng = json.load(open("/tmp/mcpres/nested_gap.json"))
    mcp = [(t["root_name"], t["root_version"]) for t in trees
           if t["root_name"] in ng and "skip" not in ng[t["root_name"]]
           and not ng[t["root_name"]]["truncated"]]
    out["mcp"] = random.sample(mcp, N_PER_ARM)
    f = json.load(open("/tmp/mcpres/frames3.json"))
    random.seed(2468)
    ctl = {"langchain": random.sample(f["keywords:langchain"]["names"], 120),
           "eslint-plugin": random.sample(f["keywords:eslint-plugin"]["names"], 120)}
    random.seed(97531)
    for arm, names in ctl.items():
        out[arm] = [(n, None) for n in random.sample(names, N_PER_ARM)]
    return out


def real_tree(name, ver):
    d = os.path.join(WORK, "t")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "package.json"), "w").write('{"name":"v","private":true}')
    spec = f"{name}@{ver}" if ver else name
    p = subprocess.run(["npm", "install", spec, "--ignore-scripts", "--no-audit",
                        "--no-fund", "--loglevel=error"],
                       cwd=d, capture_output=True, text=True, timeout=300)
    lk = os.path.join(d, "package-lock.json")
    if not os.path.exists(lk):
        shutil.rmtree(d, ignore_errors=True)
        return None, (p.stderr or "")[:160]
    lock = json.load(open(lk))
    real = {(k.split("node_modules/")[-1], m["version"])
            for k, m in lock.get("packages", {}).items() if k and "version" in m}
    shutil.rmtree(d, ignore_errors=True)
    return real, None


def run(budget):
    s = json.load(open(STATE)) if os.path.exists(STATE) else {}
    os.makedirs(WORK, exist_ok=True)
    t0 = time.time()
    for arm, items in sample().items():
        s.setdefault(arm, {})
        for name, ver in items:
            if name in s[arm]:
                continue
            if time.time() - t0 > budget:
                json.dump(s, open(STATE, "w"))
                print(f"budget reached; {sum(len(v) for v in s.values())} done")
                return
            try:
                if ver is None:
                    ver, _ = IG.resolve_at(name, "latest", None)
                if ver is None:
                    s[arm][name] = {"skip": "root unresolved"}
                    continue
                mine, _ = NG.pair_walk(name, ver, None)
                real, err = real_tree(name, ver)
                if real is None:
                    s[arm][name] = {"skip": "npm install failed", "err": err}
                    continue
                inter = real & mine
                s[arm][name] = {"version": ver, "npm": len(real), "mine": len(mine),
                                "agree": len(inter),
                                "npm_only": sorted(f"{a}@{b}" for a, b in (real - mine))[:40],
                                "mine_only": sorted(f"{a}@{b}" for a, b in (mine - real))[:40]}
                print(f"  {arm:14s} {name[:34]:34s} npm={len(real):4d} mine={len(mine):4d} "
                      f"agree={100*len(inter)/max(len(real),1):5.1f}%", flush=True)
            except Exception as e:
                s[arm][name] = {"skip": repr(e)[:120]}
            json.dump(s, open(STATE, "w"))
    json.dump(s, open(STATE, "w"))
    print("all done")


def report():
    s = json.load(open(STATE))
    out = {}
    print(f"{'arm':16s} {'n':>4s} {'npm nodes':>10s} {'agreement':>10s} "
          f"{'npm-only':>9s} {'mine-only':>10s}")
    print("-" * 64)
    for arm, rows in s.items():
        ok = [v for v in rows.values() if "skip" not in v]
        if not ok:
            continue
        tn = sum(v["npm"] for v in ok)
        ta = sum(v["agree"] for v in ok)
        no = sum(v["npm"] - v["agree"] for v in ok)
        mo = sum(v["mine"] - v["agree"] for v in ok)
        per = [100 * v["agree"] / v["npm"] for v in ok if v["npm"]]
        print(f"{arm:16s} {len(ok):4d} {tn:10d} {100*ta/tn:9.1f}% {no:9d} {mo:10d}")
        out[arm] = {"n": len(ok), "npm_nodes": tn, "agreement_pct": round(100 * ta / tn, 1),
                    "median_per_package_pct": round(statistics.median(per), 1),
                    "worst_per_package_pct": round(min(per), 1),
                    "npm_only_total": no, "mine_only_total": mo,
                    "skipped": len(rows) - len(ok)}
    allok = [v for rows in s.values() for v in rows.values() if "skip" not in v]
    tn = sum(v["npm"] for v in allok)
    ta = sum(v["agree"] for v in allok)
    print(f"\nOVERALL {ta}/{tn} = {100*ta/tn:.1f}% across {len(allok)} packages")
    out["overall"] = {"n": len(allok), "agreement_pct": round(100 * ta / tn, 1)}
    json.dump(out, open("validate_installs.json", "w"), indent=1)
    print("wrote validate_installs.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    run(float(sys.argv[2]) if len(sys.argv) > 2 else 540) if m == "run" else report()
