"""Re-derive the four existing display exceptions, never availability or authority."""
import hashlib,json,math,sys
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'generator-r3'))
from verified_source import strict_json
from varutil import tag_outliers
IDS=('8328795','8350004','8422085','8372235')
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def derive(source,hidden):
    entries={};checks={}
    for ident in IDS:
        if ident in hidden:
            checks[ident]={'status':'NOT-APPLICABLE','reason':'hidden'};continue
        name=f'data/{ident[:3]}/{ident}.json';meta=f'tracker_meta/{ident[:3]}/{ident}.json'
        if name not in source.hashes or meta not in source.hashes:
            checks[ident]={'status':'NOT-APPLICABLE','reason':'source-or-metadata-absent'};continue
        raw=source.read_bytes(source.root/name);mr=source.read_bytes(source.root/meta);d,m=strict_json(raw),strict_json(mr)
        if d.get('id')!=ident or m.get('id')!=ident:raise ValueError('Presentation ID mismatch')
        check={'source_sha256':hashlib.sha256(raw).hexdigest(),'metadata_sha256':hashlib.sha256(mr).hexdigest()};checks[ident]=check
        if m.get('unavailable') is True and type(m.get('status')) is int and m['status'] in (404,410):
            check.update(status='NOT-APPLICABLE',reason='current-negative');continue
        if type(d.get('variations')) is not dict:raise ValueError('Presentation variations invalid')
        histories=[(k,v) for k,v in d['variations'].items() if type(v) is list and v]
        if not histories:check.update(status='NOT-APPLICABLE',reason='no-history');continue
        key,series=max(histories,key=lambda kv:len(kv[1]));ordered=sorted(series,key=lambda p:p['date'])
        for p in ordered:
            if type(p['price']) not in (int,float) or not math.isfinite(p['price']) or p['price']<0 or date.fromisoformat(p['date']).isoformat()!=p['date']:raise ValueError('Presentation observation invalid')
        rows=tag_outliers([[p['date'],p['price'],1 if p.get('is_sale') else 0] for p in ordered]);base=max(r[1] for r in rows);matched=[r for r in rows if r[1]==base]
        if not all(len(r)>3 and r[3]==1 for r in matched):check.update(status='NOT-APPLICABLE',reason='comparison-not-outlier');continue
        entries[ident]={'representative_name':key,'observed_at':rows[-1][0],'current':rows[-1][1],'comparison_base':base,'comparison_outlier':True,'variant_coverage':'unknown','proof_basis':'exact-saved-source-tagged-representative-history','source_sha256':check['source_sha256']}
        check.update(status='PASS',comparison_occurrences=len(matched))
    proof={'schema':1,'entries':entries};raw=(json.dumps(proof,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
    return proof,raw,{'checks':checks,'file_sha256':hashlib.sha256(raw).hexdigest(),'canonical_sha256':hashlib.sha256(canonical(proof)).hexdigest(),'source_completion_sha256':source.completion_sha256}
