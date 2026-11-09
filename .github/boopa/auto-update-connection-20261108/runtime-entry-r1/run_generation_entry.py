"""Explicit read-only Actions-to-local-generation wiring. Publication stays OFF.
Caller verifies this entry SHA and portable dependency closure before invoking it.
"""
import argparse,copy,datetime,hashlib,importlib.util,json,os,re,sys
from pathlib import Path
ACQUISITION_ENTRY_PIN='7601f188b0e003637cd4f330bb7ebb1786b777ce004a7acc5d33034c4fa3a4fe'
SELECTOR_PIN='de5d1929249e92ebc8949448a5f839bb2893c5067b2484c916a7ba38c94fece5'

def need(v,m):
 if not v:raise ValueError('generation entry: '+m)
def sha(b):return hashlib.sha256(b).hexdigest()
def strict(b):
 def pairs(rows):
  d={}
  for k,v in rows:need(k not in d,'duplicate key');d[k]=v
  return d
 return json.loads(b,object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
def reference(p):return {'path':str(p),'sha256':sha(p.read_bytes())}
def ref(entry):
 need(type(entry) is dict and set(entry)=={'path','sha256'},'closed pinned file ref');p=Path(entry['path']);need(p.is_absolute() and p.resolve()==p and p.is_file() and not p.is_symlink(),'resolved regular ref');b=p.read_bytes();need(sha(b)==entry['sha256'],'ref hash');return strict(b)
def emit(path,value):
 with path.open('x') as f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
 return reference(path)
def freeze(entry):
 need(type(entry) is dict and set(entry)=={'directory','freeze'},'closed code group');root=Path(entry['directory']);need(root.is_absolute() and root.resolve()==root,'resolved code root');f=ref(entry['freeze']);need(Path(entry['freeze']['path']).parent==root,'code freeze location')
 for name,pin in f['files'].items():
  relative=Path(name);need(not relative.is_absolute() and '..' not in relative.parts,'code member path');p=root/relative;need(p.resolve().is_relative_to(root) and p.is_file() and not p.is_symlink(),'regular code member');h=pin['sha256'] if type(pin) is dict else pin;need(sha(p.read_bytes())==h,'code member SHA')
 return root

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def identity_ref(bundle,key,directory):
 item=bundle['identity_proofs'][key];name=item['path'];need(type(name) is str and Path(name).name==name,'flat identity path');p=directory/name;need(sha(p.read_bytes())==item['sha256'],'materialized identity pin');return reference(p),strict(p.read_bytes())

def source_plan(template,selection_ref,selection,collection,prior,identity_bundle,evidence_dir,observation_module,planned_prior,prior_handoff_ref):
 """Fill only dynamic identities; frozen helper/adapter pins remain verbatim."""
 p=copy.deepcopy(template);need(set(p)=={'schema','source','latest','selection','prior','helpers','sourceprep','archive_adapter','public_parent'} and p['schema']=='boopa-source-runner-plan-r2','closed source runner-r2 template')
 need(set(p['prior'])=={'candidate_path','snapshot_sha256','archive_source'},'archive-based previous backend template required')
 refs={};identities={}
 for key in ('saved','prior','latest'):refs[key],identities[key]=identity_ref(identity_bundle,key,evidence_dir)
 need(identities['saved']['commit']==selection['saved_commit'] and identities['saved']['root_tree']==selection['saved_root'],'acquired saved identity vs selection')
 need(identities['prior']['commit']==prior['previous_price_source_commit'],'previous source provenance')
 op=identity_bundle['latest_observation'];observation={'path':str(evidence_dir/op['path']),'sha256':op['sha256']}
 observed=observation_module.validate_observation(observation['path'],observation['sha256'],identities['latest']['commit'],identities['latest']['metadata_tree'])
 stopped=collection['stopped_at_ms'];need(type(stopped) is int and stopped>=0,'exact saved stopped_at')
 saved_day=datetime.datetime.fromtimestamp(stopped/1000,datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()
 def archive(key):
  v=identities[key];return {'commit':v['commit'],'root_tree':v['root_tree'],'metadata_tree':v['metadata_tree'],'identity_proof':refs[key],'official_download':True}
 p['source']={**archive('saved'),'as_of':saved_day}
 p['latest']={**archive('latest'),'observation':observation}
 # Date policy is explicitly documented; never use price day or unchecked today.
 p['prior']={'candidate_path':str(planned_prior),'snapshot_sha256':prior['prior_snapshot_sha256'],'archive_source':{**archive('prior'),'as_of':observed['upper_jst_date']}}
 p['selection']=selection_ref;p['public_parent']=prior_handoff_ref
 return p,{'saved_price_validation_day':saved_day,'latest_marker_observation_sha256':observation['sha256'],'prior_inventory_marker_ceiling_day':observed['upper_jst_date'],'prior_ceiling_basis':'verified-provider-observation-after-prior-identity-read; complete prior archive scanner must reject later metadata','publication_enabled':False}

def connect(plan,output,env,modules,*,execution_kind):
 """Small wiring seam for synthetic tests. Real entry supplies concrete modules."""
 need(execution_kind in ('synthetic-wiring-only','runtime-read-entries-returned'),'execution scope')
 output=Path(output);output.mkdir(mode=0o700);evidence=output/'identity-evidence';evidence.mkdir(mode=0o700)
 acqentry,acq,prior_mod,identity,integration,observation=[modules[k] for k in ('acquisition_entry','acquisition','prior','identity','integration','observation')]
 code,wf_pin,acquisition_out,needs=acqentry.prepare(plan['acquisition_code_directory'],plan['workflow_file'],output/'acquisition',env)
 result=acq.acquire(env,needs,wf_pin,acq.HTTPSGet());acqentry.persist(acquisition_out,result)
 selection=result['selection'];collection=strict(result['inputs']['collection_receipt.json'])
 repo=output/'public-repository';repo.mkdir(mode=0o700);prior_mod.load_git().git(repo,'init')
 prior,unused_blobs,management=prior_mod.fetch_current(repo)
 del unused_blobs
 prior_ref=emit(evidence/'PRIOR-OBSERVATION.json',prior);emit(evidence/'MANAGEMENT.json',management)
 identities=identity.acquire(env,needs,prior['previous_price_source_commit'],acq.HTTPSGet())
 for name,raw in identities['files'].items():
  need(type(name) is str and Path(name).name==name and name not in ('','.','..') and type(raw) is bytes,'flat byte identity member')
  with (evidence/name).open('xb') as f:f.write(raw)
 selection_ref=reference(acquisition_out/'SELECTION.json')
 template=ref(plan['source_plan_template'])
 source,policy=source_plan(template,selection_ref,selection,collection,prior,identities,evidence,observation,output/'generated/prior-candidate',prior_ref)
 source_ref=emit(evidence/'SOURCE-PLAN-TEMPLATE-FILLED.json',source);emit(evidence/'DATE-POLICY.json',policy)
 integration_plan={'schema':'boopa-local-integration-plan-r1','acquisition':{'directory':str(acquisition_out),'complete':reference(acquisition_out/'COMPLETE.json')},'selection_validator':{'path':str(Path(plan['acquisition_code_directory'])/'verify_saved_handoff.py'),'sha256':SELECTOR_PIN},'source_plan':source_ref,'code':plan['integration_code_groups'],'repository_path':str(repo),'expected_public_parent_commit':prior['expected_public_parent_commit'],'prior_mode':'inspect-local','approval_directory':plan['approval_directory']}
 ip=emit(evidence/'INTEGRATION-PLAN.json',integration_plan)
 request=integration.run(ip['path'],ip['sha256'],output/'generated')
 need(request['publication_performed'] is False,'publication must remain off')
 receipt={'schema':'boopa-actions-generation-entry-result-r1','execution_kind':execution_kind,'acquisition_complete':reference(acquisition_out/'COMPLETE.json'),'prior_observation':prior_ref,'latest_observation':reference(evidence/identities['latest_observation']['path']),'integration_plan':ip,'publish_request':reference(output/'generated/PUBLISH-REQUEST.json'),'publication_performed':False,'publish_token_read':False,'provider_authenticated':False,'source_runner_independent_review':'NOT-ACCEPTED-CONTENT-FLAG','scope':'Concrete read entry call sequence returned; no independent provider authentication, full runtime deployment or release acceptance inferred.'}
 emit(output/'COMPLETE.json',receipt);return receipt

READ_ENV_NAMES=('GITHUB_SERVER_URL','GITHUB_ACTIONS','GITHUB_REPOSITORY','GITHUB_REPOSITORY_ID','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_WORKFLOW_REF','GITHUB_WORKFLOW_SHA','GITHUB_TOKEN','BOOPA_SCRAPE_RESULT','BOOPA_SAVED_COMMIT','BOOPA_ARTIFACT_ID','BOOPA_ARTIFACT_DIGEST')
def capture_named_env(env):return {k:env.get(k) for k in READ_ENV_NAMES}

def run(plan_path,plan_pin,output,env):
 p=ref({'path':str(plan_path),'sha256':plan_pin});need(set(p)=={'schema','acquisition_entry','acquisition_code_directory','workflow_file','identity_code','prior_code','integration_code','integration_code_groups','source_plan_template','approval_directory','prior_scanner_ceiling_policy'} and p['schema']=='boopa-actions-generation-runtime-plan-r1','closed runtime plan')
 need(p['prior_scanner_ceiling_policy']=='verified-provider-observation-after-prior-identity-read','explicit prior date policy required')
 # Verify all configured groups before importing entries or making a request.
 roots={k:freeze(p[k]) for k in ('identity_code','prior_code','integration_code')}
 need(set(p['integration_code_groups'])=={'prior','source','pipeline','publisher'},'integration groups')
 group_roots={k:freeze(v) for k,v in p['integration_code_groups'].items()}
 need(p['prior_code']==p['integration_code_groups']['prior'],'single prior reader code')
 ep=Path(p['acquisition_entry']['path']);need(p['acquisition_entry']['sha256']==ACQUISITION_ENTRY_PIN and ep.is_file() and not ep.is_symlink() and sha(ep.read_bytes())==ACQUISITION_ENTRY_PIN,'existing acquisition entry pin')
 ref(p['source_plan_template']);out=Path(output).absolute();need(out.parent.resolve()==out.parent and not out.exists() and not out.is_symlink(),'fresh output directory')
 for root in [*roots.values(),*group_roots.values(),Path(plan_path).resolve().parent,Path(p['approval_directory']).resolve(),Path(p['acquisition_code_directory']).resolve()]:need(root!=out and root not in out.parents and out not in root.parents,'output/input overlap')
 # Select named variables only: never inspect BOOPADB_PUBLISH_TOKEN or other secrets.
 captured=capture_named_env(env)
 entry=load('generation_existing_acquisition_entry',ep)
 code,_,_,_=entry.prepare(p['acquisition_code_directory'],p['workflow_file'],out,captured)
 sys.path.insert(0,str(code))
 acq=load('generation_existing_acquisition',code/'acquire_saved_handoff.py')
 modules={'acquisition_entry':entry,'acquisition':acq,'prior':load('generation_prior',roots['prior_code']/'read_previous_production.py'),'identity':load('generation_identity',roots['identity_code']/'acquire_git_identities.py'),'observation':load('generation_observation',roots['identity_code']/'observation_validation.py'),'integration':load('generation_integration',roots['integration_code']/'run_integration.py')}
 return connect(p,out,captured,modules,execution_kind='runtime-read-entries-returned')
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--plan',required=True);a.add_argument('--plan-sha256',required=True);a.add_argument('--output',required=True);v=a.parse_args();run(v.plan,v.plan_sha256,v.output,os.environ)
 print('Read acquisition and local generation returned. Publication remains off.')
