"""Callable fixed-repository entry. Explicit token injection; never invoked by tests.
Pinned evidence proves consistency, not provider authentication by itself.
"""
import base64,datetime,hashlib,json,os,re,subprocess,time
from pathlib import Path
from git_publication import need,digest,json_strict,oid,snapshot,prepare,git,validate_commit,safe_env,git_command,inspect_repo,read_regular,safe_name
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

def validate_release(candidate,candidate_pin,prior_pin,expected,binding_path,binding_pin,run_dir,run_pins,pipeline_dir,pipeline_pin,negative_scan_path,negative_scan_pin,*,handoff_path,source_archive_receipt_path):
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
    population=validate_saved_population(handoff_path,source_archive_receipt_path,inputs,comp,b,binding_pin)
    public=catalog_ids(site);visibility=json_strict(site['lists_full.json'])['visibility'];hidden=visibility['hidden_ids']
    expected_visibility={'schema','hidden_ids'}|({'pending_metadata_ids'} if population['pending_mode'] else set())
    need(type(visibility) is dict and set(visibility)==expected_visibility and type(visibility['schema']) is int and visibility['schema']==1,'Candidate pending visibility schema differs')
    need(canonical_ids(visibility.get('pending_metadata_ids',[]),'candidate pending')==population['pending'],'Candidate pending partition differs')
    validate_negative_scan(negative_scan_path,negative_scan_pin,b,hidden,population['backend'],public)
    need(canonical_ids(hidden,'candidate hidden')==population['hidden'] and public==population['visible'],'Candidate differs from actual source preparation partition')

    return b


def canonical_ids(value,label):
    need(type(value) is list,label+' must be an ID array')
    result=set()
    for ident in value:
        need(type(ident) is str and re.fullmatch('[1-9][0-9]*',ident) and ident not in result,'Invalid/duplicate '+label+' ID')
        result.add(ident)
    return frozenset(result)

def bound_json(path,pin,expected_bytes=None):
    need(type(pin) is str and re.fullmatch('[0-9a-f]{64}',pin),'Expected evidence digest required')
    path=Path(path);raw=read_regular(path.parent,path.name)
    need(digest(raw)==pin and (expected_bytes is None or (type(expected_bytes) is int and len(raw)==expected_bytes)),'Complete source evidence bytes differ')
    return json_strict(raw)

def catalog_ids(site):
    expected={f'search_index_{i}.json' for i in range(24)}
    need({n for n in site if re.fullmatch(r'search_index_[0-9]+[.]json',n)}==expected,'Complete 24 search shards required')
    result=set()
    for name in sorted(expected):
        rows=json_strict(site[name]);need(type(rows) is list,'Search shard array required')
        for row in rows:
            need(type(row) is list and len(row)==14,'Search row must have 14 columns')
            ident=row[0];need(type(ident) is str and re.fullmatch('[1-9][0-9]*',ident) and ident not in result,'Invalid/duplicate public ID')
            result.add(ident)
    return frozenset(result)

def complete_backend_membership(archive,archive_dir,facts,inventory,completion,receipt,*,binding=None,overlay=None):
    """Read all saved-snapshot IDs/maps, never infer membership from public output.
    No price bodies are reread. Accepted full source preparation/semantic checks
    remain prerequisites; this additional check does not authenticate receipts.
    """
    need(archive['schema']=='boopa-rebuilt-saved-source-archive-v1' and archive['status']=='git-bound-source-materialized-semantic-preparation-pending','Unsupported saved archive receipt')
    need(archive['raw_data_metadata_materialized'] is True and archive['source_prices_semantically_scanned'] is False and archive['source_semantic_preparation_complete'] is False and archive['publication_acceptance'] is False,'Actual saved source materialization required')
    entry=archive['outputs']['backend-product-ids.private.json']
    backend=canonical_ids(bound_json(Path(archive_dir)/'backend-product-ids.private.json',entry['sha256'],entry['bytes']),'complete backend')
    need(backend and type(archive['backend_product_count']) is int and len(backend)==archive['backend_product_count'],'Complete archive backend count differs')
    need(type(inventory) is dict and inventory and completion['files']==inventory,'Complete prepared inventory differs from completion')
    need({'charts.json','data/collection_receipt.json','tracker_meta/meta_state.json','tracker_meta/recheck_state.json','tracker_meta/request_budget.json'}<=set(inventory),'Required complete source inputs missing')
    need(type(archive['selected_files']) is int and len(inventory)==archive['selected_files']+1,'Complete selected inventory count differs')
    data=set();meta=set()
    data_admin={'.gitkeep','collection_receipt.json','crawl_state.json','request_budget.json'}
    meta_admin={'meta_state.json','recheck_state.json','request_budget.json'}
    for name,pin in inventory.items():
        safe_name(name);need(type(pin) is str and re.fullmatch('[0-9a-f]{64}',pin),'Invalid prepared file digest')
        parts=name.split('/')
        if name=='charts.json':continue
        need(parts[0] in ('data','tracker_meta'),'Unexpected prepared namespace')
        if len(parts)==2 and parts[1] in (data_admin if parts[0]=='data' else meta_admin):continue
        need(len(parts)==3 and re.fullmatch('[1-9][0-9]*[.]json',parts[2]) and parts[1]==parts[2][:-5][:3],'Invalid prepared product path')
        target=data if parts[0]=='data' else meta;ident=parts[2][:-5];need(ident not in target,'Duplicate prepared product ID');target.add(ident)
    need(data==backend and meta<=backend,'Complete prepared source/backend membership differs')
    me=archive['outputs']['metadata-product-ids.private.json']
    need(canonical_ids(bound_json(Path(archive_dir)/'metadata-product-ids.private.json',me['sha256'],me['bytes']),'archive metadata')==meta and archive['metadata_product_count']==len(meta),'Complete archive metadata membership differs')
    need(type(receipt['prepared_files']) is int and len(inventory)==receipt['prepared_files'] and type(receipt['backend_products']) is int and receipt['backend_products']==len(backend) and type(receipt['metadata_products']) is int and receipt['metadata_products']==len(meta),'Prepared source counts differ')
    need(facts['schema']=='boopa-saved-source-preparation-facts-r1','Unsupported complete facts')
    need(canonical_ids(facts['backend_ids'],'facts backend')==backend and canonical_ids(facts['metadata_ids'],'facts metadata')==meta,'Facts backend/metadata membership differs')
    hidden=canonical_ids(facts['exclusion_union_ids'],'facts exclusion');visible=canonical_ids(facts['visible_ids'],'facts visible')
    saved=canonical_ids(facts['saved_negative_ids'],'facts saved negatives');retained=canonical_ids(facts['retained_ids'],'facts retained');latest=canonical_ids(facts['latest_overlay_ids'],'facts latest overlay')
    need(hidden==saved|retained|latest and hidden<=backend,'Complete permanent facts partition differs')
    pending_keys={'metadata_missing_ids','pending_metadata_ids','prior_pending_metadata_ids','resolved_pending_metadata_ids','public_hidden_ids'}
    pending_mode=bool(pending_keys&set(facts))
    pending=frozenset();public_hidden=hidden
    if pending_mode:
        need(pending_keys<=set(facts) and binding is not None and overlay is not None,'Complete explicit pending provenance required')
        need(facts.get('pending_metadata_availability_confirmed') is False and receipt.get('pending_metadata_availability_confirmed') is False,'Pending availability must remain unconfirmed')
        need(overlay.get('schema')=='boopa-latest-negative-overlay-r4','Pending proof cannot downgrade to a legacy overlay')
        markers_entry=archive['outputs']['current-negative-markers.private.json']
        markers=bound_json(Path(archive_dir)/'current-negative-markers.private.json',markers_entry['sha256'],markers_entry['bytes'])
        need(type(markers) is list and all(type(x) is dict and type(x.get('status')) is int and x['status'] in (404,410) for x in markers),'Saved negative marker evidence required')
        need(canonical_ids([x['id'] for x in markers],'archive saved negatives')==saved and saved<=meta,'Saved negative facts lack actual metadata markers')
        need(canonical_ids([x['id'] for x in overlay['entries']],'actual latest negatives')==latest,'Latest negative facts differ from actual overlay')
        proof=overlay['pending_metadata'];fields={'schema','source_commit','source_root','source_archive_receipt_sha256','prior_backend_receipt_sha256','prior_backend_ids_sha256','prior_pending_ids_sha256','missing_ids','pending_ids','resolved_pending_ids'}
        need(type(proof) is dict and set(proof)==fields and proof['schema']=='boopa-pending-metadata-r1','Closed pending proof required')
        for key,bkey in [('source_commit','price_source_commit'),('source_root','source_root_tree'),('source_archive_receipt_sha256','source_archive_receipt_sha256'),('prior_backend_receipt_sha256','prior_backend_receipt_sha256'),('prior_backend_ids_sha256','prior_backend_ids_sha256')]:
            need(proof[key]==binding[bkey],'Pending proof identity differs')
        missing=canonical_ids(facts['metadata_missing_ids'],'facts missing');pending=canonical_ids(facts['pending_metadata_ids'],'facts pending')
        previous=canonical_ids(facts['prior_backend_ids'],'facts previous backend');previous_pending=canonical_ids(facts['prior_pending_metadata_ids'],'facts previous pending')
        resolved=canonical_ids(facts['resolved_pending_metadata_ids'],'facts resolved pending');public_hidden=canonical_ids(facts['public_hidden_ids'],'facts public hidden')
        def set_sha(ids,newline=False):return digest((json.dumps(sorted(ids),separators=(',',':'))+('\n' if newline else '')).encode())
        need(set_sha(previous,True)==binding['prior_backend_ids_sha256']==receipt['prior_backend_ids_sha256'],'Actual previous backend commitment differs')
        need(set_sha(retained)==binding['retained_ids_sha256'],'Retained floor commitment differs')
        need(set_sha(previous_pending)==proof['prior_pending_ids_sha256'],'Previous pending commitment differs')
        need(previous<=backend and previous_pending<=previous and not(previous_pending&retained),'Previous backend/pending membership differs')
        need(missing==backend-meta and missing<=hidden|(backend-previous)|previous_pending,'Unknown old product lost metadata')
        need(pending==missing-hidden and not(pending&hidden) and public_hidden==hidden|pending,'Pending suppression partition differs')
        need(resolved==(previous_pending&meta)-hidden,'Resolved pending partition differs')
        for key,actual in [('missing_ids',missing),('pending_ids',pending),('resolved_pending_ids',resolved)]:
            need(canonical_ids(proof[key],'proof '+key)==actual and proof[key]==sorted(actual),'Proof differs from actual source sets')
        for key,actual in [('missing_metadata_products',missing),('pending_metadata_products',pending),('prior_pending_metadata_products',previous_pending),('resolved_pending_metadata_products',resolved),('public_hidden_products',public_hidden)]:
            need(type(receipt.get(key)) is int and receipt[key]==len(actual),'Pending source count differs')
    else:
        need(meta==backend,'Missing metadata requires explicit pending proof')
    need(visible==backend-public_hidden,'Complete public facts partition differs')
    need(type(receipt['exclusion_union']) is int and receipt['exclusion_union']==len(hidden) and type(receipt['visible_products']) is int and receipt['visible_products']==len(visible),'Source partition count differs')
    return {'backend':backend,'hidden':public_hidden,'permanent_hidden':hidden,'pending':pending,'pending_mode':pending_mode,'visible':visible}

def validate_saved_population(handoff_path,source_archive_receipt_path,inputs,composition,binding,binding_pin):
    handoff=bound_json(handoff_path,inputs['handoff_sha256'])
    need(handoff['schema']=='boopa-new-saved-prepared-handoff-r2' and handoff['status']=='producer-verified-independent-final-readback-required','Unsupported prepared handoff')
    need(all(handoff[k] is False for k in ('publication_acceptance','authenticated_context_verified','workflow_run_completion_claimed','publication_authorized')),'Prepared handoff authority changed')
    need(handoff['run_bindings_sha256']==binding_pin,'Prepared handoff run binding differs')
    need(handoff['source_receipt_sha256']==inputs['source_receipt_sha256']==composition['source_receipt_sha256'],'Actual source receipt pin differs')
    receipt=bound_json(handoff['source_receipt_path'],handoff['source_receipt_sha256'])
    need(receipt['schema'] in ('boopa-new-saved-source-preparation-r2','boopa-new-saved-source-preparation-r3') and receipt['status']=='prepared-input-verified','Unsupported source preparation receipt')
    need(receipt['run_bindings_sha256']==binding_pin and receipt['source_commit']==binding['price_source_commit'] and receipt['source_root']==binding['source_root_tree'] and receipt['metadata_tree']==binding['source_metadata_tree'],'Prepared source identity differs')
    for rk,bk in [('archive_receipt_sha256','source_archive_receipt_sha256'),('selection_receipt_sha256','selection_receipt_sha256'),('quarantine_proof_sha256','quarantine_proof_sha256'),('latest_negative_overlay_sha256','latest_negative_overlay_sha256'),('latest_negative_impact_sha256','latest_negative_impact_sha256'),('prior_snapshot_sha256','retained_snapshot_sha256'),('helper_freeze_sha256','consumer_freeze_sha256')]:
        need(receipt[rk]==binding[bk],'Source receipt binding differs: '+rk)
    need(all(receipt[k] is False for k in ('collection_completion_verified','whole_catalog_complete','price_source_is_latest','independent_source_acceptance','publication_acceptance','authenticated_context_verified','workflow_run_completion_claimed','publication_authorized')) and receipt['bindings_authority']=='caller-pinned-inputs-not-provider-authentication','Source scope flags changed')
    archive=bound_json(source_archive_receipt_path,binding['source_archive_receipt_sha256'])
    need(archive['source_commit']==binding['price_source_commit'] and archive['git_root']==binding['source_root_tree'] and archive['metadata_tree']==binding['source_metadata_tree'] and archive['archive_sha256']==binding['source_archive_sha256'],'Actual source archive identity differs')
    need(handoff['completion_sha256']==inputs['completion_sha256'],'Actual completion pin differs')
    completion=bound_json(Path(handoff['prepared_root'])/'completion.json',inputs['completion_sha256'])
    need(type(completion['schema']) is int and completion['schema']==1 and completion['status']=='complete' and completion['fixture'] is False,'Unsupported prepared completion')
    need(completion['tracker_commit']==completion['collection_id']==binding['price_source_commit'] and completion['saved_snapshot_composition']==composition,'Prepared completion identity/composition differs')
    evidence=Path(handoff['source_receipt_path']).parent
    need(handoff['facts_sha256']==receipt['composition_facts_sha256'] and handoff['prepared_inventory_sha256']==receipt['prepared_inventory_sha256'],'Handoff complete facts/inventory commitments differ')
    facts=bound_json(evidence/'composition-facts.private.json',receipt['composition_facts_sha256'])
    inventory=bound_json(evidence/'prepared-inventory.json',receipt['prepared_inventory_sha256'])
    overlay=bound_json(handoff['overlay_path'],binding['latest_negative_overlay_sha256'])
    return complete_backend_membership(archive,Path(source_archive_receipt_path).parent,facts,inventory,completion,receipt,binding=binding,overlay=overlay)

def validate_negative_scan(path,pin,binding,hidden,backend,public_ids):
    scan=pinned(path,pin)
    need(scan['schema']=='boopa-current-metadata-negative-scan-r1' and scan['status']=='git-bound-complete-metadata-negative-scan-floor-comparison-pending','Unsupported negative scan receipt')
    need(scan['source_commit']==binding['latest_negative_source_commit'] and scan['metadata_tree']==binding['latest_negative_metadata_tree'],'Scan cutoff mismatch')
    entry=scan['outputs']['current-negative-markers.private.json'];raw=(Path(path).parent/'current-negative-markers.private.json').read_bytes()
    need(len(raw)==entry['bytes'] and digest(raw)==entry['sha256'],'Complete marker output missing or changed')
    rows=json_strict(raw);need(type(rows) is list and len(rows)==scan['negative_count'],'Negative marker count differs');ids=set()
    for row in rows:
        ident=row['id'];need(type(ident) is str and re.fullmatch('[1-9][0-9]*',ident) and ident not in ids and type(row['status']) is int and row['status'] in (404,410),'Invalid negative marker');ids.add(ident)
    h=canonical_ids(hidden,'candidate hidden')
    need(type(backend) is frozenset and type(public_ids) is frozenset,'Verified complete source/public sets required')
    need((ids & backend)<=h,'Candidate omits current negative exclusions')
    need(not(ids & public_ids),'Current negative leaked into public catalog')
    need(h<=backend and public_ids==backend-h,'Candidate public/hidden partition differs from complete source')
    # ids - backend stays part of the full scan but is not a saved-source product.
    # Never add it to hidden/current saved-negative facts or publish it.
    return scan

def authenticated_git(repo,token,*args):
    need(type(token) is str and token and '\n' not in token and '\r' not in token,'Explicit BOOPADB_PUBLISH_TOKEN required')
    env=safe_env();env.update(GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',GIT_CONFIG_VALUE_0='AUTHORIZATION: basic '+base64.b64encode(('x-access-token:'+token).encode()).decode())
    try:return subprocess.check_output(git_command(repo,['-c','protocol.file.allow=never',*args]),env=env,stderr=subprocess.DEVNULL,timeout=180).decode().strip()
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError):raise RuntimeError('Git transport outcome unconfirmed') from None

def publish(*,repo,candidate,candidate_pin,prior,prior_pin,expected,binding_path,binding_pin,run_dir,run_pins,pipeline_dir,pipeline_pin,negative_scan_path,negative_scan_pin,handoff_path,source_archive_receipt_path,refresh_guard,token,journal):
    """refresh_guard runs an authenticated read-only acquisition supplied by runner.
    It must return (path, SHA) for real provider observations, acquired after start.
    No credential discovery; token is injected explicitly, never recorded.
    """
    inspect_repo(repo)
    start=time.time();b=validate_release(candidate,candidate_pin,prior_pin,expected,binding_path,binding_pin,run_dir,run_pins,pipeline_dir,pipeline_pin,negative_scan_path,negative_scan_pin,handoff_path=handoff_path,source_archive_receipt_path=source_archive_receipt_path)
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
