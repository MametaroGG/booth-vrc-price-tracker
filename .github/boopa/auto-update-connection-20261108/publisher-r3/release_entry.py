"""Callable fixed-repository entry. Explicit token injection; never invoked by tests.
Pinned evidence proves consistency, not provider authentication by itself.
"""
import base64,datetime,hashlib,json,os,subprocess,time
from pathlib import Path
from git_publication import need,digest,json_strict,oid,snapshot,prepare,git,validate_commit,safe_env,git_command,inspect_repo
REPO='https://github.com/MametaroGG/boopadb.git'
TRACKER='https://api.github.com/repos/MametaroGG/booth-vrc-price-tracker'
def pinned(path,pin):
    raw=Path(path).read_bytes();need(digest(raw)==pin,'Evidence pin differs');return json_strict(raw)
def utc(s):return datetime.datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
def fresh_guard(path,pin,candidate,binding,not_before):
    f=pinned(path,pin);need(f['schema']=='boopa-prerefswitch-fresh-negative-tree-binding-r1' and f['status']=='same-metadata-tree-as-verified-negative-cutoff','Unsupported freshness receipt')
    need(f['candidate_snapshot_observed_sha256']==candidate and f['metadata_tree_equal'] is True and f['stored_negative_classification_equal_by_exact_tree_identity'] is True,'Negative guard mismatch')
    cur=f['current'];cut=f['negative_policy_cutoff'];need(cur['main_stable_across_two_reads'] is True and cur['metadata_tree']==cut['metadata_tree']==binding['latest_negative_metadata_tree'],'Negative metadata differs')
    need(cut['commit']==binding['latest_negative_source_commit'],'Negative cutoff differs')
    need(utc(f['observed_from_utc'])>=not_before and utc(f['observed_through_utc'])>=utc(f['observed_from_utc']) and utc(f['observed_through_utc'])<=time.time()+5,'Fresh observation required')
    e=f['provider_evidence'];name=e['file'];need(Path(name).name==name,'Evidence path escapes')
    raw=(Path(path).parent/name).read_bytes();need(len(raw)==e['bytes'] and digest(raw)==e['sha256'],'Provider body missing or changed');body=json_strict(raw)
    expected={'transfer_fresh_before':TRACKER+'/git/ref/heads/main','transfer_fresh_after':TRACKER+'/git/ref/heads/main','transfer_fresh_commit':TRACKER+'/git/commits/'+oid(cur['head']),'transfer_fresh_root':TRACKER+'/git/trees/'+oid(cur['root'])}
    responses={}
    for key,url in expected.items():
        r=body['responses'][key];p=e['responses'][key];rb=r['response_raw'].encode('utf-8');need(r['url']==p['url']==url and digest(rb)==p['response_sha256'] and len(rb)==p['response_utf8_bytes'],'Provider response mismatch');responses[key]=json_strict(rb)
    for key in ('transfer_fresh_before','transfer_fresh_after'):
        need(responses[key]['ref']=='refs/heads/main' and responses[key]['object']['type']=='commit' and responses[key]['object']['sha']==cur['head'],'Observed head mismatch')
    c=responses['transfer_fresh_commit'];need(c['sha']==cur['head'] and c['tree']['sha']==cur['root'],'Commit/root mismatch')
    tree=responses['transfer_fresh_root'];need(tree['sha']==cur['root'] and tree['truncated'] is False,'Incomplete root');records=[];seen=set();meta=None
    for x in tree['tree']:
        n=x['path'];need('/' not in n and n not in seen,'Invalid direct tree');seen.add(n);mode=x['mode'];typ=x['type'];need((typ,mode) in {('tree','040000'),('blob','100644'),('blob','100755')},'Unsupported Git tree')
        records.append((n.encode()+(b'/' if typ=='tree' else b''),(b'40000' if typ=='tree' else mode.encode())+b' '+n.encode()+b'\0'+bytes.fromhex(oid(x['sha']))))
        if n=='meta':need(typ=='tree','Invalid metadata tree');meta=x['sha']
    raw=b''.join(b for _,b in sorted(records));actual=hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest();need(actual==cur['root'] and meta==cur['metadata_tree'],'Git root proof differs')
    return f

RUN_FIELDS=['authority', 'charts_selector_sha256', 'collection_completion_verified', 'consumer_freeze_sha256', 'expected_public_parent_commit', 'latest_negative_impact_sha256', 'latest_negative_metadata_tree', 'latest_negative_overlay_sha256', 'latest_negative_source_commit', 'metadata_source_commit', 'price_source_commit', 'price_source_is_latest', 'prior_backend_data_tree', 'prior_backend_ids_sha256', 'prior_backend_receipt_kind', 'prior_backend_receipt_sha256', 'prior_backend_root_tree', 'prior_backend_source_commit', 'publication_repository', 'quarantine_diagnostic_sha256', 'quarantine_proof_sha256', 'retained_ids_sha256', 'retained_lists_sha256', 'retained_snapshot_sha256', 'schema', 'selection_receipt_sha256', 'source_archive_receipt_sha256', 'source_archive_sha256', 'source_metadata_tree', 'source_repository', 'source_root_tree', 'varutil_sha256', 'whole_catalog_complete']
RUN_OIDS=('prior_backend_source_commit', 'prior_backend_root_tree', 'prior_backend_data_tree', 'expected_public_parent_commit', 'price_source_commit', 'metadata_source_commit', 'source_root_tree', 'source_metadata_tree', 'latest_negative_source_commit', 'latest_negative_metadata_tree')
RUN_DIGESTS=('source_archive_sha256', 'prior_backend_receipt_sha256', 'prior_backend_ids_sha256', 'consumer_freeze_sha256', 'charts_selector_sha256', 'varutil_sha256', 'source_archive_receipt_sha256', 'selection_receipt_sha256', 'retained_snapshot_sha256', 'retained_lists_sha256', 'retained_ids_sha256', 'latest_negative_impact_sha256', 'quarantine_proof_sha256', 'quarantine_diagnostic_sha256', 'latest_negative_overlay_sha256')
def validate_binding(b):
    need(type(b) is dict and set(b)==set(RUN_FIELDS) and b['schema']=='boopa-saved-run-bindings-r2','Closed bindings schema differs')
    import re
    need(all(type(b[k]) is str and re.fullmatch('[0-9a-f]{40}',b[k]) for k in RUN_OIDS),'Invalid binding OID')
    need(all(type(b[k]) is str and re.fullmatch('[0-9a-f]{64}',b[k]) for k in RUN_DIGESTS),'Invalid binding digest')
    need(b['source_repository']=='MametaroGG/booth-vrc-price-tracker' and b['publication_repository']=='MametaroGG/boopadb' and b['authority']=='caller-pinned-inputs-not-provider-authentication','Binding authority/repository differs')
    need(b['price_source_commit']==b['metadata_source_commit'] and b['prior_backend_receipt_kind'] in ('boopa-prior-backend-git-inventory-r1','boopa-rebuilt-saved-source-archive-v1'),'Unsupported saved source profile')
    need(all(b[k] is False for k in ('collection_completion_verified','whole_catalog_complete','price_source_is_latest')),'Binding semantic flags differ')

def validate_chain(inputs,comp,assembly,composition,freeze,prior_pin):
    need(inputs['source_receipt_sha256']==comp['source_receipt_sha256'],'Source receipt differs between input and candidate')
    descriptor=composition['descriptor'];need(assembly['schema']=='boopa-saved-snapshot-runtime-assembly-result-r1' and descriptor['schema']=='boopa-saved-snapshot-runtime-assembly-r1','Unsupported assembly schema')
    need(assembly['prior_guard_snapshot_sha256']==descriptor['prior_guard_snapshot_sha256']==prior_pin,'Assembly prior differs')
    need(assembly['source_base_snapshot_sha256']==descriptor['base_snapshot_sha256']==composition['base_candidate_snapshot_sha256'],'Assembly base differs')
    need(descriptor['source_input_manifest_sha256']==inputs['completion_sha256'] and descriptor['operator_sha256']==freeze['files']['apply_runtime_guard_r2.py'],'Assembly input/code differs')
    canonical=json.dumps(descriptor,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    need(digest(canonical)==assembly['composition_id']==composition['composition_id'],'Assembly composition differs')

def validate_release(candidate,candidate_pin,prior_pin,expected,binding_path,binding_pin,run_dir,run_pins,pipeline_dir,pipeline_pin,negative_scan_path,negative_scan_pin):
    """No provider authority inferred. Each receipt and all actual outputs are pinned."""
    b=pinned(binding_path,binding_pin);validate_binding(b);need(b['schema']=='boopa-saved-run-bindings-r2' and b['publication_repository']=='MametaroGG/boopadb' and b['expected_public_parent_commit']==expected and b['retained_snapshot_sha256']==prior_pin,'Run baseline differs')
    freeze=pinned(Path(pipeline_dir)/'PIPELINE-FREEZE.json',pipeline_pin)
    for n,h in freeze['files'].items():
        need(Path(n).name==n,'Invalid pipeline member');need(digest((Path(pipeline_dir)/n).read_bytes())==h,'Pipeline code differs')
    need(set(run_pins)=={'INPUT-PINS.json','ASSEMBLY.json','SEMANTIC.json','RUNTIME.json','LOCAL-RESULT.json'},'Closed output receipt mapping required')
    r={n:pinned(Path(run_dir)/n,h) for n,h in run_pins.items()};inputs=r['INPUT-PINS.json'];need(inputs['pipeline_freeze_sha256']==pipeline_pin and inputs['run_bindings_sha256']==binding_pin and inputs['prior_snapshot_sha256']==prior_pin,'Pipeline input binding differs')
    site=snapshot(candidate,candidate_pin);m=json_strict(site['snapshot-manifest.json']);comp=m['saved_snapshot_composition'];need(comp['run_bindings_sha256']==binding_pin and comp['retained_snapshot_sha256']==prior_pin,'Candidate composition differs')
    sem=r['SEMANTIC.json'];runtime=r['RUNTIME.json'];assembly=r['ASSEMBLY.json'];local=r['LOCAL-RESULT.json']
    need(sem['status']=='passed-declared-semantic-scope' and sem['fixture'] is False and sem['runtime_guard_bound'] is True and sem['script_sha256']==freeze['files']['verify_candidate_semantics_r2.py'],'Semantic proof differs')
    need(runtime['status']=='PASS' and runtime['test_script_sha256']==freeze['files']['verify_runtime_final_r2.cjs'] and runtime['check_count']==len(runtime['checks']) and runtime['check_count']>=76,'Runtime proof differs')
    need(all(v['candidate_snapshot_sha256']==candidate_pin for v in (sem,runtime,assembly)) and local['snapshot_sha256']==candidate_pin,'QA candidate mismatch')
    need(local['semantic_sha256']==run_pins['SEMANTIC.json'] and local['runtime_sha256']==run_pins['RUNTIME.json'],'QA output mapping differs')
    need(sem['completion_sha256']==inputs['completion_sha256'],'Source completion differs')
    validate_chain(inputs,comp,assembly,m['publication_composition'],freeze,prior_pin)
    validate_negative_scan(negative_scan_path,negative_scan_pin,b,json_strict(site['lists_full.json'])['visibility']['hidden_ids'])

    return b

def validate_negative_scan(path,pin,binding,hidden):
    scan=pinned(path,pin)
    need(scan['schema']=='boopa-current-metadata-negative-scan-r1' and scan['status']=='git-bound-complete-metadata-negative-scan-floor-comparison-pending','Unsupported negative scan receipt')
    need(scan['source_commit']==binding['latest_negative_source_commit'] and scan['metadata_tree']==binding['latest_negative_metadata_tree'],'Scan cutoff mismatch')
    entry=scan['outputs']['current-negative-markers.private.json'];raw=(Path(path).parent/'current-negative-markers.private.json').read_bytes()
    need(len(raw)==entry['bytes'] and digest(raw)==entry['sha256'],'Complete marker output missing or changed')
    rows=json_strict(raw);need(type(rows) is list and len(rows)==scan['negative_count'],'Negative marker count differs');ids=set()
    for row in rows:
        ident=row['id'];need(type(ident) is str and ident.isascii() and ident.isdecimal() and ident not in ids and type(row['status']) is int and row['status'] in (404,410),'Invalid negative marker');ids.add(ident)
    need(type(hidden) is list and len(hidden)==len(set(hidden)) and ids<=set(hidden),'Candidate omits current negative exclusions')
    return scan

def authenticated_git(repo,token,*args):
    need(type(token) is str and token and '\n' not in token and '\r' not in token,'Explicit BOOPADB_PUBLISH_TOKEN required')
    env=safe_env();env.update(GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',GIT_CONFIG_VALUE_0='AUTHORIZATION: basic '+base64.b64encode(('x-access-token:'+token).encode()).decode())
    try:return subprocess.check_output(git_command(repo,['-c','protocol.file.allow=never',*args]),env=env,stderr=subprocess.DEVNULL,timeout=180).decode().strip()
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError):raise RuntimeError('Git transport outcome unconfirmed') from None

def publish(*,repo,candidate,candidate_pin,prior,prior_pin,expected,binding_path,binding_pin,run_dir,run_pins,pipeline_dir,pipeline_pin,negative_scan_path,negative_scan_pin,refresh_guard,token,journal):
    """refresh_guard runs an authenticated read-only acquisition supplied by runner.
    It must return (path, SHA) for real provider observations, acquired after start.
    No credential discovery; token is injected explicitly, never recorded.
    """
    inspect_repo(repo)
    start=time.time();b=validate_release(candidate,candidate_pin,prior_pin,expected,binding_path,binding_pin,run_dir,run_pins,pipeline_dir,pipeline_pin,negative_scan_path,negative_scan_pin)
    tree=prepare(repo,expected,prior,prior_pin,candidate,candidate_pin)
    commit=git(repo,'commit-tree',tree,'-p',oid(expected),'-m','Publish verified BoopaDB snapshot '+candidate_pin);validate_commit(repo,commit,expected,tree)
    def head():
        fields=authenticated_git(repo,token,'ls-remote','--exit-code',REPO,'refs/heads/main').split();need(len(fields)==2 and fields[1]=='refs/heads/main','Invalid remote ref');return oid(fields[0])
    need(head()==expected,'Main changed before publication')
    path,pin=refresh_guard();f=fresh_guard(path,pin,candidate_pin,b,start);need(f['negative_policy_cutoff']['complete_metadata_scan_receipt_sha256']==negative_scan_pin,'Complete negative scan pin differs')
    need(time.time()-utc(f['observed_through_utc'])<120,'Fresh guard expired')
    record={'status':'push-pending','repository':'MametaroGG/boopadb','branch':'main','expected_parent':expected,'commit':commit,'tree':tree,'candidate_snapshot_sha256':candidate_pin,'fresh_guard_sha256':pin}
    with Path(journal).open('x') as stream:json.dump(record,stream);stream.flush();os.fsync(stream.fileno())
    try:authenticated_git(repo,token,'push','--porcelain','--force-with-lease=refs/heads/main:'+expected,REPO,commit+':refs/heads/main')
    except RuntimeError:pass
    # One readback only; error propagates as uncertain, never implicit retry.
    actual=head();return {**record,'status':'exact-commit-observed' if actual==commit else 'unchanged' if actual==expected else 'conflict','remote_head':actual,'pages_live_verified':False,'publication_accepted':False}
