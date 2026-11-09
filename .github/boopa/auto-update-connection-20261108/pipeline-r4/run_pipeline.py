"""Local success-input pipeline only. No collector, upload, network or deployment."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;GEN=HERE.parent/'generator-r3'
ASSETS=HERE.parents[1]/'rebuild-saved6126-20261108/current-generator-r1'
DEPENDENCIES=HERE.parents[1]/'rebuild-saved6126-20261108/recovered/generator/minimal-publication-integration-20261107/GENERATOR-v2-FREEZE.json'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def need(v,m):
    if not v:raise ValueError(m)
def pinned(path,pin):
    raw=Path(path).read_bytes();need(sha(raw)==pin,'Input pin mismatch');return raw
def emit(path,obj):
    with Path(path).open('x') as f:json.dump(obj,f,sort_keys=True,indent=2);f.write('\n')
def destination(output,inputs):
    output=Path(output).absolute();need(output.resolve()==output and not output.exists() and not output.is_symlink(),'New resolved output required')
    for origin in inputs:
        p=Path(origin).resolve();need(output!=p and output not in p.parents and p not in output.parents,'Output/input overlap')
    return output

def bootstrap_json(raw):
    def pairs(items):
        out={}
        for k,v in items:
            need(k not in out,'Duplicate bootstrap key');out[k]=v
        return out
    def reject_constant(value):raise ValueError('Nonfinite bootstrap value')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=reject_constant)

def local_member(root,name):
    need(type(name) is str and name and not Path(name).is_absolute() and '..' not in Path(name).parts,'Invalid freeze member')
    p=root/name;need(p.resolve().is_relative_to(root.resolve()),'Freeze member escapes root');return p

def bootstrap(pipeline_pin,bindings_path,bindings_pin):
    # Only stdlib executes before both caller-pinned code inventories are verified.
    f=bootstrap_json(pinned(HERE/'PIPELINE-FREEZE.json',pipeline_pin))
    required={'run_pipeline.py','derive_presentation_proof.py','apply_runtime_guard_r2.py','verify_candidate_semantics_r2.py','verify_runtime_final_r2.cjs'}
    need(required <= set(f['files']),'Incomplete pipeline freeze')
    for name,h in f['files'].items():pinned(local_member(HERE,name),h)
    b=bootstrap_json(pinned(bindings_path,bindings_pin))
    freeze=bootstrap_json(pinned(GEN/'CONSUMER-FREEZE.json',b['consumer_freeze_sha256']))
    need({'verified_source.py','saved_snapshot_policy.py','visibility_policy.py','build_site.py'} <= set(freeze['files']),'Incomplete consumer freeze')
    for name,entry in freeze['files'].items():pinned(local_member(GEN,name),entry['sha256'])
    dependency=bootstrap_json(pinned(DEPENDENCIES,'246b7ac4c1bbefe566c48775e0158b8eb711b82fce71e9ca6d18c4cd3f847ac0'))['generator_inventory']
    for name,pin in dependency.items():
        if name not in freeze['files'] and name!='scripts/apply_current_price_projection.py':pinned(local_member(ASSETS,name),pin)
    return bindings_pin

def run(handoff_path,handoff_pin,prior,bindings_path,bindings_pin,approval_dir,output,pipeline_pin):
    bootstrap(pipeline_pin,bindings_path,bindings_pin)
    sys.path[:0]=[str(HERE),str(GEN)]
    from verified_source import VerifiedSource,strict_json
    from saved_snapshot_policy import RunBindings,LatestNegativeOverlay
    from visibility_policy import read_retained_exclusions
    from derive_presentation_proof import derive
    import build_site
    from apply_runtime_guard_r2 import run as assemble
    from verify_candidate_semantics_r2 import audit
    b=RunBindings(bindings_path,bindings_pin);h=strict_json(pinned(handoff_path,handoff_pin))
    need(h['run_bindings_sha256']==b.sha256 and Path(h['run_bindings_path']).resolve()==Path(bindings_path).resolve(),'Handoff binding mismatch')
    need(h.get('publication_acceptance') is False,'Unexpected handoff authority')
    source=Path(h['prepared_root']);need('unaccepted' not in str(source),'Source not promoted')
    receipt=strict_json(pinned(h['source_receipt_path'],h['source_receipt_sha256']))
    prior=Path(prior);retained=read_retained_exclusions(prior,b['retained_snapshot_sha256'])
    q=Path(h['quarantine_path']);ov=Path(h['overlay_path'])
    pinned(q,b['quarantine_proof_sha256']);pinned(ov,b['latest_negative_overlay_sha256'])
    approval_dir=Path(approval_dir)
    approvals={'relation.json':'d29ebf9ad8b46f954f8128bf80676813cb937adf9f701a840aaf4337c6e8bcc7','relation-search.json':'b8acdf5b300400aad351e6ef9e103b9b8d56f160a5cf23a47c169cf196222d59','supplement.json':'a93c65b591dd9fb2c01e4621f2d671228f695bb37d31fff83ee0cf6057e0f4cc'}
    for n,p in approvals.items():pinned(approval_dir/n,p)
    output=destination(output,[source,prior,GEN,ASSETS,HERE,approval_dir,Path(handoff_path).parent,Path(bindings_path).parent,Path(h['source_receipt_path']).parent,q.parent,ov.parent]);output.mkdir(mode=0o700)
    overlay=LatestNegativeOverlay(ov,b['latest_negative_overlay_sha256'],retained,run_bindings=b)
    with VerifiedSource(source,h['completion_sha256'],run_bindings=b) as v:
        need(v.saved_snapshot_composition['source_receipt_sha256']==h['source_receipt_sha256'],'Completion/source receipt differs')
        proof,raw,presentation=derive(v,set(retained['ids'])|overlay.ids|overlay.pending_ids)
    with (output/'PRESENTATION.json').open('xb') as stream:stream.write(raw)
    emit(output/'PRESENTATION-READS.json',presentation)
    emit(output/'INPUT-PINS.json',{'handoff_sha256':handoff_pin,'run_bindings_sha256':bindings_pin,'pipeline_freeze_sha256':pipeline_pin,'prior_snapshot_sha256':b['retained_snapshot_sha256'],'completion_sha256':h['completion_sha256'],'source_receipt_sha256':h['source_receipt_sha256'],'presentation_file_sha256':presentation['file_sha256'],'presentation_canonical_sha256':presentation['canonical_sha256'],'external_write':False})
    result=build_site.build(source,source/'completion.json',ASSETS/'pinned-static',output/'base-candidate',verified_completion_sha256=h['completion_sha256'],retained_exclusions_candidate=prior,retained_exclusions_snapshot_sha256=b['retained_snapshot_sha256'],run_bindings_path=bindings_path,run_bindings_sha256=bindings_pin,quarantine_proof=q,latest_negative_proof=ov,relations_bundle=ASSETS/'relation-bundle',relations_approval=approval_dir/'relation.json',relation_search_bundle=ASSETS/'relation-search-bundle',relation_search_approval=approval_dir/'relation-search.json',supplement_bundle=ASSETS/'relation-supplement-bundle',supplement_approval=approval_dir/'supplement.json',presentation_proof=proof,presentation_sha256=presentation['canonical_sha256'])
    emit(output/'BASE-RESULT.json',result);base_pin=sha((output/'base-candidate/snapshot-manifest.json').read_bytes())
    assembled=assemble(output/'base-candidate',base_pin,prior,b['retained_snapshot_sha256'],output/'final-candidate');emit(output/'ASSEMBLY.json',assembled)
    semantic=audit(source,h['completion_sha256'],output/'final-candidate',prior,b['retained_snapshot_sha256'],True,q,ov,bindings_path,bindings_pin,h['source_receipt_path']);emit(output/'SEMANTIC.json',semantic)
    subprocess.run(['node',str(HERE/'verify_runtime_final_r2.cjs'),str(output/'final-candidate'),assembled['candidate_snapshot_sha256'],str(output/'RUNTIME.json')],check=True,timeout=180)
    emit(output/'LOCAL-RESULT.json',{'snapshot_sha256':assembled['candidate_snapshot_sha256'],'semantic_sha256':sha((output/'SEMANTIC.json').read_bytes()),'runtime_sha256':sha((output/'RUNTIME.json').read_bytes()),'external_write':False,'independent_acceptance':False})
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ['handoff','handoff-pin','prior','bindings','bindings-pin','approval-dir','output','pipeline-pin']:p.add_argument('--'+n,required=True)
    a=p.parse_args();run(a.handoff,a.handoff_pin,a.prior,a.bindings,a.bindings_pin,a.approval_dir,a.output,a.pipeline_pin)
