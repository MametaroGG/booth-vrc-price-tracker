"""Local explicit adapter wiring, not authenticated runner/release acceptance.
Entry itself must be verified before execution. No token read or publication call.
"""
import argparse,hashlib,importlib.util,json,sys
from pathlib import Path

def need(v,m):
 if not v:raise ValueError(m)
def sha(b):return hashlib.sha256(b).hexdigest()
def strict(b):
 def pairs(rows):
  d={}
  for k,v in rows:need(k not in d,'Duplicate key');d[k]=v
  return d
 return json.loads(b,object_pairs_hook=pairs)
def ref(v):
 need(type(v) is dict and set(v)=={'path','sha256'},'Closed file ref required');p=Path(v['path']);need(p.is_file() and not p.is_symlink(),'Regular input required');raw=p.read_bytes();need(sha(raw)==v['sha256'],'Input pin differs');return strict(raw)
def reference(p):return {'path':str(p),'sha256':sha(p.read_bytes())}
def emit(p,obj):
 with p.open('x') as f:json.dump(obj,f,sort_keys=True,indent=2);f.write('\n')
 return reference(p)
def freeze(v):
 need(set(v)=={'directory','freeze'},'Closed code reference required');root=Path(v['directory']).resolve(strict=True);f=ref(v['freeze']);need(Path(v['freeze']['path']).parent.resolve()==root,'Freeze directory differs')
 for n,h in f['files'].items():
  rel=Path(n);need(not rel.is_absolute() and '..' not in rel.parts,'Invalid code path');p=root/rel;need(p.resolve().is_relative_to(root) and p.is_file() and not p.is_symlink(),'Code path differs');pin=h['sha256'] if isinstance(h,dict) else h;need(sha(p.read_bytes())==pin,'Code member differs')
 return root

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def acquisition(v,selector):
 need(set(v)=={'directory','complete'},'Closed acquisition ref required');root=Path(v['directory']);c=ref(v['complete']);need(c['schema']=='boopa-runner-acquisition-output-r1','Unsupported acquisition completion')
 expected={'context.json','artifact.json','receipt.zip','collection_receipt.json','saved-commit.json','workflow.yml','SELECTION.json','ACQUISITION.json'};need(set(c['files'])==expected,'Acquisition closure differs');raw={}
 for n,e in c['files'].items():
  p=root/n;need(p.is_file() and not p.is_symlink(),'Acquisition file invalid');raw[n]=p.read_bytes();need(len(raw[n])==e['bytes'] and sha(raw[n])==e['sha256'],'Acquisition member differs')
 selected=selector.verify(raw['context.json'],raw['artifact.json'],raw['receipt.zip'],raw['collection_receipt.json'],raw['saved-commit.json'],raw['workflow.yml'],sha(raw['workflow.yml']))
 need(selected==strict(raw['SELECTION.json']),'Selection differs from actual acquisition inputs')
 need(strict(raw['ACQUISITION.json'])['schema']=='boopa-actions-read-acquisition-r1','Acquisition schema differs')
 return selected,reference(root/'SELECTION.json')

def connect(plan,out,prior_module,source_module,pipeline_module,selection,selection_ref):
 """Actual three entry calls. Test doubles prove wiring only, not acceptance."""
 template=ref(plan['source_plan']);need(template['selection']==selection_ref,'Source plan selection differs')
 need(template['source']['commit']==selection['saved_commit'] and template['source']['root_tree']==selection['saved_root'],'Selected source identity differs')
 need(plan['prior_mode']=='inspect-local','Fresh provider prior acquisition is explicit separate input, not silently fetched')
 observed,blobs,management=prior_module.inspect_local(plan['repository_path'],plan['expected_public_parent_commit'])
 prior,management=prior_module.materialize(observed,blobs,management,out/'prior-candidate')
 parent_ref=emit(out/'PRIOR-HANDOFF.json',prior);emit(out/'MANAGEMENT.json',management)
 template['public_parent']=parent_ref;template['prior']['candidate_path']=prior['prior_candidate_path'];template['prior']['snapshot_sha256']=prior['prior_snapshot_sha256']
 source_plan=emit(out/'SOURCE-PLAN.json',template);source_result=source_module.run(source_plan['path'],source_plan['sha256'],out/'source')
 need(source_result['publication_acceptance'] is False,'Unexpected source acceptance')
 handoff_ref={'path':source_result['prepared_handoff_path'],'sha256':source_result['prepared_handoff_sha256']};h=ref(handoff_ref)
 need(h['run_bindings_sha256']==source_result['run_bindings_sha256'],'Runner binding differs')
 pipeline_module.run(handoff_ref['path'],handoff_ref['sha256'],prior['prior_candidate_path'],h['run_bindings_path'],h['run_bindings_sha256'],plan['approval_directory'],out/'pipeline',plan['code']['pipeline']['freeze']['sha256'])
 result_path=out/'pipeline/LOCAL-RESULT.json';local=ref(reference(result_path));candidate=out/'pipeline/final-candidate';need(sha((candidate/'snapshot-manifest.json').read_bytes())==local['snapshot_sha256'],'Pipeline final snapshot differs')
 latest=template['latest'];negative_root=Path(latest['materialized']['path']) if 'materialized' in latest else out/'source/latest-materialized'
 negative_path=negative_root/'METADATA-NEGATIVE-SCAN.json';need(sha(negative_path.read_bytes())==source_result['latest_metadata_scan_receipt_sha256'],'Latest scan output differs')
 source_desc=template['source'];archive_root=Path(source_desc['materialized']['path']) if 'materialized' in source_desc else out/'source/source-materialized'
 archive_receipt=archive_root/'SOURCE-ARCHIVE-RECEIPT.json';need(sha(archive_receipt.read_bytes())==source_result['source_archive_receipt_sha256'],'Source archive receipt output differs')
 names=['INPUT-PINS.json','ASSEMBLY.json','SEMANTIC.json','RUNTIME.json','LOCAL-RESULT.json'];pins={n:sha((out/'pipeline'/n).read_bytes()) for n in names}
 # No API evidence fabricated, token consulted or publish called. Next runner must
 # acquire a genuine fresh guard and explicitly inject its publishing credential.
 request={'schema':'boopa-local-integration-publish-request-r1','handoff_path':handoff_ref['path'],'source_archive_receipt_path':str(archive_receipt),'candidate':str(candidate),'candidate_pin':local['snapshot_sha256'],'prior':prior['prior_candidate_path'],'prior_pin':prior['prior_snapshot_sha256'],'expected':prior['expected_public_parent_commit'],'binding_path':h['run_bindings_path'],'binding_pin':h['run_bindings_sha256'],'run_dir':str(out/'pipeline'),'run_pins':pins,'pipeline_dir':plan['code']['pipeline']['directory'],'pipeline_pin':plan['code']['pipeline']['freeze']['sha256'],'publisher_freeze':plan['code']['publisher']['freeze'],'source_runner_handoff_sha256':sha((out/'source/RUNNER-HANDOFF.json').read_bytes()),'negative_scan_path':str(negative_path),'negative_scan_pin':source_result['latest_metadata_scan_receipt_sha256'],'fresh_authenticated_guard':'UNBOUND','explicit_publish_token':'NOT-READ','publication_performed':False,'provider_authenticated':False,'source_runner_independent_review':'NOT-ACCEPTED-CONTENT-FLAG','current_marker_after_price_cutoff_policy':'existing-fail-closed-unchanged'}
 emit(out/'PUBLISH-REQUEST.json',request);return request

def run(plan_path,plan_pin,output):
 plan=ref({'path':str(plan_path),'sha256':plan_pin});need(set(plan)=={'schema','acquisition','selection_validator','source_plan','code','repository_path','expected_public_parent_commit','prior_mode','approval_directory'},'Closed integration plan required');need(plan['schema']=='boopa-local-integration-plan-r1','Unsupported integration plan')
 need(set(plan['code'])=={'prior','source','pipeline','publisher'},'Closed code group required');roots={k:freeze(v) for k,v in plan['code'].items()}
 # Verify selector before import; all frozen groups verified before any entry call.
 refcode=plan['selection_validator'];p=Path(refcode['path']);need(p.is_file() and not p.is_symlink() and sha(p.read_bytes())==refcode['sha256'],'Selection code pin differs')
 out=Path(output).absolute();need(out.resolve()==out and not out.exists(),'New resolved output required')
 for root in [*roots.values(),Path(plan_path).resolve().parent,Path(plan['acquisition']['directory']).resolve(),Path(plan['repository_path']).resolve(),Path(plan['approval_directory']).resolve()]:need(root!=out and root not in out.parents and out not in root.parents,'Input/output overlap')
 selector=load('integration_selector',p);selection,sref=acquisition(plan['acquisition'],selector)
 prior=load('integration_prior',roots['prior']/'read_previous_production.py');source=load('integration_source',roots['source']/'run_source.py');pipeline=load('integration_pipeline',roots['pipeline']/'run_pipeline.py')
 out.mkdir(mode=0o700)
 return connect(plan,out,prior,source,pipeline,selection,sref)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--plan',required=True);a.add_argument('--plan-sha256',required=True);a.add_argument('--output',required=True);v=a.parse_args();run(v.plan,v.plan_sha256,v.output)
