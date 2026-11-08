#!/usr/bin/env python3
"""Offline connector operation plan. No network, credentials, publication or scheduling.
Requires externally pinned reviewed candidate/plan and read-only Git tree receipts.
This verifies bytes/objects, not producer completion, source-code QA or authorization.
"""
import argparse,base64,hashlib,json,re
from pathlib import Path,PurePosixPath

REPO='MametaroGG/boopadb'
def sha(b):return hashlib.sha256(b).hexdigest()
def oid(kind,b):return hashlib.sha1(kind.encode()+b' '+str(len(b)).encode()+b'\0'+b).hexdigest()
def safe(name):
 p=PurePosixPath(name)
 if not isinstance(name,str) or not name or p.is_absolute() or '..' in p.parts or '\\' in name or str(p)!=name:raise ValueError('unsafe path')
 return p

def git_tree(files):
 root={}
 for name,x in files.items():
  parts=safe(name).parts;d=root
  for part in parts[:-1]:
   if part in d and not isinstance(d[part],dict):raise ValueError('tree collision')
   d=d.setdefault(part,{})
  if parts[-1] in d:raise ValueError('duplicate path')
  if x['mode'] not in ('100644','100755') or not re.fullmatch('[0-9a-f]{40}',x['sha']):raise ValueError('unsupported mode/OID')
  d[parts[-1]]=(x['mode'],x['sha'])
 def build(d):
  rows=[]
  for name,x in d.items():
   mode,h=('40000',build(x)) if isinstance(x,dict) else x
   rows.append((name+('/' if isinstance(x,dict) else ''),mode,name,h))
  body=b''.join(mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(h) for _,mode,name,h in sorted(rows,key=lambda x:x[0].encode()))
  return oid('tree',body)
 return build(root)

def make_plan(candidate,plan_path,plan_sha,tree_path,tree_sha,base_tree,expected_parent,request_budget=4*1024*1024,allow_fixture=False):
 candidate=Path(candidate).resolve()
 if request_budget<=0:raise ValueError('positive request budget required')
 raw=Path(plan_path).read_bytes()
 if sha(raw)!=plan_sha:raise ValueError('plan pin mismatch')
 p=json.loads(raw)
 if p.get('status')!='dry-run-plan' or p.get('single_commit_required') is not True or p.get('delete_paths')!=[]:raise ValueError('not a reviewed no-delete plan')
 if (p.get('owner'),p.get('repository'),p.get('branch'))!=('MametaroGG','boopadb','main'):raise ValueError('wrong repository')
 if p.get('expected_parent_commit')!=expected_parent or not re.fullmatch('[0-9a-f]{40}',expected_parent):raise ValueError('parent mismatch')
 if p.get('fixture') and not allow_fixture:raise ValueError('fixture blocked')
 raw=Path(tree_path).read_bytes()
 if sha(raw)!=tree_sha:raise ValueError('tree receipt pin mismatch')
 t=json.loads(raw)
 if t.get('truncated') is not False:raise ValueError('incomplete tree')
 old={}
 for x in t['tree']:
  safe(x['path'])
  if x['type']=='tree':continue
  if x['type']!='blob' or x['path'] in old:raise ValueError('invalid/duplicate tree entry')
  old[x['path']]={'sha':x['sha'],'mode':x['mode']}
 if git_tree(old)!=base_tree:raise ValueError('base tree reconstruction mismatch')
 files=p['files'];actual=set()
 for f in candidate.rglob('*'):
  if f.is_symlink():raise ValueError('symlink')
  if f.is_file():actual.add(str(f.relative_to(candidate)))
 if actual!=set(files):raise ValueError('candidate inventory mismatch')
 changes=[];reuse=[];blocked=[];final=dict(old)
 for name,h in sorted(files.items()):
  safe(name);b=(candidate/name).read_bytes()
  if sha(b)!=h:raise ValueError('candidate hash mismatch: '+name)
  goid=oid('blob',b);final[name]={'sha':goid,'mode':'100644'}
  if old.get(name)==final[name]:reuse.append(name);continue
  try:content=b.decode('utf-8');encoding='utf-8'
  except UnicodeDecodeError:content=base64.b64encode(b).decode('ascii');encoding='base64'
  envelope={'repository_full_name':REPO,'content':content,'encoding':encoding}
  encoded=len(json.dumps(envelope,ensure_ascii=False,separators=(',',':')).encode())
  entry={'path':name,'sha256':h,'bytes':len(b),'git_blob_oid':goid,'encoding':encoding,'json_request_bytes':encoded}
  changes.append(entry)
  if encoded>request_budget:blocked.append(name)
 manifest=files.get('snapshot-manifest.json')
 if manifest!=p.get('candidate_manifest_sha256'):raise ValueError('manifest pin mismatch')
 m=json.loads((candidate/'snapshot-manifest.json').read_text())
 if m.get('files')!={k:v for k,v in files.items() if k!='snapshot-manifest.json'}:raise ValueError('manifest differs from plan')
 return {'schema':1,'status':'offline-connector-plan','published':False,'publication_authorized':False,'repository':REPO,'branch':'main','expected_parent':expected_parent,'base_tree':base_tree,'proposed_tree':git_tree(final),'plan_sha256':plan_sha,'candidate_manifest_sha256':manifest,'reused':reuse,'create_blobs':changes,'preserve_unrelated':sorted(set(old)-set(files)),'delete_paths':[],'request_budget_assumption_bytes':request_budget,'over_budget':blocked,'endpoint_limit_verified':False,'remote_head_verified':False,'producer_completion_independently_verified':False,'required_before_write':['Reviewed exact publication authorization','Fresh remote HEAD and tree binding','Transport capability and payload size test','Immutable candidate recheck','Durable journal and uncertain-result reconciliation'],'recurring_trigger_installed':False}

def main():
 a=argparse.ArgumentParser(description=__doc__)
 for k in ('candidate','plan-path','plan-sha','tree-path','tree-sha','base-tree','expected-parent','output'):a.add_argument('--'+k,required=True)
 a.add_argument('--request-budget',type=int,default=4*1024*1024);a.add_argument('--allow-fixture',action='store_true');v=vars(a.parse_args());out=Path(v.pop('output'))
 if Path(v['candidate']).resolve() in out.resolve().parents:raise ValueError('output must be outside candidate')
 result=make_plan(**v)
 with out.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
 print(json.dumps({'status':result['status'],'changed':len(result['create_blobs']),'over_budget':result['over_budget'],'published':False}))
if __name__=='__main__':main()
