#!/usr/bin/env python3
"""
Diagnostic for the ecosyste.ms keyword query. Run before trusting eco_counts.json.

WHY
    `eco_enumerate.py count` reported total=None and 0/20 exact keyword matches
    for all fourteen keywords, and printed a line saying that means the filter
    is fuzzy. That conclusion is not supported. Uniform nulls across every
    keyword is the signature of a request or field-name mismatch, not of a
    scoring filter. Three hypotheses produce identical output:

      A  the `keyword` parameter is not the right name, so it is ignored and
         arbitrary packages come back
      B  the response objects do not carry a `keywords` field at this endpoint,
         so the exact-match test always scores zero regardless of the filter
      C  the pagination count lives in a differently named header

    This prints the raw shape so the three can be told apart. It asserts
    nothing; it just shows what the API returns.

    python3 eco_probe.py
"""
import json, urllib.parse, urllib.request

BASE = "https://packages.ecosyste.ms/api/v1/registries/npmjs.org/packages"
UA = {"User-Agent": "mcp-supply-chain-study/0.4 (academic research)"}


def get(params):
    u = BASE + "?" + urllib.parse.urlencode(params)
    r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45)
    return u, r.status, dict(r.headers), json.load(r)


def main():
    print("=== 1. headers on a keyword query (which one carries the count?)")
    u, st, hdr, body = get({"keyword": "mcp-server", "per_page": 1})
    print(f"  {u}\n  HTTP {st}, {len(body)} rows")
    for k, v in sorted(hdr.items()):
        if any(t in k.lower() for t in ("count", "page", "total", "link")):
            print(f"    {k}: {v}")

    print("\n=== 2. field names actually present on a package object")
    if body:
        p = body[0]
        print(f"  keys: {sorted(p.keys())}")
        for f in ("keywords", "topics", "tags", "name", "latest_release_number"):
            print(f"    {f}: {p.get(f)!r}")

    print("\n=== 3. does the filter apply at all? compare three queries")
    for label, params in (("keyword=mcp-server", {"keyword": "mcp-server", "per_page": 5}),
                          ("keywords=mcp-server", {"keywords": "mcp-server", "per_page": 5}),
                          ("no filter", {"per_page": 5})):
        try:
            _, _, _, b = get(params)
            names = [x.get("name") for x in b]
            print(f"  {label:24s} -> {names}")
        except Exception as e:
            print(f"  {label:24s} -> ERROR {repr(e)[:80]}")

    print("\nRead: if the three queries return the same names, the filter is being")
    print("ignored (hypothesis A). If `keywords` is absent from the key list, the")
    print("exact-match test was measuring nothing (hypothesis B). Either way the")
    print("'filter is fuzzy' line in eco_enumerate.py was wrong and eco_counts.json")
    print("must not be used until this is resolved.")


if __name__ == "__main__":
    main()
