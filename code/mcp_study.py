import json,urllib.request,urllib.parse,random,time,datetime,re,collections
UA={"User-Agent":"mcp-measurement-study/0.1 (research; bounded)"}
frame=json.load(open('/tmp/mcpres/frame.json'))
names=sorted(frame)
random.seed(20260906)
N=400
sample=random.sample(names,N)
json.dump(sample,open('/tmp/mcpres/sample400.json','w'))
now=datetime.datetime.now(datetime.timezone.utc)
def parse(t): return datetime.datetime.fromisoformat(t.replace('Z','+00:00'))
rows=[]; errs=collections.Counter(); t0=time.time()
for i,n in enumerate(sample):
    u="https://registry.npmjs.org/"+urllib.parse.quote(n,safe='@')
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=30))
    except Exception as e:
        errs[type(e).__name__]+=1; continue
    lat=d.get("dist-tags",{}).get("latest"); vers=d.get("versions",{}); tm=d.get("time",{})
    meta=vers.get(lat,{}) if lat else {}
    vlist=[v for v in tm if v not in ("created","modified")]
    age=(now-parse(tm[lat])).days if lat in tm else None
    rows.append({
      "name":n,"latest":lat,
      "license":meta.get("license") if not isinstance(meta.get("license"),dict) else (meta.get("license") or {}).get("type"),
      "deprecated":bool(meta.get("deprecated")),
      "direct_deps":len(meta.get("dependencies") or {}),
      "has_repo":bool(meta.get("repository")),
      "age_days":age,
      "n_versions":len(vlist),
      "rel30":sum(1 for v in vlist if (now-parse(tm[v])).days<=30) if tm else 0,
      "rel90":sum(1 for v in vlist if (now-parse(tm[v])).days<=90) if tm else 0,
      "files_hint":(meta.get("dist") or {}).get("fileCount"),
      "tarball":(meta.get("dist") or {}).get("tarball"),
    })
    if i%80==79: time.sleep(0.4)
json.dump(rows,open('/tmp/mcpres/stage1.json','w'))
print(f"stage 1: {len(rows)}/{N} resolved in {time.time()-t0:.0f}s   errors={dict(errs)}")
import json,urllib.request,urllib.parse,random,collections,time
UA={"User-Agent":"mcp-measurement-study/0.1 (research; bounded)"}
rows=json.load(open('/tmp/mcpres/stage1.json'))
random.seed(4242)
sub=random.sample(rows,60)
cache={}; BUDGET=3500
def packument(n):
    if n not in cache:
        if len(cache)>=BUDGET: raise RuntimeError("budget")
        u="https://registry.npmjs.org/"+urllib.parse.quote(n,safe='@')
        cache[n]=json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=30))
    return cache[n]
def pick(n,spec="latest"):
    d=packument(n); t=d.get("dist-tags",{}); v=d.get("versions",{})
    ver=t.get(spec) or t.get("latest")
    return ver, v.get(ver,{})
def walk(root,cap=800):
    seen={}; q=collections.deque([(root,0)]); errs=0
    while q and len(seen)<cap:
        n,d=q.popleft()
        if any(k[0]==n for k in seen): continue
        try: ver,meta=pick(n)
        except RuntimeError: raise
        except Exception: errs+=1; continue
        if not ver: errs+=1; continue
        seen[(n,ver)]={"license":meta.get("license") if not isinstance(meta.get("license"),dict) else (meta.get("license") or {}).get("type"),
                       "depth":d,"deprecated":bool(meta.get("deprecated"))}
        for dep in (meta.get("dependencies") or {}):
            if not any(k[0]==dep for k in seen): q.append((dep,d+1))
    return seen,errs
out=[]; allp={}; t0=time.time(); stopped=None
for i,r in enumerate(sub):
    try:
        seen,errs=walk(r["name"])
    except RuntimeError:
        stopped=i; break
    out.append({"name":r["name"],"direct":r["direct_deps"],"nodes":len(seen),
                "maxdepth":max((m["depth"] for m in seen.values()),default=0),"errors":errs})
    for k,v in seen.items(): allp.setdefault(f"{k[0]}@{k[1]}",v)
    if i%10==9: print(f"  {i+1}/60 walked, {len(cache)} packuments cached, {time.time()-t0:.0f}s")
json.dump(out,open('/tmp/mcpres/stage2_trees.json','w'))
json.dump(allp,open('/tmp/mcpres/stage2_pkgs.json','w'))
print(f"\ncompleted {len(out)}/60 walks ({'budget hit at '+str(stopped) if stopped is not None else 'all'}) in {time.time()-t0:.0f}s")
print(f"distinct transitive packages seen: {len(allp)}   registry requests: {len(cache)}")
import json,urllib.request,urllib.parse,io,tarfile,time,collections,math
UA={"User-Agent":"mcp-measurement-study/0.1 (research; bounded)"}
rows=json.load(open('/tmp/mcpres/stage1.json'))
res={}; fails=collections.Counter(); t0=time.time()
for i,r in enumerate(rows):
    if not r.get("tarball"): fails["no-tarball"]+=1; continue
    try:
        raw=urllib.request.urlopen(urllib.request.Request(r["tarball"],headers=UA),timeout=60).read()
        with tarfile.open(fileobj=io.BytesIO(raw)) as tf: names=tf.getnames()
        lic=[x for x in names if 'licen' in x.lower() or 'copying' in x.lower()]
        res[r["name"]]={"declared":r["license"],"files":len(names),"license_files":lic,"bytes":len(raw)}
    except Exception as e:
        fails[type(e).__name__]+=1
    if time.time()-t0>430: print(f"  time budget at {i+1}"); break
json.dump(res,open('/tmp/mcpres/tarballs_big.json','w'))
n=len(res)
def ci(k,n):
    p=k/n; return p*100, 1.96*math.sqrt(p*(1-p)/n)*100
nolic=[k for k,v in res.items() if not v["license_files"]]
decl_nolic=[k for k in nolic if v_ok(res[k]["declared"])] if False else [k for k in nolic if res[k]["declared"] and str(res[k]["declared"]).strip()]
p,e=ci(len(nolic),n); p2,e2=ci(len(decl_nolic),n)
print(f"\ninspected {n} published MCP-server tarballs in {time.time()-t0:.0f}s (errors {dict(fails)})")
print(f"  {len(nolic):3d}/{n}  {p:5.1f}% ±{e:.1f}   ship NO license file")
print(f"  {len(decl_nolic):3d}/{n}  {p2:5.1f}% ±{e2:.1f}   declare a license but ship no license text")
byd=collections.Counter(str(res[k]['declared']) for k in decl_nolic)
print("\n  what those packages claim to be licensed under:")
for k,v in byd.most_common(8): print(f"    {v:3d}x {k}")
sizes=sorted(v['files'] for v in res.values())
print(f"\n  files per published package: median {sizes[n//2]}, p90 {sizes[int(.9*n)]}, max {sizes[-1]}")
