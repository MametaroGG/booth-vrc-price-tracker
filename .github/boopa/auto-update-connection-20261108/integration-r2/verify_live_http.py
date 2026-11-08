"""Explicit post-Pages exact HTTP readback. No tokens, polling or remote writes.
Run selection is caller-pinned; observed summary is not provider authentication.
"""
import argparse,concurrent.futures,hashlib,json,re,time,urllib.request,urllib.parse
from pathlib import Path
BASE='https://mametarogg.github.io/boopadb/'
def need(v,m):
 if not v:raise ValueError(m)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def strict(raw):
 def pairs(rows):
  d={}
  for k,v in rows:need(k not in d,'Duplicate JSON key');d[k]=v
  return d
 return json.loads(raw,object_pairs_hook=pairs)
def pinned(path,pin):
 p=Path(path);need(p.is_file() and not p.is_symlink(),'Regular input required');raw=p.read_bytes();need(sha(raw)==pin,'Input hash differs');return strict(raw)
def path_ok(n):need(type(n) is str and n and not n.startswith('/') and '\\' not in n and all(p not in ('','.','..') for p in n.split('/')) and all(ord(c)>=32 for c in n),'Invalid public member')
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**kw):raise ValueError('Unexpected redirect')
def gate(plan_path,plan_pin,commit,run_path,run_pin,run_id):
 need(type(commit) is str and re.fullmatch('[0-9a-f]{40}',commit),'Exact commit required');need(type(run_id) is int and run_id>0,'Explicit Pages run ID required')
 run=pinned(run_path,run_pin);need(type(run['id']) is int and run['id']==run_id and type(run['attempt']) is int and run['attempt']>0,'Pages run identity differs')
 need(run['head']==commit and run['status']=='completed' and run['conclusion']=='success' and run['url']=='https://github.com/MametaroGG/boopadb/actions/runs/'+str(run_id),'Same-commit successful Pages observation required')
 plan=pinned(plan_path,plan_pin);candidate=Path(plan['candidate']);pin=plan['candidate_snapshot_sha256'];m=pinned(candidate/'snapshot-manifest.json',pin);need(m.get('fixture') is False,'Fixture cannot be checked as deployment')
 expected={**m['files'],'snapshot-manifest.json':pin};need(len(expected)==724,'Expected exact 724-member site')
 for n,h in expected.items():path_ok(n);need(type(h) is str and re.fullmatch('[0-9a-f]{64}',h),'Invalid member hash')
 return expected,pin

def get(name,want,commit):
 path_ok(name);url=BASE+urllib.parse.quote(name,safe='/')+'?publication_readback='+commit
 req=urllib.request.Request(url,headers={'Accept-Encoding':'identity','Cache-Control':'no-cache'});op=urllib.request.build_opener(NoRedirect);h=hashlib.sha256();size=0
 with op.open(req,timeout=60) as r:
  need(r.status==200 and r.geturl()==url,'Unexpected HTTP endpoint/status');need(r.headers.get('Content-Encoding','identity')=='identity','Unexpected encoding')
  while True:
   b=r.read(1024*1024)
   if not b:break
   size+=len(b);need(size<=128*1024*1024,'Oversize public response');h.update(b)
 need(h.hexdigest()==want,'Public SHA differs');return {'path':name,'http_status':200,'bytes':size,'sha256':h.hexdigest()}

def verify(plan_path,plan_pin,commit,run_path,run_pin,run_id,output,*,transport=None):
 expected,pin=gate(plan_path,plan_pin,commit,run_path,run_pin,run_id);out=Path(output);need(out.is_absolute() and out.parent.resolve()==out.parent and not out.exists() and not out.is_symlink(),'New output required')
 getter=transport or get;start=time.time();getter('snapshot-manifest.json',pin,commit);results=[];errors=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
  jobs={pool.submit(getter,n,h,commit):n for n,h in expected.items()}
  for f in concurrent.futures.as_completed(jobs):
   n=jobs[f]
   try:
    v=f.result();need(v['path']==n and v['sha256']==expected[n] and v['http_status']==200 and type(v['bytes']) is int and 0<=v['bytes']<=128*1024*1024,'Malformed readback result');results.append(v)
   except Exception:errors.append({'path':n,'error':'HTTP readback failed or hash differs'})
 result={'schema':'public-pages-exact-http-readback-r2','commit':commit,'snapshot_sha256':pin,'pages_run_id':run_id,'pages_observation_sha256':run_pin,'plan_sha256':plan_pin,'url':BASE,'started_unix':start,'finished_unix':time.time(),'matched':len(results),'bytes':sum(v['bytes'] for v in results),'expected_files':724,'results':sorted(results,key=lambda v:v['path']),'errors':errors,'status':'PASS' if not errors and len(results)==724 else 'incomplete','transport_scope':'synthetic-injected' if transport is not None else 'actual-public-https','provider_run_authenticated_by_this_script':False,'publication_acceptance':False}
 with out.open('x') as f:json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser()
 for k in ('plan','plan-pin','commit','pages-observation','pages-pin','output'):p.add_argument('--'+k,required=True)
 p.add_argument('--pages-run-id',type=int,required=True);a=p.parse_args();r=verify(a.plan,a.plan_pin,a.commit,a.pages_observation,a.pages_pin,a.pages_run_id,a.output);raise SystemExit(0 if r['status']=='PASS' else 1)
