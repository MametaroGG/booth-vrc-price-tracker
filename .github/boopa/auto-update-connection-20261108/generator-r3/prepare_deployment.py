#!/usr/bin/env python3
"""Offline single-commit deployment plan, not a publisher. No credentials/network."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from build_site import BASELINE, STATICS, load_trusted, sha

PAGES = ('index', 'item', 'sale', 'new', 'free', 'drops', 'updates', 'rising', 'active',
         'bookmarks', 'history', 'ranking', 'privacy', 'terms', 'app')
SELECTOR_SHA256 = 'b41ef07ae3982eb9a75a8b517ee92f9df6472e7a5d94d47ab3ffd2e74c761809'
HERO_SHA256 = '946f4226d75e00017404735bf295100ffd35dfafac78dd6cdea0652a07f85d68'


def prepare(candidate, target_repo, expected_head, output, allow_fixture=False):
    candidate = candidate.resolve()
    if not re.fullmatch(r'[0-9a-f]{40}', expected_head):
        raise ValueError('Explicit full expected HEAD SHA required')
    head = subprocess.check_output(['git', '-C', str(target_repo), 'rev-parse', 'HEAD'], text=True, timeout=60).strip()
    if head != expected_head:
        raise ValueError(f'Local target HEAD changed: {head} != {expected_head}')
    manifest_path = candidate / 'snapshot-manifest.json'
    m = json.loads(manifest_path.read_text())
    if m.get('status') != 'validated-candidate' or m.get('baseline_commit') != BASELINE or m.get('deployed') is not False:
        raise ValueError('Expected validated, undeployed candidate manifest')
    if type(m.get('fixture')) is not bool or (m['fixture'] and not allow_fixture):
        raise ValueError('Fixture candidate requires explicit --allow-fixture (never publishable)')
    if m.get('collection_completion') != 'producer-attested-not-independently-verified' or not m.get('collection_id'):
        raise ValueError('Producer completion provenance missing')
    required = set(STATICS) | {x+'.html' for x in PAGES} | {'lists_full.json','shop_digest.json','cat_cards.json'}
    required |= {f'{prefix}_{i}.json' for prefix in ('search_index','shop_items') for i in range(24)}
    required |= {f'relations_children_{i}.json' for i in range(8)}
    files = m.get('files')
    if not isinstance(files, dict) or required - files.keys():
        raise ValueError('Manifest missing generated pages/data/static assets')
    # Never turn off already-public UI or silently overwrite newer pinned assets.
    # Read only the exact expected commit; no network, checkout, or config change.
    def target_bytes(name):
        return subprocess.check_output(['git','-C',str(target_repo),'show',expected_head+':'+name],timeout=60)
    target_index=target_bytes('index.html').decode('utf-8')
    if re.search(r'const RELATION_UI_LIVE\s*=\s*true;',target_index):
        active=m.get('relations')
        if not isinstance(active,dict) or active.get('activate') is not True:
            raise ValueError('Candidate would withdraw already-public relationship UI')
    if 'src="relationship-search.js' in target_index:
        active=m.get('relation_search')
        if not isinstance(active,dict) or active.get('activate') is not True:
            raise ValueError('Candidate would withdraw already-public complete child search')
    target_names=subprocess.check_output(['git','-C',str(target_repo),'ls-tree','-r','--name-only',expected_head],text=True,timeout=60).splitlines()
    runtime_modules={'relationship-data.js','relationship-ui-draft.js','relationship-search.js','relationship-supplement.js'}
    target_runtime={name for name in target_names if name in runtime_modules or name.startswith(('relation-data/','relation-search/','relation-supplement/'))}
    for name in sorted(target_runtime):
        if files.get(name)!=hashlib.sha256(target_bytes(name)).hexdigest():
            raise ValueError('Candidate would alter already-public relationship runtime/data: '+name)
    # Relationship upgrades are separately reviewed/published first. Daily catalog
    # updates must preserve the exact relationship runtime at expected target HEAD.
    for name in STATICS:
        if hashlib.sha256(target_bytes(name)).hexdigest()!=files[name]:
            raise ValueError('Candidate would replace newer/different pinned static asset: '+name)

    actual=set()
    for p in candidate.rglob('*'):
        if p.is_symlink(): raise ValueError(f'Symlink forbidden: {p}')
        if p.is_file(): actual.add(p.relative_to(candidate).as_posix())
    if actual != set(files) | {'snapshot-manifest.json'}:
        raise ValueError('Candidate inventory differs from manifest')
    # Never execute a candidate-supplied replacement script during validation.
    if sha(candidate/'scripts/embed-hero.cjs') != HERO_SHA256:
        raise ValueError('Untrusted hero checker')
    # Integrity checks precede ALL candidate-code execution (including validator's
    # hero VM). The manifest itself is not an execution trust authority.
    for name, digest in files.items():
        path = (candidate/name).resolve()
        if Path(name).is_absolute() or candidate not in path.parents or path.is_symlink(): raise ValueError('Unsafe manifest path')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid manifest digest')
        if sha(path) != digest: raise ValueError('hash mismatch: '+name)
    selector = re.search(r'// HERO_SELECTOR_START[^\n]*\n([\s\S]*?)// HERO_SELECTOR_END', (candidate/'index.html').read_text())
    if not selector or hashlib.sha256(selector[1].encode()).hexdigest() != SELECTOR_SHA256:
        raise ValueError('Untrusted hero selector; pinned baseline source required')
    relation_files = {name for name in files if name.startswith('relation-data/') or name in ('relationship-ui-draft.js','relationship-data.js')}
    declared=m.get('relations')
    if isinstance(declared,dict) and declared.get('activate'):
        required_relations={'relationship-data.js','relationship-ui-draft.js','relation-data/manifest.json'} | {f'relation-data/items_{i}.json' for i in range(64)} | {f'relation-data/children_{i}.json' for i in range(8)}
        if relation_files!=required_relations:
            raise ValueError('Active relation claim requires complete actual 75-file bundle')
    declared_search=m.get('relation_search')
    if isinstance(declared_search,dict) and declared_search.get('activate'):
        from preserve_relation_search import REQUIRED as REQUIRED_SEARCH
        if {name for name in files if name.startswith('relation-search/') or name=='relationship-search.js'}!=REQUIRED_SEARCH:
            raise ValueError('Active complete-search claim requires complete actual 10-file bundle')
    if relation_files:
        approval = m.get('relations')
        if not isinstance(approval,dict) or approval.get('status')!='approved-bundle' or set(approval.get('files',{}))!=relation_files:
            raise ValueError('Relation data requires complete approved-bundle provenance')
        if any(files[name]!=approval['files'][name] for name in relation_files):
            raise ValueError('Relation approval hashes differ from snapshot hashes')
        if approval.get('activate'):
            for page in ('index.html','item.html'):
                html=(candidate/page).read_text()
                for name in ('relationship-data.js','relationship-ui-draft.js'):
                    expected=name+'?v='+approval['files'].get(name,'')[:16]
                    imports=re.findall(r'<script src="(' + re.escape(name) + r'(?:\?[^"]*)?)"></script>',html)
                    if imports!=[expected] or html.count('const RELATION_UI_LIVE = true;')!=1:
                        raise ValueError('Active relation UI import/gate differs from approved module: '+page)

        for name in relation_files:
            if name.endswith('.json'):
                data=json.loads((candidate/name).read_text())
                if data.get('schema')!='boopadb-relations-v1' or data.get('version')!=approval.get('version'):
                    raise ValueError('Mixed relation bundle versions')
    search_files={name for name in files if name.startswith('relation-search/') or name=='relationship-search.js'}
    if search_files:
        search=m.get('relation_search')
        if not isinstance(search,dict) or set(search.get('files',{}))!=search_files or any(files[name]!=search['files'][name] for name in search_files):
            raise ValueError('Complete-child-search approval inventory differs from snapshot')
        from preserve_relation_search import validate as validate_complete_search
        validate_complete_search(candidate,search,m.get('relations'))
        expected='relationship-search.js?v='+search['files']['relationship-search.js'][:16]
        for page in ('index.html','item.html'):
            imports=re.findall(r'<script src="(relationship-search\.js(?:\?[^"]*)?)"></script>',(candidate/page).read_text())
            if imports!=[expected]:raise ValueError('Complete-search import differs from approved module: '+page)
    elif any('src="relationship-search.js' in (candidate/page).read_text() for page in ('index.html','item.html')):
        raise ValueError('Complete-search import exists without approved bundle')
    from preserve_relation_supplement import valid_inventory as valid_supplement_inventory, validate as validate_supplement, check_import as check_supplement_import
    supplemental={name for name in files if name.startswith('relation-supplement/') or name=='relationship-supplement.js'}
    declared_supplement=m.get('relation_supplement')
    if supplemental or isinstance(declared_supplement,dict) and declared_supplement.get('activate'):
        if not isinstance(declared_supplement,dict) or not valid_supplement_inventory(declared_supplement.get('files')) or supplemental!=set(declared_supplement['files']) or any(files[name]!=declared_supplement['files'][name] for name in supplemental):
            raise ValueError('Supplement requires complete approved actual inventory')
        validate_supplement(candidate,declared_supplement,m.get('relations'))
        for page in ('index.html','item.html'):check_supplement_import((candidate/page).read_text(),declared_supplement)
    elif any('src="relationship-supplement.js' in (candidate/page).read_text() for page in ('index.html','item.html')):
        raise ValueError('Supplement import exists without approved bundle')
    load_trusted('validate_search_core').validate(candidate,m,required=True)
    result = load_trusted('validate_snapshot').validate(candidate, m['validation']['max_date'], manifest_path)
    if not result['ok']: raise ValueError('Snapshot validation failed: '+json.dumps(result))
    for i in range(8):
        if json.loads((candidate/f'relations_children_{i}.json').read_text()) != {}:
            raise ValueError('Relations must remain withdrawn pending explicit QA approval')
    # Every manifest asset, including optional compact output, belongs to ONE commit.
    hashes = dict(files)
    hashes['snapshot-manifest.json'] = sha(manifest_path)
    plan = {'schema':1, 'status':'dry-run-plan', 'publishable':False, 'published':False,
            'owner':'MametaroGG','repository':'boopadb','branch':'main',
            'expected_parent_commit':expected_head, 'observed_local_head':head,
            'remote_head_verified':False, 'single_commit_required':True,
            'candidate_manifest_sha256':hashes['snapshot-manifest.json'],
            'collection_id':m['collection_id'],'fixture':m['fixture'],
            'files':hashes, 'delete_paths':[],
            'publication_requirements':['Explicit authorization; this tool never publishes',
              'Complete applicable full-dataset and browser QA',
              'Independently establish producer completion evidence',
              'Verify remote main equals expected_parent_commit immediately before publication',
              'Use one atomic commit/tree update for ALL files, including lists, HTML and manifest',
              'Use compare-and-swap/non-force branch update; abort on changed HEAD or any failed step',
              'Verify resulting remote commit and published manifest; no per-file retries/partial commits']}
    output = Path(output)
    if candidate == output.resolve() or candidate in output.resolve().parents:
        raise ValueError('Plan must be outside candidate')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as f: json.dump(plan,f,indent=2);f.write('\n')
    return plan


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--target-repo',type=Path,required=True,help='Local checkout only; does not fetch')
    p.add_argument('--expected-head',required=True)
    p.add_argument('--output-plan',type=Path,required=True)
    p.add_argument('--allow-fixture',action='store_true')
    a=p.parse_args()
    plan=prepare(a.candidate,a.target_repo,a.expected_head,a.output_plan,a.allow_fixture)
    print(json.dumps({'status':plan['status'],'files':len(plan['files']),'published':False,'plan':str(a.output_plan)}))


if __name__=='__main__': main()
