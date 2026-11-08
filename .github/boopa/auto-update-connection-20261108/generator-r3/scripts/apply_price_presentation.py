#!/usr/bin/env python3
"""Presentation-only existing-outlier evidence integration, after discount guard."""
from pathlib import Path
import json,re,sys
HELPERS=r'''// PRICE_PRESENTATION_HELPERS_START
function comparisonSuppressed(base, cur, id){
  const e = PRICE_PRESENTATION.entries[String(id)];
  return !!(e && e.comparison_outlier === true && Number.isFinite(base) && Number.isFinite(cur) && e.comparison_base === base && e.current === cur);
}
function comparisonMarkup(base, cur, id, html){ return comparisonSuppressed(base, cur, id) ? "" : html; }
function freeAvailabilityLabel(id){
  const e = PRICE_PRESENTATION.entries[String(id)], v = e && e.current_variants;
  if (!v || v.verified_current !== true || !Array.isArray(v.items) || !v.items.length || !/^\d{4}-\d{2}-\d{2}$/.test(v.observed_at || "") || v.observed_at !== e.observed_at) return null;
  if (v.items.some(x => !x || typeof x.id !== "string" || !x.id) || new Set(v.items.map(x => x.id)).size !== v.items.length) return null;
  const known = v.items.filter(x => x.available === true && Number.isFinite(x.price) && x.price >= 0);
  const free = known.filter(x => x.price === 0).length, paid = known.filter(x => x.price > 0).length;
  const labels = {ja:["無料","全て無料","一部無料"],en:["Free","All free","Partly free"],ko:["무료","모두 무료","일부 무료"],"zh-Hans":["免费","全部免费","部分免费"],"zh-Hant":["免費","全部免費","部分免費"]};
  const l = labels[typeof LANG === "string" ? LANG : "ja"] || labels.ja;
  if (free && paid) return l[2];
  if (v.complete !== true || v.items.some(x => x.available !== true && x.available !== false) || v.items.some(x => x.available === true && (!Number.isFinite(x.price) || x.price < 0))) return null;
  if (free && !paid) return known.length === 1 ? l[0] : l[1];
  return null;
}
function freePriceLabel(id){ return freeAvailabilityLabel(id) || tr("free"); }
// PRICE_PRESENTATION_HELPERS_END
'''

NOTE_REPLACEMENTS={'価格は代表バリエーションの観測値です。販売内容はBOOTHで確認してください。': '各バリエーションの価格は、価格推移で確認できます。', 'Prices are observed values for a representative variation. Check BOOTH for available options.': 'See price history for each variation’s price.', '가격은 대표 옵션의 관측값입니다. 판매 내용은 BOOTH에서 확인하세요.': '각 옵션의 가격은 가격 이력에서 확인할 수 있습니다.', '价格为代表款式的观测值。请在BOOTH确认销售内容。': '各款式的价格可在价格历史中查看。', '價格為代表款式的觀測值。請在BOOTH確認販售內容。': '各款式的價格可在價格歷史中查看。'}

def transform(s,evidence):
    for old,new in NOTE_REPLACEMENTS.items():s=s.replace(old,new)
    inherited = 'PRICE_PRESENTATION_HELPERS_START' in s
    protected=[]
    if inherited:
        # Older guard runs before this phase and may append its standalone helper.
        s=re.sub(r'<script>\n// DISCOUNT_DISPLAY_GUARD_START.*?// DISCOUNT_DISPLAY_GUARD_END\n</script>\n','',s,flags=re.S)
        s=re.sub(r'<script id="price-presentation-proof">.*?</script>\n?','',s,flags=re.S)
        def protect(m):
            protected.append(m[0]);return '__PRICE_MARKUP_'+str(len(protected)-1)+'__'
        s=re.sub(r'\$\{comparisonMarkup\([^`]+`.*?`\)\}',protect,s)
    if 'DISCOUNT_DISPLAY_GUARD_START' not in s:return s
    if not inherited:s=s.replace('// DISCOUNT_DISPLAY_GUARD_START', HELPERS+'// DISCOUNT_DISPLAY_GUARD_START',1)
    s=s.replace('function displayDiscountPercent(base, cur){','function displayDiscountPercent(base, cur, id){\n  if (comparisonSuppressed(base, cur, id)) return null;')
    s=s.replace('function discountBadge(base, cur, cls, minus = "-"){','function discountBadge(base, cur, cls, minus = "-", id){\n  if (comparisonSuppressed(base, cur, id)) return `<span class="${cls}">${tr("chip_onsale")}</span>`;')
    s=s.replace('const pct = displayDiscountPercent(base, cur);','const pct = displayDiscountPercent(base, cur, id);')
    s=re.sub(r'displayDiscountPercent\((\w+)\.base, \1\.cur\)',r'displayDiscountPercent(\1.base, \1.cur, \1.id)',s)
    # Discount badges get identity but leave sorting percentages untouched.
    s=re.sub(r'discountBadge\((\w+)\.base, (\w+\.cur|cur), "([^"]+)"(?:, "(−)")?\)',lambda m:'discountBadge('+m[1]+'.base, '+m[2]+', "'+m[3]+'", "'+(m[4] or '-')+'", '+m[1]+'.id)',s)
    s=s.replace('discountBadge(x.from, x.to, "discst")','discountBadge(x.from, x.to, "discst", "-", x.id)')
    s=s.replace('function clusterCB(cur, base, sale, atLowest){','function clusterCB(cur, base, sale, atLowest, id){')
    s=s.replace('discountBadge(base, cur, "discst")','discountBadge(base, cur, "discst", "-", id)')
    s=re.sub(r'clusterCB\((\w+)\.cur, \1\.base, ([^,]+), \1\.at_lowest\)',lambda m:'clusterCB('+m[1]+'.cur, '+m[1]+'.base, '+m[2]+', '+m[1]+'.at_lowest, '+m[1]+'.id)',s)
    s=s.replace('clusterCB(0, x.base, x.on_sale !== false, true)','clusterCB(0, x.base, x.on_sale !== false, true, x.id)')
    # All struck comparison-price spans, including nested wasx/ww spans.
    pat=r'<span class="(?:was|swas|pwas)(?:\$\{wCls\((?:\w+\.)?base\)\})?">(?:<span class="(?:wasx|ww)">\$\{yen\(((?:\w+\.)?base)\)\}</span>|\$\{yen\(((?:\w+\.)?base)\)\})</span>'
    def strike(m):
        base=m[1] or m[2];obj=base[:-5] if '.' in base else None;cur='cur' if obj in (None,'now') else obj+'.cur';ident='id' if obj is None else obj+'.id'
        return '${comparisonMarkup('+base+', '+cur+', '+ident+', `'+m[0]+'`)}'
    s=re.sub(pat,strike,s)
    # Drop page compares from/to rather than a normal price; match only same exact proof.
    s=s.replace('<span class="was${wCls(x.from)}">${yen(x.from)}</span>','${comparisonMarkup(x.from, x.to, x.id, `<span class="was${wCls(x.from)}">${yen(x.from)}</span>`)}')
    # Current verified free-label support, without inferring availability from history.
    s=re.sub(r'(\w+)\.cur === 0 \? tr\("free"\)',r'\1.cur === 0 ? freePriceLabel(\1.id)',s)
    s=s.replace('s.cur === 0 ? \'<span class="free">\' + tr("free")','s.cur === 0 ? \'<span class="free">\' + freePriceLabel(s.id)')
    s=s.replace('x.cur === 0 ? `<span class="bpchip">${tr("free")}</span>`','x.cur === 0 ? `<span class="bpchip">${freePriceLabel(x.id)}</span>`')
    s=s.replace('tr("free")}</span><span class="scur">¥0', 'freePriceLabel(t.id)}</span><span class="scur">¥0')
    s=s.replace('if (t.cur === 0) return `<div class="spr"><span class="scur free">${tr("free")}', 'if (t.cur === 0) return `<div class="spr"><span class="scur free">${freePriceLabel(t.id)}')
    s=s.replace('if (t.cur === 0) return `<div class="spr solo"><span class="scur">${tr("free")}', 'if (t.cur === 0) return `<div class="spr solo"><span class="scur">${freePriceLabel(t.id)}')
    if '<div class="sp-main">' in s and 'sp_price_basis' not in s:
        notes={'ja':'各バリエーションの価格は、価格推移で確認できます。','en':'See price history for each variation’s price.','ko':'각 옵션의 가격은 가격 이력에서 확인할 수 있습니다.','zh-Hans':'各款式的价格可在价格历史中查看。','zh-Hant':'各款式的價格可在價格歷史中查看。'}
        assignment='for (const [lang, text] of Object.entries('+json.dumps(notes,ensure_ascii=False)+')) { if (I18N[lang]) I18N[lang].sp_price_basis = text; }\n'
        s=s.replace('let LANG = "ja";',assignment+'let LANG = "ja";',1)
        s=s.replace('    <div class="sp-main">','    <p class="price-basis-note" data-i="sp_price_basis">'+notes['ja']+'</p>\n    <div class="sp-main">',1)
        s=s.replace('<div class="pstats" id="ppStats"></div>', '<div class="pstats" id="ppStats"></div><p class="price-basis-note">${tr("sp_price_basis")}</p>',1)
        s=s.replace('</head>','<style>.price-basis-note{color:var(--sub);font-size:12px;line-height:1.5;margin:8px 0 12px;overflow-wrap:anywhere}</style>\n</head>',1)
    for i, markup in enumerate(protected):s=s.replace('__PRICE_MARKUP_'+str(i)+'__',markup)
    data='<script id="price-presentation-proof">const PRICE_PRESENTATION = '+json.dumps(evidence,ensure_ascii=False,separators=(',',':')).replace('<', r'\u003c')+';</script>\n'
    return s.replace('<script>\n// PRICE_PRESENTATION_HELPERS_START',data+'<script>\n// PRICE_PRESENTATION_HELPERS_START',1)

def read_proof(html):
    found=re.search(r'<script id="price-presentation-proof">const PRICE_PRESENTATION = (.*?);</script>',html,re.S)
    if found:return json.loads(found[1])
    # Old verified candidates retain only some tagged variant histories.
    found=re.search(r'^const P = (.*);$',html,re.M)
    data=json.loads(found[1]) if found else {};entries={}
    for rec in data.get('on_sale',[]):
        variants=rec.get('vars') or {};name=next(iter(variants),None)
        if not name:continue
        rows=variants[name].get('p',[]);base=rec.get('base');cur=rec.get('cur')
        matched=[r for r in rows if r[1]==base]
        if rows and rows[-1][1]==cur and matched and all(len(r)>3 and r[3]==1 for r in matched):
            entries[str(rec['id'])]={'representative_name':name,'observed_at':rows[-1][0],'current':cur,'comparison_base':base,'comparison_outlier':True,'proof_basis':'existing-tagged-representative-history','variant_coverage':'unknown'}
    return {'schema':1,'entries':entries}

def main(root,proof):
 root=Path(root);evidence=proof if isinstance(proof,dict) else json.loads(Path(proof).read_text())
 if evidence.get('schema')!=1 or not isinstance(evidence.get('entries'),dict):raise ValueError('Bad evidence schema')
 for p in list(root.glob('*.html')):
  old=p.read_text();new=transform(old,evidence)
  if new!=old:p.write_text(new)
if __name__=='__main__':main(sys.argv[1],sys.argv[2])
