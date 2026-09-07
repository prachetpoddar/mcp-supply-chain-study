import json,random,time,os,sys,collections
sys.path.insert(0,'/tmp/mcpres')
import mcplib
rows=json.load(open('/tmp/mcpres/stage1.json'))
random.seed(4242); sub60=random.sample(rows,60)
names60=[r["name"] for r in sub60]
rest=[r for r in rows if r["name"] not in set(names60)]
random.seed(777); extra=random.sample(rest,190)
sample=sub60+extra                      # 250, first 60 identical to the pilot
json.dump([r["name"] for r in sample],open('/tmp/mcpres/sample250.json','w'))

OUT='/tmp/mcpres/walk250.jsonl'
done=set()
if os.path.exists(OUT):
    for line in open(OUT):
        try: done.add(json.loads(line)["name"])
        except Exception: pass
t0=time.time(); n=0
with open(OUT,'a') as f:
    for r in sample:
        if r["name"] in done: continue
        try:
            nodes,st=mcplib.npm_walk(r["name"], "latest", include_optional=True, include_peer=False)
        except Exception as e:
            f.write(json.dumps({"name":r["name"],"error":f"{type(e).__name__}"})+"\n"); f.flush(); continue
        rec={"name":r["name"],"declared":r["license"],"direct":r["direct_deps"],
             "nodes":len(nodes),"maxdepth":max((m["depth"] for m in nodes.values()),default=0),
             "stats":dict(st),
             "pkgs":{f"{k[0]}@@{k[1]}":{"license":v.get("license"),"kind":v.get("kind"),
                                        "deprecated":v.get("deprecated"),"nonregistry":v.get("nonregistry")}
                     for k,v in nodes.items()}}
        f.write(json.dumps(rec)+"\n"); f.flush(); n+=1
        if time.time()-t0>3000:
            print(f"  time budget: {n} walked this pass, {len(done)+n}/250 total"); break
print(f"pass done: +{n} walks, total {len(done)+n}/250, {time.time()-t0:.0f}s, fetch={dict(mcplib.STATS)}")
import json,random,re,sys,time,collections
sys.path.insert(0,'/tmp/mcpres'); import mcplib
frame=[n for n in json.load(open('/tmp/mcpres/pypi_frame.json')) if 'server' in n.lower()]
random.seed(20260907); sample=random.sample(frame,250)
rows=[]; errs=collections.Counter(); t0=time.time()
for n in sample:
    try:
        d=mcplib.fetch_json(f"https://pypi.org/pypi/{n}/json", cache_key="pypi:"+n)
    except Exception as e:
        errs[type(e).__name__]+=1; continue
    info=d.get("info",{})
    lexp=info.get("license_expression")
    lraw=info.get("license")
    cls=[c for c in info.get("classifiers",[]) if c.startswith("License ::")]
    urls=d.get("urls",[]) or []
    latest=info.get("version")
    files=d.get("releases",{}).get(latest,[]) or urls
    rows.append({"name":n,"version":latest,
        "license_expression":lexp,
        "license_raw":(lraw[:80] if isinstance(lraw,str) else lraw),
        "license_raw_len":len(lraw) if isinstance(lraw,str) else 0,
        "classifiers":[c.split("::")[-1].strip() for c in cls],
        "license_files":info.get("license_files"),
        "requires_dist":len(info.get("requires_dist") or []),
        "n_files":len(files),
        "home":bool(info.get("home_page") or (info.get("project_urls") or {}))})
json.dump(rows,open('/tmp/mcpres/pypi250.json','w'))
print(f"pypi arm: {len(rows)}/250 in {time.time()-t0:.0f}s errors={dict(errs)} fetch={dict(mcplib.STATS)}")
