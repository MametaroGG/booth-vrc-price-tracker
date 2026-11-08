#!/usr/bin/env python3
"""Separately authorized atomic Git publisher. DEFAULT DRY RUN. Not cron-wired.
Uses existing repository Git remote/credential configuration without modifying it.
Never invoked during this handover; requires verified real QA and authorization.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from prepare_deployment import prepare
from build_site import sha


def run_git(repo, *args, env=None, input=None):
    return subprocess.check_output(['git','-C',str(repo),*args],env=env,input=input,timeout=480).decode().strip()


def publish(candidate, repo, plan_path, authorization_path, execute=False, journal_path=None):
    plan_path=Path(plan_path);plan=json.loads(plan_path.read_text())
    if not execute:
        return {'status':'dry-run','published':False,'expected_parent_commit':plan.get('expected_parent_commit')}
    authorization=json.loads(Path(authorization_path).read_text())
    required={'action':'publish-single-snapshot','repository':'MametaroGG/boopadb','branch':'main',
              'plan_sha256':sha(plan_path),'expected_parent_commit':plan.get('expected_parent_commit'),
              'full_dataset_and_browser_qa_passed':True,'producer_completion_verified':True}
    if any(authorization.get(k)!=v for k,v in required.items()) or not authorization.get('authorized_by'):
        raise ValueError('Exact snapshot publication authorization and completed QA evidence required')
    if plan.get('fixture') or plan.get('status')!='dry-run-plan' or not plan.get('single_commit_required'):
        raise ValueError('Only real single-snapshot plans may be published')
    candidate=Path(candidate).resolve();repo=Path(repo).resolve()
    snapshot = json.loads((candidate/'snapshot-manifest.json').read_text())
    relations = snapshot.get('relations')
    if isinstance(relations,dict) and relations.get('activate') and relations.get('scope') != 'publication-approved':
        raise ValueError('Relation activation is approved only for local testing, not publication')
    search = snapshot.get('relation_search')
    if isinstance(search,dict) and search.get('activate') and search.get('scope') != 'publication-approved':
        raise ValueError('Complete child-search is approved only for local testing, not publication')
    supplement=snapshot.get('relation_supplement')
    if isinstance(supplement,dict) and supplement.get('activate') and supplement.get('scope')!='publication-approved':
        raise ValueError('Supplement is approved only for local testing, not publication')
    if sha(candidate/'snapshot-manifest.json')!=plan.get('candidate_manifest_sha256'):
        raise ValueError('Candidate manifest changed since plan')
    from publication_journal import save, ALLOWED_ORIGINS
    journal_path = Path(journal_path) if journal_path else plan_path.with_name(plan_path.name+'.publication.json')
    receipt = {'schema':1,'status':'planned','plan_sha256':sha(plan_path),
               'expected_parent_commit':plan['expected_parent_commit'],'collection_id':plan['collection_id'],
               'repository':'MametaroGG/boopadb','branch':'main','files':len(plan['files'])}
    # Existing receipt is never overwritten: reconcile it before any new attempt.
    save(journal_path,receipt,create=True)
    with tempfile.TemporaryDirectory(prefix='boopadb-publish-') as work:
        work=Path(work)
        # Re-run inventory/hash/selector gate before any Git write or network call.
        checked=prepare(candidate,repo,plan['expected_parent_commit'],work/'rechecked-plan.json')
        if checked['files']!=plan['files']: raise ValueError('Candidate inventory changed since plan')
        remote=run_git(repo,'remote','get-url','origin')
        if remote not in ALLOWED_ORIGINS:
            raise ValueError('Existing origin does not identify the authorized repository')
        expected=plan['expected_parent_commit']
        remote_head=run_git(repo,'ls-remote','--exit-code','origin','refs/heads/main').split()[0]
        if remote_head!=expected: raise ValueError('Remote HEAD changed; no publication')
        env=dict(os.environ,GIT_INDEX_FILE=str(work/'index'))
        run_git(repo,'read-tree',expected,env=env)
        for number,(name,digest) in enumerate(sorted(plan['files'].items()),1):
            path=candidate/name
            data=path.read_bytes()
            import hashlib
            if hashlib.sha256(data).hexdigest()!=digest: raise ValueError('Candidate changed during commit preparation')
            blob=run_git(repo,'hash-object','-w','--stdin',input=data)
            # Paths were manifest-validated; NUL protocol handles spaces safely.
            entry=('100644 '+blob+'\t'+name+'\0').encode()
            run_git(repo,'update-index','-z','--index-info',env=env,input=entry)
            receipt.update(status='blobs-prepared',prepared_files=number,last_path=name,last_blob=blob);save(journal_path,receipt)
        tree=run_git(repo,'write-tree',env=env)
        commit=run_git(repo,'commit-tree',tree,'-p',expected,'-m','Publish validated BoopaDB snapshot '+plan['collection_id'])
        receipt.update(status='commit-prepared',commit=commit,tree=tree);save(journal_path,receipt)
        # All files share one commit with exactly expected as parent. The explicit
        # lease is compare-and-swap, not an unconditional force or history rewrite.
        receipt.update(status='push-started');save(journal_path,receipt)
        try:
            run_git(repo,'push','--porcelain','--force-with-lease=refs/heads/main:'+expected,
                    'origin',commit+':refs/heads/main')
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            receipt.update(status='push-uncertain',error=str(exc));save(journal_path,receipt)
            raise RuntimeError(f'Push did not return confirmed success for {commit}; inspect remote HEAD before any retry') from exc
        try:
            actual=run_git(repo,'ls-remote','--exit-code','origin','refs/heads/main').split()[0]
        except Exception as exc:
            receipt.update(status='verification-uncertain',error=str(exc));save(journal_path,receipt);raise
        if actual!=commit:
            receipt.update(status='remote-conflict',observed_remote_head=actual);save(journal_path,receipt)
            raise RuntimeError('Publication result uncertain: remote HEAD differs; inspect before retrying')
        receipt.update(status='remote-commit-verified',observed_remote_head=actual);save(journal_path,receipt)
        return {'status':'published','published':True,'commit':commit,'parent':expected,
                'snapshot_manifest_sha256':plan['candidate_manifest_sha256'],
                'next_run_requires_local_checkout_refresh':True, 'published_http_manifest_verified':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',type=Path,required=True);p.add_argument('--target-repo',type=Path,required=True)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--authorization-file',type=Path)
    p.add_argument('--journal',type=Path)
    p.add_argument('--execute',action='store_true',help='Requires separate exact-snapshot publication authorization; never set by refresh/deploy wrappers')
    a=p.parse_args()
    if a.execute and not a.authorization_file:p.error('--execute requires --authorization-file')
    print(json.dumps(publish(a.candidate,a.target_repo,a.plan,a.authorization_file,a.execute,a.journal),indent=2))
