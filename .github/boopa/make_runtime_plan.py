"""Emit explicit local code paths/pins; no environment/token/network operations."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent;G=ROOT/'auto-update-connection-20261108'
def ref(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def group(n,f='FREEZE.json'):return {'directory':str(G/n),'freeze':ref(G/n/f)}
def emit(p,obj):
 with p.open('x') as f:json.dump(obj,f,sort_keys=True,indent=2);f.write('\n')
 return ref(p)
def make(workflow,out):
 workflow=Path(workflow).resolve(strict=True);out=Path(out).absolute()
 if out.resolve()!=out or out.exists():raise ValueError('New resolved plan directory required')
 out.mkdir(mode=0o700);helpers=G/'generator-r3'
 template={'schema':'boopa-source-runner-plan-r2','source':{},'latest':{},'selection':{},'prior':{'candidate_path':'UNBOUND-until-verified-prior','snapshot_sha256':'UNBOUND','archive_source':{}},'helpers':{'path':str(helpers),'consumer_freeze_sha256':ref(helpers/'CONSUMER-FREEZE.json')['sha256'],'charts_selector_sha256':ref(helpers/'charts_contract.py')['sha256'],'varutil_sha256':ref(helpers/'varutil.py')['sha256']},'sourceprep':{'path':str(G/'sourceprep-r3'),'freeze_sha256':ref(G/'sourceprep-r3/FREEZE.json')['sha256']},'archive_adapter':ref(G/'source-runner-r1/archive_adapter.py'),'public_parent':{}}
 tp=emit(out/'SOURCE-PLAN-TEMPLATE.json',template)
 plan={'schema':'boopa-actions-generation-runtime-plan-r1','acquisition_entry':ref(G/'workflow-install-r1/run_acquisition.py'),'acquisition_code_directory':str(G),'workflow_file':str(workflow),'identity_code':group('identity-acquisition-r1'),'prior_code':group('prior-reader-r1'),'integration_code':group('integration-r1'),'integration_code_groups':{'prior':group('prior-reader-r1'),'source':group('source-runner-r2','RUNNER-FREEZE.json'),'pipeline':group('pipeline-r4','PIPELINE-FREEZE.json'),'publisher':group('publisher-r4')},'source_plan_template':tp,'approval_directory':str(ROOT/'local-authorized-trial-preparation-20261102/historical-inputs/producer-install/inputs/approvals'),'prior_scanner_ceiling_policy':'verified-provider-observation-after-prior-identity-read'}
 return emit(out/'RUNTIME-PLAN.json',plan)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--workflow',required=True);p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(make(a.workflow,a.output)))
