#!/usr/bin/env python3
"""
Cluster bootstrap over publishers for rows 3 and 6, on the validated resolver.

WHY A BOOTSTRAP AND NOT THE DESIGN EFFECT
    design_effect_corrected.json carries a "deprecated in tree" entry computed
    as 1 + (m-1)*ICC on the realised sample. Rows 1, 2, 4 and 5 were later moved
    off that estimator onto a stratified cluster bootstrap over publishers,
    because the ICC route had already produced two wrong answers in this study
    (a population design effect quoted for a sample, then a sample arithmetic
    mean where Kish's unequal-cluster formula was required). Rows 3 and 6 stayed
    on the old estimator only because they were not re-run at the time. This
    puts them on the same footing as the rest of the table.

    Publishers, not packages, are the resampling unit, because keyword tagging
    and publishing behaviour are publisher-level properties in every ecosystem
    measured. "GitHub Actions" is excluded as a publisher identity: it is a CI
    label covering packages from unrelated projects, and treating it as one
    account merges clusters that have nothing to do with each other. Packages
    carrying it are treated as singleton clusters instead.

    python3 rerun_bootstrap_rows36.py pubs [seconds]
    python3 rerun_bootstrap_rows36.py report
"""
import json, os, random, statistics, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcplib

HERE = os.path.dirname(os.path.abspath(__file__))
PUBS = "/tmp/mcpres/rows36_pubs.json"
UA = {"User-Agent": "mcp-supply-chain-study/0.5 (academic research)"}
NOT_A_PUBLISHER = {"GitHub Actions", "github-actions", None, ""}
ITERS = 4000


def arms_names():
    f = json.load(open("/tmp/mcpres/frames3.json"))
    random.seed(2468)
    return {"langchain": random.sample(f["keywords:langchain"]["names"], 120),
            "eslint-plugin": random.sample(f["keywords:eslint-plugin"]["names"], 120)}


def publisher(name):
    """npm search reports the publishing account; fall back to first maintainer."""
    u = ("https://registry.npmjs.org/-/v1/search?text="
         + urllib.parse.quote(name) + "&size=5")
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
            d = json.load(r)
        for o in d.get("objects", []):
            if o["package"]["name"] == name:
                p = (o["package"].get("publisher") or {}).get("username")
                if p:
                    return p
    except Exception:
        pass
    try:
        m = mcplib.npm_packument(name).get("maintainers") or []
        if m and isinstance(m[0], dict):
            return m[0].get("name")
    except Exception:
        pass
    return None


def pubs(budget):
    s = json.load(open(PUBS)) if os.path.exists(PUBS) else {}
    todo = [n for names in arms_names().values() for n in names if n not in s]
    print(f"publishers to resolve: {len(todo)}")
    t0 = time.time()
    for i, n in enumerate(todo):
        if time.time() - t0 > budget:
            print(f"  budget reached at {i}/{len(todo)}")
            break
        s[n] = publisher(n)
        if i % 25 == 0:
            json.dump(s, open(PUBS, "w"))
            print(f"  {i}/{len(todo)}", flush=True)
        time.sleep(0.35)
    json.dump(s, open(PUBS, "w"))
    print(f"resolved {sum(1 for v in s.values() if v)} of {len(s)}")


def clusters(pairs):
    """pairs: [(publisher_or_None, outcome_bool)] -> list of outcome lists."""
    by = {}
    singles = []
    for p, o in pairs:
        if p in NOT_A_PUBLISHER:
            singles.append([o])
        else:
            by.setdefault(p, []).append(o)
    return list(by.values()) + singles


def boot(cl, iters=ITERS, seed=13):
    rng = random.Random(seed)
    n = len(cl)
    obs = 100 * sum(sum(c) for c in cl) / sum(len(c) for c in cl)
    out = []
    for _ in range(iters):
        pick = [cl[rng.randrange(n)] for _ in range(n)]
        tot = sum(len(c) for c in pick)
        if tot:
            out.append(100 * sum(sum(c) for c in pick) / tot)
    return obs, statistics.pstdev(out)


def report():
    pubmap = json.load(open(PUBS))
    mcp_pub = json.load(open("/tmp/mcpres/frame_complete_mcp-server.json"))["names"]
    ng = json.load(open("/tmp/mcpres/nested_gap.json"))
    tw = json.load(open("/tmp/mcpres/rerun_tree_rows.json"))

    def split(x):
        n, _, v = x.rpartition("@@")
        return n, v

    HOOKS = ("preinstall", "install", "postinstall")

    def measure(nodes):
        dep = hook = 0
        for nm, ver in nodes:
            try:
                m = mcplib.npm_packument(nm)["versions"].get(ver, {}) or {}
            except Exception:
                continue
            if m.get("deprecated"):
                dep += 1
            sc = m.get("scripts") or {}
            if any(sc.get(h) for h in HOOKS):
                hook += 1
        return dep > 0, hook > 0

    arms = {"mcp": [], "eslint-plugin": [], "langchain": []}
    for root, g in ng.items():
        if "skip" in g or g["truncated"]:
            continue
        d, h = measure({split(x) for x in g["installed"]})
        arms["mcp"].append((mcp_pub.get(root), d, h))
    for arm in ("eslint-plugin", "langchain"):
        for n, v in tw.get(arm, {}).items():
            if "skip" in v or v.get("truncated"):
                continue
            arms[arm].append((pubmap.get(n), v["deprecated"] > 0, v["hooks"] > 0))

    print(f"{'row':22s} {'arm':16s} {'rate':>7s} {'boot SE':>8s} {'clusters':>9s} {'n':>5s}")
    print("-" * 72)
    out = {}
    for idx, label in ((1, "deprecated in tree"), (2, "install hook in tree")):
        res = {}
        for arm, rows in arms.items():
            cl = clusters([(r[0], r[idx]) for r in rows])
            obs, se = boot(cl)
            res[arm] = (obs, se, len(cl), len(rows))
            print(f"{label if arm=='mcp' else '':22s} {arm:16s} {obs:6.1f}% {se:7.2f} "
                  f"{len(cl):9d} {len(rows):5d}")
        zs = {}
        for c in ("eslint-plugin", "langchain"):
            a, sa, _, _ = res["mcp"]
            b, sb, _, _ = res[c]
            zs[c] = round((a - b) / ((sa ** 2 + sb ** 2) ** 0.5), 2)
        print(f"{'':22s} {'z vs eslint':16s} {zs['eslint-plugin']:>7} "
              f"   z vs langchain {zs['langchain']}")
        out[label] = {arm: {"rate": round(v[0], 1), "bootstrap_se": round(v[1], 2),
                            "clusters": v[2], "n": v[3]} for arm, v in res.items()}
        out[label]["z_vs_eslint_clustered"] = zs["eslint-plugin"]
        out[label]["z_vs_langchain_clustered"] = zs["langchain"]
        print()
    out["note"] = ("cluster bootstrap over publishers, 4000 resamples; 'GitHub Actions' "
                   "treated as no publisher and those packages as singleton clusters; "
                   "resolver validated at 99.5% against 85 real npm installs")
    json.dump(out, open(os.path.join(HERE, "rows36_bootstrap.json"), "w"), indent=1)
    print("wrote rows36_bootstrap.json")


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "report"
    pubs(float(sys.argv[2]) if len(sys.argv) > 2 else 540) if m == "pubs" else report()
