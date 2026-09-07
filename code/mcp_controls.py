import json,random,sys,time,collections
sys.path.insert(0,'/tmp/mcpres'); import mcplib
recs=[json.loads(l) for l in open('/tmp/mcpres/walk250.jsonl')]
recs=[r for r in recs if "error" not in r]
mcpnames={r["name"] for r in recs}
# candidate control roots: ordinary npm packages seen as transitive deps, excluding MCP packages
pool=collections.Counter()
for r in recs:
    for pv,m in r["pkgs"].items():
        nm=pv.rsplit("@@",1)[0]
        if nm in mcpnames or m.get("nonregistry"): continue
        if m.get("kind")=="root": continue
        pool[nm]+=1
cands=sorted(pool)
print(f"control pool (distinct non-MCP npm packages seen as deps): {len(cands)}")
random.seed(31337); sample=random.sample(cands,250)
OUT='/tmp/mcpres/control_walk.jsonl'
done=set()
import os
if os.path.exists(OUT):
    for line in open(OUT):
        try: done.add(json.loads(line)["name"])
        except Exception: pass
t0=time.time(); n=0
with open(OUT,'a') as f:
    for nm in sample:
        if nm in done: continue
        try:
            nodes,st=mcplib.npm_walk(nm,"latest",include_optional=True,include_peer=False)
        except Exception as e:
            f.write(json.dumps({"name":nm,"error":type(e).__name__})+"\n"); f.flush(); continue
        f.write(json.dumps({"name":nm,"nodes":len(nodes),
            "maxdepth":max((m["depth"] for m in nodes.values()),default=0),
            "deprecated":[f"{k[0]}@{k[1]}" for k,v in nodes.items() if v.get("deprecated")],
            "licenses":[v.get("license") for v in nodes.values()]})+"\n"); f.flush(); n+=1
        if time.time()-t0>2400: break
print(f"control walks: +{n}, total {len(done)+n}/250, {time.time()-t0:.0f}s, fetch={dict(mcplib.STATS)}")
import json,random,sys,time,urllib.request,urllib.parse,collections,os
sys.path.insert(0,'/tmp/mcpres'); import mcplib
UA={"User-Agent":"mcp-supply-chain-study/0.2 (research)"}
# application-shaped control: npm packages keyworded cli / server, i.e. things people run, like MCP servers
frame={}
for kw in ["keywords:cli","keywords:server"]:
    for frm in range(0,2500,250):
        u=f"https://registry.npmjs.org/-/v1/search?text={urllib.parse.quote(kw)}&size=250&from={frm}"
        try: d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=40))
        except Exception as e: print("  stop",kw,frm,type(e).__name__); break
        objs=d.get("objects",[])
        if not objs: break
        for o in objs:
            p=o.get("package",{}); frame[p["name"]]=kw
        time.sleep(0.4)
mcpnames={json.loads(l)["name"] for l in open('/tmp/mcpres/walk250.jsonl')}
cands=[n for n in frame if n not in mcpnames and 'mcp' not in n.lower()]
print(f"application-shaped control frame: {len(cands)}")
json.dump(cands,open('/tmp/mcpres/ctl2_frame.json','w'))
random.seed(555); sample=random.sample(cands,250)
OUT='/tmp/mcpres/control2_walk.jsonl'
done=set()
if os.path.exists(OUT):
    for line in open(OUT):
        try: done.add(json.loads(line)["name"])
        except Exception: pass
t0=time.time(); n=0
with open(OUT,'a') as f:
    for nm in sample:
        if nm in done: continue
        try: nodes,st=mcplib.npm_walk(nm,"latest",include_optional=True,include_peer=False)
        except Exception as e:
            f.write(json.dumps({"name":nm,"error":type(e).__name__})+"\n"); f.flush(); continue
        f.write(json.dumps({"name":nm,"nodes":len(nodes),
          "deprecated":[f"{k[0]}@{k[1]}" for k,v in nodes.items() if v.get("deprecated")],
          "licenses":[v.get("license") for v in nodes.values()]})+"\n"); f.flush(); n+=1
        if time.time()-t0>2400: break
print(f"control2 walks: +{n} total {len(done)+n}/250 in {time.time()-t0:.0f}s")
import json,sys,io,tarfile,urllib.request,time,collections
sys.path.insert(0,'/tmp/mcpres'); import mcplib
UA={"User-Agent":"mcp-supply-chain-study/0.2 (research)"}
names=[json.loads(l)["name"] for l in open('/tmp/mcpres/control2_walk.jsonl') if "error" not in json.loads(l)]
res={}; errs=collections.Counter(); t0=time.time()
for n in names:
    try:
        d=mcplib.npm_packument(n)
        lat=d["dist-tags"]["latest"]; meta=d["versions"][lat]
        lic=meta.get("license")
        if isinstance(lic,dict): lic=lic.get("type")
        url=(meta.get("dist") or {}).get("tarball")
        raw=urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=60).read()
        with tarfile.open(fileobj=io.BytesIO(raw)) as tf: fn=tf.getnames()
        res[n]={"declared":lic,"files":len(fn),
                "license_files":[x for x in fn if 'licen' in x.lower() or 'copying' in x.lower()]}
    except Exception as e: errs[type(e).__name__]+=1
json.dump(res,open('/tmp/mcpres/control2_tarballs.json','w'))
print(f"control tarballs: {len(res)}/{len(names)} in {time.time()-t0:.0f}s errors={dict(errs)}")
import json,random,re,sys,time,collections
sys.path.insert(0,'/tmp/mcpres'); import mcplib
allnames=[p["name"] for p in json.load(open('/tmp/mcpres/pypi_simple.json'))["projects"]]
mcpset=set(json.load(open('/tmp/mcpres/pypi_frame.json')))
control_pool=[n for n in allnames if n not in mcpset]
print(f"PyPI total {len(allnames):,}; mcp-token {len(mcpset):,}; control pool {len(control_pool):,}")
random.seed(9091); sample=random.sample(control_pool,250)
rows=[]; errs=collections.Counter(); t0=time.time()
for n in sample:
    try: d=mcplib.fetch_json(f"https://pypi.org/pypi/{n}/json",cache_key="pypi:"+n)
    except Exception as e: errs[type(e).__name__]+=1; continue
    i=d.get("info",{})
    lraw=i.get("license")
    rows.append({"name":n,"version":i.get("version"),
      "license_expression":i.get("license_expression"),
      "license_raw":(lraw[:80] if isinstance(lraw,str) else lraw),
      "license_raw_len":len(lraw) if isinstance(lraw,str) else 0,
      "classifiers":[c.split("::")[-1].strip() for c in i.get("classifiers",[]) if c.startswith("License ::")],
      "license_files":i.get("license_files"),
      "requires_dist":len(i.get("requires_dist") or [])})
json.dump(rows,open('/tmp/mcpres/pypi_control.json','w'))
print(f"control arm: {len(rows)}/250 in {time.time()-t0:.0f}s errors={dict(errs)}")
