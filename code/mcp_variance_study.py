import json,sys,collections
sys.path.insert(0,'/tmp/mcpres'); import mcplib
HOOKS=("preinstall","install","postinstall")
def hooks_for(name,ver=None):
    try: d=mcplib.npm_packument(name)
    except Exception: return None
    v=ver or d.get("dist-tags",{}).get("latest")
    m=d.get("versions",{}).get(v) or {}
    s=m.get("scripts") or {}
    return {k:s[k] for k in HOOKS if k in s}
recs=[json.loads(l) for l in open('/tmp/mcpres/walk250.jsonl')]
recs=[r for r in recs if "error" not in r]
out=[]
seen={}
for r in recs:
    root=hooks_for(r["name"])
    tree_hooks={}
    for pv in r["pkgs"]:
        nm,ver=pv.rsplit("@@",1)
        if ver.startswith("NON-REGISTRY") or ver=="UNRESOLVED": continue
        key=(nm,ver)
        if key not in seen: seen[key]=hooks_for(nm,ver)
        h=seen[key]
        if h: tree_hooks[f"{nm}@{ver}"]=h
    out.append({"name":r["name"],"nodes":r["nodes"],
                "root_hooks":root or {},
                "tree_hook_pkgs":tree_hooks})
json.dump(out,open('/tmp/mcpres/hooks_mcp.json','w'))
n=len(out)
rk=sum(1 for x in out if x["root_hooks"])
tk=sum(1 for x in out if x["tree_hook_pkgs"])
print(f"MCP servers analysed: {n}")
print(f"  root declares an install hook      : {rk}/{n} = {100*rk/n:.1f}%")
print(f"  tree contains >=1 install hook     : {tk}/{n} = {100*tk/n:.1f}%")
cnt=collections.Counter(len(x['tree_hook_pkgs']) for x in out)
print(f"  distribution of hook-packages per tree: {dict(sorted(cnt.items())[:8])}")
allh=collections.Counter()
for x in out:
    for p in x["tree_hook_pkgs"]: allh[p]+=1
print(f"\n  most common hook-bearing packages in MCP trees:")
for p,c in allh.most_common(10): print(f"    {c:3d} trees  {p}")
import json,random,sys,time,collections
sys.path.insert(0,'/tmp/mcpres'); import mcplib
HOOKS=("preinstall","install","postinstall")
frames=json.load(open('/tmp/mcpres/frames3.json'))
random.seed(2468)
targets={"langchain":random.sample(frames["keywords:langchain"]["names"],120),
         "eslint-plugin":random.sample(frames["keywords:eslint-plugin"]["names"],120)}
def hooks_for(name,ver=None):
    try: d=mcplib.npm_packument(name)
    except Exception: return None
    v=ver or d.get("dist-tags",{}).get("latest")
    m=d.get("versions",{}).get(v) or {}
    s=m.get("scripts") or {}
    return {k:s[k] for k in HOOKS if k in s}
out={}
seen={}
t0=time.time()
for lbl,names in targets.items():
    rows=[]
    for nm in names:
        try: nodes,_=mcplib.npm_walk(nm,"latest",include_optional=True,include_peer=False)
        except Exception: continue
        th={}
        for (n2,v2) in nodes:
            if str(v2).startswith("NON-REGISTRY") or v2=="UNRESOLVED": continue
            k=(n2,v2)
            if k not in seen: seen[k]=hooks_for(n2,v2)
            if seen[k]: th[f"{n2}@{v2}"]=seen[k]
        rows.append({"name":nm,"nodes":len(nodes),"root_hooks":hooks_for(nm) or {},"tree_hook_pkgs":th})
        if time.time()-t0>2600: break
    out[lbl]=rows
    print(f"  {lbl}: {len(rows)} walked ({time.time()-t0:.0f}s)")
json.dump(out,open('/tmp/mcpres/hooks_ctl.json','w'))
print("done", dict(mcplib.STATS))
import json,re,collections
desc=json.load(open('/tmp/mcpres/frame_desc.json'))
CATS={
 "filesystem":r"\bfile ?system|\bfiles?\b.*\b(read|write|access)|\bfs\b|directory",
 "github/git":r"\bgithub\b|\bgitlab\b|\bgit\b|\bpull request|\brepo(sitory)?\b",
 "database/sql":r"\bpostgres|\bmysql|\bsqlite|\bsql\b|\bdatabase\b|\bmongo|\bredis\b|\bclickhouse|\bsupabase",
 "web search":r"\bweb search|\bsearch (the )?web|\bbrave\b|\btavily|\bperplexity|\bserp\b|\bgoogle search",
 "web fetch/scrape":r"\bscrap(e|ing)|\bcrawl|\bfetch (a )?(url|web|page)|\bfirecrawl|\bhtml to markdown",
 "browser automation":r"\bplaywright|\bpuppeteer|\bselenium|\bbrowser automation|\bheadless browser",
 "memory/knowledge":r"\bmemory\b|\bknowledge graph|\bvector (db|store)|\bembedding|\brecall\b",
 "slack/chat":r"\bslack\b|\bdiscord\b|\bteams\b|\btelegram\b|\bwhatsapp\b",
 "notion/docs":r"\bnotion\b|\bconfluence\b|\bobsidian\b|\bgoogle docs\b|\bmarkdown notes",
 "jira/issues":r"\bjira\b|\blinear\b|\basana\b|\bissue tracker|\btrello\b",
 "aws/cloud":r"\baws\b|\bazure\b|\bgcp\b|\bs3\b|\bcloudflare\b|\bkubernetes|\bk8s\b|\bdocker\b",
 "time/date":r"\btime\b.*\bzone|\bdatetime\b|\bcalendar\b",
 "email":r"\bemail\b|\bgmail\b|\bimap\b|\bsmtp\b|\boutlook\b",
 "finance/crypto":r"\bstock|\bcrypto|\bbitcoin|\bethereum|\btrading|\bfinanc",
 "maps/weather":r"\bweather\b|\bmaps?\b|\bgeocod|\bforecast\b",
}
comp=[(k,re.compile(v,re.I)) for k,v in CATS.items()]
assign=collections.defaultdict(list)
for n,m in desc.items():
    blob=(n+" "+m["desc"]+" "+" ".join(m["kw"]))
    hits=[k for k,rx in comp if rx.search(blob)]
    for h in hits: assign[h].append(n)
    if not hits: assign["_unclassified"].append(n)
print(f"frame: {len(desc)} packages\n")
print(f"{'functional cluster':22s} {'servers':>8s}  {'% of frame':>10s}")
tot=0
for k,v in sorted(assign.items(),key=lambda x:-len(x[1])):
    if k=="_unclassified": continue
    tot+=len(v)
    print(f"  {k:20s} {len(v):8d}  {100*len(v)/len(desc):9.1f}%")
print(f"  {'_unclassified':20s} {len(assign['_unclassified']):8d}  {100*len(assign['_unclassified'])/len(desc):9.1f}%")
json.dump({k:v for k,v in assign.items()},open('/tmp/mcpres/clusters.json','w'))
print(f"\n(packages can match multiple clusters; {tot} cluster memberships across {len(desc)-len(assign['_unclassified'])} classified packages)")
import json,re,random,sys,collections,time
sys.path.insert(0,'/tmp/mcpres'); import mcplib
desc=json.load(open('/tmp/mcpres/frame_desc.json'))
clusters=json.load(open('/tmp/mcpres/clusters.json'))
spdx={l['licenseId'] for l in json.load(open('/tmp/mcpres/spdx_licenses.json'))['licenses']}
def clean(l):
    if not l or not str(l).strip(): return False
    a=[t.strip() for t in re.split(r'\s+(?:AND|OR|WITH)\s+|[()]',str(l)) if t.strip()]
    return any(x in spdx or x.rstrip('+') in spdx for x in a)
def lic(n):
    try:
        d=mcplib.npm_packument(n); lat=d.get("dist-tags",{}).get("latest")
        m=d.get("versions",{}).get(lat,{}); L=m.get("license")
        if isinstance(L,dict): L=L.get("type")
        return L
    except Exception: return "__ERR__"
random.seed(1234)
res={}
t0=time.time()
for cname,members in clusters.items():
    if cname=="_unclassified" or len(members)<25: continue
    ranked=sorted(members,key=lambda n:desc[n]["rank"])
    top=ranked[:20]
    tail=ranked[20:]
    tsamp=random.sample(tail,min(20,len(tail)))
    rows={"top":[],"tail":[]}
    for grp,names in (("top",top),("tail",tsamp)):
        for n in names:
            L=lic(n)
            rows[grp].append({"name":n,"license":L,"clean":clean(L) if L!="__ERR__" else None,
                              "rank":desc[n]["rank"]})
    res[cname]={"size":len(members),**rows}
    print(f"  {cname:22s} size={len(members):4d}  sampled {len(rows['top'])}+{len(rows['tail'])}  ({time.time()-t0:.0f}s)")
json.dump(res,open('/tmp/mcpres/merit.json','w'))
print(f"done in {time.time()-t0:.0f}s, fetch={dict(mcplib.STATS)}")
