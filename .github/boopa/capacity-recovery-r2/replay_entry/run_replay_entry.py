"""Read-only saved replay entry. Caller verifies this complete code freeze first."""
import argparse,hashlib,importlib.util,io,json,os,zipfile
from pathlib import Path
def need(v,m):
 if not v:raise ValueError('replay entry: '+m)
def sha(b):return hashlib.sha256(b).hexdigest()
def strict(raw):
 def pairs(rows):
  d={}
  for k,v in rows:need(k not in d,'duplicate key');d[k]=v
  return d
 return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def selector_files(v):
 out=dict(v['inputs'])
 with zipfile.ZipFile(io.BytesIO(out['receipt.zip'])) as z:
  rows=z.infolist();need(len(rows)==1 and rows[0].filename=='saved-collection.json' and not rows[0].is_dir(),'ZIP closure');out['saved-collection.json']=z.read(rows[0])
 need(set(out)==set(v['selection']['evidence']),'selector closure')
 for n,b in out.items():need(len(b)==v['selection']['evidence'][n]['bytes'] and sha(b)==v['selection']['evidence'][n]['sha256'],'selector pin')
 return out
def check_persisted(rt,replay,p,recovery,directory,selector):
 c=rt.strict((directory/'COMPLETE.json').read_bytes());need(set(c)=={'schema','selection','mandatory_replay','evidence','selector_evidence','publication_performed'} and c['schema']=='boopa-replay-evidence-complete-r2' and c['publication_performed'] is False,'complete schema')
 for closure in ('evidence','selector_evidence'):
  need(type(c[closure]) is dict,'closure map')
  for n,ref in c[closure].items():
   need(type(n) is str and Path(n).name==n and n not in ('','.','..'),'flat name');f=directory/n;need(f.is_file() and not f.is_symlink() and ref==rt.reference(f),'persisted pin')
 v=replay.verify(p,recovery,{n:(directory/n).read_bytes() for n in c['evidence']},selector);selected=selector_files(v)
 need(set(c['selector_evidence'])==set(selected),'selector closure changed')
 for n,b in selected.items():need((directory/n).read_bytes()==b,'selector bytes changed')
 for n,key in [('SELECTION.json','selection'),('REPLAY.json','replay')]:need((directory/n).read_bytes()==replay.raw(v[key]),'selection/sidecar bytes')
 need(c['selection']==rt.reference(directory/'SELECTION.json') and c['mandatory_replay']==rt.reference(directory/'REPLAY.json'),'sidecar pins');return v
def persist_replay(rt,replay,p,recovery,result,selector,directory):
 v=replay.verify(p,recovery,result['replay_evidence'],selector)
 need(all(v[k]==result[k] for k in ('selection','replay','inputs')),'recomputed replay differs');selected=selector_files(v);merged=dict(v['replay_evidence'])
 for n,b in selected.items():
  if n in merged:need(merged[n]==b,'overlapping evidence differs')
  merged[n]=b
 directory.mkdir(mode=0o700)
 for n,b in merged.items():
  need(Path(n).name==n and n not in ('','.','..') and type(b) is bytes,'flat evidence')
  with (directory/n).open('xb') as f:f.write(b)
 for n,key in [('SELECTION.json','selection'),('REPLAY.json','replay')]:
  with (directory/n).open('xb') as f:f.write(replay.raw(v[key]))
 complete=rt.emit(directory/'COMPLETE.json',{'schema':'boopa-replay-evidence-complete-r2','selection':rt.reference(directory/'SELECTION.json'),'mandatory_replay':rt.reference(directory/'REPLAY.json'),'evidence':{n:rt.reference(directory/n) for n in v['replay_evidence']},'selector_evidence':{n:rt.reference(directory/n) for n in selected},'publication_performed':False})
 return check_persisted(rt,replay,p,recovery,directory,selector),complete

def connect(p,out,token,modules,execution_kind):
 need(execution_kind in ('synthetic-wiring-only','runtime-read-entries-returned'),'execution scope')
 rt,replay,selector,adapter,prior,identity,selected,integration,observation=[modules[k] for k in ('runtime','replay','selector','adapter','prior','identity','selected','integration','observation')]
 out=Path(out);out.mkdir(mode=0o700);evidence=out/'identity-evidence';evidence.mkdir(mode=0o700)
 result=replay.acquire(p['producer'],p['recovery'],token,modules['transport'],selector,adapter)
 verified,complete=persist_replay(rt,replay,p['producer'],p['recovery'],result,selector,out/'replay')
 selection=verified['selection'];sref=rt.reference(out/'replay/SELECTION.json');sidecar=rt.reference(out/'replay/REPLAY.json')
 repo=out/'public-repository';repo.mkdir(mode=0o700);prior.load_git().git(repo,'init');observed,blobs,management=prior.fetch_current(repo);del blobs
 pref=rt.emit(evidence/'PRIOR-OBSERVATION.json',observed);rt.emit(evidence/'MANAGEMENT.json',management)
 identities=selected.acquire_selected(identity,selection['saved_commit'],observed['previous_price_source_commit'],token,modules['transport'])
 for name,raw in identities['files'].items():
  need(Path(name).name==name and name not in ('','.','..') and type(raw) is bytes,'identity file')
  with (evidence/name).open('xb') as f:f.write(raw)
 source,policy=rt.source_plan(rt.ref(p['source_plan_template']),sref,selection,rt.strict(verified['inputs']['collection_receipt.json']),observed,identities,evidence,observation,out/'generated/prior-candidate',pref)
 sr=rt.emit(evidence/'SOURCE-PLAN.json',source);rt.emit(evidence/'DATE-POLICY.json',policy)
 ip={'schema':'boopa-explicit-replay-integration-plan-r2','mandatory_replay':sidecar,'replay_complete':complete,'source_plan':sr,'code':p['integration_code_groups'],'repository_path':str(repo),'expected_public_parent_commit':observed['expected_public_parent_commit'],'prior_mode':'inspect-local','approval_directory':p['approval_directory']};ipr=rt.emit(evidence/'INTEGRATION-PLAN.json',ip)
 need(rt.reference(out/'replay/COMPLETE.json')==complete,'complete changed');checked=check_persisted(rt,replay,p['producer'],p['recovery'],out/'replay',selector)
 need(rt.ref(sidecar)==checked['replay'] and rt.ref(sref)==checked['selection'],'mandatory boundary')
 generated=out/'generated';generated.mkdir(mode=0o700)
 request=integration.connect(ip,generated,prior,modules['source'],modules['pipeline'],selection,sref);need(request['publication_performed'] is False,'publication off')
 receipt={'schema':'boopa-replay-generation-result-r2','execution_kind':execution_kind,'mandatory_replay':sidecar,'replay_complete':complete,'selection':sref,'recovery_execution':p['recovery'],'integration_plan':ipr,'publish_request':rt.reference(generated/'PUBLISH-REQUEST.json'),'publication_performed':False,'publish_token_read':False,'provider_authenticated':False,'source_runner_independent_review':'NOT-ACCEPTED-CONTENT-FLAG'}
 rt.emit(out/'COMPLETE.json',receipt);return receipt

def recovery_from_env(env):
 need(env.get('GITHUB_ACTIONS')=='true' and env.get('GITHUB_SERVER_URL')=='https://github.com','Actions context');repo=env.get('GITHUB_REPOSITORY');rid=env.get('GITHUB_REPOSITORY_ID');path='.github/workflows/boopadb_recover.yml'
 need(type(rid) is str and rid.isdecimal(),'repository id');need(env.get('GITHUB_WORKFLOW_REF')==str(repo)+'/'+path+'@refs/heads/main','recovery workflow')
 return {'kind':'github-actions-recovery','repository':repo,'repository_id':int(rid),'run_id':env.get('GITHUB_RUN_ID'),'run_attempt':env.get('GITHUB_RUN_ATTEMPT'),'workflow_commit':env.get('GITHUB_WORKFLOW_SHA'),'workflow_path':path}
KEYS={'schema','runtime_code','replay_code','identity_code','prior_code','integration_code','integration_code_groups','acquisition_code_directory','source_plan_template','approval_directory','producer','recovery'}
def run(plan_path,plan_pin,output,token,recovery):
 raw=Path(plan_path).read_bytes();need(sha(raw)==plan_pin,'plan hash');p=strict(raw);need(type(p) is dict and set(p)==KEYS and p['schema']=='boopa-replay-generation-plan-r2','closed plan')
 group=p['runtime_code'];need(set(group)=={'directory','freeze'},'runtime group');root=Path(group['directory']);fp=Path(group['freeze']['path']);need(root.is_absolute() and root.resolve()==root and fp.parent==root and not fp.is_symlink(),'runtime path');fraw=fp.read_bytes();need(sha(fraw)==group['freeze']['sha256'],'runtime freeze');f=strict(fraw);entry=root/'run_generation_entry.py';pin=f['files']['run_generation_entry.py'];pin=pin['sha256'] if type(pin) is dict else pin;need(not entry.is_symlink() and sha(entry.read_bytes())==pin,'runtime code')
 rt=load('replay_runtime',entry);roots={k:rt.freeze(p[k]) for k in ('runtime_code','replay_code','identity_code','prior_code','integration_code')};need(set(p['integration_code_groups'])=={'prior','source','pipeline','publisher'},'groups');groups={k:rt.freeze(v) for k,v in p['integration_code_groups'].items()};need(p['prior_code']==p['integration_code_groups']['prior'],'prior code');rt.ref(p['source_plan_template'])
 out=Path(output).absolute();need(out.parent.resolve()==out.parent and not out.exists() and not out.is_symlink(),'fresh output')
 for r in [*roots.values(),*groups.values(),Path(plan_path).resolve().parent,Path(p['approval_directory']).resolve(),Path(p['acquisition_code_directory']).resolve()]:need(r!=out and r not in out.parents and out not in r.parents,'output overlap')
 replay=load('replay_saved',roots['replay_code']/'replay_saved.py');replay.validate_plan(p['producer']);replay.validate_recovery(p['recovery'],p['producer']);need(recovery==p['recovery'],'actual recovery differs');selector,adapter=replay.modules(p['acquisition_code_directory'])
 modules={'runtime':rt,'replay':replay,'selector':selector,'adapter':adapter,'transport':adapter.HTTPSGet(),'prior':load('replay_prior',roots['prior_code']/'read_previous_production.py'),'identity':load('replay_identity',roots['identity_code']/'acquire_git_identities.py'),'selected':load('replay_selected',Path(__file__).with_name('acquire_selected.py')),'integration':load('replay_integration',roots['integration_code']/'run_integration.py'),'observation':load('replay_observation',roots['identity_code']/'observation_validation.py'),'source':load('replay_source',groups['source']/'run_source.py'),'pipeline':load('replay_pipeline',groups['pipeline']/'run_pipeline.py')}
 return connect(p,out,token,modules,'runtime-read-entries-returned')
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--plan',required=True);a.add_argument('--plan-sha256',required=True);a.add_argument('--output',required=True);v=a.parse_args();run(v.plan,v.plan_sha256,v.output,os.environ.get('GITHUB_TOKEN'),recovery_from_env(os.environ))
