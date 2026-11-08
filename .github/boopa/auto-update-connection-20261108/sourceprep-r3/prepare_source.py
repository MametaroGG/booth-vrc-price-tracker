"""Offline caller-pinned saved-source preparation. No network or publication operations.

The saved source, prior backend oracle, policy proofs and helper implementation
have separate external commitments. A failed run leaves no accepted output.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile

WORK = Path('/workspace/scratch/40867809e914')
BASE = WORK/'saved-source-6126-rebuild-20261108'
# Legacy constants below are regression fixture defaults, never run authority.
COMMIT = '6126cf5baa0d04869b5e2a6b8fc0f0345df58756'
ROOT = '5cb10361859324844d3cd9d02257b2823aed57f1'
META = 'c81f29d9f31ec731016a7a5a7ee94626b9386360'
ARCHIVE_RECEIPT = 'c478d7d16386dd32a9f059c70ffd1c8abb599b1ecad7e59fe66f55142c84af5d'
ARCHIVE = 'df356f4dc6096ec7b5e94184bd6a01b65a4c7da668330cbe7ecb55d8b4204f80'
SELECTION = '73bfb6ec9ea497feed0bf7e3f2dff2f6c1b336ddb084ed1a0a837da039851460'
QUARANTINE = '13d7f7b29dac8ab903ec325be6b0c312ab604eff0deef20c019cfab652ed205d'
DIAGNOSTIC = 'cf335856da2d845067f28cddc66cc2bdf9ce48cb9820a147ecfa1f7c51af7e48'
OVERLAY = '8cd1a134530c9322a6fe62b277f33a6f12b16bb27dcced099f03e9467fb3b91f'
IMPACT = '4d7f54db036009e9f98f09a031d9cf5266cd31e774caec0db1c9128d320aace0'
SNAPSHOT = '003bd3894f0567609a54e2b81266a2bc29853ef920a9b97c59aa81c476cbbdde'
HELPER_FREEZE = '37d71020b9c9e1bd9472c8fac5a9e71b3deb6edf7cdecbaa3ed404ac8cff3aa7'
CHARTS = 'ebb65e3d38fa1b2e3df274704397373f4621e8f4d9adcfa3c0b88b782ad0f81a'
VARUTIL = 'ea900c3de864c631e675cd0020be99bb7c77f0f9c71dbf8bc6fa56b69ff18003'
MAX_RECORD = 128*1024**2
SHA = re.compile(r'[0-9a-f]{64}\Z')
ID = re.compile(r'[1-9][0-9]*\Z', re.ASCII)
DATA_ADMIN = {'.gitkeep','collection_receipt.json','crawl_state.json','request_budget.json'}
META_ADMIN = {'meta_state.json','recheck_state.json','request_budget.json'}

def need(ok, message):
    if not ok: raise ValueError(message)

def digest(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
def git_blob(raw): return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def strict(raw):
    def pairs(rows):
        result={}
        for key,value in rows:
            need(key not in result, 'Duplicate JSON key')
            result[key]=value
        return result
    def bad(value): raise ValueError('Nonfinite JSON constant')
    def number(value):
        result=float(value);need(math.isfinite(result),'Overflow/nonfinite JSON number');return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad, parse_float=number)

def safe_name(name):
    need(type(name) is str and name and '\\' not in name and all(ord(x)>=32 and ord(x)!=127 for x in name),'Unsafe source name')
    p=PurePosixPath(name)
    need(not p.is_absolute() and '..' not in p.parts and p.as_posix()==name and name!='.','Noncanonical source name')
    return p

def hash_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024**2),b''): h.update(chunk)
    return h.hexdigest()

def pinned(path, pin):
    need(type(pin) is str and SHA.fullmatch(pin),'External SHA256 required')
    path=Path(path);need(path.is_file() and not path.is_symlink(),'Regular pinned file required')
    raw=path.read_bytes();need(digest(raw)==pin,'Pinned file differs: '+path.name)
    return strict(raw)

def id_list(value):
    need(type(value) is list and all(type(x) is str and ID.fullmatch(x) for x in value),'Canonical ID array required')
    need(value==sorted(set(value)),'Sorted unique ID array required')
    return set(value)

def product_id(name, namespace):
    p=safe_name(name)
    if p.parts[0]!=namespace:return None
    if len(p.parts)==2:
        need(p.name in (DATA_ADMIN if namespace=='data' else META_ADMIN),'Unknown source administration file')
        return None
    need(len(p.parts)==3 and p.suffix=='.json' and ID.fullmatch(p.stem) and p.parts[1]==p.stem[:3],'Noncanonical product path')
    return p.stem

def read_inventory(path, pin):
    need(hash_file(path)==pin,'Selected source inventory changed')
    result={}
    with Path(path).open('rb') as f:
        for line in f:
            row=strict(line)
            need(type(row) is dict and set(row)=={'path','bytes','mode','git_blob','sha256'},'Closed source inventory row required')
            name=row['path'];p=safe_name(name)
            need(p.parts[0] in ('data','meta') and len(p.parts)>=2 and row['mode']=='100644','Unexpected source namespace/mode')
            product_id(name,p.parts[0])
            need(name not in result and type(row['bytes']) is int and 0<=row['bytes']<=MAX_RECORD,'Duplicate/over-budget source record')
            need(type(row['sha256']) is str and SHA.fullmatch(row['sha256']) and type(row['git_blob']) is str and re.fullmatch('[0-9a-f]{40}',row['git_blob']),'Invalid inventory digest')
            result[name]=row
    need(result,'Empty selected inventory')
    return result

def assert_closure(root, names):
    expected=set(names);expected_dirs={'data','meta'}
    for name in expected:expected_dirs.update(str(p) for p in PurePosixPath(name).parents if str(p)!='.')
    files=set();dirs=set()
    need(root.is_dir() and not root.is_symlink(),'Regular source root required')
    for parent,folders,children in os.walk(root,followlinks=False):
        for name in folders:
            p=Path(parent)/name;need(not p.is_symlink(),'Linked source directory');dirs.add(p.relative_to(root).as_posix())
        for name in children:
            p=Path(parent)/name;st=p.lstat();need(stat.S_ISREG(st.st_mode) and st.st_nlink==1,'Linked/nonregular source file');files.add(p.relative_to(root).as_posix())
    need(files==expected and dirs==expected_dirs,'Source closure mismatch')

def exact_source(reader, fd, row):
    raw=reader(fd,row['path'],MAX_RECORD)
    need(len(raw)==row['bytes'] and digest(raw)==row['sha256'] and git_blob(raw)==row['git_blob'],'Source bytes differ from bound Git leaf: '+row['path'])
    if row['path'].endswith('.gitkeep'):need(not raw,'Nonempty source placeholder')
    return raw

def write_raw(root, name, raw):
    safe_name(name);target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as f:f.write(raw)

def inspect_history(record, ident, as_of):
    need(type(record) is dict and record.get('id')==ident,'Product ID mismatch')
    need(type(record.get('name')) is str,'Product name must be a string')
    variations=record.get('variations');need(type(variations) is dict,'Variations object required')
    counts=Counter();minimum=maximum=None
    for key,series in variations.items():
        need(type(key) is str and type(series) is list,'Invalid variation history')
        for row in series:
            need(type(row) is dict,'Observation object required')
            stamp=row.get('date');need(type(stamp) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}',stamp),'Canonical date required')
            d=date.fromisoformat(stamp);need(d.isoformat()==stamp and d<=as_of,'Future/noncanonical saved observation')
            price=row.get('price');need(type(price) in (int,float) and math.isfinite(price) and price>=0,'Invalid saved price')
            if 'is_sale' in row:need(type(row['is_sale']) is bool,'Optional sale flag must be an exact boolean')
            counts[stamp]+=1;minimum=stamp if minimum is None else min(minimum,stamp);maximum=stamp if maximum is None else max(maximum,stamp)
    return counts,minimum,maximum

def load_helpers(folder, bindings):
    freeze=pinned(folder/'CONSUMER-FREEZE.json',bindings['consumer_freeze_sha256'])
    hashes={name:row['sha256'] for name,row in freeze['files'].items() if name.endswith('.py')}
    hashes.update({'charts_contract.py':bindings['charts_selector_sha256'],'varutil.py':bindings['varutil_sha256']})
    for name,pin in hashes.items():need(hash_file(folder/name)==pin,'Frozen helper changed: '+name)
    sys.path.insert(0,str(folder))
    import verified_source,visibility_policy,saved_snapshot_policy,charts_contract
    for module in (verified_source,visibility_policy,saved_snapshot_policy,charts_contract):
        need(Path(module.__file__).resolve().parent==folder.resolve(),'Unexpected imported helper')
    return verified_source,visibility_policy,saved_snapshot_policy,charts_contract,hashes

def prior_public(candidate, manifest, exact_read, open_directory):
    fd=open_directory(candidate);visible=set();pins={}
    try:
        shard_names={name for name in manifest['files'] if re.fullmatch(r'search_index_\d+\.json',name)}
        need(shard_names=={'search_index_'+str(i)+'.json' for i in range(24)},'Exact prior24 search shards required')
        for name in sorted(shard_names):
            raw=exact_read(fd,name,MAX_RECORD);pin=manifest['files'][name];need(digest(raw)==pin,'Prior search shard changed')
            rows=strict(raw);need(type(rows) is list,'Search rows required')
            for row in rows:
                need(type(row) is list and len(row)==14 and type(row[0]) is str and ID.fullmatch(row[0]) and row[0] not in visible,'Invalid/duplicate prior search row')
                visible.add(row[0])
            pins[name]=pin
    finally:os.close(fd)
    return visible,pins

class ChartReadAdapter:
    """Use the exact frozen selector while doing the one full history pass."""
    def __init__(self, source, fd, inventory, prepared, exact_read, policy, as_of):
        self.root=source;self.fd=fd;self.inventory=inventory;self.prepared=prepared;self.exact_read=exact_read;self.policy=policy;self.as_of=as_of
        self.consumed=set();self.date_counts=Counter();self.product_dates=Counter();self.first_dates={};self.minimum=self.maximum=None
    def paths(self, namespace, products_only=False):
        need(namespace=='data' and products_only is True,'Unexpected chart source traversal')
        for name in sorted(self.inventory):
            if product_id(name,'data') is not None:yield self.root/name
    def relative(self,path):
        name=path.relative_to(self.root).as_posix();safe_name(name)
        need(name in self.inventory,'Unbound chart source read');return name
    def read_json(self,path):
        name=self.relative(path)
        row=self.inventory[name];raw=exact_source(self.exact_read,self.fd,row);record=strict(raw)
        if name not in self.consumed:
            ident=product_id(name,'data');need(ident is not None,'Chart read must be product')
            counts,first,last=inspect_history(record,ident,self.as_of)
            self.date_counts.update(counts);self.product_dates.update(counts.keys());self.first_dates[ident]=first
            if first is not None:self.minimum=first if self.minimum is None else min(self.minimum,first)
            if last is not None:self.maximum=last if self.maximum is None else max(self.maximum,last)
            self.policy.observe_product(record,raw=raw)
            write_raw(self.prepared,name,raw);self.consumed.add(name)
        return record

def inventory_data_tree(inventory):
    """Reconstruct Git tree objects from every data path, including admin files."""
    root={}
    for name,row in inventory.items():
        parts=PurePosixPath(name).parts
        if parts[0]!='data':continue
        node=root
        for part in parts[1:-1]:
            need(not isinstance(node.get(part),tuple),'File/tree path collision')
            node=node.setdefault(part,{})
        need(parts[-1] not in node,'Duplicate/tree path collision')
        node[parts[-1]]=(row['mode'],row['git_blob'])
    need(root,'Empty prior data tree')
    def tree(node):
        body=b''
        for name,value in sorted(node.items(),key=lambda item:(item[0]+('/' if isinstance(item[1],dict) else '')).encode()):
            mode,oid=('40000',tree(value)) if isinstance(value,dict) else value
            body+=mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(oid)
        return hashlib.sha1(b'tree '+str(len(body)).encode()+b'\0'+body).hexdigest()
    return tree(root)

def validate_prior_backend(args,b):
    need(args.prior_backend_ids_sha256==b['prior_backend_ids_sha256'] and args.prior_backend_receipt_sha256==b['prior_backend_receipt_sha256'],'Prior CLI pins differ from bindings')
    ids=id_list(pinned(args.prior_backend_ids,b['prior_backend_ids_sha256']))
    r=pinned(args.prior_backend_receipt,b['prior_backend_receipt_sha256'])
    need(r.get('schema')==b['prior_backend_receipt_kind'],'Prior receipt kind differs')
    need(r.get('source_commit')==b['prior_backend_source_commit'] and r.get('source_prices_semantically_scanned') is False,'Prior source identity/scope differs')
    if b['prior_backend_receipt_kind']=='boopa-prior-backend-git-inventory-r1':
        need(r.get('status')=='verified-git-backend-ids' and r.get('root_tree')==b['prior_backend_root_tree'] and r.get('data_tree')==b['prior_backend_data_tree'],'Legacy prior tree identity differs')
        binding=r.get('backend_ids',{})
        need(binding.get('file')==args.prior_backend_ids.name and binding.get('sha256')==b['prior_backend_ids_sha256'] and binding.get('bytes')==args.prior_backend_ids.stat().st_size and binding.get('count')==len(ids),'Prior backend receipt does not bind actual ID bytes')
    else:
        need(r.get('status')=='git-bound-source-materialized-semantic-preparation-pending' and r.get('git_root')==b['prior_backend_root_tree'],'Saved prior archive identity differs')
        need(r.get('source_semantic_preparation_complete') is False and r.get('publication_acceptance') is False,'Prior archive scope differs')
        binding=r['outputs']['backend-product-ids.private.json']
        need(binding['sha256']==b['prior_backend_ids_sha256'] and binding['bytes']==args.prior_backend_ids.stat().st_size and r['backend_product_count']==len(ids),'Saved prior ID binding differs')
        need(args.prior_backend_inventory is not None,'Saved prior archive requires exact inventory')
        invpin=r['outputs']['selected-inventory.jsonl']
        need(args.prior_backend_inventory.stat().st_size==invpin['bytes'],'Prior inventory size differs')
        inventory=read_inventory(args.prior_backend_inventory,invpin['sha256'])
        need(len(inventory)==r['selected_files'] and sum(row['bytes'] for row in inventory.values())==r['selected_bytes'],'Prior complete inventory counts differ')
        actual={product_id(n,'data') for n in inventory if product_id(n,'data') is not None}
        need(actual==ids and inventory_data_tree(inventory)==b['prior_backend_data_tree'],'Prior Git data tree/ID membership differs')
    return ids

SAME_RUN_SELECTION_FIELDS={'schema','repository','saved_commit','saved_root','run_id','run_attempt','workflow_file_commit','collector_checkout_commit','artifact_id','artifact_wrapper_sha256','saved_collection_sha256','collection_receipt_sha256','bounded_segment_eligible','whole_catalog_complete','collection_completion_verified','price_source_is_latest','workflow_run_completion_claimed','authenticated_context_verified','publication_authorized','scope','evidence'}

def validate_selection_scope(selection, receipt_sha256):
    """Accept only the explicit completed or same-run assertion receipt contract."""
    need(type(selection) is dict,'Selection object required')
    schema=selection.get('schema')
    if schema=='boopa-reselected-saved-snapshot-v1':
        need(receipt_sha256=='73bfb6ec9ea497feed0bf7e3f2dff2f6c1b336ddb084ed1a0a837da039851460','Legacy completed selection requires exact known receipt commitment')
        return
    need(schema=='boopa-same-workflow-saved-selection-r2','Unsupported selection schema')
    need(set(selection)==SAME_RUN_SELECTION_FIELDS,'Closed same-run selection fields required')
    need(selection['repository']=='MametaroGG/booth-vrc-price-tracker','Same-run repository differs')
    need(all(selection[k] is False for k in ('workflow_run_completion_claimed','authenticated_context_verified','publication_authorized')),'Same-run assertions are not workflow completion/authentication/publication authority')
    need(all(type(selection[k]) is str and re.fullmatch('[1-9][0-9]*',selection[k]) for k in ('run_id','run_attempt','artifact_id')),'Same-run canonical IDs required')
    need(all(type(selection[k]) is str and re.fullmatch('[0-9a-f]{40}',selection[k]) for k in ('saved_commit','saved_root','workflow_file_commit','collector_checkout_commit')),'Same-run OIDs required')
    need(all(type(selection[k]) is str and SHA.fullmatch(selection[k]) for k in ('artifact_wrapper_sha256','saved_collection_sha256','collection_receipt_sha256')),'Same-run digest fields required')
    evidence=selection['evidence']
    need(type(evidence) is dict and set(evidence)=={'context.json','artifact.json','receipt.zip','collection_receipt.json','saved-commit.json','workflow.yml','saved-collection.json'},'Same-run exact evidence set required')
    for row in evidence.values():
        need(type(row) is dict and set(row)=={'bytes','sha256'} and type(row['bytes']) is int and row['bytes']>0 and type(row['sha256']) is str and SHA.fullmatch(row['sha256']),'Same-run evidence commitment invalid')
    for name,key in [('receipt.zip','artifact_wrapper_sha256'),('saved-collection.json','saved_collection_sha256'),('collection_receipt.json','collection_receipt_sha256')]:
        need(evidence[name]['sha256']==selection[key],'Same-run evidence linkage differs')

def run(args):
    source=args.source.absolute();helpers=args.helpers.absolute();candidate=args.prior_candidate.absolute();output=args.output.absolute()
    need(not output.exists() and not output.is_symlink(),'New preparation destination required')
    bootstrap=pinned(args.run_bindings,args.run_bindings_sha256)
    vs,vp,sp,charts,helper_hashes=load_helpers(helpers,bootstrap)
    b=sp.RunBindings(args.run_bindings,args.run_bindings_sha256)
    need(dict(b.data)==bootstrap,'Run bindings changed during bootstrap')
    COMMIT=b['price_source_commit'];ROOT=b['source_root_tree'];META=b['source_metadata_tree']
    ARCHIVE_RECEIPT=b['source_archive_receipt_sha256'];ARCHIVE=b['source_archive_sha256']
    SELECTION=b['selection_receipt_sha256'];QUARANTINE=b['quarantine_proof_sha256']
    DIAGNOSTIC=b['quarantine_diagnostic_sha256'];OVERLAY=b['latest_negative_overlay_sha256']
    IMPACT=b['latest_negative_impact_sha256'];SNAPSHOT=b['retained_snapshot_sha256']
    HELPER_FREEZE=b['consumer_freeze_sha256']
    receipt=pinned(source/'SOURCE-ARCHIVE-RECEIPT.json',ARCHIVE_RECEIPT)
    need(receipt['source_commit']==COMMIT and receipt['git_root']==ROOT and receipt['metadata_tree']==META and receipt['archive_sha256']==ARCHIVE,'Wrong saved source identity')
    need(receipt['source_semantic_preparation_complete'] is False and receipt['publication_acceptance'] is False,'Archive/source scope mismatch')
    selection=pinned(args.selection_receipt,SELECTION)
    validate_selection_scope(selection,SELECTION)
    need(selection['saved_commit']==COMMIT and selection['saved_root']==ROOT and selection['bounded_segment_eligible'] is True,'Saved selection differs')
    need(all(selection[k] is False for k in ('collection_completion_verified','whole_catalog_complete','price_source_is_latest')),'Selection three false flags required')
    for name,row in selection['evidence'].items():
        need(safe_name(name).name==name,'Unsafe selection evidence name')
        p=args.selection_receipt.parent/name;need(p.stat().st_size==row['bytes'] and hash_file(p)==row['sha256'],'Selection evidence changed')
    inventory=read_inventory(source/'selected-inventory.jsonl',receipt['outputs']['selected-inventory.jsonl']['sha256'])
    need(len(inventory)==receipt['selected_files'] and sum(r['bytes'] for r in inventory.values())==receipt['selected_bytes'],'Source inventory counts differ')
    source_root=source/'selected';assert_closure(source_root,inventory)
    backend={product_id(n,'data') for n in inventory if product_id(n,'data') is not None}
    metadata={product_id(n,'meta') for n in inventory if product_id(n,'meta') is not None}
    need(backend==metadata,'Saved backend/metadata exact coverage differs')
    need(len(backend)==receipt['backend_product_count'] and len(metadata)==receipt['metadata_product_count'],'Archive product counts differ from exact inventory')
    for key,ids in [('backend-product-ids.private.json',backend),('metadata-product-ids.private.json',metadata)]:
        array=pinned(source/key,receipt['outputs'][key]['sha256']);need(id_list(array)==ids,'Archive ID membership mismatch')
    prior_ids=validate_prior_backend(args,b)
    need(prior_ids<=backend,'Prior backend products disappeared')
    retained=vp.read_retained_exclusions(candidate,SNAPSHOT);manifest=pinned(candidate/'snapshot-manifest.json',SNAPSHOT)
    prior_visible,prior_search_pins=prior_public(candidate,manifest,vs.exact_read,vs.open_directory)
    need(not(prior_visible&retained['ids']) and prior_visible|retained['ids']==prior_ids,'Prior public plus hidden set differs from independently proven prior backend')
    qraw=pinned(args.quarantine,QUARANTINE);diag=pinned(args.diagnostic,DIAGNOSTIC)
    need(qraw['diagnostic_receipt_sha256']==DIAGNOSTIC and diag['source_commit']==COMMIT and diag['outside_floor_conflicts']==0,'Quarantine diagnostic differs')
    need(qraw['entries']==[{k:v for k,v in row.items() if k!='prior_floor_member'} for row in diag['conflicts']],'Quarantine entries differ from new diagnostic')
    oraw=pinned(args.overlay,OVERLAY);impact=pinned(args.impact,IMPACT)
    need(oraw['impact_receipt_sha256']==IMPACT and sorted(e['id'] for e in oraw['entries'])==impact['additional_exclusion_ids'],'Overlay differs from complete latest impact')
    need(oraw['source_commit']==impact['source_commit'] and oraw['metadata_tree']==impact['source_metadata_tree'],'Overlay source identity differs')
    fd=vs.open_directory(source_root)
    try:
        collection_raw=exact_source(vs.exact_read,fd,inventory['data/collection_receipt.json'])
        need(digest(collection_raw)==selection['collection_receipt_sha256'],'Actual saved collection receipt differs')
        collection=strict(collection_raw);stop=collection['stopped_at_ms'];need(type(stop) is int and stop>0,'Saved stop timestamp required')
        stopped=datetime.fromtimestamp(stop/1000,timezone.utc);as_of=stopped.astimezone(timezone(timedelta(hours=9))).date()
        with tempfile.TemporaryDirectory(prefix='.prepared-unaccepted-',dir=output.parent) as temporary:
            stage=Path(temporary);prepared=stage/'prepared';evidence=stage/'evidence';prepared.mkdir(mode=0o700);evidence.mkdir(mode=0o700)
            (prepared/'data').mkdir();(prepared/'tracker_meta').mkdir()
            hashes={};metadata_hashes={}
            for name,row in inventory.items():
                if name.startswith('meta/') or product_id(name,'data') is None:
                    raw=exact_source(vs.exact_read,fd,row)
                    if name.endswith('.json'):strict(raw)
                    target='tracker_meta/'+name[5:] if name.startswith('meta/') else name
                    write_raw(prepared,target,raw);hashes[target]=row['sha256']
                    if name.startswith('meta/'):metadata_hashes[target]=row['sha256']
            quarantine=sp.Quarantine(args.quarantine,QUARANTINE,retained,run_bindings=b);overlay=sp.LatestNegativeOverlay(args.overlay,OVERLAY,retained,run_bindings=b)
            observed=overlay.observation_binding
            if observed is not None:
                need(impact.get('latest_negative_observation_sha256')==observed['observation_sha256'] and impact.get('latest_negative_observation_upper_jst_day')==observed['upper_jst_date'],'Latest impact observation binding differs')
                need(impact['source_commit']==observed['commit'] and impact['source_metadata_tree']==observed['metadata_tree'],'Latest impact observation identity differs')
            else:
                need('latest_negative_observation_sha256' not in impact and 'latest_negative_observation_upper_jst_day' not in impact,'Observation claim requires observed overlay')
            policy=vp.VisibilityPolicy(prepared/'tracker_meta',expected_hashes=metadata_hashes,generation_time=stopped,retained_exclusions=retained,quarantine=quarantine,latest_negative_overlay=overlay)
            count=sum(1 for _ in policy.iter_metadata());need(count==len(metadata),'Policy metadata coverage mismatch')
            expected_markers=pinned(source/'current-negative-markers.private.json',receipt['outputs']['current-negative-markers.private.json']['sha256'])
            need(set(policy.markers)=={m['id'] for m in expected_markers},'Current saved marker set differs')
            adapter=ChartReadAdapter(source_root,fd,inventory,prepared,vs.exact_read,policy,as_of)
            chart_rows=charts.generate_charts(source_root,verified_source=adapter)
            wanted={n for n in inventory if product_id(n,'data') is not None};need(adapter.consumed==wanted and policy.backend_ids==backend,'Full saved product pass incomplete')
            qresult=quarantine.finish();need(set(policy.hidden_ids)==backend&policy.excluded_ids(),'Hidden backend partition mismatch')
            need(policy.excluded_ids()==set(retained['ids'])|set(policy.markers)|set(overlay.ids),'Exclusion union mismatch')
            need(len(policy.excluded_ids())==impact['exclusion_union_count'],'Latest impact union differs')
            need(digest(vp.json_bytes(sorted(policy.excluded_ids())))==impact['exclusion_union_ids_sha256'],'Latest impact exact union commitment differs')
            need(set(overlay.ids)<=backend,'Unexpected metadata-only latest exclusions')
            for name in wanted:hashes[name]=inventory[name]['sha256']
            charts.validate_charts(chart_rows,source_root,verified_source=adapter)
            chart_raw=encoded(chart_rows);write_raw(prepared,'charts.json',chart_raw);hashes['charts.json']=digest(chart_raw)
            expected_hashes={('tracker_meta/'+name[5:] if name.startswith('meta/') else name):row['sha256'] for name,row in inventory.items()}
            expected_hashes['charts.json']=digest(chart_raw)
            need(hashes==expected_hashes,'Prepared inventory must map every selected source byte plus derived charts')
            need(adapter.maximum is not None and adapter.maximum<=as_of.isoformat(),'Saved source date range absent/future')
            ledger_summary=policy.write_evidence(evidence,adapter.minimum,adapter.maximum)
            new_ids=backend-prior_ids;visible=backend-policy.hidden_ids
            facts={'schema':'boopa-saved-source-preparation-facts-r1','backend_ids':sorted(backend),'metadata_ids':sorted(metadata),'prior_backend_ids':sorted(prior_ids),'new_backend_ids':sorted(new_ids),'saved_negative_ids':sorted(policy.markers),'retained_ids':sorted(retained['ids']),'latest_overlay_ids':sorted(overlay.ids),'exclusion_union_ids':sorted(policy.excluded_ids()),'visible_ids':sorted(visible),'new_visible_ids':sorted(new_ids&visible),'new_hidden_ids':sorted(new_ids&policy.hidden_ids),'source_date_counts':dict(adapter.date_counts),'product_date_counts':dict(adapter.product_dates),'new_product_first_dates':{i:adapter.first_dates[i] for i in sorted(new_ids)},'quarantine':qresult}
            facts_raw=encoded(facts);(evidence/'composition-facts.private.json').write_bytes(facts_raw)
            hashes=dict(sorted(hashes.items()));inventory_raw=encoded(hashes);(evidence/'prepared-inventory.json').write_bytes(inventory_raw)
            source_receipt={'schema':'boopa-new-saved-source-preparation-r2','run_bindings_sha256':b.sha256,'bindings_authority':'caller-pinned-inputs-not-provider-authentication','authenticated_context_verified':False,'workflow_run_completion_claimed':False,'publication_authorized':False,'status':'prepared-input-verified','source_commit':COMMIT,'source_root':ROOT,'metadata_tree':META,'archive_receipt_sha256':ARCHIVE_RECEIPT,'selection_receipt_sha256':SELECTION,'prior_backend_receipt_sha256':args.prior_backend_receipt_sha256,'prior_backend_ids_sha256':args.prior_backend_ids_sha256,'prior_snapshot_sha256':SNAPSHOT,'prior_search_shard_pins':prior_search_pins,'quarantine_proof_sha256':QUARANTINE,'quarantine_diagnostic_sha256':DIAGNOSTIC,'latest_negative_overlay_sha256':OVERLAY,'latest_negative_impact_sha256':IMPACT,'helper_freeze_sha256':HELPER_FREEZE,'helper_hashes':helper_hashes,'sourceprep_sha256':hash_file(Path(__file__)),'prepared_inventory_sha256':digest(inventory_raw),'composition_facts_sha256':digest(facts_raw),'visibility_ledger_sha256':ledger_summary['ledger_sha256'],'charts_sha256':digest(chart_raw),'prepared_files':len(hashes),'backend_products':len(backend),'metadata_products':len(metadata),'metadata_only_products':len(metadata-backend),'prior_backend_products':len(prior_ids),'new_backend_products':len(new_ids),'saved_negative_products':len(policy.markers),'retained_products':len(retained['ids']),'latest_additional_exclusions':len(overlay.ids),'exclusion_union':len(policy.excluded_ids()),'visible_products':len(visible),'new_visible_products':len(new_ids&visible),'source_min_date':adapter.minimum,'source_max_date':adapter.maximum,'history_observations':sum(adapter.date_counts.values()),'source_date_counts':dict(adapter.date_counts),'products_by_observation_date':dict(adapter.product_dates),'quarantine':qresult,'restored_products':0,'collection_completion_verified':False,'whole_catalog_complete':False,'price_source_is_latest':False,'independent_source_acceptance':False,'publication_acceptance':False,'old_ad021_restored':False}
            source_receipt['schema']='boopa-new-saved-source-preparation-r3'
            source_receipt['price_history_validation_as_of_date']=as_of.isoformat()
            source_receipt['latest_negative_observation']=None if observed is None else dict(observed)
            receipt_raw=encoded(source_receipt);(evidence/'source-preparation-receipt.json').write_bytes(receipt_raw)
            composition={'schema':'boopa-saved-snapshot-composition-r2','run_bindings_sha256':b.sha256,'price_source_commit':COMMIT,'metadata_source_commit':COMMIT,'source_receipt_sha256':digest(receipt_raw),'selection_receipt_sha256':SELECTION,'quarantine_proof_sha256':QUARANTINE,'latest_negative_overlay_sha256':OVERLAY,'retained_snapshot_sha256':SNAPSHOT,'collection_completion_verified':False,'whole_catalog_complete':False,'price_source_is_latest':False}
            completion={'schema':1,'status':'complete','fixture':False,'collection_id':COMMIT,'tracker_commit':COMMIT,'expected_date':adapter.maximum,'files':hashes,'saved_snapshot_composition':composition}
            completion_raw=encoded(completion);write_raw(prepared,'completion.json',completion_raw);completion_sha=digest(completion_raw)
            with vs.VerifiedSource(prepared,completion_sha,run_bindings=b) as verifier:
                verification=verifier.finish()
                need(verifier.saved_snapshot_composition is not None,'Prepared composition not accepted by frozen reader')
            assert_closure(source_root,inventory)
            need(hash_file(source/'SOURCE-ARCHIVE-RECEIPT.json')==ARCHIVE_RECEIPT,'Source receipt changed')
            for name,pin in helper_hashes.items():need(hash_file(helpers/name)==pin,'Helper changed during preparation')
            handoff={'schema':'boopa-new-saved-prepared-handoff-r2','authenticated_context_verified':False,'workflow_run_completion_claimed':False,'publication_authorized':False,'run_bindings_path':str(args.run_bindings.absolute()),'run_bindings_sha256':b.sha256,'prepared_root':str(output/'prepared'),'completion_sha256':completion_sha,'source_receipt_path':str(output/'evidence/source-preparation-receipt.json'),'source_receipt_sha256':digest(receipt_raw),'prepared_inventory_sha256':digest(inventory_raw),'facts_sha256':digest(facts_raw),'verification':verification,'quarantine_path':str(args.quarantine.absolute()),'quarantine_sha256':QUARANTINE,'overlay_path':str(args.overlay.absolute()),'overlay_sha256':OVERLAY,'status':'producer-verified-independent-final-readback-required','publication_acceptance':False}
            (stage/'prepared-handoff.json').write_bytes(encoded(handoff))
            need(not output.exists(),'Destination appeared');stage.rename(output)
    finally:os.close(fd)
    return handoff

def arguments():
    p=argparse.ArgumentParser()
    p.add_argument('--run-bindings',type=Path,required=True);p.add_argument('--run-bindings-sha256',required=True)
    p.add_argument('--prior-backend-inventory',type=Path)
    p.add_argument('--source',type=Path,default=BASE/'source');p.add_argument('--helpers',type=Path,default=WORK/'auto-update-connection-20261108/generator-r3')
    p.add_argument('--selection-receipt',type=Path,default=WORK/'rebuild-saved6126-20261108/selection-evidence/SELECTION-RECEIPT.json')
    p.add_argument('--prior-candidate',type=Path,default=WORK/'recovery-current003bd-20261108/restored/candidate')
    p.add_argument('--quarantine',type=Path,default=BASE/'QUARANTINE-PROOF.private.json');p.add_argument('--diagnostic',type=Path,default=BASE/'CONFLICT-DIAGNOSTIC.private.json')
    p.add_argument('--overlay',type=Path,default=BASE/'LATEST-NEGATIVE-OVERLAY.private.json');p.add_argument('--impact',type=Path,default=WORK/'latest-negative-b747-20261108/LATEST-NEGATIVE-IMPACT-V2.json')
    p.add_argument('--prior-backend-ids',type=Path,required=True);p.add_argument('--prior-backend-ids-sha256',required=True)
    p.add_argument('--prior-backend-receipt',type=Path,required=True);p.add_argument('--prior-backend-receipt-sha256',required=True)
    p.add_argument('--output',type=Path,required=True)
    return p.parse_args()

if __name__=='__main__':print(json.dumps(run(arguments()),sort_keys=True))
