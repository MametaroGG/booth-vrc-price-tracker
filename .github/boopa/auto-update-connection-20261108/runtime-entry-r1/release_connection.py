"""Local release wiring. No CLI, environment lookup, network or publication on import.
Not installed. Producer tests are not independent source-runner review acceptance.
"""
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

FIELDS = {'schema','handoff_path','source_archive_receipt_path','candidate','candidate_pin','prior','prior_pin','expected','binding_path','binding_pin','run_dir','run_pins','pipeline_dir','pipeline_pin','publisher_freeze','source_runner_handoff_sha256','negative_scan_path','negative_scan_pin','fresh_authenticated_guard','explicit_publish_token','publication_performed','provider_authenticated','source_runner_independent_review','current_marker_after_price_cutoff_policy'}
ARGS = ('candidate','candidate_pin','prior_pin','expected','binding_path','binding_pin','run_dir','run_pins','pipeline_dir','pipeline_pin','negative_scan_path','negative_scan_pin','handoff_path','source_archive_receipt_path')

def need(value, message):
    if not value:
        raise ValueError('release connection: '+message)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def strict(raw):
    def pairs(rows):
        obj={}
        for key,value in rows:
            need(key not in obj,'duplicate JSON key')
            obj[key]=value
        return obj
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))

def pinned(path, pin):
    need(type(pin) is str and re.fullmatch('[0-9a-f]{64}',pin),'exact SHA-256 required')
    p=Path(path)
    need(p.is_absolute() and p.resolve()==p and p.is_file() and not p.is_symlink(),'regular resolved input required')
    raw=p.read_bytes()
    need(digest(raw)==pin,'input changed')
    return strict(raw)

def load_request(path,pin):
    r=pinned(path,pin)
    need(type(r) is dict and set(r)==FIELDS and r['schema']=='boopa-local-integration-publish-request-r1','closed request schema')
    need(r['publication_performed'] is False and r['provider_authenticated'] is False,'input authority changed')
    need(r['explicit_publish_token']=='NOT-READ' and r['fresh_authenticated_guard']=='UNBOUND','request already altered')
    need(r['source_runner_independent_review']=='NOT-ACCEPTED-CONTENT-FLAG','unresolved independent review must remain explicit')
    return r

def load_verified_publisher(code_root,freeze_ref):
    root=Path(code_root)
    need(root.is_absolute() and root.resolve()==root and root.is_dir() and not root.is_symlink(),'resolved publisher directory')
    need(type(freeze_ref) is dict and set(freeze_ref)=={'path','sha256'},'closed freeze reference')
    fpath=Path(freeze_ref['path'])
    need(fpath.parent==root,'publisher freeze directory')
    f=pinned(fpath,freeze_ref['sha256'])
    need(type(f.get('files')) is dict and {'release_entry.py','git_publication.py'}<=set(f['files']),'publisher closure')
    for name,pin in f['files'].items():
        need(Path(name).name==name and name not in ('','.','..'),'flat publisher code')
        p=root/name
        need(p.is_file() and not p.is_symlink() and p.resolve().parent==root,'regular code')
        need(digest(p.read_bytes())==pin,'publisher code changed')
    def load(name,p):
        spec=importlib.util.spec_from_file_location(name,p)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    old=sys.modules.get('git_publication')
    try:
        sys.modules['git_publication']=load('git_publication',root/'git_publication.py')
        return load('boopa_verified_release_entry',root/'release_entry.py')
    finally:
        if old is None:sys.modules.pop('git_publication',None)
        else:sys.modules['git_publication']=old

def validate_request(r,publisher):
    binding=publisher.validate_release(**{key:r[key] for key in ARGS})
    need(binding['source_repository']=='MametaroGG/booth-vrc-price-tracker' and binding['publication_repository']=='MametaroGG/boopadb','fixed repositories')
    need(binding['expected_public_parent_commit']==r['expected'],'expected parent differs')
    return binding

def read_only_preflight(request_path,request_pin,publisher):
    """Use all existing publisher gates, with no token/fresh network/push."""
    r=load_request(request_path,request_pin)
    binding=validate_request(r,publisher)
    return {'schema':'boopa-release-preflight-local-r1','request_sha256':request_pin,'candidate_snapshot_sha256':r['candidate_pin'],'expected_public_parent':r['expected'],'price_source_commit':binding['price_source_commit'],'status':'existing-publisher-validation-returned','fresh_guard_acquired':False,'publish_token_read':False,'publication_performed':False,'independent_review':'NOT-ACCEPTED-CONTENT-FLAG'}

def publish_once(request_path,request_pin,*,publisher,repo,publish_token,refresh_guard):
    """UNDEPLOYED explicit call. No automatic use, credential discovery or retry.
    Caller must first resolve release authorization and outstanding acceptance.
    Fresh callback is invoked by the existing publisher immediately before push.
    """
    r=load_request(request_path,request_pin)
    need(type(publish_token) is str and publish_token and '\n' not in publish_token and '\r' not in publish_token,'explicit publish token required')
    need(callable(refresh_guard),'fresh acquisition callback required')
    validate_request(r,publisher)
    root=Path(request_path).parent
    attempt=root/'RELEASE-ATTEMPT.json';result_path=root/'RELEASE-RESULT.json';journal=root/'PUBLISH-PENDING.json'
    need(not any(p.exists() or p.is_symlink() for p in (attempt,result_path,journal)),'existing attempt; inspect outcome, never implicit retry')
    record={'schema':'boopa-release-attempt-local-r1','request_sha256':request_pin,'candidate_snapshot_sha256':r['candidate_pin'],'expected_public_parent':r['expected'],'independent_review':'NOT-ACCEPTED-CONTENT-FLAG','state':'single-call-started'}
    # Exclusive durable intent is written before entering any publishing code.
    import os
    with attempt.open('x') as f:
        json.dump(record,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    try:
        result=publisher.publish(repo=repo,prior=r['prior'],token=publish_token,refresh_guard=refresh_guard,journal=str(journal),**{key:r[key] for key in ARGS})
    except Exception:
        # Do not serialize exception text; transports may contain credentials.
        with result_path.open('x') as f:json.dump({'schema':'boopa-release-result-local-r1','status':'error-or-outcome-unconfirmed','retry_permitted':False,'pages_live_verified':False,'publication_accepted':False},f)
        raise RuntimeError('Release outcome unconfirmed; inspect journal and remote without repeating write') from None
    need(type(result) is dict and result.get('status') in ('exact-commit-observed','unchanged','conflict'),'publisher result schema')
    # Copy only known nonsecret outcome fields; never include token or arbitrary exceptions.
    allowed=('status','repository','branch','expected_parent','commit','tree','candidate_snapshot_sha256','fresh_guard_sha256','remote_head','pages_live_verified','publication_accepted')
    clean={key:result[key] for key in allowed if key in result}
    clean.update(schema='boopa-release-result-local-r1',retry_permitted=False,independent_review='NOT-ACCEPTED-CONTENT-FLAG')
    with result_path.open('x') as f:json.dump(clean,f,sort_keys=True)
    return clean
