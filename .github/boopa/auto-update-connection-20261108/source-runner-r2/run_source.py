"""Local saved-source orchestration. Pins are assertions, not live/provider authority."""
import argparse,hashlib,importlib.util,json,os,re,tempfile
from pathlib import Path
from datetime import date,datetime,timezone,timedelta
from types import SimpleNamespace

def need(x,m):
    if not x:raise ValueError(m)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
def strict(raw):
    def pairs(rows):
        d={}
        for k,v in rows:need(k not in d,'Duplicate JSON key');d[k]=v
        return d
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
def raw_pin(path,pin):
    p=Path(path);need(p.is_file() and not p.is_symlink(),'Regular pinned file required')
    raw=p.read_bytes();need(re.fullmatch('[0-9a-f]{64}',pin) and sha(raw)==pin,'Pinned bytes differ');return raw
def ref(r):
    need(type(r) is dict and set(r)=={'path','sha256'},'Closed file reference required')
    return raw_pin(r['path'],r['sha256'])
def load_code(name,path,pin):
    raw_pin(path,pin);spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def put(path,value):
    raw=encode(value);path.write_bytes(raw);return sha(raw)
def oid(v):return type(v) is str and re.fullmatch('[0-9a-f]{40}',v)
def identity(item,adapter):
    fields={'commit','root_tree','metadata_tree','as_of','identity_proof'}
    need(type(item) is dict and set(item) in (fields|{'archive'},fields|{'materialized'},fields|{'official_download'}),'Closed source descriptor required')
    need(all(oid(item[k]) for k in ('commit','root_tree','metadata_tree')),'Source OID invalid')
    need(date.fromisoformat(item['as_of']).isoformat()==item['as_of'],'Source date invalid')
    ref(item['identity_proof']);proof=adapter.verify_identity(Path(item['identity_proof']['path']),item['identity_proof']['sha256'])
    need(type(proof) is dict and all(proof.get(k)==item[k] for k in ('commit','root_tree','metadata_tree')),'Source identity proof differs')

def source_input(item,stage,adapter,metadata_only,p):
    identity(item,adapter);name='METADATA-NEGATIVE-SCAN.json' if metadata_only else 'SOURCE-ARCHIVE-RECEIPT.json'
    if 'materialized' in item:
        r=item['materialized'];need(set(r)=={'path','receipt_sha256'},'Closed materialized reference required')
        root=Path(r['path']).absolute();pin=r['receipt_sha256']
    else:
        if 'official_download' in item:
            need(item['official_download'] is True,'Explicit official download required')
            archive_path=stage/('latest-archive.tar.gz' if metadata_only else 'source-archive.tar.gz')
            acquired=adapter.download_official(item['commit'],archive_path)
            put(stage/('latest-acquisition.json' if metadata_only else 'source-acquisition.json'),acquired)
            archive={'path':str(archive_path),'sha256':acquired['sha256']}
        else:archive=item['archive']
        need(set(archive)=={'path','sha256'},'Closed archive reference required')
        root=stage/('latest-materialized' if metadata_only else 'source-materialized')
        adapter.materialize(Path(archive['path']),archive['sha256'],root,item['commit'],item['root_tree'],item['metadata_tree'],date.fromisoformat(item['as_of']),metadata_only=metadata_only)
        pin=p.hash_file(root/name)
    receipt=p.pinned(root/name,pin)
    need(receipt['source_commit']==item['commit'] and receipt['git_root']==item['root_tree'] and receipt['metadata_tree']==item['metadata_tree'],'Materialized identity differs')
    need(receipt['as_of_date']==item['as_of'] and receipt['publication_acceptance'] is False,'Materialized date/scope differs')
    if not metadata_only:need(receipt.get('raw_data_metadata_materialized') is True,'Source requires actual materialized raw inputs')
    expected={'boopa-latest-metadata-negative-scan-v1','boopa-current-metadata-negative-scan-r1'} if metadata_only else {'boopa-rebuilt-saved-source-archive-v1'}
    need(receipt['schema'] in expected,'Materialized receipt schema differs')
    return root,receipt,pin

def scan_markers(root,receipt,p,metadata_only=False):
    def output(name):
        r=receipt['outputs'][name];path=root/name
        need(path.stat().st_size==r['bytes'],'Scan output size differs')
        return p.pinned(path,r['sha256'])
    markers=output('current-negative-markers.private.json');ids=p.id_list(output('metadata-product-ids.private.json'))
    need(type(markers) is list and len(markers)==receipt['negative_count'],'Negative scan count differs')
    mapped={}
    for m in markers:
        need(type(m) is dict and set(m)=={'id','path','sha256','git_blob','bytes','status','fetched_at'},'Closed marker required')
        ident=m['id'];need(type(ident) is str and p.ID.fullmatch(ident) and ident not in mapped and ident in ids,'Unique covered marker ID required')
        need(m['path']=='meta/'+ident[:3]+'/'+ident+'.json' and type(m['status']) is int and m['status'] in (404,410),'Negative marker identity differs')
        need(type(m['bytes']) is int and 0<m['bytes']<=p.MAX_RECORD and p.SHA.fullmatch(m['sha256']) and oid(m['git_blob']),'Marker byte commitments invalid')
        need(date.fromisoformat(m['fetched_at']).isoformat()==m['fetched_at'] and m['fetched_at']<=receipt['as_of_date'],'Marker date invalid')
        mapped[ident]=m
    need(list(mapped)==sorted(mapped),'Canonical marker order required')
    if metadata_only:
        pin=receipt['outputs']['metadata-inventory.jsonl'];path=root/'metadata-inventory.jsonl'
        need(path.stat().st_size==pin['bytes'] and p.hash_file(path)==pin['sha256'],'Latest inventory differs')
        products=set();negative=set();tree={};count=0
        with path.open('rb') as f:
            for line in f:
                r=p.strict(line);need(type(r) is dict and set(r)=={'path','bytes','mode','git_blob','sha256','id','negative'},'Closed latest inventory row required')
                ident=p.product_id(r['path'],'meta');need(r['path'].startswith('meta/') and r['id']==ident and type(r['negative']) is bool,'Latest inventory ID/flag differs')
                need(r['mode']=='100644' and oid(r['git_blob']) and type(r['sha256']) is str and p.SHA.fullmatch(r['sha256']) and type(r['bytes']) is int and 0<=r['bytes']<=p.MAX_RECORD,'Latest inventory commitments invalid')
                path2='data/'+r['path'][5:];need(path2 not in tree,'Duplicate latest path');tree[path2]=r;count+=1
                if ident is not None:need(ident not in products,'Duplicate latest ID');products.add(ident)
                if r['negative']:
                    need(ident in mapped,'Missing negative marker');negative.add(ident)
                    need(all(r[k]==mapped[ident][k] for k in ('path','bytes','sha256','git_blob')),'Marker inventory mismatch')
        need(count==receipt['metadata_file_count'] and products==ids and len(ids)==receipt['metadata_product_count'] and negative==set(mapped),'Complete latest scan coverage differs')
        need(p.inventory_data_tree(tree)==receipt['metadata_tree'],'Latest metadata Git tree differs')
    return mapped

def issue_policy(source,sr,sourcepin,latest,lr,latestpin,prior,candidate,selection,selectionpin,helpers,helper_pins,stage,p,observation):
    vs,vp,sp,charts,hashes=p.load_helpers(helpers,helper_pins)
    retained=vp.read_retained_exclusions(candidate,prior['snapshot_sha256'])
    manifest=p.pinned(candidate/'snapshot-manifest.json',prior['snapshot_sha256'])
    composition=manifest.get('saved_snapshot_composition')
    need(type(composition) is dict and composition.get('schema') in ('boopa-saved-snapshot-composition-r1','boopa-saved-snapshot-composition-r2') and composition.get('price_source_commit')==prior['prior_backend_source_commit'],'Actual prior manifest price source differs from backend')
    visible,_=p.prior_public(candidate,manifest,vs.exact_read,vs.open_directory)
    bprior={k:prior[k] for k in ('prior_backend_receipt_kind','prior_backend_source_commit','prior_backend_root_tree','prior_backend_data_tree')}
    bprior.update(prior_backend_ids_sha256=prior['ids']['sha256'],prior_backend_receipt_sha256=prior['receipt']['sha256'])
    pa=SimpleNamespace(prior_backend_ids=Path(prior['ids']['path']),prior_backend_ids_sha256=prior['ids']['sha256'],prior_backend_receipt=Path(prior['receipt']['path']),prior_backend_receipt_sha256=prior['receipt']['sha256'],prior_backend_inventory=Path(prior['inventory']['path']) if prior['inventory'] is not None else None)
    if prior['inventory'] is not None:ref(prior['inventory'])
    priorids=p.validate_prior_backend(pa,bprior)
    need(not visible&retained['ids'] and visible|retained['ids']==priorids,'Actual prior public/floor differs from backend')
    inventory=p.read_inventory(source/'selected-inventory.jsonl',sr['outputs']['selected-inventory.jsonl']['sha256'])
    p.assert_closure(source/'selected',inventory)
    backend={p.product_id(n,'data') for n in inventory if p.product_id(n,'data') is not None}
    need(priorids<=backend,'Prior backend missing from saved source')
    saved=scan_markers(source,sr,p);current=scan_markers(latest,lr,p,True)
    need(set(saved)<=backend,'Saved markers lack backend')
    additional=(set(current)&backend)-retained['ids']
    outside_backend=set(current)-backend
    fd=vs.open_directory(source/'selected');conflicts=[]
    try:
        raw=p.exact_source(vs.exact_read,fd,inventory['data/collection_receipt.json'])
        need(p.digest(raw)==selection['collection_receipt_sha256'],'Saved collection receipt mismatch')
        stopped=p.strict(raw)['stopped_at_ms'];need(type(stopped) is int and stopped>0,'Actual stop time required')
        asof=datetime.fromtimestamp(stopped/1000,timezone.utc).astimezone(timezone(timedelta(hours=9))).date()
        for ident in sorted(set(saved)|additional):
            row=inventory['data/'+ident[:3]+'/'+ident+'.json'];raw=p.exact_source(vs.exact_read,fd,row)
            counts,_,_=p.inspect_history(p.strict(raw),ident,asof)
            if ident in additional:need(current[ident]['fetched_at']<=observation['upper_jst_date'] and not any(d>current[ident]['fetched_at'] for d in counts),'Latest negative conflicts with saved history/date')
            if ident not in saved:continue
            m=saved[ident];mraw=p.exact_source(vs.exact_read,fd,inventory[m['path']])
            need(len(mraw)==m['bytes'] and p.digest(mraw)==m['sha256'] and p.git_blob(mraw)==m['git_blob'],'Saved marker bytes differ')
            v=p.strict(mraw);need(v.get('id')==ident and v.get('unavailable') is True and v.get('status')==m['status'] and v.get('fetched_at')==m['fetched_at'] and not v.get('name'),'Saved marker semantics differ')
            after=sum(c for d,c in counts.items() if d>m['fetched_at'])
            if after:
                need(ident in retained['ids'],'Contradiction outside actual previous floor')
                conflicts.append({'id':ident,'price_sha256':row['sha256'],'metadata_sha256':m['sha256'],'status':m['status'],'fetched_at':m['fetched_at'],'observations_total':sum(counts.values()),'observations_after_marker':after,'prior_floor_member':True})
    finally:os.close(fd)
    floor={'prior_snapshot_sha256':retained['snapshot_sha256'],'prior_lists_sha256':retained['lists_sha256'],'prior_ids_sha256':retained['ids_sha256']}
    diag={'schema':'boopa-saved-source-conflict-diagnostic-runner-r1','source_commit':sr['source_commit'],'source_root':sr['git_root'],'metadata_tree':sr['metadata_tree'],'archive_receipt_sha256':sourcepin,'selection_receipt_sha256':selectionpin,**floor,'conflicts':conflicts,'outside_floor_conflicts':0,'exception_applied':False,'publication_acceptance':False}
    dp=stage/'diagnostic.private.json';dsha=put(dp,diag)
    qp=stage/'quarantine.private.json';qsha=put(qp,{'schema':'boopa-saved-conflict-quarantine-r2','source_commit':sr['source_commit'],**floor,'diagnostic_receipt_sha256':dsha,'entries':[{k:v for k,v in e.items() if k!='prior_floor_member'} for e in conflicts]})
    union=set(retained['ids'])|set(saved)|additional
    ip=stage/'impact.private.json';isha=put(ip,{'schema':'boopa-latest-negative-impact-runner-r1','source_commit':lr['source_commit'],'source_metadata_tree':lr['metadata_tree'],'latest_scan_receipt_sha256':latestpin,'latest_negative_observation_sha256':observation['observation_sha256'],'latest_negative_observation_upper_jst_day':observation['upper_jst_date'],'latest_negative_ids_outside_saved_backend':sorted(outside_backend),'latest_negative_count':len(current),'additional_exclusion_ids':sorted(additional),'exclusion_union_count':len(union),'exclusion_union_ids_sha256':p.digest(vp.json_bytes(sorted(union))),'publication_acceptance':False})
    op=stage/'overlay.private.json';osha=put(op,{'schema':'boopa-latest-negative-overlay-r3','observation':{'path':'observation/latest-observation.json','sha256':observation['observation_sha256']},'source_commit':lr['source_commit'],'metadata_tree':lr['metadata_tree'],**floor,'impact_receipt_sha256':isha,'entries':[current[i] for i in sorted(additional)]})
    return {'retained':retained,'prior_args':pa,'prior_bindings':bprior,'diagnostic':dp,'diagnostic_sha256':dsha,'quarantine':qp,'quarantine_sha256':qsha,'impact':ip,'impact_sha256':isha,'overlay':op,'overlay_sha256':osha}

def bind_latest_observation(latest,proofs,validator):
    fields={'commit','root_tree','metadata_tree','identity_proof','observation'}
    need(type(latest) is dict and set(latest) in (fields|{'archive'},fields|{'materialized'},fields|{'official_download'}),'Closed latest descriptor requires observation, not caller as_of')
    entry=latest['observation'];ref(entry)
    observation=validator.validate_observation(Path(entry['path']).absolute(),entry['sha256'],latest['commit'],latest['metadata_tree'])
    need(observation['provider_authenticated'] is False,'Observation is not provider authentication')
    raw=validator.read_regular(Path(entry['path']).absolute());o=validator.strict(raw)
    need(o['identity_proof']['sha256']==latest['identity_proof']['sha256'],'Latest observation/identity proof SHA differs')
    root=Path(entry['path']).absolute().parent;files={}
    def fetch(refrow):
        name=refrow['path'];need(type(name) is str and re.fullmatch('[a-z-]+[.]json',name) and name!='latest-observation.json','Flat safe observation evidence required')
        body=validator.read_regular(root/name);need(sha(body)==refrow['sha256'],'Observation evidence changed')
        if name in files:need(files[name]==body,'Conflicting observation evidence path')
        files[name]=body;return validator.strict(body)
    ident=fetch(o['identity_proof']);fetch(ident['commit_response']);fetch(ident['root_response']);fetch(o['ref_before']);fetch(o['ref_after'])
    dest=proofs/'observation';dest.mkdir()
    (dest/'latest-observation.json').write_bytes(raw)
    for name,body in files.items():(dest/name).write_bytes(body)
    rebound=validator.validate_observation(dest/'latest-observation.json',entry['sha256'],latest['commit'],latest['metadata_tree'])
    need(rebound==observation,'Copied observation binding changed')
    normalized={k:v for k,v in latest.items() if k!='observation'};normalized['as_of']=observation['upper_jst_date']
    return normalized,observation

def run(plan_path,plan_sha256,output):
    plan=strict(raw_pin(plan_path,plan_sha256));output=Path(output).absolute()
    need(type(plan) is dict and set(plan)=={'schema','source','latest','selection','prior','helpers','sourceprep','archive_adapter','public_parent'},'Closed runner plan required')
    need(plan['schema']=='boopa-source-runner-plan-r2','Runner plan schema differs')
    need(not output.exists() and not output.is_symlink(),'New runner destination required')
    prep=plan['sourceprep'];need(set(prep)=={'path','freeze_sha256'},'Closed sourceprep descriptor required')
    freeze=strict(raw_pin(Path(prep['path'])/'FREEZE.json',prep['freeze_sha256']))
    code=freeze['files']['prepare_source.py'];p=load_code('runner_preparation',Path(prep['path'])/'prepare_source.py',code['sha256'])
    ad=plan['archive_adapter'];ref(ad);adapter=load_code('runner_archive_adapter',ad['path'],ad['sha256'])
    hs=plan['helpers'];need(set(hs)=={'path','consumer_freeze_sha256','charts_selector_sha256','varutil_sha256'},'Closed helpers descriptor required')
    helpers=Path(hs['path']).absolute();helper_pins={k:v for k,v in hs.items() if k!='path'}
    # Verify executable helpers before proof diagnosis or materialization.
    _,_,_,_,helper_hashes=p.load_helpers(helpers,helper_pins)
    observation_validator=load_code('runner_observation_validation',helpers/'observation_validation.py',helper_hashes['observation_validation.py'])
    selection_raw=ref(plan['selection']);selection=p.strict(selection_raw);p.validate_selection_scope(selection,plan['selection']['sha256'])
    parent=strict(ref(plan['public_parent']))
    need(parent['schema']=='boopa-previous-production-input-r1' and parent['repository']=='MametaroGG/boopadb' and parent['branch']=='main','Previous production handoff scope differs')
    need(oid(parent['expected_public_parent_commit']),'Previous parent OID invalid')
    need(parent.get('provider_authenticated') is False and parent.get('deployment_verified') is False,'Previous local proof must not claim provider/deployment authority')
    prior=dict(plan['prior'])
    need(prior.get('candidate_path')==parent['prior_candidate_path'] and prior.get('snapshot_sha256')==parent['prior_snapshot_sha256'],'Prior candidate differs from production handoff')
    candidate=Path(prior['candidate_path']).absolute()
    with tempfile.TemporaryDirectory(prefix='.source-runner-unaccepted-',dir=output.parent) as tmp:
        stage=Path(tmp);proofs=stage/'proofs';proofs.mkdir()
        source,sr,sourcepin=source_input(plan['source'],stage,adapter,False,p)
        latest_descriptor,observation=bind_latest_observation(plan['latest'],proofs,observation_validator)
        latest,lr,latestpin=source_input(latest_descriptor,stage,adapter,True,p)
        need(selection['saved_commit']==sr['source_commit'] and selection['saved_root']==sr['git_root'],'Selected saved input differs')
        if 'archive_source' in prior:
            need(set(prior)=={'candidate_path','snapshot_sha256','archive_source'},'Closed prior archive descriptor required')
            desc=prior['archive_source'];identity(desc,adapter)
            need('archive' in desc or desc.get('official_download') is True,'Prior archive path or official download required')
            proof=adapter.verify_identity(Path(desc['identity_proof']['path']),desc['identity_proof']['sha256'])
            target=stage/'prior-inventory'
            if 'official_download' in desc:
                priorarchive=stage/'prior-archive.tar.gz';acquired=adapter.download_official(desc['commit'],priorarchive);put(stage/'prior-acquisition.json',acquired);archive={'path':str(priorarchive),'sha256':acquired['sha256']}
            else:archive=desc['archive']
            adapter.materialize(Path(archive['path']),archive['sha256'],target,desc['commit'],desc['root_tree'],desc['metadata_tree'],date.fromisoformat(desc['as_of']),inventory_only=True)
            rr=target/'SOURCE-ARCHIVE-RECEIPT.json';r=p.strict(rr.read_bytes())
            need(r['source_commit']==desc['commit'] and r['git_root']==desc['root_tree'] and r['metadata_tree']==desc['metadata_tree'] and r['raw_data_metadata_materialized'] is False,'Prior inventory-only result differs')
            prior.update(prior_backend_receipt_kind=r['schema'],prior_backend_source_commit=desc['commit'],prior_backend_root_tree=desc['root_tree'],prior_backend_data_tree=proof['data_tree'],receipt={'path':str(rr),'sha256':p.hash_file(rr)},ids={'path':str(target/'backend-product-ids.private.json'),'sha256':r['outputs']['backend-product-ids.private.json']['sha256']},inventory={'path':str(target/'selected-inventory.jsonl'),'sha256':r['outputs']['selected-inventory.jsonl']['sha256']})
        else:
            need(set(prior)=={'candidate_path','snapshot_sha256','prior_backend_receipt_kind','prior_backend_source_commit','prior_backend_root_tree','prior_backend_data_tree','receipt','ids','inventory'},'Closed prior local descriptor required')
        need(prior['prior_backend_source_commit']==parent['previous_price_source_commit'],'Prior backend source differs from actual published provenance')
        issued=issue_policy(source,sr,sourcepin,latest,lr,latestpin,prior,candidate,selection,plan['selection']['sha256'],helpers,helper_pins,proofs,p,observation)
        retained=issued['retained'];need(retained['lists_sha256']==parent['prior_lists_sha256'] and retained['ids_sha256']==parent['retained_ids_sha256'] and len(retained['ids'])==parent['retained_ids_count'],'Actual production retained floor differs')
        b={'schema':'boopa-saved-run-bindings-r2','source_repository':'MametaroGG/booth-vrc-price-tracker','publication_repository':'MametaroGG/boopadb','expected_public_parent_commit':parent['expected_public_parent_commit'],'price_source_commit':sr['source_commit'],'metadata_source_commit':sr['source_commit'],'source_root_tree':sr['git_root'],'source_metadata_tree':sr['metadata_tree'],'source_archive_receipt_sha256':sourcepin,'source_archive_sha256':sr['archive_sha256'],'selection_receipt_sha256':plan['selection']['sha256'],'retained_snapshot_sha256':retained['snapshot_sha256'],'retained_lists_sha256':retained['lists_sha256'],'retained_ids_sha256':retained['ids_sha256'],'latest_negative_source_commit':lr['source_commit'],'latest_negative_metadata_tree':lr['metadata_tree'],'latest_negative_impact_sha256':issued['impact_sha256'],'quarantine_proof_sha256':issued['quarantine_sha256'],'quarantine_diagnostic_sha256':issued['diagnostic_sha256'],'latest_negative_overlay_sha256':issued['overlay_sha256'],'authority':'caller-pinned-inputs-not-provider-authentication','collection_completion_verified':False,'whole_catalog_complete':False,'price_source_is_latest':False,**issued['prior_bindings'],**helper_pins}
        bp=proofs/'run-bindings.json';bsha=put(bp,b)
        args=issued['prior_args'];args.source=source;args.helpers=helpers;args.prior_candidate=candidate;args.output=stage/'prepared-run';args.selection_receipt=Path(plan['selection']['path']);args.quarantine=issued['quarantine'];args.diagnostic=issued['diagnostic'];args.overlay=issued['overlay'];args.impact=issued['impact'];args.run_bindings=bp;args.run_bindings_sha256=bsha
        handoff=p.run(args)
        # Only locator fields change on atomic relocation. Receipt and completion bytes do not.
        def relocated(path):
            v=Path(path)
            try:return str(output/v.relative_to(stage))
            except ValueError:return str(v)
        for key in ('prepared_root','source_receipt_path','quarantine_path','overlay_path','run_bindings_path'):handoff[key]=relocated(handoff[key])
        put(stage/'prepared-run/prepared-handoff.json',handoff)
        result={'schema':'boopa-source-runner-handoff-r2','latest_negative_observation_sha256':observation['observation_sha256'],'latest_negative_observation_upper_jst_day':observation['upper_jst_date'],'prepared_handoff_path':str(output/'prepared-run/prepared-handoff.json'),'prepared_handoff_sha256':p.hash_file(stage/'prepared-run/prepared-handoff.json'),'run_bindings_sha256':bsha,'source_archive_receipt_sha256':sourcepin,'latest_metadata_scan_receipt_sha256':latestpin,'plan_sha256':plan_sha256,'previous_production_handoff_sha256':plan['public_parent']['sha256'],'sourceprep_freeze_sha256':prep['freeze_sha256'],'runner_sha256':p.hash_file(Path(__file__)),'archive_adapter_sha256':ad['sha256'],'publication_acceptance':False,'authenticated_context_verified':False,'publication_authorized':False,'independent_source_acceptance':False}
        put(stage/'RUNNER-HANDOFF.json',result)
        need(p.hash_file(Path(plan_path))==plan_sha256 and p.hash_file(Path(prep['path'])/'prepare_source.py')==code['sha256'] and p.hash_file(Path(ad['path']))==ad['sha256'],'Inputs/code changed during runner')
        need(not output.exists(),'Runner destination appeared');stage.rename(output)
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--inputs',type=Path,required=True);ap.add_argument('--inputs-sha256',required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    print(json.dumps(run(a.inputs,a.inputs_sha256,a.output),sort_keys=True))
