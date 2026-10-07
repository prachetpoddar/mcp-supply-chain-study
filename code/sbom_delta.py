#!/usr/bin/env python3
"""
SBOM Delta: what an SBOM declares against what an install actually materialises.

    python3 code/sbom_delta.py <file> [--node 22.11.0] [--json out.json]

    <file> may be a CycloneDX JSON document, an SPDX JSON document, a
    package-lock.json, a package.json, or an MCP launch config. Nothing leaves
    the machine it runs on except registry reads.

WHAT IT CLAIMS, AND WHAT IT DOES NOT
    It claims that a frozen component list and a real install disagree, and by
    how much. It does NOT claim that anyone's scanner is wrong: a scanner may
    resolve differently, and this tool has no view of how. Every number is
    printed with its denominator and with both dates.

DESIGN CONSTRAINTS, EACH FROM A DEFECT THIS PROJECT ALREADY SHIPPED
    Version-matched advisories, never name-matched. A name-level join once put
    `colors` (installed 1.0.3, advisory >=1.4.1) and `rc` (installed 1.2.8,
    advisories enumerating 1.2.9, 1.3.9, 2.3.9) into a published result, where
    `rc` alone supplied 15 of 17 claimed trees.

    Distinct name@version is the unit for every rate. One package appearing
    thirty times in a tree is one component, not thirty.

    An empty input is an error, not a finding. Running a report over a state
    file holding one record once produced a full results table and the most
    publishable sentence the study could reach. Every hard stop below exists
    because the alternative is a plausible answer where a complaint belongs.

    The drop taxonomy must partition the input. It is asserted, not hoped for.
"""
import argparse, collections, datetime as dt, json, os, re, sys, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mcplib

OSV = "https://api.osv.dev/v1/query"
PURL_NPM = re.compile(r"^pkg:npm/(?:(@[^/]+)/)?([^@]+)@(.+)$")


def die(msg):
    print("STOP: " + msg, file=sys.stderr)
    sys.exit(2)


def ts_now():
    return dt.datetime.now(dt.timezone.utc)


# ---------- input ----------

def parse_input(path):
    """Return (components, kind, created) where components is a set of (name, version).

    `created` is the SBOM's own timestamp when it carries one. Without it the
    elapsed-time split cannot be computed and the report says so rather than
    assuming the document is current.
    """
    try:
        with open(path) as fh:
            doc = json.load(fh)
    except Exception as e:
        die(f"cannot read {path} as JSON: {type(e).__name__}")
    comps, kind, created = set(), None, None

    if isinstance(doc, dict) and doc.get("bomFormat") == "CycloneDX":
        kind = "CycloneDX " + str(doc.get("specVersion", "?"))
        created = (doc.get("metadata") or {}).get("timestamp")
        for c in doc.get("components", []) or []:
            purl = c.get("purl") or ""
            m = PURL_NPM.match(purl)
            if m:
                scope, nm, ver = m.group(1), m.group(2), m.group(3)
                comps.add(((scope + "/" + nm) if scope else nm, urllib.parse.unquote(ver)))
            elif c.get("name") and c.get("version"):
                comps.add((c["name"], c["version"]))
    elif isinstance(doc, dict) and ("SPDXID" in doc or doc.get("spdxVersion")):
        kind = "SPDX " + str(doc.get("spdxVersion", "?"))
        created = ((doc.get("creationInfo") or {}).get("created"))
        for p in doc.get("packages", []) or []:
            for ref in p.get("externalRefs", []) or []:
                m = PURL_NPM.match(ref.get("referenceLocator") or "")
                if m:
                    scope, nm, ver = m.group(1), m.group(2), m.group(3)
                    comps.add(((scope + "/" + nm) if scope else nm, urllib.parse.unquote(ver)))
                    break
            else:
                if p.get("name") and p.get("versionInfo"):
                    comps.add((p["name"], p["versionInfo"]))
    elif isinstance(doc, dict) and "lockfileVersion" in doc:
        kind = "package-lock v%s" % doc.get("lockfileVersion")
        for p, m in (doc.get("packages") or {}).items():
            if not p or not m.get("version"):
                continue
            nm = p.split("node_modules/")[-1]
            comps.add((nm, m["version"]))
        for nm, m in (doc.get("dependencies") or {}).items():
            if m.get("version"):
                comps.add((nm, m["version"]))
    elif isinstance(doc, dict) and ("dependencies" in doc or "mcpServers" in doc):
        kind = "manifest or launch config"
    else:
        die("unrecognised document: not CycloneDX, SPDX, a lockfile, or a manifest")
    return comps, kind, created


def roots_from(path):
    """The root packages to resolve, and the spec for each."""
    doc = json.load(open(path))
    roots = []
    if isinstance(doc, dict) and doc.get("mcpServers"):
        for name, cfg in doc["mcpServers"].items():
            args = cfg.get("args") or []
            for a in args:
                if a in ("-y", "--yes") or a.startswith("-"):
                    continue
                m = re.match(r"^(@?[^@]+(?:/[^@]+)?)(?:@(.+))?$", a)
                if m:
                    # A BARE NAME IS A RANGE, NOT A TAG.
                    # npm-package-arg resolves `foo` to type=range fetchSpec=*,
                    # and `foo@latest` to type=tag. The two take different paths
                    # through pick-manifest: a range goes through the dist-tag
                    # fast path and is subject to its deprecation and engines
                    # conditions, while a tag selector returns the tagged
                    # manifest unconditionally. Measured on npm 11: a deprecated
                    # latest is returned for selector "latest" and skipped for
                    # selector "*". Recording a bare name as "latest" would
                    # resolve the version npx would decline to install.
                    roots.append((m.group(1), m.group(2) or "*"))
                    break
    elif isinstance(doc, dict) and doc.get("name") and "dependencies" in doc:
        for n, r in (doc.get("dependencies") or {}).items():
            roots.append((n, r if r not in ("", "latest") else "*"))
    elif isinstance(doc, dict) and doc.get("metadata", {}).get("component", {}).get("purl"):
        m = PURL_NPM.match(doc["metadata"]["component"]["purl"])
        if m:
            scope, nm, ver = m.group(1), m.group(2), m.group(3)
            roots.append(((scope + "/" + nm) if scope else nm, ver))
    return roots


# ---------- advisories ----------

def osv_query(name, version):
    body = json.dumps({"version": version,
                       "package": {"name": name, "ecosystem": "npm"}}).encode()
    req = urllib.request.Request(OSV, data=body,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "sbom-delta/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return [v.get("id") for v in (json.load(r).get("vulns") or [])]


def advisories_for(pairs, cache):
    """OSV is queried per (name, version), so a hit means the advisory's range
    actually contains that version. This is the version-matched join; a
    name-level one is what produced a retracted result in this project."""
    out, errs = {}, 0
    for i, (n, v) in enumerate(sorted(pairs)):
        key = f"{n}@{v}"
        if key not in cache:
            try:
                cache[key] = osv_query(n, v)
            except Exception:
                errs += 1
                cache[key] = None
        if cache[key]:
            out[(n, v)] = cache[key]
        if i % 50 == 0 and i:
            print(f"    advisories {i}/{len(pairs)}", flush=True)
    return out, errs


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--node", default=None,
                    help="host node version for npm's engines condition; "
                         "without it the condition is not evaluated and the report says so")
    ap.add_argument("--json", default=None)
    ap.add_argument("--cache", default=os.path.join(os.path.dirname(HERE), "data",
                                                    "sbom_delta_osv_cache.json"))
    a = ap.parse_args()

    mcplib.PREFER_DIST_TAG = True          # match npm 10 and 11, see RESOLVER-NOTES.md
    mcplib.NODE_VERSION = a.node

    declared, kind, created = parse_input(a.file)
    roots = roots_from(a.file)
    print(f"input   : {a.file}")
    print(f"format  : {kind}")
    print(f"declared: {len(declared)} distinct name@version")
    print(f"roots   : {len(roots)}")
    if not roots:
        die("no root package could be identified, so there is nothing to resolve "
            "against. Supply a manifest, a launch config, or a CycloneDX document "
            "whose metadata.component carries an npm purl.")

    resolved, drops = {}, collections.Counter()
    for name, spec in roots:
        try:
            nodes, st = mcplib.npm_walk(name, spec)
        except Exception as e:
            drops[f"root_unresolvable:{type(e).__name__}"] += 1
            continue
        for (n, v), meta in nodes.items():
            if str(v).startswith("NON-REGISTRY") or v in ("UNRESOLVED", None):
                drops["non_registry_or_unresolved"] += 1
                continue
            resolved[(n, v)] = meta
    if not resolved:
        die("the resolve produced zero nodes. Nothing is reported. This is not a "
            "finding about the SBOM.")

    print(f"resolved: {len(resolved)} distinct name@version"
          f"   (drops {dict(drops)})")
    if not declared:
        die("the document declared zero components. Nothing is reported.")

    only_declared = declared - set(resolved)
    only_resolved = set(resolved) - declared
    both = declared & set(resolved)
    assert len(only_declared) + len(both) == len(declared), "declared set does not partition"
    assert len(only_resolved) + len(both) == len(resolved), "resolved set does not partition"

    print()
    print(f"COVERAGE   declared {len(declared)}, materialised {len(resolved)}, "
          f"in both {len(both)}")
    print(f"           the document describes {100*len(both)/max(len(resolved),1):.1f}% "
          f"of what installs")
    print(f"           {len(only_resolved)} installed components are absent from it")
    print(f"           {len(only_declared)} declared components are not installed")

    cache = {}
    if os.path.exists(a.cache):
        try:
            cache = json.load(open(a.cache))
        except Exception:
            cache = {}
    print("\nquerying OSV, version-matched")
    adv_declared, e1 = advisories_for(only_declared, cache)
    adv_resolved, e2 = advisories_for(only_resolved | both, cache)
    json.dump(cache, open(a.cache, "w"))

    resolved_names = collections.defaultdict(set)
    for n, v in resolved:
        resolved_names[n].add(v)
    phantom = {}
    for (n, v), ids in adv_declared.items():
        live = [i for vv in resolved_names.get(n, ()) for i in adv_resolved.get((n, vv), [])]
        gone = [i for i in ids if i not in live]
        if gone:
            phantom[(n, v)] = gone
    missed = {k: ids for k, ids in adv_resolved.items() if k[0] not in {n for n, _ in declared}}

    print()
    print(f"PHANTOM    {sum(len(v) for v in phantom.values())} findings across "
          f"{len(phantom)} declared components")
    print(f"           advisories that match a declared version and match no "
          f"installed version of that package")
    print(f"MISSED     {sum(len(v) for v in missed.values())} findings across "
          f"{len(missed)} installed components absent from the document")
    if e1 + e2:
        print(f"           {e1+e2} OSV queries failed and are excluded from both counts")

    print()
    print(f"as of      resolution {ts_now().strftime('%Y-%m-%d')}, "
          f"document {created or 'NO TIMESTAMP IN THE DOCUMENT'}")
    if not created:
        print("           without a document timestamp the elapsed-time share of this")
        print("           delta cannot be separated from declaration practice")
    print(f"engines    {'evaluated against node ' + a.node if a.node else 'NOT evaluated; pass --node to match a real host'}")
    print("scope      npm registry dependencies only; platform-conditional and")
    print("           optional edges are included without evaluating os and cpu")

    if a.json:
        json.dump({"input": a.file, "format": kind, "document_timestamp": created,
                   "resolved_at": ts_now().isoformat(), "node_version": a.node,
                   "declared": len(declared), "materialised": len(resolved),
                   "in_both": len(both),
                   "installed_not_declared": sorted(f"{n}@{v}" for n, v in only_resolved),
                   "declared_not_installed": sorted(f"{n}@{v}" for n, v in only_declared),
                   "phantom_findings": {f"{n}@{v}": ids for (n, v), ids in phantom.items()},
                   "missed_findings": {f"{n}@{v}": ids for (n, v), ids in missed.items()},
                   "osv_query_failures": e1 + e2, "drops": dict(drops)},
                  open(a.json, "w"), indent=1)
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
