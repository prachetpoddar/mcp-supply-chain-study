#!/usr/bin/env python3
"""Build the advisory snapshot the gap measurement joins against.

WHY THIS EXISTS
    The first computation of the frozen-versus-live figure read
    /tmp/mcpres/advisories.json, which no longer exists, so the figure could not
    be reproduced from the release. This rebuilds that map from the OSV npm
    bulk export already in data/, writes it into data/ where it ships, and
    records what it was built from.

OUTPUT
    data/advisories_npm.json       {package: [{id, severity, vulnerable_versions,
                                   published, modified}]}
    data/advisories_npm_meta.json  what it was built from, and what was dropped

PUBLICATION DATES, AND WHAT THEY ARE NOT
    `published` and `modified` are carried through verbatim from the OSV entry
    so that a frozen-side finding can be asked whether its advisory existed when
    the root shipped. They are OSV's timestamps: `published` is when the advisory
    entered OSV, which can lag the upstream GHSA publication. Any statement built
    on them is a bound on knowledge timing and not a measurement of it. Either
    may be absent, in which case the field is None and the row is counted in the
    metadata rather than given a substitute date.

RANGE CONVERSION, AND ITS ONE APPROXIMATION
    OSV states affected versions as event lists: an `introduced` bound, then
    either `fixed` (exclusive) or `last_affected` (inclusive). Those map onto
    semver ranges directly. Where an entry gives no usable range but does give
    an explicit `versions` list, the list is enumerated only when short, because
    a disjunction of hundreds of exact versions is both slow to evaluate and
    unlikely to be what a reader expects; longer ones are dropped and counted.
    Nothing is inferred beyond that.
"""
import collections, json, os, sys, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
ZIP = os.path.join(DATA, "osv_npm_all.zip")
OUT = os.environ.get("ADVISORY_OUT") or os.path.join(DATA, "advisories_npm.json")
META = os.environ.get("ADVISORY_META") or os.path.join(DATA,
                                                       "advisories_npm_meta.json")
MAX_ENUMERATED = 40

# WHICH ADVISORIES COUNT. The OSV npm export carries 221,191 non-withdrawn MAL
# rows, one per
# reported malicious package, against 9,522 GHSA rows. A malicious-package
# report is a different object from a vulnerability advisory: it says a package
# should not exist rather than that a version range is affected, and most of
# the named packages have been removed from the registry. "Advisory verdict"
# here means what a vulnerability scanner would say, so the join is GHSA, and
# the excluded prefixes are counted rather than silently dropped.
BASIS = tuple(x for x in (os.environ.get("ADVISORY_BASIS") or "GHSA").split(",") if x)


def to_range(rng):
    """One OSV range to a semver range string, or None."""
    parts, cur = [], None
    for ev in rng.get("events") or []:
        if "introduced" in ev:
            cur = [">=" + ev["introduced"]] if ev["introduced"] != "0" else [">=0.0.0"]
        elif "fixed" in ev:
            if cur is None:
                cur = [">=0.0.0"]
            cur.append("<" + ev["fixed"])
            parts.append(" ".join(cur)); cur = None
        elif "last_affected" in ev:
            if cur is None:
                cur = [">=0.0.0"]
            cur.append("<=" + ev["last_affected"])
            parts.append(" ".join(cur)); cur = None
    if cur is not None:
        parts.append(" ".join(cur))
    return " || ".join(parts) or None


def main():
    if not os.path.exists(ZIP):
        sys.exit(f"missing {ZIP}")
    out = collections.defaultdict(list)
    drop = collections.Counter()
    ids, modified = set(), []
    sevs = collections.Counter()
    undated_ids, undated_rows = set(), 0
    with zipfile.ZipFile(ZIP) as z:
        names = [n for n in z.namelist() if n.endswith(".json")]
        for i, n in enumerate(names):
            try:
                a = json.loads(z.read(n))
            except Exception:
                drop["unparseable_entry"] += 1
                continue
            if a.get("withdrawn"):
                drop["withdrawn"] += 1
                continue
            aid = a.get("id")
            if not aid:
                drop["no_id"] += 1
                continue
            if BASIS and not aid.startswith(BASIS):
                drop["excluded_prefix_" + aid.split("-")[0]] += 1
                continue
            sev = ((a.get("database_specific") or {}).get("severity") or "").lower() or None
            if a.get("modified"):
                modified.append(a["modified"])
            wrote = False
            for aff in a.get("affected") or []:
                pkg = aff.get("package") or {}
                if (pkg.get("ecosystem") or "") != "npm":
                    continue
                name = pkg.get("name")
                if not name:
                    continue
                rs = [to_range(r) for r in (aff.get("ranges") or [])]
                rs = [r for r in rs if r]
                vr = " || ".join(rs) if rs else None
                if not vr:
                    vers = aff.get("versions") or []
                    if 0 < len(vers) <= MAX_ENUMERATED:
                        vr = " || ".join(vers)
                    else:
                        drop["affected_without_usable_range"] += 1
                        continue
                out[name].append({"id": aid, "severity": sev,
                                  "vulnerable_versions": vr,
                                  "published": a.get("published"),
                                  "modified": a.get("modified")})
                wrote = True
                if not a.get("published"):
                    undated_rows += 1
                    undated_ids.add(aid)
            if wrote:
                ids.add(aid)
                sevs[sev or "none"] += 1
            if i % 2000 == 0:
                print(f"  {i}/{len(names)}", flush=True)
    meta = {
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": os.path.basename(ZIP),
        "source_mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                          time.gmtime(os.path.getmtime(ZIP))),
        "entries_in_zip": len(names),
        "advisories_kept": len(ids),
        "packages": len(out),
        "advisory_rows": sum(len(v) for v in out.values()),
        "latest_modified_in_export": max(modified) if modified else None,
        "rows_without_published": undated_rows,
        "advisories_without_published": len(undated_ids),
        "severity_counts": dict(sevs),
        "dropped": dict(drop),
        "max_enumerated_versions": MAX_ENUMERATED,
        "basis": list(BASIS),
    }
    json.dump(dict(out), open(OUT, "w"))
    json.dump(meta, open(META, "w"), indent=1)
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
