"""Pinned current-price projection. Does not mutate raw price histories.

No default file and no hard-coded product override. Caller must supply an
approved package and expected package digest, plus explicit generation time.
"""
import hashlib,json
from datetime import datetime,timezone,timedelta
from selected_price_selector import select_price

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def dt(value):
    x=datetime.fromisoformat(value.replace('Z','+00:00'))
    if x.tzinfo is None:raise ValueError('timezone required')
    return x

class CurrentPriceProjection:
    def __init__(self,package,expected_sha256,as_of,evidence_artifacts):
        if digest(package)!=expected_sha256:raise ValueError('projection package hash mismatch')
        if package.get('schema')!=1:raise ValueError('projection schema mismatch')
        self.package_sha256=expected_sha256
        self.evidence_artifacts=evidence_artifacts
        self.as_of=dt(as_of);self.records=package['records'];self.applied={}
        if not isinstance(self.records,dict):raise ValueError('projection records required')
    def for_item(self,raw):
        item=str(raw['id']);proof=self.records.get(item)
        if proof is None:return None
        if proof['raw_record_sha256']!=digest(raw):raise ValueError('projection raw changed: '+item)
        snap=proof['snapshot'];observed=dt(snap['observed_at']);expires=dt(proof['expires_at'])
        source_hash=snap['source_content_sha256']
        artifact=self.evidence_artifacts.get(source_hash)
        if not isinstance(artifact,bytes) or hashlib.sha256(artifact).hexdigest()!=source_hash:raise ValueError('source evidence artifact missing/mismatched')
        if not observed<=self.as_of<expires:raise ValueError('projection stale/future: '+item)
        if not 0<(expires-observed).total_seconds()<=86400:raise ValueError('projection freshness exceeds24h')
        if snap['item_id']!=item:raise ValueError('projection item mismatch')
        for evidence in proof['evidence']:
            if evidence.get('seller_declared_start') and self.as_of<dt(evidence['seller_declared_start']):raise ValueError('promotion not started')
            if evidence.get('seller_declared_end') and self.as_of>dt(evidence['seller_declared_end']):raise ValueError('promotion ended')
            if evidence['source_content_sha256']!=snap['source_content_sha256']:raise ValueError('evidence hash mismatch')
        out=select_price(snap,proof['evidence'],proof.get('legacy_variant_id'))
        if out['selected_sale'] is not True:return None
        key=raw.get('variation_keys',{}).get(out['selected_variant_id'])
        if not key:raise ValueError('selected variant not bound to raw history')
        series=raw.get('variations',{}).get(key)
        if not series:raise ValueError('selected series missing')
        latest=max(series,key=lambda p:p['date'])
        if latest['price']!=out['selected_price']:raise ValueError('selected current price differs from raw latest')
        evidence=next(e for e in proof['evidence'] if e['evidence_id']==out['selected_sale_evidence_id'])
        regular=evidence.get('regular_price')
        if type(regular) is not int or regular<=out['selected_price']:raise ValueError('unverified comparison price')
        legacy_series=max(raw['variations'].values(),key=len)
        legacy_prices=[p['price'] for p in sorted(legacy_series,key=lambda p:p['date'])]
        out['legacy']={'cur':legacy_prices[-1],'base':max(legacy_prices),'lowest':min(legacy_prices)}
        out.update(cur=out['selected_price'],base=regular,lowest=min(p['price'] for p in series),sale=True,on_sale=True,selected_variant_key=key,expires_at=proof['expires_at'],raw_record_sha256=proof['raw_record_sha256'])
        out['observed_display_variant_id']=out['selected_variant_id']
        out['observed_display_variant_key']=out['selected_variant_key']
        out['observed_display_price']=out['cur']
        out['observed_display_at']=snap['observed_at']
        sorted_series=sorted(series,key=lambda point:point['date'])
        stride=max(1,len(sorted_series)//24)
        out['observed_display_spark']=[[p['date'],p['price']] for i,p in enumerate(sorted_series) if i%stride==0 or i==len(sorted_series)-1]
        accepted=[proof['raw_record_sha256']]
        for binding in proof.get('runtime_snapshot_bindings',[]):
            if dt(binding['observed_at'])>self.as_of:raise ValueError('runtime snapshot captured in future')
            artifact=self.evidence_artifacts.get(binding['artifact_sha256'])
            if not isinstance(artifact,bytes) or hashlib.sha256(artifact).hexdigest()!=binding['artifact_sha256']:raise ValueError('runtime snapshot artifact mismatch')
            newer=json.loads(artifact)
            if digest(newer)!=binding['record_sha256'] or newer.get('id')!=raw['id']:raise ValueError('runtime snapshot identity mismatch')
            if {k:v for k,v in newer.items() if k!='variations'}!={k:v for k,v in raw.items() if k!='variations'}:raise ValueError('runtime snapshot metadata changed')
            if set(newer['variations'])!=set(raw['variations']):raise ValueError('runtime snapshot variant set changed')
            for key,old_series in raw['variations'].items():
                recent=newer['variations'][key]
                if recent[:len(old_series)]!=old_series:raise ValueError('runtime snapshot changed historical prefix')
                if old_series and any(p['date']<=max(q['date'] for q in old_series) for p in recent[len(old_series):]):raise ValueError('runtime snapshot is not append-only')
                if any(p['date']>self.as_of.astimezone(timezone(timedelta(hours=9))).date().isoformat() for p in recent[len(old_series):]):raise ValueError('runtime snapshot observation is in future')
            for variant in snap['variants']:
                key=newer.get('variation_keys',{}).get(variant['id']) or proof.get('identity_bindings',{}).get(variant['id'])
                if not key or key not in newer['variations']:raise ValueError('runtime snapshot SKU binding missing')
                if max(newer['variations'][key],key=lambda p:p['date'])['price']!=variant['price']:raise ValueError('runtime snapshot price differs from official observation')
            accepted.append(binding['record_sha256'])
        out['accepted_raw_record_sha256']=list(dict.fromkeys(accepted))
        self.applied[item]=out
        return out
