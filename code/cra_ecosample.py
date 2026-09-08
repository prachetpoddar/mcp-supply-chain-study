#!/usr/bin/env python3
"""
Build the cross-ecosystem sample as a FUNCTION-MATCHED PANEL.

WHY FUNCTION-MATCHED RATHER THAN POPULAR
    "Deep transitive trees are an npm pathology" is the challenge this is meant
    to answer, and a popularity-ranked sample cannot answer it: the most-used
    package in each ecosystem does different work, and dependency depth is a
    property of what a library does at least as much as of the ecosystem it
    lives in. So the panel fixes the FUNCTION and varies the ecosystem. Twelve
    jobs a real application actually needs, one package per ecosystem per job.

    That makes the comparison like-for-like, and it makes the sample a
    convenience sample by construction. It is chosen by hand, it is small, and
    it is not a random draw from anything. Say so. The claim it can support is
    "for the same twelve jobs, the ratio looks like X here and Y there", and no
    claim about an ecosystem as a whole.

    Latest version per package is read from deps.dev rather than hardcoded, so
    the panel does not silently rot.

    python3 cra_ecosample.py      writes data/crossecosystem_sample.json
"""
import json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
API = "https://api.deps.dev/v3alpha"
UA = {"User-Agent": "mcp-supply-chain-study/0.5 (academic research)"}

PANEL = {
    "http client":   {"npm": "axios", "maven": "com.squareup.okhttp3:okhttp", "pypi": "requests",
                      "go": "github.com/go-resty/resty/v2", "cargo": "reqwest"},
    "web framework": {"npm": "express", "maven": "org.springframework:spring-webmvc", "pypi": "flask",
                      "go": "github.com/gin-gonic/gin", "cargo": "actix-web"},
    "json":          {"npm": "ajv", "maven": "com.fasterxml.jackson.core:jackson-databind", "pypi": "orjson",
                      "go": "github.com/tidwall/gjson", "cargo": "serde_json"},
    "logging":       {"npm": "winston", "maven": "ch.qos.logback:logback-classic", "pypi": "loguru",
                      "go": "github.com/sirupsen/logrus", "cargo": "tracing"},
    "cli parsing":   {"npm": "commander", "maven": "info.picocli:picocli", "pypi": "click",
                      "go": "github.com/spf13/cobra", "cargo": "clap"},
    "testing":       {"npm": "jest", "maven": "org.junit.jupiter:junit-jupiter", "pypi": "pytest",
                      "go": "github.com/stretchr/testify", "cargo": "proptest"},
    "date/time":     {"npm": "dayjs", "maven": "joda-time:joda-time", "pypi": "arrow",
                      "go": "github.com/jinzhu/now", "cargo": "chrono"},
    "orm":           {"npm": "prisma", "maven": "org.hibernate:hibernate-core", "pypi": "sqlalchemy",
                      "go": "gorm.io/gorm", "cargo": "diesel"},
    "templating":    {"npm": "handlebars", "maven": "org.freemarker:freemarker", "pypi": "jinja2",
                      "go": "github.com/flosch/pongo2", "cargo": "tera"},
    "yaml":          {"npm": "js-yaml", "maven": "org.yaml:snakeyaml", "pypi": "pyyaml",
                      "go": "gopkg.in/yaml.v3", "cargo": "serde_yaml"},
    "jwt":           {"npm": "jsonwebtoken", "maven": "io.jsonwebtoken:jjwt-api", "pypi": "pyjwt",
                      "go": "github.com/golang-jwt/jwt/v5", "cargo": "jsonwebtoken"},
    "validation":    {"npm": "joi", "maven": "org.hibernate.validator:hibernate-validator", "pypi": "pydantic",
                      "go": "github.com/go-playground/validator/v10", "cargo": "validator"},
}


def get(path):
    for a in range(4):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(API + path, headers=UA), timeout=45) as r:
                return json.load(r)
        except Exception as e:
            if getattr(e, "code", None) == 404:
                return None
            if a == 3:
                return None
            time.sleep(2 ** a)


def latest(eco, name):
    d = get(f"/systems/{eco}/packages/{urllib.parse.quote(name, safe='')}")
    if not d:
        return None
    vs = d.get("versions") or []
    # deps.dev marks the default version; fall back to the last listed
    for v in vs:
        if v.get("isDefault"):
            return (v.get("versionKey") or {}).get("version")
    return (vs[-1].get("versionKey") or {}).get("version") if vs else None


def main():
    out, missing = {}, []
    for job, row in PANEL.items():
        for eco, name in row.items():
            v = latest(eco, name)
            if not v:
                missing.append((job, eco, name))
                continue
            out.setdefault(eco, []).append([name, v])
            print(f"  {eco:6s} {name:52s} {v}", flush=True)
            time.sleep(0.2)
    os.makedirs(DATA, exist_ok=True)
    json.dump(out, open(os.path.join(DATA, "crossecosystem_sample.json"), "w"), indent=1)
    print(f"\npanel: {sum(len(v) for v in out.values())} packages across {len(out)} ecosystems")
    if missing:
        print(f"NOT RESOLVED ({len(missing)}), these drop out of the panel and the")
        print("panel is therefore no longer balanced across ecosystems, which matters:")
        for j, e, n in missing:
            print(f"  {j:14s} {e:6s} {n}")
    print("\nwrote data/crossecosystem_sample.json")


if __name__ == "__main__":
    main()
