"""New r2 reconstruction. Explicit historical replay, never current-run impersonation."""
import base64, hashlib, importlib.util, json, math, re, sys, time, io, zipfile
from pathlib import Path
REPO='MametaroGG/booth-vrc-price-tracker'; REPO_ID=1134883798
API='https://api.github.com/repos/'+REPO
WORKFLOW='.github/workflows/daily_scrape.yml'; WORKFLOW_ID=223837658
SELECTOR_PIN='de5d1929249e92ebc8949448a5f839bb2893c5067b2484c916a7ba38c94fece5'
TRANSPORT_PIN='1214d8c4b1cfdc1441de395ca81a84c6061deb99e39bde557eb4e7a17350f7ba'
EXPECTED=dict(schema='boopa-saved-replay-plan-r1',run_id='42511857976',run_attempt='1',scrape_job_id='128826442906',artifact_id='13639946190',artifact_digest='sha256:1fb0c32f121918aae46fdb9e8e328888a94e5d3503f55399186bd8f12ff16fd2',saved_commit='55037ade650d560d6935d9d96537e1ca7fabdb04',producer_workflow_commit='f55d9865da808c7e98d41c51e28d91bad9f3acb0',producer_workflow_sha256='cef9acf3e52aabc868ff9465f3abdc167c6af331d5bd1b658c5872c6ee7d0887')
NAMES={'producer-run.json','producer-jobs.json','artifact.json','receipt.zip','saved-commit.json','collection-contents.json','workflow-contents.json'}
def need(v,m):
 if not v:raise ValueError('saved replay: '+m)
def sha(b):return hashlib.sha256(b).hexdigest()
def raw(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def oid(v,n=40):return type(v) is str and re.fullmatch('[0-9a-f]{'+str(n)+'}',v) is not None
def ident(v):return type(v) is str and re.fullmatch('[1-9][0-9]{0,15}',v) is not None and int(v)<=9007199254740991
def strict(b):
 need(type(b) is bytes and 0<len(b)<=2*1024*1024,'bounded JSON')
 def pairs(rows):
  d={}
  for k,v in rows:need(k not in d,'duplicate key');d[k]=v
  return d
 def number(s):
  v=float(s);need(math.isfinite(v),'nonfinite number');return v
 def bad(s):raise ValueError('nonfinite JSON')
 return json.loads(b,object_pairs_hook=pairs,parse_float=number,parse_constant=bad)
def modules(directory):
 p=Path(directory).resolve(strict=True)
 for name,pin in [('verify_saved_handoff.py',SELECTOR_PIN),('acquire_saved_handoff.py',TRANSPORT_PIN)]:
  f=p/name;need(f.is_file() and not f.is_symlink() and sha(f.read_bytes())==pin,'helper pin')
 name='verify_saved_handoff'
 if name in sys.modules:
  selector=sys.modules[name];need(Path(selector.__file__).resolve()==p/(name+'.py'),'module collision')
 else:
  sp=importlib.util.spec_from_file_location(name,p/(name+'.py'));selector=importlib.util.module_from_spec(sp);sp.loader.exec_module(selector);sys.modules[name]=selector
 sp=importlib.util.spec_from_file_location('replay_transport_r2',p/'acquire_saved_handoff.py');adapter=importlib.util.module_from_spec(sp);sp.loader.exec_module(adapter)
 return selector,adapter
def validate_plan(p):need(type(p) is dict and p==EXPECTED,'exact approved historical producer plan')
def validate_recovery(r,p):
 need(type(r) is dict,'recovery record')
 if r=={'kind':'local-offline'}:return
 need(set(r)=={'kind','repository','repository_id','run_id','run_attempt','workflow_commit','workflow_path'},'closed recovery')
 need(r['kind']=='github-actions-recovery' and r['repository']==REPO and type(r['repository_id']) is int and r['repository_id']==REPO_ID,'recovery repository')
 need(ident(r['run_id']) and ident(r['run_attempt']) and r['run_id']!=p['run_id'],'separate recovery run')
 need(oid(r['workflow_commit']) and r['workflow_path']=='.github/workflows/boopadb_recover.yml','recovery workflow')
def contents(b,path):
 v=strict(b);need(type(v) is dict and v.get('type')=='file' and v.get('path')==path and v.get('encoding')=='base64','contents relation')
 need(type(v.get('size')) is int and 0<v['size']<=65536 and type(v.get('content')) is str,'contents size')
 try:d=base64.b64decode(v['content'].replace('\n',''),validate=True)
 except Exception:raise ValueError('contents base64') from None
 need(len(d)==v['size'] and hashlib.sha1(b'blob '+str(len(d)).encode()+b'\0'+d).hexdigest()==v.get('sha'),'contents blob')
 return d
def provider(p,files):
 run=strict(files['producer-run.json']);jobs=strict(files['producer-jobs.json']);a=strict(files['artifact.json'])
 for k in ('id','run_attempt','workflow_id'):need(type(run.get(k)) is int,'run integer')
 need(run['id']==int(p['run_id']) and run['run_attempt']==int(p['run_attempt']) and run['workflow_id']==WORKFLOW_ID,'run identity')
 need(run.get('path')==WORKFLOW and run.get('head_branch')=='main' and run.get('head_sha')==p['producer_workflow_commit'],'reviewed producer workflow/event commit')
 need(run.get('status')=='completed' and run.get('conclusion') in ('success','failure') and run.get('event') in ('schedule','workflow_dispatch','repository_dispatch'),'completed producer')
 for k in ('repository','head_repository'):
  v=run.get(k);need(type(v) is dict and type(v.get('id')) is int and v['id']==REPO_ID and v.get('full_name')==REPO,'repo identity')
 need(type(jobs) is dict and type(jobs.get('total_count')) is int and type(jobs.get('jobs')) is list and 0<len(jobs['jobs'])==jobs['total_count']<=100,'complete jobs')
 ids=set();scrapes=[]
 for j in jobs['jobs']:
  need(type(j) is dict and type(j.get('id')) is int and j['id'] not in ids,'unique jobs');ids.add(j['id'])
  need(type(j.get('run_id')) is int and j['run_id']==int(p['run_id']) and type(j.get('run_attempt')) is int and j['run_attempt']==int(p['run_attempt']) and j.get('head_sha')==p['producer_workflow_commit'],'job producer')
  if j.get('name')=='scrape':scrapes.append(j)
 need(len(scrapes)==1,'one scrape');j=scrapes[0]
 need(j['id']==int(p['scrape_job_id']) and j.get('status')=='completed' and j.get('conclusion')=='success','successful scrape')
 need(type(j.get('steps')) is list,'steps');steps={}
 for s in j['steps']:
  need(type(s) is dict and type(s.get('name')) is str and s['name'] not in steps,'unique steps');steps[s['name']]=s
 for name in ('Run tests','Run Scraper','Commit and Push','Verify reviewed source after save','Record immutable saved collection','Retain immutable saved collection'):
  need(name in steps and steps[name].get('status')=='completed' and steps[name].get('conclusion')=='success','required step '+name)
 ar=a.get('workflow_run');need(type(ar) is dict and ar.get('head_repository_id')==REPO_ID and ar.get('head_branch')=='main' and ar.get('head_sha')==p['producer_workflow_commit'],'artifact event identity')
def verify(p,recovery,files,selector):
 validate_plan(p);validate_recovery(recovery,p);need(type(files) is dict and set(files)==NAMES,'exact evidence closure');provider(p,files)
 collection=contents(files['collection-contents.json'],'data/collection_receipt.json');workflow=contents(files['workflow-contents.json'],WORKFLOW)
 context=dict(schema='boopa-same-workflow-context-r2',server_url='https://github.com',actions='true',repository=REPO,repository_id=REPO_ID,run_id=p['run_id'],run_attempt=p['run_attempt'],workflow_ref=REPO+'/'+WORKFLOW+'@refs/heads/main',workflow_sha=p['producer_workflow_commit'],scrape_job_result='success',artifact_id=p['artifact_id'],artifact_digest=p['artifact_digest'],saved_commit=p['saved_commit'])
 cb=raw(context);s=selector.verify(cb,files['artifact.json'],files['receipt.zip'],collection,files['saved-commit.json'],workflow,p['producer_workflow_sha256'])
 with zipfile.ZipFile(io.BytesIO(files['receipt.zip'])) as z:saved=z.read('saved-collection.json')
 need(sha(saved)==s['saved_collection_sha256'],'extracted saved pin')
 inputs={'context.json':cb,'artifact.json':files['artifact.json'],'receipt.zip':files['receipt.zip'],'collection_receipt.json':collection,'saved-commit.json':files['saved-commit.json'],'workflow.yml':workflow}
 replay=dict(schema='boopa-historical-producer-replay-r2',producer_plan=p,recovery_execution=recovery,selection_sha256=sha(raw(s)),producer_context_sha256=sha(cb),evidence={n:dict(bytes=len(b),sha256=sha(b)) for n,b in files.items()},producer_run_completed=True,producer_job_success_verified_from_records=True,current_recovery_is_producer=False,authenticated_context_verified=False,runtime_execution_attested=False,publication_authorized=False,source_runner_independent_review='NOT-ACCEPTED-CONTENT-FLAG',scope='Historical producer consistency only. Mandatory replay sidecar; current recovery is separate. Externally reviewed workflow commit is checked against event commit, never inferred as current workflow identity.')
 return dict(selection=s,replay=replay,inputs=inputs,replay_evidence=files,saved_collection=saved)
def acquire(p,recovery,token,transport,selector,adapter,*,clock=time.monotonic):
 validate_plan(p);validate_recovery(recovery,p);need(type(token) is str and re.fullmatch('[A-Za-z0-9_.-]{1,4096}',token),'explicit token')
 paths={'producer-run.json':f"/actions/runs/{p['run_id']}/attempts/{p['run_attempt']}",'producer-jobs.json':f"/actions/runs/{p['run_id']}/attempts/{p['run_attempt']}/jobs?per_page=100",'artifact.json':f"/actions/artifacts/{p['artifact_id']}",'saved-commit.json':f"/git/commits/{p['saved_commit']}",'collection-contents.json':f"/contents/data/collection_receipt.json?ref={p['saved_commit']}",'workflow-contents.json':f"/contents/{WORKFLOW}?ref={p['producer_workflow_commit']}"}
 allowed={API+v for v in paths.values()}|{API+paths['artifact.json']+'/zip'};start=clock();calls=0;obs=[]
 def get(url,auth=True,status=200):
  nonlocal calls
  need(calls<8 and clock()-start<120,'GET budget');calls+=1
  if auth:need(url in allowed,'fixed API')
  else:adapter.storage_url(url)
  h={'Accept':'application/vnd.github+json','Accept-Encoding':'identity','User-Agent':'boopa-replay-r2'}
  if auth:h.update(Authorization='Bearer '+token,**{'X-GitHub-Api-Version':'2022-11-28'})
  limit=2*1024*1024 if url.endswith('/jobs?per_page=100') else 65536
  try:code,headers,b=transport(url,h,limit)
  except Exception:raise ValueError('replay GET failed; no retry') from None
  need(type(code) is int and code==status and type(headers) is dict and type(b) is bytes and len(b)<=limit,'GET response')
  need(headers.get('content-encoding','identity')=='identity','encoding')
  obs.append(dict(kind='fixed-api' if auth else 'credential-free-storage',status=code,bytes=len(b),sha256=sha(b)))
  return headers,b
 files={}
 for n in ('producer-run.json','producer-jobs.json','artifact.json'):files[n]=get(API+paths[n])[1]
 provider(p,files);a=strict(files['artifact.json']);need(a.get('digest')==p['artifact_digest'] and a.get('expired') is False,'artifact before download')
 headers,_=get(API+paths['artifact.json']+'/zip',status=302);url=headers.get('location');adapter.storage_url(url)
 files['receipt.zip']=get(url,False)[1];need('sha256:'+sha(files['receipt.zip'])==p['artifact_digest'],'wrapper pin')
 for n in ('saved-commit.json','collection-contents.json','workflow-contents.json'):files[n]=get(API+paths[n])[1]
 result=verify(p,recovery,files,selector);result['acquisition']=dict(schema='boopa-read-only-replay-acquisition-r2',requests=calls,observations=obs,runtime_execution_attested=False,publication_performed=False)
 return result
