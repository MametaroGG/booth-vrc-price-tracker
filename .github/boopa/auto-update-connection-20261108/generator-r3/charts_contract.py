"""Validate explicit charts against frozen raw source; no execution of input code."""
from datetime import date
import json
import math


def validate_charts(charts, inputs, fixture=False, verified_source=None, excluded_ids=None, allow_empty=False):
    if type(allow_empty) is not bool or (allow_empty and excluded_ids is None):
        raise ValueError('Empty charts require explicit state exclusions')
    excluded_ids = _exclusion_set(excluded_ids)
    if not isinstance(charts, list) or (not charts and not fixture and not allow_empty):
        raise ValueError('Nonempty chart array required (empty only for explicit fixtures)')
    seen=set()
    for chart in charts:
        if not isinstance(chart,dict): raise ValueError('Chart must be an object')
        ident=chart.get('id')
        if not isinstance(ident,str) or not ident.isascii() or not ident.isdecimal() or ident.startswith('0') or ident in seen:
            raise ValueError('Invalid/duplicate chart ID')
        seen.add(ident)
        if ident in excluded_ids:raise ValueError('Excluded product appears in chart: '+ident)
        path=inputs/'data'/ident[:3]/(ident+'.json')
        if verified_source:
            verified_source.relative(path)
        elif not path.is_file(): raise ValueError('Chart ID absent from frozen snapshot: '+ident)
        source=verified_source.read_json(path) if verified_source else json.loads(path.read_text())
        if source.get('id')!=ident or chart.get('name')!=source.get('name') or not isinstance(chart.get('name'),str) or not chart['name']:
            raise ValueError('Chart name/ID differs from frozen source')
        variations=chart.get('variations')
        if not isinstance(variations,dict) or not variations: raise ValueError('Chart variations required')
        for key,series in variations.items():
            raw=(source.get('variations') or {}).get(key)
            if not isinstance(key,str) or not isinstance(raw,list) or not raw: raise ValueError('Chart variation absent from source')
            rows=series.get('p') if isinstance(series,dict) else series
            if not isinstance(rows,list) or not rows: raise ValueError('Nonempty chart point rows required')
            allowed={(r['date'],r['price'],int(bool(r.get('is_sale')))) for r in raw}
            previous=''
            for row in rows:
                if not isinstance(row,list) or len(row) not in (3,4): raise ValueError('Chart row must be date/price/sale[/outlier]')
                day,price,sale=row[:3]
                if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day or day<previous:
                    raise ValueError('Invalid/unsorted chart date')
                if type(price) not in (int,float) or not math.isfinite(price) or price<0 or type(sale) is not int or sale not in (0,1):
                    raise ValueError('Invalid chart price/sale')
                if len(row)==4 and (type(row[3]) is not int or row[3] not in (0,1)):
                    raise ValueError('Invalid chart outlier flag')
                if (day,price,sale) not in allowed: raise ValueError('Chart point differs from frozen source')
                previous=day
            if rows[0][0]!=min(r['date'] for r in raw) or rows[-1][0]!=max(r['date'] for r in raw):
                raise ValueError('Chart endpoints differ from frozen source')
            if isinstance(series,dict) and (series.get('d')!=len(raw) or series.get('sd')!=sum(bool(r.get('is_sale')) for r in raw)):
                raise ValueError('Chart history counts differ from frozen source')
            if isinstance(series,dict) and 'average_source' in series:
                from varutil import average_source, tag_outliers
                full_rows=tag_outliers([[p['date'],p['price'],int(bool(p.get('is_sale')))] for p in sorted(raw,key=lambda p:p['date'])])
                a=series['average_source']
                if not isinstance(a,dict) or set(a)!={'sum','count'} or type(a['sum']) not in (int,float) or type(a['count']) is not int or a != average_source(full_rows):
                    raise ValueError('Chart average statistics differ from frozen source')
    return charts


def enrich_bootstrap(payload, inputs, fixture=False, verified_source=None):
    """Retain original sale/drop embedded variation readiness using real helper."""
    if fixture:
        return payload
    try:
        from varutil import thin_vars_from_item
    except ImportError as exc:
        raise ValueError('Production bootstrap enrichment requires reviewed varutil.py; no silent vars removal') from exc
    for record in payload.get('on_sale',[])[:12] + [r for r in payload.get('drops',[]) if r.get('date','') >= '2026-10-02'][:10]:
        ident=record['id'];path=inputs/'data'/ident[:3]/(ident+'.json')
        raw=verified_source.read_json(path) if verified_source else json.loads(path.read_text())
        variations=thin_vars_from_item(raw)
        if variations: record['vars']=variations
    return payload


def _exclusion_set(value):
    if value is None:return frozenset()
    if type(value) not in (set, frozenset) or any(type(i) is not str or not i.isascii() or not i.isdecimal() or i.startswith('0') for i in value):
        raise ValueError('Explicit canonical chart exclusion set required')
    return frozenset(value)

def generate_charts(inputs, verified_source=None, excluded_ids=None):
    """Original prototype chart selection/scoring over frozen data, real varutil."""
    from varutil import thin_vars_from_item
    excluded_ids = _exclusion_set(excluded_ids)
    candidates=[];records={}
    paths = verified_source.paths('data', products_only=True) if verified_source else (inputs/'data').glob('*/*.json')
    for path in paths:
        d=verified_source.read_json(path) if verified_source else json.loads(path.read_text());best=[]
        # Full raw read/validation happens before this ranking-only exclusion.
        if d.get('id') in excluded_ids:continue
        for series in (d.get('variations') or {}).values():
            if isinstance(series,list) and len(series)>len(best):best=series
        if not best:continue
        series=sorted(best,key=lambda p:p['date']);distinct=len({p['price'] for p in series})
        transitions=sum(1 for i in range(1,len(series)) if series[i].get('is_sale') and not series[i-1].get('is_sale'))
        if distinct>=3 and len(series)>=60:
            score=distinct*2+transitions*3+len(series)/50.0
            candidates.append((score,d['id']));records[d['id']]=d
            # Only the final top three are consumed. Keep exactly that ranking
            # prefix (including reverse score/ID ties), not every raw history.
            candidates.sort(reverse=True)
            del candidates[3:]
            retained={ident for _,ident in candidates}
            for ident in list(records):
                if ident not in retained: del records[ident]
    candidates.sort(reverse=True)
    from varutil import convert_raw_variations
    charts=[]
    for _,ident in candidates[:3]:
        record=records[ident]
        variations=thin_vars_from_item(record)
        if not variations:
            # Original scanner emitted {} for one-variation chart candidates.
            # Keep its selected ID/score, but serialize valid exact history rather
            # than rerank/drop the candidate or pass an unusable chart to the UI.
            raw={name:[[p['date'],p['price'],int(bool(p.get('is_sale')))] for p in sorted(series,key=lambda p:p['date'])]
                 for name,series in (record.get('variations') or {}).items() if isinstance(series,list) and len(series)>=2}
            variations=convert_raw_variations(raw)
        charts.append({'id':ident,'name':record.get('name',''),'variations':variations})
    return charts

def eligible_visible_ids(inputs, verified_source, excluded_ids):
    """Independent full-input selector eligibility, never only selected charts."""
    excluded_ids = _exclusion_set(excluded_ids)
    eligible=set()
    paths=verified_source.paths('data',products_only=True) if verified_source else (inputs/'data').glob('*/*.json')
    for path in paths:
        record=verified_source.read_json(path) if verified_source else json.loads(path.read_text())
        ident=record.get('id');best=[]
        if ident in excluded_ids:continue
        for rows in (record.get('variations') or {}).values():
            if isinstance(rows,list) and len(rows)>len(best):best=rows
        if len(best)>=60 and len({r['price'] for r in best})>=3:eligible.add(ident)
    return eligible

def validate_chart_population(charts, eligible):
    ids=[c.get('id') for c in charts]
    if len(ids)!=len(set(ids)) or not set(ids)<=eligible or len(ids)!=min(3,len(eligible)):
        raise ValueError('Chart eligible population mismatch')
