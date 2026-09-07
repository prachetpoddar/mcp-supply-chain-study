import json,urllib.request,urllib.parse,time,random,sys,datetime,math
sys.path.insert(0,'/tmp/mcpres'); import mcplib
UA={"User-Agent":"mcp-supply-chain-study/0.2 (research)"}
def build(kw,cap=5250):
    seen={}; frm=0
    while frm<cap:
        u=f"https://registry.npmjs.org/-/v1/search?text={urllib.parse.quote(kw)}&size=250&from={frm}"
        try: d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=40))
        except Exception as e: break
        objs=d.get("objects",[])
        if not objs: break
        for o in objs: seen[o["package"]["name"]]=o.get("score",{}).get("final",0)
        if len(objs)<250: break
        frm+=250; time.sleep(0.5)
    return seen,d.get("total")
frames={}
for kw,cap in [("keywords:eslint-plugin",5250),("keywords:langchain",2200)]:
    f,tot=build(kw,cap)
    frames[kw]={"frame":f,"total":tot}
    print(f"  {kw:26s} frame {len(f)} of total {tot}  = {100*len(f)/tot:.0f}% coverage")
json.dump({k:{"total":v["total"],"names":sorted(v["frame"])} for k,v in frames.items()},
          open('/tmp/mcpres/frames3.json','w'))
now=datetime.datetime.now(datetime.timezone.utc)
def P(t): return datetime.datetime.fromisoformat(t.replace('Z','+00:00'))
out={}
for kw,v in frames.items():
    random.seed(2468); s=random.sample(sorted(v["frame"]),min(250,len(v["frame"])))
    rows=[]
    for n in s:
        try: d=mcplib.npm_packument(n)
        except Exception: continue
        tm=d.get("time",{}); lat=d.get("dist-tags",{}).get("latest")
        if not lat or lat not in tm or "created" not in tm: continue
        vs=[x for x in tm if x not in ("created","modified")]
        lic=d.get("versions",{}).get(lat,{}).get("license")
        if isinstance(lic,dict): lic=lic.get("type")
        rows.append({"name":n,"nver":len(vs),"one":len(vs)==1,
                     "age_days":(now-P(tm["created"])).days,
                     "last_days":(now-P(tm[lat])).days,"license":lic})
    out[kw]=rows
    print(f"  {kw}: profiled {len(rows)}")
json.dump(out,open('/tmp/mcpres/control3.json','w'))
import json,sys,datetime,math
sys.path.insert(0,'/tmp/mcpres'); import mcplib
now=datetime.datetime.now(datetime.timezone.utc)
def P(t):
    try: return datetime.datetime.fromisoformat(t.replace('Z','+00:00')).replace(tzinfo=datetime.timezone.utc)
    except Exception: return None
def prof(names):
    out=[]
    for n in names:
        try: d=mcplib.fetch_json(f"https://pypi.org/pypi/{n}/json",cache_key="pypi:"+n)
        except Exception: continue
        i=d.get("info",{}); rel=d.get("releases",{}) or {}
        times=[]
        for v,fs in rel.items():
            for f in fs or []:
                t=P(f.get("upload_time_iso_8601") or f.get("upload_time") or "")
                if t: times.append(t)
        if not times: continue
        first=min(times); last=max(times)
        lexp=i.get("license_expression"); lraw=i.get("license")
        cls=[c for c in i.get("classifiers",[]) if c.startswith("License ::")]
        has=bool(lexp) or bool(lraw and str(lraw).strip()) or bool(cls)
        out.append({"name":n,"age_days":(now-first).days,"last_days":(now-last).days,
                    "nver":len(rel),"has_license":has})
    return out
mcp=[r["name"] for r in json.load(open('/tmp/mcpres/pypi250.json'))]
ctl=[r["name"] for r in json.load(open('/tmp/mcpres/pypi_control.json'))]
A=prof(mcp); B=prof(ctl)
json.dump({"mcp":A,"control":B},open('/tmp/mcpres/pypi_age.json','w'))
print(f"profiled: MCP {len(A)}, control {len(B)}")
