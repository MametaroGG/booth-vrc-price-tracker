"""New saved6126 policy. Pinned assertions are not collection/publication authority."""
import hashlib
import re
from pathlib import Path
from types import MappingProxyType

PRICE_COMMIT='6126cf5baa0d04869b5e2a6b8fc0f0345df58756'
LATEST_COMMIT='b74706ee84d3059bcc54ed230912fa5b7f397819'
LATEST_META='6be82e9acf028bd185144a322f27bc4955be82c3'
FLOOR='003bd3894f0567609a54e2b81266a2bc29853ef920a9b97c59aa81c476cbbdde'
FALSE_FIELDS=('collection_completion_verified','whole_catalog_complete','price_source_is_latest')
PINS=('source_receipt_sha256','selection_receipt_sha256','quarantine_proof_sha256','latest_negative_overlay_sha256','retained_snapshot_sha256')
FIELDS={'schema','price_source_commit','metadata_source_commit',*FALSE_FIELDS,*PINS}

def fail(test,message):
    if not test:raise ValueError(message)

def digest(value,n=64):return type(value) is str and re.fullmatch('[0-9a-f]{'+str(n)+'}',value) is not None

RUN_FIELDS={'schema','source_repository','publication_repository','expected_public_parent_commit','price_source_commit','metadata_source_commit','source_root_tree','source_metadata_tree','source_archive_receipt_sha256','selection_receipt_sha256','retained_snapshot_sha256','retained_lists_sha256','retained_ids_sha256','latest_negative_source_commit','latest_negative_metadata_tree','latest_negative_impact_sha256','quarantine_proof_sha256','quarantine_diagnostic_sha256','latest_negative_overlay_sha256',*FALSE_FIELDS,'authority','source_archive_sha256','prior_backend_receipt_kind','prior_backend_receipt_sha256','prior_backend_ids_sha256','prior_backend_source_commit','prior_backend_root_tree','prior_backend_data_tree','consumer_freeze_sha256','charts_selector_sha256','varutil_sha256'}
RUN_OIDS=('prior_backend_source_commit','prior_backend_root_tree','prior_backend_data_tree','expected_public_parent_commit','price_source_commit','metadata_source_commit','source_root_tree','source_metadata_tree','latest_negative_source_commit','latest_negative_metadata_tree')
RUN_DIGESTS=('source_archive_sha256','prior_backend_receipt_sha256','prior_backend_ids_sha256','consumer_freeze_sha256','charts_selector_sha256','varutil_sha256','source_archive_receipt_sha256','selection_receipt_sha256','retained_snapshot_sha256','retained_lists_sha256','retained_ids_sha256','latest_negative_impact_sha256','quarantine_proof_sha256','quarantine_diagnostic_sha256','latest_negative_overlay_sha256')

class RunBindings:
    """Externally pinned assertions only. Sourceprep validates the underlying evidence."""
    __slots__=('data','sha256')
    def __init__(self,path,pin):
        v=read_pinned(path,pin)
        fail(set(v)==RUN_FIELDS and v['schema']=='boopa-saved-run-bindings-r2','Closed run bindings required')
        fail(v['source_repository']=='MametaroGG/booth-vrc-price-tracker' and v['publication_repository']=='MametaroGG/boopadb','Run repository scope differs')
        fail(all(digest(v[k],40) for k in RUN_OIDS) and all(digest(v[k]) for k in RUN_DIGESTS),'Run identity/pins invalid')
        fail(v['prior_backend_receipt_kind'] in ('boopa-prior-backend-git-inventory-r1','boopa-rebuilt-saved-source-archive-v1'),'Unsupported prior backend receipt kind')
        fail(v['price_source_commit']==v['metadata_source_commit'],'This saved profile requires same-commit price/display metadata')
        fail(all(v[k] is False for k in FALSE_FIELDS),'Run three false flags required')
        fail(v['authority']=='caller-pinned-inputs-not-provider-authentication','Run authority must remain caller assertion')
        object.__setattr__(self,'data',MappingProxyType(dict(v)))
        object.__setattr__(self,'sha256',pin)
    def __setattr__(self,name,value):raise AttributeError('Immutable run bindings')
    def __getitem__(self,key):return self.data[key]

def checked_bindings(value):
    fail(type(value) is RunBindings,'Explicit externally pinned RunBindings required')
    return value

def provenance(manifest,run_bindings=None):
    if 'saved_snapshot_composition' not in manifest:
        fail(run_bindings is None,'Bindings require explicit saved composition');return None
    v=manifest['saved_snapshot_composition']
    fail('historical_composition' not in manifest,'Mutually exclusive composition modes')
    fail(type(v) is dict,'Saved composition object required')
    if v.get('schema')=='boopa-saved-snapshot-composition-r2':
        b=checked_bindings(run_bindings)
        fail(set(v)==FIELDS|{'run_bindings_sha256'},'Closed saved r2 composition required')
        fail(v['run_bindings_sha256']==b.sha256,'Completion run bindings differ')
        for k in ('price_source_commit','metadata_source_commit','selection_receipt_sha256','quarantine_proof_sha256','latest_negative_overlay_sha256','retained_snapshot_sha256'):
            fail(v[k]==b[k],'Completion differs from run bindings: '+k)
        fail(manifest.get('tracker_commit')==b['price_source_commit'],'Prepared tracker commit differs')
    else:
        fail(run_bindings is None,'r2 bindings cannot downgrade to legacy composition')
        fail(set(v)==FIELDS and v['schema']=='boopa-saved-snapshot-composition-r1' and v['price_source_commit']==v['metadata_source_commit']==PRICE_COMMIT,'Fixed saved6126 identity required')
        fail(v['retained_snapshot_sha256']==FLOOR,'Exact legacy floor required')
    fail(all(v[k] is False for k in FALSE_FIELDS),'Three false flags required')
    fail(all(digest(v[k]) for k in PINS),'Saved composition pins required')
    return MappingProxyType(dict(v))

def read_pinned(path,pin):
    from verified_source import open_directory,exact_read,canonical_absolute
    from visibility_policy import strict_json
    import os
    fail(digest(pin),'External policy pin required')
    path=canonical_absolute(path);fd=open_directory(path.parent)
    try:raw=exact_read(fd,path.name,16*1024*1024)
    finally:os.close(fd)
    fail(hashlib.sha256(raw).hexdigest()==pin,'Policy commitment mismatch')
    value=strict_json(raw);fail(type(value) is dict,'Policy object required')
    return value

def floor_check(value,retained,run_bindings=None):
    fail(type(retained) is dict and type(retained.get('ids')) is frozenset,'Prior retained floor required')
    for k,r in [('prior_snapshot_sha256','snapshot_sha256'),('prior_lists_sha256','lists_sha256'),('prior_ids_sha256','ids_sha256')]:
        fail(digest(value[k]) and value[k]==retained[r],'Prior floor binding differs')
    from visibility_policy import json_bytes, canonical_id
    fail(all(canonical_id(x) for x in retained['ids']) and hashlib.sha256(json_bytes(sorted(retained['ids']))).hexdigest()==retained['ids_sha256'],'Floor IDs commitment differs')
    if run_bindings is None:fail(value['prior_snapshot_sha256']==FLOOR,'Exact003bd floor required')
    else:
        b=checked_bindings(run_bindings)
        for k,r in [('retained_snapshot_sha256','snapshot_sha256'),('retained_lists_sha256','lists_sha256'),('retained_ids_sha256','ids_sha256')]:
            fail(b[k]==retained[r],'Actual floor differs from run binding: '+k)

def entries(value,fields):
    from visibility_policy import canonical_id,canonical_date
    fail(type(value) is list,'Policy entries array required')
    result={}
    for row in value:
        fail(type(row) is dict and set(row)==fields,'Closed policy entry required')
        ident=row['id'];fail(canonical_id(ident) and ident not in result,'Unique canonical policy ID required')
        fail(type(row['status']) is int and row['status'] in (404,410),'Negative HTTP status required')
        canonical_date(row['fetched_at'])
        result[ident]=dict(row)
    fail(list(result)==sorted(result),'Canonical policy entry order required')
    return result

class Quarantine:
    def __init__(self,path,pin,retained,*,run_bindings=None):
        v=read_pinned(path,pin)
        fields={'schema','source_commit','prior_snapshot_sha256','prior_lists_sha256','prior_ids_sha256','diagnostic_receipt_sha256','entries'}
        fail(set(v)==fields,'Closed quarantine required')
        if run_bindings is None:
            fail(v['schema']=='boopa-saved-conflict-quarantine-r1' and v['source_commit']==PRICE_COMMIT,'Closed saved quarantine required')
        else:
            b=checked_bindings(run_bindings)
            fail(v['schema']=='boopa-saved-conflict-quarantine-r2' and v['source_commit']==b['price_source_commit'] and pin==b['quarantine_proof_sha256'] and v['diagnostic_receipt_sha256']==b['quarantine_diagnostic_sha256'],'Quarantine run binding mismatch')
        floor_check(v,retained,run_bindings);fail(digest(v['diagnostic_receipt_sha256']),'Diagnostic pin required')
        self.entries=entries(v['entries'],{'id','price_sha256','metadata_sha256','status','fetched_at','observations_total','observations_after_marker'})
        for ident,row in self.entries.items():
            fail(ident in retained['ids'],'Quarantine outside prior floor')
            fail(digest(row['price_sha256']) and digest(row['metadata_sha256']),'Quarantine leaf pins required')
            fail(type(row['observations_total']) is int and type(row['observations_after_marker']) is int and 0<row['observations_after_marker']<=row['observations_total'],'Quarantine counts invalid')
        self.pin=pin;self.consumed=set();self.path=path;self.retained=retained;self.run_bindings=run_bindings
    def check(self,record,raw,marker,total,after):
        ident=record['id'];row=self.entries.get(ident)
        fail(row is not None and ident not in self.consumed,'Unknown or duplicate quarantine conflict')
        fail(type(raw) is bytes and hashlib.sha256(raw).hexdigest()==row['price_sha256'],'Quarantine actual price hash differs')
        from visibility_policy import strict_json, json_bytes
        fail(json_bytes(strict_json(raw))==json_bytes(record),'Quarantine parsed record differs from actual bytes')
        fail(marker['sha256']==row['metadata_sha256'] and marker['status']==row['status'] and marker['fetched_at']==row['fetched_at'],'Quarantine marker differs')
        fail(total==row['observations_total'] and after==row['observations_after_marker'],'Quarantine observation counts differ')
        self.consumed.add(ident)
    def finish(self):
        fail(self.consumed==set(self.entries),'Unconsumed quarantine entries')
        return {'proof_sha256':self.pin,'ids':sorted(self.consumed),'availability_confirmed':False}
    def fresh(self):return Quarantine(self.path,self.pin,self.retained,run_bindings=self.run_bindings)

class LatestNegativeOverlay:
    def __init__(self,path,pin,retained,*,run_bindings=None):
        v=read_pinned(path,pin)
        fields={'schema','source_commit','metadata_tree','prior_snapshot_sha256','prior_lists_sha256','prior_ids_sha256','impact_receipt_sha256','entries'}
        pending_mode=v.get('schema')=='boopa-latest-negative-overlay-r4'
        observed_mode=v.get('schema') in ('boopa-latest-negative-overlay-r3','boopa-latest-negative-overlay-r4')
        if pending_mode:fields=fields|{'pending_metadata'}
        fail(set(v)==(fields|{'observation'} if observed_mode else fields),'Closed latest negative overlay required')
        self.observation_binding=None
        self.observation_upper_day=None
        if run_bindings is None:
            fail(v['schema']=='boopa-latest-negative-overlay-r1' and v['source_commit']==LATEST_COMMIT and v['metadata_tree']==LATEST_META,'Fixed legacy latest overlay required')
        else:
            b=checked_bindings(run_bindings)
            fail(v['schema'] in ('boopa-latest-negative-overlay-r2','boopa-latest-negative-overlay-r3','boopa-latest-negative-overlay-r4') and v['source_commit']==b['latest_negative_source_commit'] and v['metadata_tree']==b['latest_negative_metadata_tree'] and pin==b['latest_negative_overlay_sha256'] and v['impact_receipt_sha256']==b['latest_negative_impact_sha256'],'Latest negative run binding mismatch')
        floor_check(v,retained,run_bindings);fail(digest(v['impact_receipt_sha256']),'Latest impact pin required')
        if observed_mode:
            fail(run_bindings is not None,'Observed overlay requires explicit run binding')
            reference=v['observation']
            fail(type(reference) is dict and set(reference)=={'path','sha256'} and digest(reference['sha256']),'Closed observation reference required')
            name=reference['path']
            fail(type(name) is str and name and '\\' not in name and '\x00' not in name,'Observation path required')
            relative=Path(name)
            fail(not relative.is_absolute() and relative.as_posix()==name and all(part not in ('','.', '..') for part in relative.parts),'Observation must be a canonical relative path')
            from observation_validation import validate_observation
            from visibility_policy import canonical_date
            observation=validate_observation(Path(path).parent/relative,reference['sha256'],v['source_commit'],v['metadata_tree'])
            fail(observation['observation_sha256']==reference['sha256'] and observation['provider_authenticated'] is False,'Observation evidence is not provider authentication')
            self.observation_binding=MappingProxyType(dict(observation))
            self.observation_upper_day=canonical_date(observation['upper_jst_date'])

        self.entries=entries(v['entries'],{'id','path','sha256','git_blob','bytes','status','fetched_at'})
        for ident,row in self.entries.items():
            fail(ident not in retained['ids'],'Additional negative must not be represented as prior floor')
            fail(row['path']=='meta/'+ident[:3]+'/'+ident+'.json','Latest marker path differs')
            fail(digest(row['sha256']) and digest(row['git_blob'],40) and type(row['bytes']) is int and row['bytes']>0,'Latest marker identity invalid')
        self.retained=retained;self.pin=pin;self.ids=frozenset(self.entries);self.source_commit=v['source_commit'];self.metadata_tree=v['metadata_tree']
        self.pending_metadata=None;self.pending_ids=frozenset()
        if pending_mode:
            obj=v['pending_metadata']
            required={'schema','source_commit','source_root','source_archive_receipt_sha256','prior_backend_receipt_sha256','prior_backend_ids_sha256','prior_pending_ids_sha256','missing_ids','pending_ids','resolved_pending_ids'}
            fail(type(obj) is dict and set(obj)==required and obj['schema']=='boopa-pending-metadata-r1','Closed pending metadata proof required')
            for k,bk in [('source_commit','price_source_commit'),('source_root','source_root_tree'),('source_archive_receipt_sha256','source_archive_receipt_sha256'),('prior_backend_receipt_sha256','prior_backend_receipt_sha256'),('prior_backend_ids_sha256','prior_backend_ids_sha256')]:
                fail(obj[k]==b[bk],'Pending source binding differs: '+k)
            from visibility_policy import json_bytes,canonical_id
            previous=retained.get('pending_ids',frozenset())
            fail(type(previous) is frozenset and all(canonical_id(i) for i in previous),'Prior pending set')
            expected=hashlib.sha256(json_bytes(sorted(previous))).hexdigest()
            fail(obj['prior_pending_ids_sha256']==expected and retained.get('pending_ids_sha256',expected)==expected,'Prior pending commitment differs')
            for k in ('missing_ids','pending_ids','resolved_pending_ids'):
                ids=obj[k];fail(type(ids) is list and all(canonical_id(i) for i in ids) and ids==sorted(set(ids)),'Canonical pending sets')
            fail(set(obj['pending_ids'])<=set(obj['missing_ids']) and not(set(obj['pending_ids'])&(set(retained['ids'])|set(self.ids))),'Pending is separate from HTTP/floor')
            fail(set(obj['resolved_pending_ids'])<=set(previous) and not(set(obj['resolved_pending_ids'])&set(obj['missing_ids'])),'Pending resolution partition')
            self.pending_metadata=dict(obj);self.pending_ids=frozenset(obj['pending_ids'])
    def validate_population(self,backend,metadata,success_ids,http_and_retained,current_marker_ids=()):
        if self.pending_metadata is None:return
        backend=set(backend);metadata=set(metadata);h=set(http_and_retained);previous=set(self.retained.get('pending_ids',()))
        obj=self.pending_metadata;missing=backend-metadata
        fail(metadata<=backend and missing==set(obj['missing_ids']),'Actual missing metadata differs')
        fail(self.pending_ids==missing-h and not(self.pending_ids&h),'Actual pending partition differs')
        fail((previous&metadata)<=set(success_ids)|set(current_marker_ids),'Unknown metadata cannot resolve prior pending')
        resolved=(previous&metadata)-h
        fail(resolved==set(obj['resolved_pending_ids']) and resolved<=set(success_ids),'Pending resolution requires success')

    def binding(self):
        result={'proof_sha256':self.pin,'source_commit':self.source_commit,'metadata_tree':self.metadata_tree,'ids':sorted(self.ids),'scope':'separate-latest-negative-overlay-not-display-metadata'}
        if self.observation_binding is not None:
            result['negative_observation']={k:self.observation_binding[k] for k in ('observation_sha256','provider_observation_upper_utc','upper_jst_date','provider_authenticated')}
        if self.pending_metadata is not None:result['pending_metadata']=self.pending_metadata
        return result
