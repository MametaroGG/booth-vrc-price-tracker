"""Fixed saved input recovery plan; no collection or secret operations."""
import hashlib,importlib.util,json,pathlib
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parent
G=ROOT/'auto-update-connection-20261108'
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def ref(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def group(p):return {'directory':str(p),'freeze':ref(p/'FREEZE.json')}
def make(workflow,out,env):
 out=pathlib.Path(out).absolute()
 if out.resolve()!=out or out.exists():raise ValueError('New recovery plan directory required')
 out.mkdir(mode=0o700)
 original=load('recovery_original_plan',ROOT/'make_runtime_plan.py')
 pr=original.make(workflow,out/'base');p=json.loads(pathlib.Path(pr['path']).read_bytes())
 entry=load('recovery_entry_plan',HERE/'replay_entry/run_replay_entry.py')
 recovery=entry.recovery_from_env(env)
 replay=load('recovery_plan_validator',HERE/'replay_adapter/replay_saved.py')
 producer=dict(replay.EXPECTED);replay.validate_plan(producer);replay.validate_recovery(recovery,producer)
 p={k:p[k] for k in ('identity_code','prior_code','integration_code','integration_code_groups','acquisition_code_directory','source_plan_template','approval_directory')}
 p.update(schema='boopa-replay-generation-plan-r2',runtime_code=group(G/'runtime-entry-r1'),replay_code=group(HERE/'replay_adapter'),producer=producer,recovery=recovery)
 target=out/'REPLAY-PLAN.json';target.write_text(json.dumps(p,sort_keys=True,indent=2)+'\n');return ref(target)
