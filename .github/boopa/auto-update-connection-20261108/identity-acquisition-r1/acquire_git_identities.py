"""Fixed tracker GET identity acquisition. No network/env access on import.
All returned records are evidence, not self-authentication or publication authority.
"""
import datetime,email.utils,hashlib,importlib.util,json,math,re,time
from pathlib import Path
BASE='https://api.github.com/repos/MametaroGG/booth-vrc-price-tracker'
ADAPTER_PIN='1214d8c4b1cfdc1441de395ca81a84c6061deb99e39bde557eb4e7a17350f7ba'
SELECTOR_PIN='de5d1929249e92ebc8949448a5f839bb2893c5067b2484c916a7ba38c94fece5'
LIMIT=2*1024*1024
UTC=datetime.timezone.utc

def need(v,m):
 if not v:raise ValueError('Git identity acquisition: '+m)
def sha(b):return hashlib.sha256(b).hexdigest()
def enc(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def oid(v):need(type(v) is str and re.fullmatch('[0-9a-f]{40}',v),'canonical Git OID');return v
def pin(v):need(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'canonical digest');return v
def iso(t):return datetime.datetime.fromtimestamp(t,UTC).isoformat().replace('+00:00','Z')
def strict(raw):
 need(type(raw) is bytes and 0<len(raw)<=LIMIT,'bounded JSON')
 def pairs(rows):
  d={}
  for k,v in rows:need(k not in d,'duplicate JSON key');d[k]=v
  return d
 def bad(v):raise ValueError('Git identity acquisition: nonfinite JSON')
 def number(v):
  f=float(v);need(math.isfinite(f),'finite JSON number');return f
 return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad,parse_float=number)
def load_adapter():
 # Resolve only sibling pinned modules; no sys.path lookup of secret/config files.
 p=Path(__file__).resolve().parent.parent
 need(sha((p/'verify_saved_handoff.py').read_bytes())==SELECTOR_PIN,'selector pin')
 need(sha((p/'acquire_saved_handoff.py').read_bytes())==ADAPTER_PIN,'GET adapter pin')
 import sys
 name='verify_saved_handoff'
 if name in sys.modules:need(Path(sys.modules[name].__file__).resolve()==p/(name+'.py'),'unexpected loaded selector')
 else:
  s=importlib.util.spec_from_file_location(name,p/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);sys.modules[name]=m
 spec=importlib.util.spec_from_file_location('identity_existing_get_adapter',p/'acquire_saved_handoff.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def tree_identity(body,expected):
 need(type(body) is dict and body.get('sha')==oid(expected) and body.get('truncated') is False and type(body.get('tree')) is list,'complete root response')
 records=[];names=set();sub={}
 for row in body['tree']:
  need(type(row) is dict,'tree entry');name=row.get('path');mode=row.get('mode');kind=row.get('type')
  need(type(name) is str and name not in ('','.','..') and '/' not in name and '\\' not in name and all(ord(x)>=32 and ord(x)!=127 for x in name) and name not in names,'direct unique tree path');names.add(name)
  need((kind,mode) in {('tree','040000'),('blob','100644'),('blob','100755')},'supported source root type/mode');h=oid(row.get('sha'))
  n=name.encode();records.append((n+(b'/' if kind=='tree' else b''),(b'40000' if kind=='tree' else mode.encode())+b' '+n+b'\0'+bytes.fromhex(h)))
  if name in ('data','meta'):need(kind=='tree','source subtree');sub[name]=h
 raw=b''.join(v for _,v in sorted(records));need(hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==expected,'Git root rehash')
 need(set(sub)=={'data','meta'},'required source subtrees');return sub

class Reader:
 def __init__(self,token,transport,clock,monotonic):
  need(type(token) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,4096}',token),'explicit tracker runtime token')
  self.token=token;self.transport=transport;self.clock=clock;self.monotonic=monotonic;self.started=monotonic();self.calls=0;self.files={};self.responses={};self.cache={}
 def get(self,path,label):
  need(re.fullmatch(r'/(git/ref/heads/main|git/commits/[0-9a-f]{40}|git/trees/[0-9a-f]{40})',path),'fixed GET endpoint')
  need(self.calls<10 and self.monotonic()-self.started<90,'request/time budget');self.calls+=1;url=BASE+path;before=self.clock()
  headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json','Accept-Encoding':'identity','X-GitHub-Api-Version':'2022-11-28','User-Agent':'boopa-source-identity-r1'}
  try:status,h,b=self.transport(url,headers,LIMIT)
  except Exception:raise ValueError('Git identity acquisition: transport failure') from None
  after=self.clock();need(type(status) is int and status==200,'GET status; no redirect/retry');need(type(h) is dict and h.get('content-encoding','identity')=='identity','response headers')
  body=strict(b);need(type(body) is dict,'object response')
  date=h.get('date');need(type(date) is str and len(date)<=64,'provider HTTP Date required')
  try:dt=email.utils.parsedate_to_datetime(date)
  except Exception:raise ValueError('Git identity acquisition: provider date') from None
  need(dt is not None and dt.tzinfo is not None and dt.utcoffset()==datetime.timedelta(0),'provider UTC date')
  ts=dt.timestamp();need(before<=after and before-300<=ts<=after+300,'stale/future provider date')
  name=label+'.json';self.files[name]=b;self.responses[label]={'url':url,'response_raw':b.decode('utf-8'),'response_sha256':sha(b),'response_utf8_bytes':len(b),'http_date':date,'provider_utc':iso(ts),'observed_from_utc':iso(before),'observed_through_utc':iso(after)}
  return body,{'path':name,'sha256':sha(b)},ts
 def identity(self,commit,prefix):
  commit=oid(commit)
  if commit in self.cache:return self.cache[commit]
  c,cp,_=self.get('/git/commits/'+commit,prefix+'-commit');need(c.get('sha')==commit and type(c.get('tree')) is dict,'commit identity');root=oid(c['tree'].get('sha'))
  t,tp,_=self.get('/git/trees/'+root,prefix+'-root');sub=tree_identity(t,root)
  obj={'schema':'boopa-git-source-identity-r1','commit':commit,'root_tree':root,'metadata_tree':sub['meta'],'data_tree':sub['data'],'commit_response':cp,'root_response':tp}
  self.cache[commit]=obj;return obj

def acquire(env,needs,previous_price_source_commit,transport,*,clock=time.time,monotonic=time.monotonic):
 adapter=load_adapter();ctx=adapter.capture(env,needs);previous=oid(previous_price_source_commit)
 r=Reader(env.get('GITHUB_TOKEN'),transport,clock,monotonic)
 saved=r.identity(ctx['saved_commit'],'saved');prior=r.identity(previous,'prior')
 before,bp,_=r.get('/git/ref/heads/main','latest-before')
 def head(v):
  need(v.get('ref')=='refs/heads/main' and type(v.get('object')) is dict and v['object'].get('type')=='commit','main ref response');return oid(v['object'].get('sha'))
 current=head(before)
 # Deliberately obtain current commit/root inside the two-ref observation window.
 r.cache.pop(current,None);latest=r.identity(current,'latest')
 after,ap,_=r.get('/git/ref/heads/main','latest-after');need(head(after)==current,'main moved; do not retry')
 identities={'saved':saved,'prior':prior,'latest':latest};refs={}
 for key,obj in identities.items():
  name=key+'-identity.json';r.files[name]=enc(obj);refs[key]={'path':name,'sha256':sha(r.files[name])}
 recent={k:v for k,v in r.responses.items() if k.startswith('latest-')};dates=[v['provider_utc'] for v in recent.values()]
 observation={'schema':'boopa-latest-source-observation-r1','identity_proof':refs['latest'],'ref_before':bp,'ref_after':ap,'main_stable_across_two_reads':True,'observed_from_utc':r.responses['latest-before']['observed_from_utc'],'observed_through_utc':r.responses['latest-after']['observed_through_utc'],'provider_observation_upper_utc':max(dates),'responses':recent,'provider_authenticated':False,'runtime_execution_attested':False}
 r.files['LATEST-OBSERVATION.json']=enc(observation)
 return {'schema':'boopa-source-identity-acquisition-r1','identity_proofs':refs,'latest_observation':{'path':'LATEST-OBSERVATION.json','sha256':sha(r.files['LATEST-OBSERVATION.json'])},'requests':r.calls,'provider_authenticated':False,'runtime_execution_attested':False,'files':r.files}

def validate_observation(observation_raw,expected_sha256,files):
 p=Path(__file__).resolve().parent/'observation_validation.py'
 spec=importlib.util.spec_from_file_location('identity_observation_validation',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 return m.validate_observation_bytes(observation_raw,expected_sha256,files)

def fresh_guard_inputs(bundle,candidate_snapshot,cutoff_commit,cutoff_meta,negative_scan_pin):
 """Exact metadata-tree relation only; does not manufacture full scan/provider authority."""
 pin(candidate_snapshot);oid(cutoff_commit);oid(cutoff_meta);pin(negative_scan_pin)
 files=bundle['files'];op=bundle['latest_observation'];ob=files[op['path']];need(sha(ob)==op['sha256'],'observation pin');o=strict(ob)
 ip=o['identity_proof'];ib=files[ip['path']];need(sha(ib)==ip['sha256'],'latest identity pin');ident=strict(ib)
 validate_observation(ob,op['sha256'],files)
 need(ident['metadata_tree']==cutoff_meta and o['main_stable_across_two_reads'] is True,'latest classification required; metadata differs')
 keys={'transfer_fresh_before':'latest-before','transfer_fresh_after':'latest-after','transfer_fresh_commit':'latest-commit','transfer_fresh_root':'latest-root'}
 body={'responses':{k:{'url':o['responses'][v]['url'],'response_raw':o['responses'][v]['response_raw']} for k,v in keys.items()}};raw=enc(body);name='FRESH-PROVIDER-RESPONSES.json'
 evidence={k:{'url':o['responses'][v]['url'],'response_sha256':o['responses'][v]['response_sha256'],'response_utf8_bytes':o['responses'][v]['response_utf8_bytes']} for k,v in keys.items()}
 guard={'schema':'boopa-prerefswitch-fresh-negative-tree-binding-r1','status':'same-metadata-tree-as-verified-negative-cutoff','candidate_snapshot_observed_sha256':candidate_snapshot,'metadata_tree_equal':True,'stored_negative_classification_equal_by_exact_tree_identity':True,'current':{'head':ident['commit'],'root':ident['root_tree'],'metadata_tree':ident['metadata_tree'],'main_stable_across_two_reads':True},'negative_policy_cutoff':{'commit':cutoff_commit,'metadata_tree':cutoff_meta,'complete_metadata_scan_receipt_sha256':negative_scan_pin},'observed_from_utc':o['observed_from_utc'],'observed_through_utc':o['observed_through_utc'],'provider_evidence':{'file':name,'bytes':len(raw),'sha256':sha(raw),'responses':evidence},'provider_authenticated':False,'runtime_execution_attested':False}
 return {'FRESH-NEGATIVE-BINDING.json':enc(guard),name:raw}

def acquire_current_actions(needs,previous_price_source_commit):
 import os
 adapter=load_adapter();return acquire(os.environ,needs,previous_price_source_commit,adapter.HTTPSGet())
