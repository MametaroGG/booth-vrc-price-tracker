#!/usr/bin/env python3
"""BoopaDB prototype builder: scans Boopa price-history JSON and emits a
single self-contained HTML prototype with real data."""
import json, os, sys, math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DATA = None
OUT = None

def rep_variation(d):
    """Pick representative variation: most points, then name."""
    vars_ = d.get("variations") or {}
    best_key, best_series = None, []
    for k, series in vars_.items():
        if isinstance(series, list) and len(series) > len(best_series):
            best_key, best_series = k, series
    return best_key, best_series

def main():
    if DATA is None or OUT is None:
        raise ValueError('Explicit DATA and OUT paths required; use build_site.py for the supported pipeline')
    # Scanner-only dependency: template consumers do not need data utilities.
    from varutil import thin_vars_from_item

    total = 0
    on_sale = []       # dicts
    drops = []         # (date, drop_amount, dict)
    free_now = 0
    sale_count_now = 0
    changed_products = 0
    max_date = ""
    min_date = "9999"
    chart_candidates = []  # (score, id)

    files = []
    for shard in os.scandir(DATA):
        if shard.is_dir():
            for f in os.scandir(shard.path):
                if f.name.endswith(".json"):
                    files.append(f.path)
    print(f"files: {len(files)}", file=sys.stderr)

    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        total += 1
        key, series = rep_variation(d)
        if not series:
            continue
        series = sorted(series, key=lambda p: p["date"])
        prices = [p["price"] for p in series]
        cur = prices[-1]
        cur_sale = bool(series[-1].get("is_sale"))
        base = max(prices)
        lowest = min(prices)
        last_date = series[-1]["date"]
        if last_date > max_date: max_date = last_date
        if series[0]["date"] < min_date: min_date = series[0]["date"]
        distinct = len(set(prices))
        if distinct >= 2:
            changed_products += 1
        if cur_sale:
            sale_count_now += 1
        if cur == 0 and base >= 100:
            free_now += 1
        all_low = False
        _vs = [x2 for x2 in (d.get("variations") or {}).values() if isinstance(x2, list) and x2]
        if _vs:
            all_low = True
            for _s2 in _vs:
                _ps = [p["price"] for p in sorted(_s2, key=lambda p: p["date"])]
                if _ps[-1] > min(_ps):
                    all_low = False
                    break
        # sale list: currently on sale, meaningful base price
        if cur_sale and base >= 500 and cur < base:
            pct = round((base - cur) / base * 100)
            on_sale.append({
                "id": d["id"], "name": d.get("name", ""), "cur": cur,
                "base": base, "lowest": lowest, "pct": pct,
                "at_lowest": all_low, "date": last_date,
            })
        # most recent downward change
        for i in range(len(series) - 1, 0, -1):
            if prices[i] != prices[i - 1]:
                if prices[i] < prices[i - 1]:
                    drops.append((series[i]["date"], prices[i - 1] - prices[i], {
                        "id": d["id"], "name": d.get("name", ""),
                        "from": prices[i - 1], "to": prices[i],
                        "date": series[i]["date"], "lowest": lowest,
                        "at_lowest": prices[i] <= lowest,
                        "on_sale": cur_sale,
                        "sale_event": bool(series[i].get("is_sale")),
                    }))
                break
        # chart candidate score
        transitions = sum(1 for i in range(1, len(series))
                          if series[i].get("is_sale") and not series[i - 1].get("is_sale"))
        if distinct >= 3 and len(series) >= 60:
            score = distinct * 2 + transitions * 3 + len(series) / 50.0
            chart_candidates.append((score, d["id"]))

    on_sale.sort(key=lambda x: (-x["pct"], x["base"] - x["cur"]))
    drops.sort(key=lambda x: (x[0], x[1]), reverse=True)
    recent_drops = [d for _, _, d in drops if d["date"] >= "2026-10-02"][:10]
    chart_candidates.sort(reverse=True)
    chart_ids = [cid for _, cid in chart_candidates[:3]]

    charts = []
    for cid in chart_ids:
        shard = cid[:3]
        d = json.load(open(DATA / shard / f"{cid}.json", encoding="utf-8"))
        charts.append({"id": cid, "name": d.get("name", ""),
                       "variations": thin_vars_from_item(d) or {}})
    # Attach per-variation histories to the sale/drop items as well, so
    # their product pages can switch variations too.
    for rec in on_sale[:12] + [d for _, _, d in drops if d["date"] >= "2026-10-02"][:10]:
        try:
            d = json.load(open(DATA / str(rec["id"])[:3] / f"{rec['id']}.json", encoding="utf-8"))
        except Exception:
            continue
        v = thin_vars_from_item(d)
        if v:
            rec["vars"] = v

    payload = {
        "stats": {
            "total": total, "sale_now": sale_count_now, "free_now": free_now,
            "changed": changed_products, "min_date": min_date, "max_date": max_date,
        },
        "on_sale": on_sale[:12],
        "drops": recent_drops,
        "charts": charts,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = TEMPLATE.replace("/*__PAYLOAD__*/", json.dumps(payload, ensure_ascii=False))
    html = add_index_diagnostics(html)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)", file=sys.stderr)
    print(json.dumps(payload["stats"], ensure_ascii=False), file=sys.stderr)
    print("sale sample:", [s["name"][:30] for s in payload["on_sale"][:3]], file=sys.stderr)
    print("chart ids:", chart_ids, file=sys.stderr)

VISIBILITY_JS = r"""
// VISIBILITY_POLICY_START: immutable build exclusions; additive runtime confirmations only.
const snapshotHiddenIds = new Set(P.visibility && P.visibility.schema === 1 && Array.isArray(P.visibility.hidden_ids) ? P.visibility.hidden_ids.filter(id => typeof id === "string" && /^[1-9][0-9]*$/.test(id)) : []);
const runtimeHiddenIds = new Set();
const visibilityObservationDates = new Map();
function visibilityDate(value){
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.slice(0,4) === "0000") return null;
  const parsed = new Date(value + "T00:00:00.000Z");
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0,10) === value ? value : null;
}
// A stale cached 404 must not override a newer rebuilt snapshot. A date-only
// source cannot establish ordering within the same day; equal dates are allowed.
const visibilitySourceFloor = visibilityDate(P.stats && P.stats.max_date);
function visibilityRecordDate(record){
  if (!record || typeof record !== 'object') return null;
  let latest = visibilityDate(record.date) || '';
  const series = [record.spark || [], ...Object.values(record.variations || record.vars || {})];
  for (const value of series) {
    const rows = Array.isArray(value) ? value : value && Array.isArray(value.p) ? value.p : [];
    for (const row of rows) {
      const date = visibilityDate(Array.isArray(row) ? row[0] : row && row.date);
      if (date && date > latest) latest = date;
    }
  }
  return latest || null;
}
function noteVisibilityObservation(record){
  if (!record || record.id == null) return;
  const id = String(record.id), date = visibilityRecordDate(record);
  if (date && date > (visibilityObservationDates.get(id) || '')) visibilityObservationDates.set(id,date);
}
function visibilityAllowsLiveMarker(id, meta){
  if (!visibilitySourceFloor || !confirmedUnavailableMeta(id,meta) || meta.fetched_at < visibilitySourceFloor) return false;
  let latest = visibilityObservationDates.get(String(id)) || '';
  try { if (typeof PROD !== 'undefined') latest = [latest,visibilityRecordDate(PROD.get(String(id))) || ''].sort().pop(); } catch {}
  return meta.fetched_at >= latest;
}
function hiddenItem(id){ return snapshotHiddenIds.has(String(id)) || runtimeHiddenIds.has(String(id)); }
function visibleItem(x){ return !!x && !hiddenItem(Array.isArray(x) ? x[0] : x.id); }
function visibleItems(rows){ return Array.isArray(rows) ? rows.filter(visibleItem) : []; }
function filterVisibleLists(data){
  const out = {...(data || {})};
  for (const key of Object.keys(out)) if (Array.isArray(out[key]) && key !== "hidden_ids") out[key] = visibleItems(out[key]);
  return out;
}
function confirmedUnavailableMeta(id, meta){
  if (!meta || typeof meta !== "object" || Array.isArray(meta) || meta.unavailable !== true || !!meta.name ||
      !Number.isInteger(meta.status) || ![404,410].includes(meta.status) ||
      typeof meta.id !== "string" || !/^[1-9][0-9]*$/.test(meta.id) || meta.id !== String(id) ||
      typeof meta.fetched_at !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(meta.fetched_at)) return false;
  const parsed = new Date(meta.fetched_at + "T00:00:00.000Z");
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0,10) !== meta.fetched_at || meta.fetched_at.slice(0,4) === "0000") return false;
  return meta.fetched_at <= new Date(Date.now() + 9*60*60*1000).toISOString().slice(0,10);
}
function visibilityPrune(root = document){
  // Backstop for already-painted cards when metadata confirms an unavailable item.
  // Source histories/bookmarks are never rewritten by this presentation-only pass.
  if (!root || !root.querySelectorAll) return;
  const selector='[data-pid],[data-fill],a[href]';
  const nodes=[...(root.matches && root.matches(selector) ? [root] : []),...root.querySelectorAll(selector)];
  nodes.forEach(node => {
    const href = node.getAttribute && node.getAttribute('href') || '';
    const match = href.match(/(?:\/items\/|#item-|item\.html\?id=)([1-9][0-9]*)(?:[&#/?]|$)/);
    const id = node.dataset && (node.dataset.pid || node.dataset.fill) || match && match[1];
    if (!id || !hiddenItem(id)) return;
    const card = node.closest && node.closest('.card,.brow,.bmcard,.pcard,.hslide,.rtile,.mcell,.ucard,.shcard,.nrow,.ritem,.hthumb,.capcard');
    (card || node).remove();
  });
}
function acceptVisibilityMeta(id, meta){
  if (visibilityAllowsLiveMarker(id, meta) && !hiddenItem(id)) {
    runtimeHiddenIds.add(String(id));
    visibilityPrune();
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('boopa:visibility', {detail:{id:String(id)}}));
  }
  return hiddenItem(id) ? null : meta;
}
Object.assign(P, filterVisibleLists(P));
if (typeof window !== 'undefined') window.BoopaVisibility = {isHidden:hiddenItem,filter:visibleItems,acceptMeta:acceptVisibilityMeta,prune:visibilityPrune};
if (typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
  new MutationObserver(changes => { for (const change of changes) for (const node of change.addedNodes || []) if (node.nodeType === 1) visibilityPrune(node); }).observe(document.body, {childList:true,subtree:true});
}
// VISIBILITY_POLICY_END
"""

TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="theme-color" content="#101012"><script>try{var t=localStorage.getItem("boopadb_theme");if(t!=="dark"&&t!=="light")t=matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";document.documentElement.dataset.theme=t;var m=document.querySelector('meta[name="color-scheme"]');if(m)m.content=t;}catch(e){document.documentElement.dataset.theme="dark"}</script><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap" rel="stylesheet"><link rel="preconnect" href="https://booth.pximg.net"><link rel="preconnect" href="https://nucbox-m7.tailb48431.ts.net:8443">
<meta name="color-scheme" content="dark">
<title>BoopaDB — BOOTHのVRChat向け価格データベース（プロトタイプ）</title>
<meta property="og:type" content="website">
<meta property="og:site_name" content="BoopaDB">
<meta property="og:title" content="BoopaDB — BOOTHのVRChat向け価格データベース（プロトタイプ）">
<meta property="og:description" content="BOOTHのVRChat向け商品の価格推移・セール・値下げを追えるデータベース">
<meta property="og:url" content="https://mametarogg.github.io/boopadb/">
<meta property="og:image" content="https://mametarogg.github.io/boopadb/ogp-16x9.png">
<meta property="og:image:width" content="1920">
<meta property="og:image:height" content="1080">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://mametarogg.github.io/boopadb/ogp-16x9.png">
<link rel="icon" href="favicon.ico?v=3" sizes="any">
<link rel="icon" type="image/png" href="favicon-192.png?v=3" sizes="192x192">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="manifest" href="manifest.webmanifest">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="BoopaDB">
<script>if("serviceWorker" in navigator){navigator.serviceWorker.register("sw.js").catch(function(){})}</script>
<style>
  :root{--bg:#101012;--panel:#17171a;--card:#1b1b1f;--border:#26262c;--border2:#34343c;--text:#ececee;--sub:#a2a2ab;--faint:#6f6f78;--accent:#fc4d50;--red:#fc4d50;--accent-dim:#e04347;--green:#a4d007;--green-bg:#4c6b22;--amber:#d9a521}
  *{box-sizing:border-box;margin:0;padding:0}
  :root{color-scheme:dark}
  body{font-family:"Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,sans-serif;background:radial-gradient(1200px 520px at 50% -120px,#26262c 0%,rgba(38,38,44,0) 60%),var(--bg);color:var(--text);line-height:1.55;font-size:14px;font-variant-numeric:tabular-nums}
  a{color:inherit;text-decoration:none}
  a:hover{color:#fff}
  #splash{position:fixed;inset:0;z-index:9999;background:#101012;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;transition:opacity .35s ease}
  [data-theme="light"] #splash{background:#f4f4f5}
  #splash[hidden]{display:none}
  #splash.bye{opacity:0;pointer-events:none}
  #splash svg{width:112px;height:112px;animation:splIn .45s ease-out;will-change:transform;transform:translateZ(0)}
  #splash .spl-ring,#splash .spl-line{will-change:stroke-dashoffset}
  #splash .spl-ring{stroke-dasharray:346;stroke-dashoffset:346;animation:splDraw .7s ease-out forwards}
  #splash .spl-line{stroke-dasharray:130;stroke-dashoffset:130;animation:splDraw .55s .5s ease-out forwards}
  #splash .spl-head{opacity:0;animation:splFade .2s .95s ease-out forwards}
  #splash .spl-tag{opacity:0;animation:splFade .25s 1.1s ease-out forwards}
  @keyframes splDraw{to{stroke-dashoffset:0}}
  @keyframes splFade{to{opacity:1}}
  #splash .splogo{font-family:"Orbitron","Hiragino Kaku Gothic ProN",sans-serif;font-size:30px;font-weight:900;letter-spacing:.5px;color:#ececee;animation:splIn .45s ease-out}
  [data-theme="light"] #splash .splogo{color:#17171a}
  #splash .splogo span{color:var(--accent)}
  @keyframes splIn{from{opacity:0;transform:scale(.92)}to{opacity:1;transform:scale(1)}}
  html.splock,html.splock body{overflow:hidden}
  header{background:linear-gradient(180deg,#1f1f23,#151517);border-bottom:1px solid var(--border);padding:12px 0}
  .hwrap{max-width:1080px;margin:0 auto;padding:0 20px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  .hwrap .logo{order:1}
  .hwrap .badge{order:2}
  .hwrap nav{order:3}
  .hwrap .langsw{order:4}
  .hwrap .themebtn{order:5}
  .logo{font-family:"Orbitron","Hiragino Kaku Gothic ProN",sans-serif;font-size:21px;font-weight:900;letter-spacing:.5px}
  .logo span{color:var(--accent)}
  .langsw{position:relative;margin-left:auto;flex:none}
  #langBtn{display:inline-flex;align-items:center;gap:6px;background:#1b1b1f;border:1px solid var(--border2);color:var(--text);font-size:12.5px;font-weight:700;padding:6px 10px;border-radius:99px;cursor:pointer;font-family:inherit}
  #langBtn svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
  #langBtn .lchev{width:12px;height:12px}
  .langmenu{position:absolute;right:0;top:calc(100% + 8px);background:#1b1b1f;border:1px solid var(--border2);border-radius:12px;padding:5px;min-width:158px;display:none;box-shadow:0 14px 34px rgba(0,0,0,.5);z-index:300}
  .langmenu.open{display:block}
  .langmenu button{display:flex;width:100%;align-items:center;justify-content:space-between;gap:8px;background:none;border:none;color:var(--sub);font-size:13.5px;font-weight:600;padding:8px 10px;border-radius:8px;cursor:pointer;font-family:inherit;text-align:left}
  .langmenu button:hover{background:#26262c;color:var(--text)}
  .langmenu button.on{color:#fff}
  .langmenu button.on::after{content:"\2713";color:#c8ec6e;font-weight:800}
  .badge{font-size:10.5px;background:#26262c;color:var(--sub);border:1px solid var(--border2);padding:2px 8px;border-radius:99px;font-weight:700;letter-spacing:.08em}
  .unofficial{font-size:12px;color:var(--faint)}
  main{max-width:1080px;margin:0 auto;padding:22px 20px}
  .stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--border);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:8px}
  .stat{background:var(--panel);padding:13px 12px;min-width:0}
  @media(min-width:1100px){.stats{grid-template-columns:repeat(6,minmax(0,1fr))}}
  @media(max-width:899px){.stats{grid-template-columns:repeat(3,minmax(0,1fr))}}
  @media(max-width:560px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.stat{padding:12px 10px}}
  .stat .num{font-family:'Orbitron',sans-serif;font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
  .stats-status{margin:0 0 4px}
  .stats-details summary{cursor:pointer}
  .stats-details p{margin:5px 0;overflow-wrap:anywhere}
  .stats-note{font-size:11px;color:var(--faint);line-height:1.6;margin:0 0 16px}
  @media(max-width:560px){.stat .num{font-size:clamp(16px,4.5vw,18px)}}
  .stat[data-stat="tracking-since"] .num{font-size:16px;letter-spacing:-.03em}
  .stat .lbl{font-size:11px;color:var(--faint);letter-spacing:0;margin-top:3px;white-space:nowrap}
  h2{font-size:19px;font-weight:600;letter-spacing:.05em;color:#fff;margin:36px 0 14px;text-shadow:0 1px 3px rgba(0,0,0,.5)}
  table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--border);border-radius:10px;overflow:hidden}
  th,td{padding:8px 12px;font-size:13.5px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}
  th{color:var(--faint);font-size:11px;letter-spacing:.07em;background:#131316;font-weight:600}
  tbody tr:hover{background:#1e1e23}
  tr:last-child td{border-bottom:none}
  .price{font-weight:700;white-space:nowrap}
  .was{color:var(--faint);white-space:nowrap;position:relative}
  .was::after{content:"";position:absolute;left:-2px;right:-2px;top:50%;height:2px;margin-top:-1px;background:currentColor;border-radius:2px;transform:rotate(-11deg);pointer-events:none}
  .wasx{position:relative}
  .wasx::after{content:"";position:absolute;left:-2px;right:-2px;top:50%;height:2px;margin-top:-1px;background:currentColor;border-radius:2px;transform:rotate(-11deg);pointer-events:none}
  .caprow > .was::after,.mcell .scrim > .was::after{content:none}
  .pct{color:var(--green);font-weight:700;white-space:nowrap}
  .free{color:var(--text);font-weight:700}
  .lowest{font-size:10.5px;background:var(--green-bg);color:#c8ec6e;padding:1px 7px;border-radius:4px;margin-left:6px;white-space:nowrap;font-weight:600}
  .tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
  .tab{background:var(--panel);border:1px solid var(--border);color:var(--sub);padding:7px 12px;border-radius:8px;cursor:pointer;font-size:13px;max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .tab:hover{color:var(--text);border-color:var(--border2)}
  .tab.active{border-color:var(--border2);color:#fff;background:#26262c}
  .panel{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px}
  .pstats{display:flex;gap:22px;flex-wrap:wrap;margin:10px 0 4px}
  .pstats .k{font-size:11px;color:var(--faint);letter-spacing:.05em}
  .pstats .v{font-size:19px;font-weight:700}
  .vhistorydate{display:block;font-size:11px;font-weight:400;line-height:1.4;color:var(--sub)}
  select{background:#131316;color:var(--text);border:1px solid var(--border2);border-radius:6px;padding:5px 8px;font-size:13px}
  svg{width:100%;height:auto;display:block}
  #appPromoX svg{width:16px;height:16px;flex:none}
  .btn{display:inline-block;background:var(--accent-dim);color:#fff;font-weight:700;padding:8px 16px;border-radius:8px;font-size:14px}
  .btn:hover{background:var(--accent);text-decoration:none}
  footer{color:var(--faint);font-size:12px;max-width:1080px;margin:24px auto 0;padding:20px 20px 44px;border-top:1px solid var(--border);line-height:1.7}
  .flegal{margin-top:12px}
  .flink{color:#4fb3a5}
  .flink:hover{color:#4fb3a5;text-decoration:underline}
  .note{font-size:12px;color:var(--faint);margin-top:6px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));gap:12px}
  #spGrid{grid-template-columns:repeat(2,1fr)}
  @media (min-width:900px){#spGrid{grid-template-columns:repeat(auto-fill,minmax(165px,1fr))}}
  #featGrid{display:flex;gap:10px;overflow-x:auto;scrollbar-width:none;padding:2px 2px 10px}
  #featGrid::-webkit-scrollbar{display:none}
  #featTrack{display:contents}
  .featwrap{position:relative}
  #featGrid .card{flex:0 0 168px;position:relative;overflow:visible;border-radius:0}
  #featGrid .capimg{border-radius:0}
  @media (min-width:900px){#featGrid .card{flex-basis:212px}}
  .card{background:linear-gradient(180deg,#1d1d21,#17171a);border:1px solid #202025;border-radius:10px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 2px 10px rgba(0,0,0,.42)}
  .card:hover{border-color:var(--border2)}
  .thumbwrap{position:relative;aspect-ratio:1/1;background:#131316;overflow:hidden}
  .thumbwrap img{width:100%;height:100%;object-fit:cover;display:block}
  .disc{position:absolute;right:8px;top:8px;background:var(--green-bg);color:#c8ec6e;font-weight:800;font-size:14px;padding:2px 8px;border-radius:5px;z-index:2}
  .cbody{padding:10px 12px 12px;display:flex;flex-direction:column;gap:4px;flex:1}
  .cname{font-size:13.5px;font-weight:600;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.9em}
  .cshop{font-size:12px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .clikes{display:flex;align-items:center;gap:4px;font-size:11.5px;color:var(--sub);margin-top:3px}
  .clikes svg{width:11px;height:11px;fill:none;stroke:currentColor;stroke-width:2}
  svg.hico{display:inline-block;width:11px;height:11px;fill:none;stroke:#f2506e;stroke-width:2;vertical-align:-1px;margin-right:3px}
  .pp-more{display:block;margin:12px auto 2px;background:none;border:1px solid var(--border);color:var(--text);border-radius:99px;padding:7px 24px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit}
  .crow{margin-top:auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
  .crow .price.solo{display:inline-flex;align-items:center;height:26px;background:#26262c;padding:0 8px;font-size:16px;font-weight:600}
  .drow{display:flex;gap:12px;align-items:center;background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:8px 12px;margin-bottom:8px}
  .drow img{width:64px;height:48px;object-fit:cover;border-radius:6px;background:#131316;flex:none}
  .drow .dn{flex:1;min-width:0}
  .drow .dn .t{font-size:13.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .drow .dn .s{font-size:12px;color:var(--faint)}
  .drow .dp{text-align:right;white-space:nowrap}
  .phead{display:flex;gap:16px;align-items:flex-start}
  .phead img{width:150px;height:150px;object-fit:cover;border-radius:8px;background:#131316;flex:none}
  @media (max-width:560px){.phead{flex-direction:column}.phead img{width:100%;height:auto;aspect-ratio:1/1}}
  header nav{display:flex;gap:16px;margin-left:10px}
  @media (max-width:899px){
    .hwrap{gap:8px;row-gap:10px;padding:0 14px}
    .hwrap .logo{order:1;font-size:18px;letter-spacing:0;flex:none}
    .hwrap .badge{order:2;flex:none;font-size:9px;padding:1px 6px;letter-spacing:.04em}
    .hwrap .langsw{order:3;margin-left:auto;min-width:0}
    .hwrap .themebtn{order:4;width:32px;height:32px;flex:none}
    #langBtn{padding:5px 8px;font-size:12px;gap:5px;max-width:100%}
    #langCur{display:inline-block;max-width:72px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:bottom}
    .hwrap nav{order:5;flex-basis:100%;margin-left:0}
  }
  @media (max-width:359px){.hwrap .badge{display:none}}
  nav a{font-size:13px;color:var(--sub)}
  nav a:hover{color:#fff;text-decoration:none}
  .searchbox{margin-left:auto}
  .searchbox input{background:#101012;border:1px solid var(--border2);color:var(--text);border-radius:8px;padding:7px 12px;font-size:13px;width:220px;outline:none}
  .searchbox input:focus{border-color:var(--faint)}
  .spot{display:flex;gap:0;background:var(--panel);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:14px}
  .spot .simg{flex:0 0 46%;position:relative;background:#131316;min-height:230px}
  .spot .simg img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
  .spot .sbody{flex:1;padding:22px 24px;display:flex;flex-direction:column;gap:8px;min-width:0}
  .spot .kicker{font-size:11px;letter-spacing:.16em;color:var(--accent);font-weight:700}
  .spot .sname{font-size:21px;font-weight:800;line-height:1.4}
  .spot .sshop{font-size:13px;color:var(--faint)}
  .spot .sprice{display:flex;align-items:center;gap:12px;margin-top:auto;flex-wrap:wrap}
  .spot .sdisc{background:var(--green-bg);color:#c8ec6e;font-weight:800;font-size:20px;padding:3px 12px;border-radius:6px}
  .spot .snow{font-size:26px;font-weight:800}
  @media (max-width:640px){.spot{flex-direction:column}.spot .simg{flex:none;aspect-ratio:16/9;min-height:0}nav{display:none}.searchbox input{width:150px}}
  .card{transition:border-color .15s, transform .15s}
  .card:hover{transform:translateY(-2px);box-shadow:0 8px 22px rgba(0,0,0,.6);filter:brightness(1.07)}
  .thumbwrap img{transition:transform .25s}
  .card:hover .thumbwrap img{transform:scale(1.04)}
  .shead{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin:44px 0 14px;flex-wrap:wrap;row-gap:8px}
  .shead h2{margin:0}
  .shead select{background:#131316;color:var(--sub);border:1px solid var(--border2);border-radius:6px;padding:4px 8px;font-size:12px}
  .empty{color:var(--faint);font-size:13px;padding:14px 2px;display:none}
  @keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
  @keyframes dash{to{stroke-dashoffset:0}}
  .card{animation:rise .5s cubic-bezier(.22,.9,.3,1) both}
  .card:active{transform:scale(.975)}
  .btn{transition:transform .25s cubic-bezier(.34,1.56,.64,1), background .15s}
  .btn:active{transform:scale(.94)}
  .chips{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 4px}
  .chip{border:1px solid var(--border2);background:var(--panel);color:var(--sub);border-radius:99px;padding:6px 14px;font-size:12.5px;cursor:pointer;transition:all .18s cubic-bezier(.34,1.4,.64,1);font-family:inherit}
  #chips{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;padding-bottom:2px}
  #chips::-webkit-scrollbar{display:none}
  #chips .chip{white-space:nowrap;flex:none;padding:6px 11px;font-size:12px}
  .chip:hover{color:var(--text);border-color:var(--faint)}
  .chip:active{transform:scale(.93)}
  .chip.on{background:var(--text);color:#111214;font-weight:700;border-color:var(--text)}
  .pilltabs{position:relative;display:inline-flex;gap:2px;border-bottom:1px solid var(--border)}
  .pilltabs button{position:relative;z-index:1;background:none;border:none;color:var(--sub);padding:7px 13px;cursor:pointer;font-size:13px;font-family:inherit;transition:color .2s;border-bottom:2px solid transparent;margin-bottom:-1px}
  .pilltabs button.on{color:#fff;font-weight:700;border-bottom-color:var(--accent)}
  .pill-ind{display:none}
  .salepanel{background:linear-gradient(180deg,#1f1f23,#17171a);border:1px solid var(--border);border-radius:0;padding:12px;margin-top:10px;box-shadow:0 4px 16px rgba(0,0,0,.4)}
  #saleGrid .card{border-radius:0}
  .saleRail{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;align-items:flex-start}
  .saleRail::-webkit-scrollbar{display:none}
  .saleTrack{display:contents}
  .sarrow{display:none}
  .saleDots{display:none}
  .railbar{display:none}
  @media (max-width:899px){
    .railbar{display:block;height:4px;border-radius:2px;background:#232329;background-clip:content-box;padding:6px 0;margin-top:4px;position:relative;overflow:hidden;cursor:pointer;touch-action:none}
    .railbar span{position:absolute;top:6px;left:0;height:4px;border-radius:2px;background:#5b5b66}
  }
  @media (min-width:900px){
    .salepanel{position:relative}
    .salepanel.hp{margin-left:54px;margin-right:54px}
    .featwrap{margin:0 54px}
    #featGrid{overflow:hidden}
    #featTrack{display:flex;gap:10px;position:relative;transition:transform .55s cubic-bezier(.22,.8,.3,1)}
    .featwrap .sarrow{top:46%}
    .saleRail{overflow:hidden}
    .saleTrack{display:flex;gap:8px;position:relative;transition:transform .55s cubic-bezier(.22,.8,.3,1)}
    .sarrow{display:block;position:absolute;top:50%;transform:translateY(-50%);z-index:5;background:none;border:none;color:rgba(255,255,255,.75);font-size:56px;line-height:1;cursor:pointer;padding:8px 2px;font-family:inherit}
    .sarrow.prev{left:-54px}
    .sarrow.next{right:-54px}
    .sarrow:hover{color:#fff}
    .saleDots{display:flex;gap:6px;justify-content:center;margin-top:10px}
    .saleDots span{width:22px;height:4px;border-radius:2px;background:#33333a}
    .saleDots span.on{background:#e8e8ec}
  }
  .rtile{flex:0 0 280px;display:flex;flex-direction:column;background:#131316;text-decoration:none}
  .rstack{flex:0 0 118px;display:grid;grid-template-rows:158px 158px;gap:8px}
  @media (min-width:900px){.rtile{flex-basis:308px}.rstack{flex-basis:132px;grid-template-rows:172px 172px}}
  .rtile.sm .pstrip{gap:0;padding:0;flex:1}
  .rtile.sm .pstrip .bprice{flex:1}
  .rtile.sm .pstrip .bstack{flex:1;padding:2px 6px}
  .rtile.sm .pstrip .discst{font-size:11.5px;padding:0 6px}
  .rtile.sm .pprice{font-size:12.5px}
  .rtile .rimg{position:relative;aspect-ratio:1/1;width:100%;overflow:hidden;display:block;flex:none}
  .rtile .rimg img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
  .rtile .pstrip{display:flex;align-items:center;gap:6px;flex:none;padding:6px;background:#1b1b1f}
  .rtile .pstrip>*{flex:none}
  .rtile .pwas{display:inline-flex;align-items:center;background:#26262c;color:var(--faint);font-size:13px;white-space:nowrap;padding:9px 3px 9px 10px;flex:1;justify-content:flex-end}
  .rtile .pprice{display:inline-flex;align-items:center;background:#26262c;font-size:17px;font-weight:700;color:var(--text);white-space:nowrap;padding:9px 10px 9px 3px}
  .rtile .pprice.free{color:var(--text)}
  .rtile .pstrip{gap:0;padding:0;align-items:stretch}
  .rtile .pstrip .discst{height:auto;font-size:16px;padding:0 10px}
  .mosaic{display:grid;gap:10px;grid-template-columns:1fr 1fr}
  .mosaic .card{background:none;border:none;border-radius:0}
  .mcell{position:relative;overflow:hidden;display:flex;flex-direction:column;border-radius:0;text-decoration:none}
  .mcell .mimg{position:relative;aspect-ratio:1/1;display:block;flex:none}
  .mcell .mimg img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
  .mcell .scrim{position:static;padding:0;background:#1b1b1f;display:flex;align-items:center;gap:0;flex-wrap:nowrap;flex:none}
  .mcell .scrim .discst{flex:none;font-size:13px;padding:0 5px;height:22px}
  .mcell .scrim .was{font-size:11px;padding:0 2px 0 6px;height:22px;flex:none;color:#c2c2cb;white-space:nowrap;flex:1;justify-content:flex-end}
  .mcell .scrim .price{font-size:15px;padding:0 6px 0 2px;height:22px;flex:none}
  .mcell .mlab,.rtile .mlab,.card .thumbwrap .mlab{position:absolute;top:0;left:0;font-size:11px;line-height:1.3;font-weight:800;color:#fff;background:#4c6b22;padding:3px 8px;letter-spacing:.05em;z-index:2;box-shadow:0 2px 6px rgba(0,0,0,.35)}
  @media (min-width:900px){
    .mosaic{grid-template-columns:repeat(4,1fr)}
  }
  .capgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-top:10px}
  .relrow{display:flex;gap:10px;overflow-x:auto;overflow-y:hidden;margin-top:10px;padding:2px 2px 10px;scroll-snap-type:x proximity;scrollbar-width:thin;scrollbar-color:#3d3d44 transparent}
  .relrow::-webkit-scrollbar{height:6px}
  .relrow::-webkit-scrollbar-track{background:transparent}
  .relrow::-webkit-scrollbar-thumb{background:#3d3d44;border-radius:99px}
  .relrow .card{flex:0 0 190px;scroll-snap-align:start}
  @media (max-width:640px){.relrow .card{flex-basis:154px}}
  .relwrap{position:relative}
  .relsec{display:flex;align-items:baseline;justify-content:space-between;gap:10px}
  .relmore{font-size:12.5px;font-weight:700;color:var(--sub);text-decoration:none;white-space:nowrap}
  .relmore:hover{color:var(--text)}
  button.relmore,a.relmore[data-relation-search]{display:inline-block;background:transparent;border:1px solid var(--sub);border-radius:8px;padding:7px 12px;cursor:pointer;margin:8px 12px 0 0;font-family:inherit}
  .relbtn{display:none;position:absolute;top:36%;transform:translateY(-50%);z-index:4;width:38px;height:38px;border-radius:50%;border:1px solid var(--line);background:rgba(24,24,28,.88);color:#e8e8ec;cursor:pointer;align-items:center;justify-content:center;padding:0}
  .relbtn svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round}
  .relbtn.prev{left:-6px}
  .relbtn.next{right:-6px}
  .relbtn:hover{background:#2c2c33}
  @media (min-width:900px){.relwrap.hasmore .relbtn{display:flex}}
  html[data-theme="light"] .relbtn{background:rgba(255,255,255,.92);color:#33333a}
  .capimg{position:relative;aspect-ratio:1/1;background:#131316;display:block;overflow:hidden}
  .capimg img{width:100%;height:100%;object-fit:cover;display:block}
  .capbody{padding:10px 12px 0;display:flex;flex-direction:column;gap:5px;flex:1}
  .capname{font-size:14px;font-weight:700;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:40px}
  .capshop{font-size:11.5px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .caprow{display:flex;align-items:stretch;gap:0;margin-top:auto;flex-wrap:nowrap}
  /* Joined Steam-style price cluster: every segment is the same height and
     touches the next with no gap, so badge + prices read as one strip. */
  .discst{display:inline-flex;align-items:center;height:24px;box-sizing:border-box;background:var(--green-bg);color:#c8ec6e;font-weight:800;font-size:13.5px;padding:0 7px;border-radius:0;line-height:1}
  .newtag{display:inline-flex;align-items:center;height:24px;box-sizing:border-box;background:var(--accent);color:#fff;font-weight:800;font-size:13px;letter-spacing:.05em;padding:0 9px;line-height:1}
  .caprow .was,.bprice .was,.bprow .was,.mcell .scrim .was{display:inline-flex;align-items:center;height:24px;box-sizing:border-box;background:#26262c;padding:0 3px 0 8px;line-height:1}
  .caprow .was{font-size:12px}
  .caprow .was{padding:0 2px 0 5px}
  .caprow .price{padding:0 5px 0 2px}
  .caprow .discst{padding:0 5px}
  .caprow .saletag{display:inline-flex;align-items:center;background:#4c6b22;color:#c8ec6e;font-weight:800;font-size:12px;padding:0 7px;line-height:1}
  .caprow .was{flex:1;justify-content:flex-end}
  .caprow .price,.bprice .price,.bprow .price,.mcell .scrim .price{display:inline-flex;align-items:center;height:24px;box-sizing:border-box;background:#26262c;padding:0 8px 0 3px;line-height:1}
  .bprice .price{font-size:14px}
  .discst + .price{padding-left:8px}
  .bprice .price:first-child,.caprow .price:first-child{padding-left:8px}
  .caprow > .price{justify-content:center;padding:0 8px}
  .caprow > .was + .price{padding-left:3px}
  .caprow{margin-left:-12px;margin-right:-12px;padding:0}
  .caprow .discst,.caprow .was,.caprow .price,.caprow .saletag{height:auto;padding-block:6px}
  .caprow .newtag{height:auto;padding-block:6px}
  .lowtx{font-size:10.5px;color:#c8ec6e;font-weight:700;width:100%}
  .capbtm{margin-top:auto}
  #spGrid .caprow .bprice{flex:1}
  #spGrid .caprow .bstack{flex:1}
  .mcell .scrim .discst,.mcell .scrim .was,.mcell .scrim .price{height:34px}
  .smore{text-align:right;margin-top:2px}
  .smore button{background:rgba(255,255,255,.07);color:#e8e8ea;border:1px solid rgba(255,255,255,.16);font-weight:700;font-size:12.5px;padding:7px 20px;border-radius:3px;cursor:pointer;font-family:inherit}
  .smore button:hover{background:rgba(255,255,255,.14)}
  .smore button:active{transform:scale(.96)}
  #searchPage .smore{height:4px;margin:0}
  .sp-price{padding:2px 2px 0}
  .sp-price-val{text-align:center;color:var(--sub);font-size:13px;margin-top:2px}
  #spPrice{-webkit-appearance:none;appearance:none;width:100%;height:26px;background:transparent;cursor:pointer;margin:0}
  #spPrice::-webkit-slider-runnable-track{height:4px;border-radius:2px;background:#3a3a41}
  #spPrice::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:18px;height:18px;border-radius:50%;background:#e8e8ec;margin-top:-7px;box-shadow:0 1px 5px rgba(0,0,0,.5)}
  #spPrice::-moz-range-track{height:4px;border-radius:2px;background:#3a3a41}
  #spPrice::-moz-range-thumb{width:18px;height:18px;border:none;border-radius:50%;background:#e8e8ec}
  #spCatalogStatus{padding:10px 0;color:var(--sub);font-size:13px;overflow-wrap:anywhere} #spCatalogRetry{font:inherit;color:var(--text);background:var(--panel);border:1px solid var(--border2);border-radius:8px;padding:6px 12px}
  .sp-sidehead,.sp-sidefoot,#spFilterBtn{display:none}
  .sp-resbar{display:flex;align-items:center;justify-content:space-between;gap:10px}
  .sp-mode{display:flex;align-items:center;gap:8px;margin:0 0 10px;padding:7px 8px 7px 12px;border:1px solid #fc4d50;background:#fc4d50;color:#fff;border-radius:10px;font-size:13px;font-weight:700}
  .sp-mode[hidden]{display:none}
  #spModeImg{width:26px;height:26px;border-radius:6px;object-fit:cover;flex:none}
  #spModeImg[hidden]{display:none}
  .sp-search .sp-imgbtn{right:8px}
  .sp-search.has-query .sp-imgbtn{right:54px}
  .sp-search input#spQ{flex:1 1 0%;width:0;min-width:0;padding-right:58px}
  .sp-search.has-query input#spQ{padding-right:104px}
  .sp-mode-t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .sp-mode-x{flex:none;width:28px;height:28px;border-radius:50%;border:1px solid transparent;background:rgba(255,255,255,.22);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}
  .sp-mode-x svg{width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round}
  html[data-theme="light"] .sp-mode-x{background:rgba(255,255,255,.22)}
  .spsortdd{position:relative;display:inline-block;margin-left:auto;flex:none}
  #spSortBtn{display:inline-flex;align-items:center;background:#17171a;border:1px solid var(--border2);border-radius:8px;color:var(--text);font-size:13px;font-weight:600;padding:8px 12px;cursor:pointer;font-family:inherit;white-space:nowrap}
  .spcaret{display:inline-block;width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:6px solid currentColor;margin-left:7px}
  .spsortmenu{position:absolute;right:0;top:calc(100% + 8px);background:#1b1b1f;border:1px solid var(--border2);border-radius:12px;padding:5px;box-shadow:0 14px 34px rgba(0,0,0,.5);min-width:196px;z-index:30}
  .spsortmenu[hidden]{display:none}
  .spsortmi{display:flex;align-items:center;width:100%;background:none;border:none;color:#a2a2ab;font-size:13.5px;font-weight:600;padding:9px 12px;border-radius:8px;cursor:pointer;font-family:inherit;text-align:left;white-space:nowrap}
  .spsortmi:hover{background:#26262c;color:var(--text)}
  .spsortmi.on{color:#fff}
  .spsortmi.on::after{content:"✓";margin-left:auto;color:#c8ec6e;font-weight:800;padding-left:14px}
  body.spfilter-open .tabbar{opacity:0;pointer-events:none}
  #searchPage::-webkit-scrollbar{width:10px}
  #searchPage::-webkit-scrollbar-thumb{background:#3d3d44;border-radius:99px}
  #searchPage .sp-side{scrollbar-gutter:stable;padding-right:10px;scrollbar-width:thin;scrollbar-color:#3d3d44 transparent}
  #searchPage .sp-side::-webkit-scrollbar{width:8px}
  #searchPage .sp-side::-webkit-scrollbar-thumb{background:#3d3d44;border-radius:99px}
  @media (max-width:899px){
    .sp-resbar{display:flex;align-items:center;justify-content:space-between;gap:10px}
    #spFilterBtn{display:inline-flex;align-items:center;background:#17171a;border:1px solid var(--border2);border-radius:8px;color:var(--text);font-size:13px;font-weight:600;padding:8px 14px;cursor:pointer;font-family:inherit;white-space:nowrap}
    .sp-side{position:fixed;inset:0;background:var(--bg);z-index:65;overflow-y:auto;overscroll-behavior:contain;padding:14px 16px 110px;transform:translateY(103%);transition:transform .45s cubic-bezier(.32,1.18,.36,1);pointer-events:none}
    .sp-side.open{transform:none;pointer-events:auto}
    .sp-sidehead{display:flex;align-items:center;justify-content:space-between;font-size:16px;font-weight:800;color:var(--text);margin:2px 0 4px}
    .sp-sidehead + .sp-sec{display:none}
    .sp-sidex{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;border-radius:50%;background:#1b1b1f;border:1px solid var(--border2);color:var(--text);cursor:pointer;flex:none;position:relative}
    .sp-sidex::after{content:"";position:absolute;inset:-7px;border-radius:50%}
    .sp-sidex svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round}
    .sp-sidefoot{display:flex;gap:10px;position:fixed;left:0;right:0;bottom:0;padding:12px 16px calc(12px + env(safe-area-inset-bottom));background:rgba(16,16,18,.97);border-top:1px solid var(--border);z-index:2}
    .sp-freset{background:#1b1b1f;border:1px solid var(--border2);color:var(--text);border-radius:9px;padding:12px 18px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit}
    .sp-fshow{flex:1;background:var(--accent);border:none;color:#fff;border-radius:9px;padding:12px;font-size:14.5px;font-weight:800;cursor:pointer;font-family:inherit}
  }
  @media (min-width:900px){
    .sp-inner{padding-left:106px}
    .sp-main{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:26px;align-items:start}
    .sp-results{grid-column:1;grid-row:1;min-width:0}
    .sp-side{grid-column:2;grid-row:1;position:sticky;top:0;max-height:calc(100dvh - 150px);overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin}
    .sp-side .chips{flex-direction:column;align-items:stretch;flex-wrap:nowrap}
    .sp-side .chip{text-align:left}
    .sp-side .kwrap{flex-direction:column;align-items:stretch}
  }
  .hmeta{font-size:12.5px;color:var(--sub);margin-top:3px}
  .hmain .htags2{display:flex;gap:5px;flex-wrap:wrap;margin-top:10px}
  .htag{font-size:11px;background:#2a2a2f;color:var(--sub);padding:2.5px 9px;border-radius:4px}
  .hstatus{font-size:12.5px;color:#c8ec6e;font-weight:700;margin-top:10px}
  .hero-view{overflow:visible}
  .harrow{position:absolute;top:38%;transform:translateY(-50%);z-index:5;background:none;border:none;color:rgba(255,255,255,.75);font-size:52px;line-height:1;cursor:pointer;padding:8px 6px;display:none;font-family:inherit}
  @media (min-width:900px){.harrow{display:block}}
  .harrow.prev{left:2px}
  .harrow.next{right:2px}
  .harrow:hover{color:#fff}
  @media (min-width:900px){
    .hslide{flex-direction:row;height:330px}
    #hero .hslide .himg{flex:none;height:100%;aspect-ratio:1/1;min-height:0;border-radius:14px 0 0 14px}
    #hero .hslide .hbody{flex:1;min-width:0;flex-direction:column;align-items:stretch;padding:18px 20px;height:auto}
    .hslide .hprice2{margin-top:auto;align-self:flex-end}
    .hslide .hname{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;font-size:21px;overflow:hidden;min-width:0}
  }
  .nprice,.rprice{flex:none;text-align:right}
  .nprice .was,.rprice .was{display:block;font-size:11.5px;width:fit-content;margin-left:auto}
  .cols{display:grid;grid-template-columns:1fr 330px;gap:28px;align-items:start}
  @media (max-width:880px){.cols{grid-template-columns:1fr}}
  .nrow{display:flex;gap:12px;padding:11px 2px;border-bottom:1px solid var(--border);align-items:center}
  .nprice .price{font-size:15.5px}
  .rprice .price{font-size:14.5px}
  .nrow img{width:76px;height:76px;object-fit:cover;border-radius:8px;background:#131316;flex:none}
  .nrow .nt{font-size:14px;font-weight:600;line-height:1.45}
  .nrow .nm{font-size:12px;color:var(--faint);margin-top:3px}
  .tag{display:inline-block;font-size:10.5px;font-weight:700;background:var(--green-bg);color:#c8ec6e;padding:1px 8px;border-radius:99px;margin-right:6px;vertical-align:1px}
  .tag.red{background:#5b2326;color:#f3b8ba}
  .ritem{display:flex;gap:11px;align-items:center;padding:8px 8px;border-radius:10px;transition:background .15s}
  .ritem:hover{background:#1e1e23}
  .ritem img{width:64px;height:64px;object-fit:cover;border-radius:6px;background:#131316;flex:none}
  .rnum{font-size:21px;font-weight:800;width:27px;text-align:center;color:var(--faint);flex:none;font-style:italic}
  .rnum.top{color:var(--green)}
  .ritem .rn{font-size:13px;font-weight:600;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .ritem .rp{font-size:12px;color:var(--sub)}
  .hero{position:relative}
  html,body{overflow-x:clip}
  .heroh{margin:26px 0 12px}
  .topslot{display:block;position:relative;overflow:hidden;width:100vw;margin-left:calc(50% - 50vw);background:#293543}
  .topslot img{width:min(840px,100%);height:auto;display:block;margin:0 auto}
  .adtag{position:absolute;top:8px;right:8px;background:rgba(10,10,12,.55);color:#cfcfd4;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;letter-spacing:.06em}
  .hero-track{display:flex;gap:12px;transition:transform .65s cubic-bezier(.3,1.25,.4,1)}
  .hslide{flex:0 0 90%;min-width:0;display:flex;border-radius:14px;position:relative;opacity:.35;filter:saturate(.55) brightness(.7);transition:opacity .45s,filter .45s}
  .hslide.active{opacity:1;filter:none}
  @media (min-width:900px){.hslide{flex-basis:84%}}
  @media (max-width:899px){.hslide{flex-direction:column}}
  .hslide .himg{position:relative;aspect-ratio:16/8;background:#131316;display:block;overflow:hidden;border-radius:14px 14px 0 0}
  .hslide .himg img{position:absolute;inset:0;width:100%;height:100%}
  .hslide .himg .hbg{object-fit:cover;filter:blur(26px) brightness(.5);transform:scale(1.3)}
  .hslide .himg .hfg{object-fit:contain;object-position:center}
  .hslide .hbody{padding:10px 14px 12px;display:flex;flex-direction:column;height:98px;box-sizing:border-box}
  .hslide .hprice2{display:flex;align-items:center;gap:7px;flex:none;margin-top:auto;align-self:flex-end}
  .hslide .hprice2 .disc{position:static}
  .hslide .hprice2 .was{display:inline;font-size:12.5px;color:var(--faint)}
  .hslide .hprice2 .price{font-size:17px}
  .hslide .hprice2 .price.free{color:var(--text)}
  .hslide .hname{font-size:17px;font-weight:800;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .hsub{display:flex;gap:8px;align-items:baseline;margin-top:3px;min-width:0}
  .hsub .hstatus{margin-top:0;white-space:nowrap}
  .hshop{font-size:12.5px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .hslide .hprice{display:flex;align-items:center;gap:10px;margin-top:6px;flex-wrap:wrap}
  .rib{position:absolute;left:10px;bottom:10px;color:#fff;font-weight:800;font-size:12.5px;padding:3px 12px;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,.45);z-index:2}
  .rib.sale{background:#e04347}
  .rib.act{background:#3a3a41}
  .rib.new{background:var(--accent);color:#fff}
  .hslide .rib{left:0;bottom:0;border-radius:0;padding:3px 12px;box-shadow:none}
  @media (min-width:900px){.hslide .rib{border-bottom-left-radius:14px}}
  .hslide .himg img{border-radius:inherit}
  .hmeta{display:none}
  @media (min-width:900px){.hmeta{display:flex;flex-wrap:wrap;gap:6px 7px;align-items:center;margin-top:12px}}
  .htag{background:#26262c;color:var(--sub);border:1px solid var(--line);border-radius:999px;padding:2px 9px;font-size:11.5px;font-weight:600}
  a.htag{color:var(--sub);text-decoration:none;max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  a.htag:hover{color:var(--text)}
  .hrel-g{font-size:11px;font-weight:800;color:var(--sub);margin-left:6px}
  .hthumbs{display:inline-flex;gap:5px;vertical-align:middle}
  .hrelrow{flex-basis:100%;display:flex;align-items:center;gap:7px;margin-top:9px}
  .hrelrow .hrel-g{margin-left:0}
  .hthumb{width:64px;height:64px;border-radius:8px;overflow:hidden;flex:none;border:1px solid var(--line);background:#131316;display:block}
  .hthumb img{width:100%;height:100%;object-fit:cover;display:block}
  html[data-theme="light"] .htag{background:#ececf1}
  .fnote2{font-size:12px;color:var(--faint);margin:-8px 0 10px}
  .ftag{position:absolute;top:-1px;left:-1px;background:rgba(23,23,26,.88);color:#fff;font-size:11px;line-height:1.3;font-weight:800;letter-spacing:.05em;padding:4px 8px 4px;z-index:2;pointer-events:none}
  .ftag.new{background:#fc4d50}
  .spark{margin-top:2px}
  .spark svg{display:block;width:100%;height:28px}
  .fmeta{font-size:11px;color:var(--faint);margin-left:auto}
  .tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}
  .tile{background:linear-gradient(135deg,#232329,#17171a);border:1px solid var(--border);border-radius:8px;padding:15px 14px;text-align:left;cursor:pointer;color:var(--text);font-family:inherit;transition:border-color .15s,transform .15s}
  .tile:hover{border-color:var(--border2)}
  .tile:active{transform:scale(.97)}
  .tile .tt{font-size:15px;font-weight:800;display:block}
  .tile .ts{font-size:11.5px;color:var(--sub);display:block;margin-top:3px}
  .hreason{font-size:12px;color:var(--sub);margin-top:9px;line-height:1.6}
  .pp-inner{max-width:900px;margin:0 auto;padding:4px 20px 90px}
  .pp-top{display:flex;gap:18px;align-items:flex-start}
  .pp-viscol{flex:0 0 300px;display:flex;flex-direction:column;gap:8px;min-width:0}
  .pp-imgwrap{position:relative;width:100%;aspect-ratio:1/1;border-radius:10px;overflow:hidden;background:#131316}
  .pp-imgcount{position:absolute;right:8px;bottom:8px;background:rgba(0,0,0,.65);color:#fff;font-size:11px;font-weight:700;border-radius:999px;padding:2px 8px;z-index:2}
  .pp-imgcount[hidden]{display:none}
  .pp-thumbs{display:flex;gap:6px;overflow-x:auto;padding-bottom:2px;scrollbar-width:thin}
  .pp-thumbs[hidden]{display:none}
  .pp-thumbs button{flex:0 0 52px;width:52px;height:52px;border-radius:8px;overflow:hidden;border:2px solid transparent;padding:0;background:#1a1a1e;cursor:pointer}
  .pp-thumbs button.on{border-color:#fc4d50}
  .pp-thumbs img{width:100%;height:100%;object-fit:cover;display:block}
  .pp-imgwrap .hbg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:blur(22px) brightness(.5);transform:scale(1.3)}
  .pp-imgwrap .hfg{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}
  @media (max-width:640px){.pp-top{flex-direction:column}.pp-viscol{flex:none;width:100%}}
  .pp-name{font-size:19px;font-weight:800;line-height:1.45}
  .pp-shop{font-size:13px;color:var(--sub);margin-top:3px}
  .pp-meta{display:flex;align-items:center;gap:7px 8px;flex-wrap:wrap;margin-top:10px}
  .pp-likes{display:inline-flex;align-items:center;gap:5px;font-size:13.5px;font-weight:700;margin-right:6px}
  .pp-likes svg{width:15px;height:15px;fill:none;stroke:#f2506e;stroke-width:2}
  #ppSameSec{display:flex;align-items:center;gap:10px}
  #ppSameSec .pp-more{margin:0 0 0 auto;background:none;border:1px solid var(--line);color:var(--sub);border-radius:999px;padding:3px 12px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit}
  .cshop[data-shop],.pp-shop[data-shop]{cursor:pointer}
  .cshop[data-shop]:hover,.pp-shop[data-shop]:hover{text-decoration:underline}
  button.srow{background:none;border:none;padding:0;font:inherit;cursor:pointer;text-align:left}
  .pp-tag{background:#1d1d22;color:var(--sub);border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit}
  .pp-tag.cat{position:relative;background:linear-gradient(90deg,#4a6f92,#5b7f5e);border:1px solid rgba(255,255,255,.55);color:#fff;border-radius:6px;padding:4px 11px 4px 18px;font-weight:800;letter-spacing:.05em}
  .pp-tag.cat::before{content:"";position:absolute;left:5px;top:50%;transform:translateY(-50%);width:6px;height:6px;border-radius:50%;background:var(--bg);border:1.5px solid rgba(255,255,255,.8)}
  html[data-theme="light"] .pp-tag{background:#ececf1}
  html[data-theme="light"] .pp-tag.cat{background:linear-gradient(90deg,#93b9dd,#8fc79b);border-color:#6f9a7d;color:#264434}
  html[data-theme="light"] .pp-tag.cat::before{border-color:#52705e}
  .pp-actions{display:flex;gap:9px;margin-top:14px;flex-wrap:wrap}
  .pp-booth{background:#e04347;color:#fff;font-weight:700;font-size:13.5px;padding:9px 18px;border-radius:8px;text-decoration:none}
  .pp-bmbtn{background:#232329;color:var(--text);border:1px solid var(--border2);font-weight:700;font-size:13.5px;line-height:1;padding:9px 16px;border-radius:8px;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;justify-content:center;gap:7px;width:200px;box-sizing:border-box}
  .pp-bmbtn svg{width:17px;height:17px;display:block;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;flex:none}
  .pp-recbtn,.pp-sharebtn{background:#232329;color:var(--text);border:1px solid var(--border2);font-weight:700;font-size:13.5px;line-height:1;padding:9px 16px;border-radius:8px;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;justify-content:center;gap:7px;box-sizing:border-box}
  .pp-recbtn svg,.pp-sharebtn svg{width:17px;height:17px;display:block;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;flex:none}
  .pp-recbtn .pp-recn{font-variant-numeric:tabular-nums;font-weight:700}
  .pp-recbtn [hidden]{display:none!important}
  .pp-recbtn.on{background:#3a2729;border-color:#9c4a4e;color:#ff8f93}
  .pp-recbtn.on svg{fill:currentColor}
  .newsbar{text-align:right;margin:8px 2px 0;font-size:13px}
  .newsbar a{color:var(--sub);text-decoration:none}
  .noimg{display:flex;align-items:center;justify-content:center;width:100%;height:100%;min-height:110px;background:#1b1b1f}
  .noimg svg{width:36px;height:36px;stroke:#2c2c33;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
  .pp-varlabel{font-size:12px;color:var(--sub);font-weight:700;margin:10px 0 0}
  .varchips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 2px}
  .varsel{width:100%;margin:8px 0 2px;background:#1b1b1f;color:var(--text);border:1px solid var(--border2);border-radius:8px;padding:9px 10px;font-size:13.5px;font-family:inherit}
  .outlb{background:#ffdf00;color:#000;padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;vertical-align:2px;white-space:nowrap}
  .cmpoutl{color:#e8c547;font-size:12px;font-weight:700;margin:0 0 8px}
  #cmpChart{position:relative}
  .cmpranges{display:flex;gap:2px;flex-wrap:wrap;margin-top:10px;border-bottom:1px solid var(--border)}
  .cmprange{background:none;color:var(--sub);border:none;border-bottom:2px solid transparent;margin-bottom:-1px;font-size:13px;font-weight:400;padding:7px 13px;cursor:pointer;font-family:inherit}
  .cmprange.on{color:#fff;font-weight:700;border-bottom-color:var(--accent)}
  .pp-ranges{position:sticky;top:-17px;z-index:5;background:var(--bg);margin:0 0 10px;padding-top:8px}
  .chartbox{position:relative}
  .chartbox svg,#cmpChart svg{-webkit-touch-callout:none;user-select:none;touch-action:pan-y}
  @media (max-width:700px){
    .chartbox,#cmpChart{overflow-x:auto;scrollbar-width:thin;scrollbar-color:#3d3d44 transparent}
    .chartbox svg,#cmpChart svg{width:720px;max-width:none;height:auto}
  }
  .chExpand{width:30px;height:30px;flex:none;border-radius:8px;background:rgba(23,23,26,.88);border:1px solid var(--border2);display:none;align-items:center;justify-content:center;cursor:pointer}
  .chExpand svg{width:16px;height:16px;fill:none;stroke:#ececee;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
  .pp-varhead .chExpand{margin-left:auto}
  @media (max-width:700px){.chExpand{display:flex}}
  #chartPop{position:fixed;inset:0;z-index:80;background:rgba(6,6,8,.88);display:flex;align-items:center;justify-content:center;padding:12px;touch-action:none;overscroll-behavior:contain}
  #chartPop[hidden]{display:none}
  .cp-box{background:#17171a;border:1px solid var(--border2);border-radius:14px;width:100%;max-width:880px;max-height:94vh;overflow-y:auto;padding:14px;overscroll-behavior:contain}
  .cp-head{display:flex;align-items:center;gap:10px;margin-bottom:8px}
  #cpTitle{font-size:15px;font-weight:700;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #cpClose{width:32px;height:32px;flex:none;border-radius:8px;background:#232329;border:1px solid var(--border2);display:flex;align-items:center;justify-content:center;cursor:pointer}
  #cpClose svg{width:16px;height:16px;fill:none;stroke:#ececee;stroke-width:2;stroke-linecap:round}
  .cpchart{position:relative}
  .cpchart svg{width:100%;height:auto;display:block;-webkit-touch-callout:none;user-select:none;touch-action:pan-y}
  #cpRanges{margin-top:10px}
  #cpReadout{display:none}
  #cpReadout.on{display:block;height:76px;margin-bottom:6px}
  #cpReadout .hvTip{position:static}
  #cmpTip,#cpCmpTip,.hvTip{position:absolute;top:8px;display:none;pointer-events:none;background:#101012;border:1px solid var(--border2);border-radius:10px;padding:8px 10px;font-size:12px;pointer-events:none;z-index:3;min-width:180px;max-width:300px;box-shadow:0 8px 24px rgba(0,0,0,.45)}
  .cmtd{color:var(--sub);font-weight:700;margin-bottom:5px}
  .cmtr{display:flex;align-items:center;gap:6px;padding:1.5px 0}
  .cmtn{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--sub)}
  #cmpTip,#cpCmpTip{max-width:min(320px,calc(100% - 16px))}
  #cmpTip.wide{max-width:min(560px,calc(100% - 16px))}
  #cmpTip .cmtrows{display:grid;grid-template-columns:1fr;gap:0 14px}
  #cmpTip.wide .cmtrows{grid-template-columns:1fr 1fr}
  .cmtr b{flex:none}
  .cmmore{color:var(--faint);font-size:11px}
  .cmpchip:not(.on){opacity:.45}
  .pp-varblock{position:relative;background:#17171a;border:1px solid #26262c;border-radius:12px;padding:14px 16px;margin:0 0 14px}
  .pp-varhead{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
  .pp-varname{font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
  .pp-varprice{font-weight:700;font-size:15px}
  .pp-varblock .pstats{margin:0 0 8px}
  .pp-changes{margin-top:8px}
  .cmplegend{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
  .cmpchip{display:inline-flex;align-items:center;gap:6px;background:#1b1b1f;border:1px solid var(--border2);color:var(--sub);border-radius:999px;padding:5px 10px;font-size:12px;cursor:pointer;font-family:inherit;opacity:.55}
  .cmpchip.on{color:var(--text);border-color:#3d3d44;opacity:1}
  .cmpdot{width:9px;height:9px;border-radius:50%;flex:none}
  .pp-bmbtn.on svg{fill:currentColor}
  .pp-bmbtn.on{background:#33302a;border-color:#8a6d1f;color:#f5c542}
  .bmflag{position:absolute;top:0;left:0;z-index:5;pointer-events:none;color:#17171a;background:#f5c542;width:24px;height:24px;display:flex;align-items:center;justify-content:center}
  .hslide>.bmflag{border-radius:14px 0 0 0}
  .bmflag svg{width:14px;height:14px;display:block;fill:currentColor}
  .bmflag[hidden]{display:none !important}
  .bmflag.r{left:auto;right:6px}
  .bmflag.u{top:32px;left:8px}
  .bmflag.u2{top:24px;left:0}
  .bthw{position:relative;flex:none;display:block}
  .brow .bmflag{top:-3px;left:1px;background:none;width:auto;height:auto;display:block;color:#f5c542;filter:drop-shadow(0 1px 3px rgba(0,0,0,.65))}
  .brow .bmflag svg{width:24px;height:24px}
  .pcard .pimgw{position:relative;display:block}
  .pcard .bmflag{top:0;left:0;border-radius:10px 0 0 0}
  .pp-sec{font-size:15px;font-weight:800;margin:24px 0 10px}
  #ppRel:not(:empty){padding-top:24px}
  #ppRel>section:first-child>.pp-sec{margin-top:0}
  .chgtable{display:grid;grid-template-columns:86px 46px minmax(0,1fr) minmax(0,1fr) auto;column-gap:10px;font-size:13px;padding:0 2px}
  .chgtable>*{padding:8px 0;border-bottom:1px solid var(--border);white-space:nowrap;display:flex;align-items:center;min-width:0}
  .chgtable .cd{color:var(--faint)}
  .chgtable .cb,.chgtable .ca,.chgtable .cr{font-variant-numeric:tabular-nums;justify-content:flex-end}
  .chgtable .chh{font-size:11px;color:var(--faint);padding:4px 0}
  @media (max-width:560px){.chgtable{grid-template-columns:72px 40px minmax(0,1fr) minmax(0,1fr) auto;column-gap:7px;font-size:12px;padding:0}.chgtable .cd{font-size:11.5px}}
  .pp-toggle{display:inline-flex;align-items:center;gap:7px;background:none;border:none;color:var(--sub);font-size:12.5px;font-weight:700;cursor:pointer;font-family:inherit;padding:4px 2px}
  .pp-toggle:hover{color:var(--text)}
  .pp-toggle .car{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:6px solid var(--sub);transition:transform .2s;flex:none}
  .pp-toggle.open .car{transform:rotate(180deg)}
  .down{color:#a4d007;font-weight:700}
  .up{color:#fc4d50;font-weight:700}
  .prow{display:flex;gap:10px;overflow-x:auto;padding-bottom:8px;scrollbar-width:thin;scrollbar-color:#3d3d44 transparent}
  #personal{margin:30px 0 38px}
  #personal:empty{display:none}
  .pmods{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(340px,100%),1fr));gap:28px}
  .pmod-h{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
  .pmod-h h2{margin:0}
  .bmmore{flex:none;background:#dcdce1;color:#17171a;font-weight:700;font-size:12.5px;border:none;border-radius:6px;padding:8px 16px;cursor:pointer;text-decoration:none;font-family:inherit}
  .bmmore:hover,.bmmore:focus,.bmmore:active{background:#fff;color:#17171a}
  html[data-theme="light"] .bmmore{background:#e2e2e8}
  html[data-theme="light"] .bmmore:hover{background:#d5d5dd}
  .bmpanel{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:14px}
  .pmod-f{display:flex;justify-content:flex-end;margin-top:10px}
  .pmod{min-width:0;max-width:470px}
  .bmgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px 12px}
  .bmgrid>*{min-width:0}
  .bmgrid.frozen .bmcard:nth-child(n+5){display:none}
  .bmcard{display:block;text-decoration:none;color:var(--text);min-width:0}
  .bmcard .bmimg{position:relative;display:block;border-radius:8px;overflow:hidden;background:#131316}
  .bmcard .bmimg img{width:100%;aspect-ratio:1/1;object-fit:cover;display:block}
  .bmcard .bmimg .pph{display:flex;align-items:center;justify-content:center;width:100%;aspect-ratio:1/1;background:#1b1b1f}
  .bmcard .bmimg .pph svg{width:34px;height:34px;stroke:#2c2c33;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
  .bmcard .bmflag{top:0;left:0;border-radius:8px 0 0 0}
  /* bookmark-price-layout-v1: let badges wrap, never overlap price values. */
  .bmstrip{display:flex;flex-wrap:wrap;align-items:stretch;min-height:42px;height:auto;margin-top:0;min-width:0;background:#26262c}
  .bmstrip .discst{flex:0 1 auto;max-width:100%;box-sizing:border-box;min-height:42px;height:auto;font-size:13px;padding:6px;overflow-wrap:anywhere}
  .bmstrip .saletag{display:inline-flex;align-items:center;flex:0 1 auto;max-width:100%;box-sizing:border-box;min-height:42px;height:auto;background:var(--green-bg);color:#c8ec6e;font-weight:800;font-size:12.5px;padding:6px;overflow-wrap:anywhere}
  .bmvals{flex:1 1 5.5rem;box-sizing:border-box;background:#26262c;display:flex;flex-direction:column;align-items:flex-end;justify-content:center;gap:2px;padding:4px 6px;min-width:0;max-width:100%}
  html[data-theme="light"] .bmvals{background:#e8e8ed}
  .bmvals .was{background:none;padding:0;height:auto;font-size:12.5px;max-width:100%;white-space:normal;overflow-wrap:anywhere;line-height:1.15;text-align:right}
  .bmvals .price{font-weight:800;font-size:14.5px;max-width:100%;white-space:normal;overflow-wrap:anywhere;line-height:1.2;text-align:right}
  .bmvals .price .free{white-space:normal;overflow-wrap:anywhere}
  html[data-theme="light"] .bmstrip{background:#e8e8ed}
  span.was.wl{font-size:11px}
  span.was.wxl{font-size:9.5px}
  .bmvals .was.wl{font-size:11px}
  .bmvals .was.wxl{font-size:9.5px}
  .caprow .was.wl{font-size:10.5px}
  .caprow .was.wxl{font-size:9px}
  .bprice .bstack .was.wl{font-size:9.5px}
  .bprice .bstack .was.wxl{font-size:8.5px}
  .mcell .scrim .was.wl{font-size:10px}
  .mcell .scrim .was.wxl{font-size:9px}
  .bmvals .price.wl{font-size:12.5px}
  .bmvals .price.wxl{font-size:11px}
  .caprow .price.wl{font-size:12px}
  .caprow .price.wxl{font-size:10.5px}
  .bmname{display:block;font-size:12px;font-weight:600;line-height:1.35;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .prow::-webkit-scrollbar{height:6px}
  .prow::-webkit-scrollbar-track{background:transparent}
  .prow::-webkit-scrollbar-thumb{background:#3d3d44;border-radius:99px}
  .prow::-webkit-scrollbar-thumb:hover{background:#4b4b53}
  .prow::-webkit-scrollbar-button{display:none;width:0;height:0}
  html{background:#101012;scrollbar-width:thin;scrollbar-color:#3d3d44 #101012}
  body::-webkit-scrollbar{width:10px}
  body::-webkit-scrollbar-track{background:#101012}
  body::-webkit-scrollbar-thumb{background:#3d3d44;border-radius:99px;border:2px solid #101012}
  .spage{scrollbar-width:thin;scrollbar-color:#3d3d44 transparent}
  body.veil header,body.veil main{display:none}
  .spage::-webkit-scrollbar{width:8px}
  .spage::-webkit-scrollbar-track{background:transparent}
  .spage::-webkit-scrollbar-thumb{background:#3d3d44;border-radius:99px}
  .pcard{flex:0 0 138px;display:flex;flex-direction:column;background:#17171a;border:1px solid var(--border);border-radius:10px;overflow:visible;text-decoration:none;color:var(--text);position:relative}
  .pcard img{width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:#131316;border-radius:10px 10px 0 0}
  .pcard .pph{display:flex;align-items:center;justify-content:center;width:100%;aspect-ratio:1/1;background:#1b1b1f;border-radius:10px 10px 0 0}
  .pcard .pph svg{width:34px;height:34px;stroke:#2c2c33;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
  .pcard .pb{display:flex;flex-direction:column;flex:1;padding:8px 9px}
  .pcard .pn{display:block;font-size:11.5px;font-weight:600;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:32px}
  .pcard .pp2{display:flex;gap:6px;align-items:center;margin-top:auto;padding-top:5px}
  .pcard .price.solo{display:inline-flex;align-items:center;height:24px;background:#26262c;padding:0 7px;font-size:13px;font-weight:600}
  .vchip{background:#4c6b22;color:#c8ec6e;font-size:10px;font-weight:700;padding:1.5px 6px;border-radius:4px;white-space:nowrap}
  .browse2{margin-top:28px}
  .btabs{display:flex;gap:2px;overflow-x:auto;border-bottom:1px solid var(--border);scrollbar-width:none}
  .catsec{margin:36px 0 8px}
  .catwrap{position:relative}
  .catbtn{position:absolute;top:50%;transform:translateY(-50%);z-index:6;width:44px;height:44px;border-radius:50%;background:var(--panel);border:1px solid var(--border2);color:var(--text);cursor:pointer;display:none;align-items:center;justify-content:center;box-shadow:0 4px 16px rgba(0,0,0,.35);font-family:inherit}
  .catbtn svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
  .catbtn.prev{left:-14px}
  .catbtn.next{right:-14px}
  .catbtn.off{opacity:.35;pointer-events:none}
  @media (min-width:900px){.catbtn{display:flex}}
  .catrail{display:flex;gap:12px;overflow-x:auto;padding:8px 2px 14px;scrollbar-width:none;-webkit-overflow-scrolling:touch}
  .catrail::-webkit-scrollbar{display:none}
  .updrail{display:flex;gap:12px;overflow-x:auto;padding:8px 2px 14px;scrollbar-width:none;-webkit-overflow-scrolling:touch}
  .updrail::-webkit-scrollbar{display:none}
  .ucard{flex:0 0 236px;width:236px;background:var(--panel);border:1px solid var(--border);border-radius:14px;overflow:hidden;text-decoration:none;color:var(--text);display:flex;flex-direction:column}
  .ucard .uimg{position:relative;display:block;aspect-ratio:16/10;background:var(--panel2);overflow:hidden}
  .ucard .uimg img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;object-position:center}
  .ucard .uimg .ubg{object-fit:cover;filter:blur(22px) brightness(.55);transform:scale(1.3)}
  .ucard .uimg .ufg{object-fit:contain;object-position:center}
  .ucard .ubody{padding:10px 12px 12px;display:flex;flex-direction:column;gap:4px;flex:1}
  .ucard .uname{font-weight:700;font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .ucard .ushop{font-size:11.5px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .ucard .uupd{margin-top:5px;display:flex;align-items:center;gap:6px;min-width:0}
  .ucard .uchip{flex:0 0 auto;font-size:10.5px;font-weight:800;color:#fff;background:#4c6b22;padding:2px 7px;border-radius:4px;letter-spacing:.03em}
  .ucard .uvar{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .ucard .umore{flex:0 0 auto;font-size:11px;font-weight:700;color:var(--sub)}
  .ucard .udate{font-size:11px;color:var(--sub)}
  .ucard .uprice{margin-top:auto;padding-top:8px;display:flex;align-items:stretch;gap:0}
  .ucard .udisc{font-size:12.5px;font-weight:800;color:#fff;background:#4c6b22;display:inline-flex;align-items:center;padding:4px 7px}
  .ucard .uwas{background:#26262c;color:var(--faint);font-size:12.5px;display:inline-flex;align-items:center;padding:4px 2px 4px 8px}
  .ucard .upr{background:#26262c;color:#f2f2f5;font-size:15.5px;font-weight:700;display:inline-flex;align-items:center;padding:4px 9px 4px 5px;flex:1}
  .ucard .upr.free{color:#9ecb45}
  .ucard .upr.solo{padding-left:9px}
  html[data-theme="light"] .ucard .upr{background:#eeeef1;color:#1c1c21}
  html[data-theme="light"] .ucard .uwas{background:#eeeef1;color:#83838c}
  html[data-theme="light"] .ucard .upr.free{color:#4c6b22}
  .shcard{flex:0 0 300px;scroll-snap-align:start;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column;text-align:left}
  .shcard .simg{position:relative;display:block;aspect-ratio:16/10;overflow:hidden;background:#26262c;flex:0 0 auto}
  .shcard .simg img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;object-position:center}
  .shcard .simg .sbg{object-fit:cover;filter:blur(22px) brightness(.55);transform:scale(1.3)}
  .shcard .sbody{padding:10px 12px 12px;display:flex;flex-direction:column;gap:7px;flex:1}
  .shcard .srow{display:flex;align-items:center;gap:9px;text-decoration:none;color:inherit;min-width:0}
  .shcard .sava{flex:0 0 auto;width:34px;height:34px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:15px;color:#fff;overflow:hidden}
  .shcard .sava img{width:100%;height:100%;object-fit:cover}
  .shcard .snm{font-size:13.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .shcard .scnt{font-size:11px;color:var(--sub)}
  .shcard .snew{font-size:11.5px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .shcard .snew .stag{color:var(--gold);font-weight:700;margin-right:5px}
  .shcard .stop{margin-top:auto;border-top:1px solid var(--line);padding-top:8px;text-decoration:none;color:inherit;display:block}
  .shcard .stop .tnm{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:6px}
  .shcard .spr{display:flex;align-items:stretch;border-radius:8px;overflow:hidden;background:#26262c;color:#f2f2f5;font-size:12.5px;font-weight:700}
  .shcard .spr .sg{background:var(--green);color:#0c1a05;display:flex;align-items:center;padding:5px 7px}
  .shcard .spr .sgt{color:var(--green);display:flex;align-items:center;padding:5px 8px}
  .shcard .spr .scur{margin-left:auto;display:flex;align-items:center;padding:5px 9px;font-size:13.5px}
  .shcard .spr .swas{position:relative;color:#9a9aa2;font-size:11px;font-weight:400;display:flex;align-items:center;padding:5px 2px 5px 8px}
  .shcard .spr .swas .ww{position:relative;display:inline-block}
  .shcard .spr .swas .ww::after{content:"";position:absolute;left:-2px;right:-2px;top:50%;height:2px;background:currentColor;transform:rotate(-11deg);border-radius:1px}
  .shcard .spr.solo .scur{margin-left:0}
  html[data-theme="light"] .shcard .spr{background:#eeeef1;color:#1c1c21}
  html[data-theme="light"] .shcard .spr .swas{color:#83838c}
  .upddots{display:flex;gap:6px;justify-content:center;margin:8px 0 0}
  .upddots button{width:8px;height:8px;border-radius:99px;border:none;background:rgba(255,255,255,.45);cursor:pointer;padding:0;transition:all .4s cubic-bezier(.34,1.5,.64,1)}
  .upddots button.on{width:22px;background:#fff}
  html[data-theme="light"] .upddots button{background:rgba(29,29,32,.28)}
  html[data-theme="light"] .upddots button.on{background:#1d1d20}
  .catcard{position:relative;flex:0 0 auto;width:172px;aspect-ratio:4/5;border:none;padding:0;border-radius:14px;overflow:hidden;cursor:pointer;background:var(--panel);font-family:inherit}
  .catcard .ccflat{position:absolute;left:-50%;top:-82%;width:200%;height:245%;transform:perspective(360px) rotateX(57deg) rotateZ(-11deg);display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);gap:1.2%}
  .catcard .ccflat img{width:100%;height:100%;object-fit:cover;display:block;border-radius:6px}
  .catcard .cctint{position:absolute;inset:0;background:linear-gradient(160deg,hsla(var(--h,210),70%,45%,.40),hsla(var(--h,210),80%,20%,.55))}
  .cclabel{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);background:#fff;color:#141416;font-size:13.5px;font-weight:700;line-height:1.25;padding:7px 13px;border-radius:999px;white-space:nowrap;box-shadow:0 2px 10px rgba(0,0,0,.35);max-width:92%;overflow:hidden;text-overflow:ellipsis}
  @media (max-width:899px){.catcard{width:148px}.cclabel{font-size:12.5px}}
  .btabs::-webkit-scrollbar{display:none}
  .btab{background:none;border:none;color:var(--sub);font-size:15.5px;font-weight:700;font-family:inherit;padding:9px 13px;cursor:pointer;white-space:nowrap;border-bottom:2px solid transparent;margin-bottom:-1px}
  .btab:hover{color:var(--text)}
  .btab.on{color:var(--text);border-bottom-color:#fc4d50}
  .bwrap{display:grid;grid-template-columns:1fr 330px;gap:18px;margin-top:14px;align-items:start}
  .bwrap>*{min-width:0}
  @media (max-width:899px){.bwrap{grid-template-columns:1fr}.bprev{display:none}}
  .brow{display:flex;gap:13px;align-items:center;background:#1b1b1f;padding:9px 12px;text-decoration:none;color:var(--text);position:relative}
  .brow:nth-child(even){background:#17171a}
  .brow:hover,.brow.sel{background:#26262c}
  .brow img{width:86px;height:86px;object-fit:cover;border-radius:6px;background:#131316;flex:none}
  .bthph{flex:none;width:86px;height:86px;border-radius:6px;background:#17171a;display:inline-flex;align-items:center;justify-content:center}
  .bthph svg{width:27px;height:27px;stroke:#3d3d44;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
  .phcard{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
  .phcard svg{width:36px;height:36px;stroke:#2c2c33;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
  .bmain{flex:1;min-width:0}
  .bname{display:block;font-size:14.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .bshop{display:block;font-size:12px;color:var(--sub);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .bnote{display:block;font-size:12px;color:var(--faint);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .bsub{display:block;font-size:12px;color:var(--sub);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .bprice{display:inline-flex;align-items:stretch;text-align:right;flex:none}
  .bprice .discst{height:auto;align-items:center;justify-content:center;text-align:center}
  .bprice .bstack{display:inline-flex;flex-direction:column;justify-content:center;background:#26262c;padding:3px 8px}
  .bprice .bstack .was{display:block;height:auto;background:none;padding:0;font-size:10.5px;color:var(--faint);text-align:right;line-height:1.3;align-self:flex-end}
  .bprice .bstack .price{display:block;height:auto;background:none;padding:0;font-size:14.5px;text-align:right;line-height:1.3}
  @media (max-width:560px){
    .brow{gap:9px;padding:8px 10px}
    .brow img{width:60px;height:60px;border-radius:5px}
    .bthph{width:60px;height:60px;border-radius:5px}
    .bname{font-size:13.5px}
  }
  .bprev{background:linear-gradient(180deg,#202025,#1a1a1e);border:1px solid var(--border);border-radius:10px;padding:14px;position:sticky;top:14px;box-shadow:0 4px 16px rgba(0,0,0,.4)}
  .bpname{font-size:16px;font-weight:800;line-height:1.45}
  .bpmeta{font-size:12px;color:var(--sub);margin-top:3px}
  .bpchips{display:flex;gap:5px;flex-wrap:wrap;margin-top:9px}
  .bpchip{background:#2b2b31;color:#d6d6db;font-size:11px;padding:2.5px 8px;border-radius:4px}
  .bpchip.sale{background:#4c6b22;color:#c8ec6e}
  .bpimg{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:8px;background:#131316;display:block;margin-top:11px}
  .bpspark{margin-top:11px}
  .bpspark .cap{font-size:11px;color:var(--faint);margin-bottom:3px}
  .bpspark svg{display:block;width:100%;height:44px;background:#131316;border-radius:6px}
  .bpchart svg{height:auto}
  .bpchart-load{aspect-ratio:340/118;background:#131316;border-radius:6px}
  .spark.kp svg{height:auto;background:#131316;border-radius:5px}
  .bprow{display:flex;gap:0;align-items:stretch;margin-top:11px}
  .bprow .lowest{margin-left:8px;align-self:center}
  .rib.low{background:#4c6b22}
  .rib.free{background:#e8b400;color:#221a00}
  .htags{font-size:12px;color:#4fb3a5;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .hero-dots{position:static;display:flex;gap:6px;justify-content:center;margin:10px 0 18px}
  .hero-dots button{width:8px;height:8px;border-radius:99px;border:none;background:rgba(255,255,255,.45);cursor:pointer;padding:0;transition:all .4s cubic-bezier(.34,1.5,.64,1)}
  .hero-dots button.on{width:22px;background:#fff}
  .card .thumbwrap .rib{font-size:11px;padding:2px 8px;left:8px;bottom:8px}
  body{padding-bottom:96px}
  .tabbar{position:fixed;margin:0;left:50%;transform:translateX(-50%);bottom:calc(10px + env(safe-area-inset-bottom));width:min(430px,calc(100% - 20px));height:70px;background:transparent;display:flex;align-items:flex-start;justify-content:space-around;padding:9px 10px 0;z-index:60;transition:transform .38s cubic-bezier(.32,1.15,.36,1),opacity .3s}
  #barShape{position:absolute;left:0;top:-30px;width:100%;height:calc(100% + 30px);overflow:visible;z-index:0;filter:drop-shadow(0 14px 22px rgba(0,0,0,.5));pointer-events:none}
  .tspacer{width:64px;flex:none}
  .tabbar button.fab{position:absolute;left:50%;top:-27px;transform:translateX(-50%);width:58px;height:58px;border-radius:50%;background:linear-gradient(135deg,#fc4d50,#d63a3e);color:#fff;box-shadow:0 6px 16px rgba(0,0,0,.35);z-index:3;transition:transform .25s cubic-bezier(.34,1.6,.64,1),filter .2s}
  .tabbar button.fab svg{width:26px;height:26px;stroke:#fff;stroke-width:2.2;opacity:1}
  .tabbar button.fab:active{transform:translateX(-50%) scale(.9)}
  .tabbar button.fab.on{filter:brightness(1.15)}
  .tabbar button.pop svg{animation:bpop .45s cubic-bezier(.34,1.6,.64,1)}
  .tabbar.hide{transform:translateX(-50%) translateY(150%);opacity:0;pointer-events:none}
  .tabbar button{background:none;border:none;color:#a7a7b0;width:60px;height:54px;border-radius:16px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;cursor:pointer;position:relative;z-index:1;transition:transform .2s,color .2s;padding:0;font-family:inherit}
  .tabbar button svg{width:23px;height:23px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;transition:opacity .18s}
  .tabbar button.on{color:#f2f2f4}
  .tabbar button:active{transform:scale(.9)}
  .tlabel{font-size:9.5px;line-height:1.1;white-space:nowrap}
  .tabbar button.on .tlabel{font-weight:700}
  @keyframes bpop{0%{transform:scale(.35)}55%{transform:scale(1.2)}100%{transform:scale(1)}}
  .spage{position:fixed;inset:0;background:var(--bg);z-index:40;overflow-y:auto;overscroll-behavior:contain;padding:16px 16px 112px;transform:translateY(102%);transition:transform .55s cubic-bezier(.32,1.18,.36,1);pointer-events:none}
  .spage.open{transform:none;pointer-events:auto}
  #prodPage{z-index:45}
  .sp-head{display:flex;align-items:center;gap:12px;max-width:1080px;margin:0 auto}
  .sp-back{background:var(--panel);border:1px solid var(--border2);color:var(--text);width:44px;height:44px;border-radius:50%;cursor:pointer;flex:none;transition:transform .2s;display:flex;align-items:center;justify-content:center;position:relative}
  .sp-back::after{content:"";position:absolute;inset:-7px;border-radius:50%}
  .sp-back svg{width:19px;height:19px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
  .sp-back:active{transform:scale(.88)}
  .sp-title{font-size:19px;font-weight:800}
  .sp-share{background:var(--panel);border:1px solid var(--border2);color:var(--text);width:44px;height:44px;border-radius:50%;cursor:pointer;flex:none;display:flex;align-items:center;justify-content:center;margin-left:auto}
  .sp-share svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
  .sp-inner{width:100%;max-width:1080px;min-width:0;margin:0 auto}
  .sp-search{display:flex;min-width:0;max-width:100%;align-items:center;gap:9px;background:var(--panel);border:1px solid var(--border2);border-radius:99px;padding:12px 18px;margin:16px 0 4px;position:relative}
  .sp-clear{position:absolute;right:8px;top:50%;transform:translateY(-50%);width:44px;height:44px;border-radius:50%;background:none;border:none;color:var(--sub);display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0}
  .sp-clear svg{width:19px;height:19px;stroke:currentColor}
  .sp-clear[hidden]{display:none}
  .sp-search svg{width:20px;height:20px;fill:none;stroke:var(--faint);stroke-width:2;stroke-linecap:round;flex:none}
  .sp-search input{background:none;border:none;outline:none;color:var(--text);font-size:16px;width:100%;font-family:inherit;padding-right:42px}
  .sp-sec{font-size:13px;font-weight:700;color:var(--sub);margin:18px 0 8px}
  .kwrap{display:flex;gap:8px;flex-wrap:wrap}
  .kw{background:#1e1e23;border:1px solid var(--border);color:var(--text);border-radius:99px;padding:6px 13px;font-size:12.5px;cursor:pointer;transition:transform .18s}
  .kw.on{background:#4c6b22;color:#c8ec6e;border-color:transparent}
  .kw:active{transform:scale(.93)}
  .sp-count{font-size:12.5px;color:var(--faint);margin:16px 0 8px}
  @media (min-width: 900px){
    body{padding-bottom:40px;padding-left:118px;padding-right:118px}
    header{margin-left:-118px;padding-left:118px;margin-right:-118px;padding-right:118px}
    .tabbar{left:16px;top:50%;bottom:auto;transform:translateY(-50%);width:74px;height:auto;flex-direction:column;align-items:center;justify-content:flex-start;gap:6px;padding:12px 0}
    .tabbar.hide{transform:translateY(-50%) translateX(-180%);opacity:0}
    #barShape{left:0;top:0;width:calc(100% + 30px);height:100%}
    .tspacer{width:auto;height:64px}
    .tabbar button.fab{left:calc(100% - 29px);top:50%;transform:translateY(-50%)}
    .tabbar button.fab:active{transform:translateY(-50%) scale(.9)}
  }
  @media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
  button:focus,a:focus,input:focus,select:focus,textarea:focus,summary:focus,[tabindex]:focus{outline:none}
/* ===== Theme toggle + light theme ===== */
  .themebtn{display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;border-radius:50%;background:var(--card);border:1px solid var(--border2);color:var(--text);cursor:pointer;flex:none;padding:0}
  .themebtn svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
  .themebtn .ic-moon{display:none}
  html[data-theme="light"] .themebtn .ic-sun{display:none}
  html[data-theme="light"] .themebtn .ic-moon{display:block}
  html[data-theme="light"]{color-scheme:light;--bg:#f4f4f6;--panel:#ffffff;--card:#ffffff;--border:#dddde2;--border2:#c6c6cf;--text:#1d1d20;--sub:#5b5b64;--faint:#8b8b94;--accent:#e04347;--red:#e04347;--accent-dim:#c93338;--amber:#c99700;background:#f4f4f6;scrollbar-color:#c2c2cc #f4f4f6}
  html[data-theme="light"] body{background:radial-gradient(1200px 520px at 50% -120px,#e3e3ea 0%,rgba(227,227,234,0) 60%),var(--bg)}
  html[data-theme="light"] header{background:linear-gradient(180deg,#fdfdfd,#f0f0f3)}
  html[data-theme="light"] body::-webkit-scrollbar-thumb{background:#c2c2cc;border-color:#f4f4f6}
  html[data-theme="light"] th,html[data-theme="light"] select,html[data-theme="light"] .shead select{background:#e9e9ee}
  html[data-theme="light"] .thumbwrap,html[data-theme="light"] .drow img,html[data-theme="light"] .phead img,html[data-theme="light"] .spot .simg,html[data-theme="light"] .rtile,html[data-theme="light"] .capimg,html[data-theme="light"] .nrow img,html[data-theme="light"] .ritem img,html[data-theme="light"] .hslide .himg,html[data-theme="light"] .pp-imgwrap,html[data-theme="light"] .pcard img,html[data-theme="light"] .brow img,html[data-theme="light"] .bpimg,html[data-theme="light"] .bpspark svg,html[data-theme="light"] .bpchart-load,html[data-theme="light"] .spark.kp svg,html[data-theme="light"] .mcell .mimg{background:#e4e4ea}
  html[data-theme="light"] #langBtn,html[data-theme="light"] .langmenu,html[data-theme="light"] .spsortmenu,html[data-theme="light"] .sp-sidex,html[data-theme="light"] .sp-freset,html[data-theme="light"] .varsel,html[data-theme="light"] .cmpchip{background:#ffffff}
  html[data-theme="light"] .rtile .pstrip,html[data-theme="light"] .mcell .scrim{background:#f0f0f3}
  html[data-theme="light"] .noimg,html[data-theme="light"] .pcard .pph{background:#ececf0}
  html[data-theme="light"] .brow{background:#ffffff;border:1px solid var(--border)}
  html[data-theme="light"] .crow .price.solo,html[data-theme="light"] .rtile .pwas,html[data-theme="light"] .rtile .pprice,html[data-theme="light"] .caprow .was,html[data-theme="light"] .bprice .was,html[data-theme="light"] .bprow .was,html[data-theme="light"] .mcell .scrim .was,html[data-theme="light"] .caprow .price,html[data-theme="light"] .bprice .price,html[data-theme="light"] .bprow .price,html[data-theme="light"] .mcell .scrim .price,html[data-theme="light"] .pcard .price.solo,html[data-theme="light"] .bprice .bstack,html[data-theme="light"] .badge{background:#e7e7ec}
  html[data-theme="light"] .tab.active{background:#e7e7ec;color:var(--text)}
  html[data-theme="light"] .langmenu button:hover,html[data-theme="light"] .spsortmi:hover{background:#eef0f2}
  html[data-theme="light"] .pp-varblock{background:var(--panel);border-color:var(--border)}
  html[data-theme="light"] .lowtx{color:#4c7a1f}
  html[data-theme="light"] .langmenu button.on::after,html[data-theme="light"] .spsortmi.on::after{color:#4c7a1f}
  html[data-theme="light"] .chartbox,html[data-theme="light"] .prow,html[data-theme="light"] .relrow,html[data-theme="light"] .spage{scrollbar-color:#c2c2cc transparent}
  html[data-theme="light"] .prow::-webkit-scrollbar-thumb,html[data-theme="light"] .relrow::-webkit-scrollbar-thumb,html[data-theme="light"] .spage::-webkit-scrollbar-thumb{background:#c2c2cc}
  html[data-theme="light"] .bthph svg{stroke:#c9c9d2}
  html[data-theme="light"] .cmpchip.on{border-color:var(--border2)}
  html[data-theme="light"] .railbar{background:#d8d8df}
  html[data-theme="light"] .tile{background:linear-gradient(135deg,#ffffff,#eef0f2)}
  html[data-theme="light"] .pp-bmbtn,html[data-theme="light"] #cpClose{background:#f0f0f3}
  html[data-theme="light"] #cpClose svg{stroke:#3c3c43}
  html[data-theme="light"] .pp-recbtn,html[data-theme="light"] .pp-sharebtn{background:#f0f0f3}
  html[data-theme="light"] .pp-recbtn.on{background:#fdeeee;border-color:#e3a7ab;color:#c93a3f}
  html[data-theme="light"] tbody tr:hover,html[data-theme="light"] .ritem:hover{background:#f0f0f3}
  html[data-theme="light"] .kw{background:#f0f0f3}
  html[data-theme="light"] .kw.on{background:#4c6b22;color:#c8ec6e;border-color:transparent}
  html[data-theme="light"] #spPrice::-webkit-slider-runnable-track,html[data-theme="light"] #spPrice::-moz-range-track{background:#cfcfd8}
  html[data-theme="light"] .rib.act{background:#3a3a41}
  html[data-theme="light"] .noimg svg,html[data-theme="light"] .pcard .pph svg,html[data-theme="light"] .phcard svg{stroke:#c4c4cd}
  html[data-theme="light"] .rtile .pprice.free{color:var(--text)}
  html[data-theme="light"] #spSortBtn{background:#ffffff}
  html[data-theme="light"] .sp-sidefoot{background:rgba(244,244,246,.97)}
  html[data-theme="light"] #barPath{fill:#ffffff;stroke:#d8d8df}
  html[data-theme="light"] #barShape{filter:drop-shadow(0 14px 22px rgba(0,0,0,.16))}
  html[data-theme="light"] #cmpTip,html[data-theme="light"] #cpCmpTip,html[data-theme="light"] .hvTip{background:#ffffff;box-shadow:0 10px 26px rgba(0,0,0,.16)}
  @media (max-width:899px){html[data-theme="light"] #spFilterBtn{background:#ffffff}}
  html[data-theme="light"] h2{color:var(--text);text-shadow:none}
  html[data-theme="light"] a:hover,html[data-theme="light"] nav a:hover{color:var(--text)}
  html[data-theme="light"] .langmenu button.on,html[data-theme="light"] .pilltabs button.on,html[data-theme="light"] .spsortmi.on,html[data-theme="light"] .cmprange.on,html[data-theme="light"] .stabs button.on,html[data-theme="light"] .sarrow:hover,html[data-theme="light"] .harrow:hover{color:var(--text)}
  html[data-theme="light"] .chip.on{color:#f4f4f6}
  html[data-theme="light"] .hstatus{color:#4c7a1f}
  html[data-theme="light"] .card{background:linear-gradient(180deg,#ffffff,#f7f7f9);border-color:var(--border)}
  html[data-theme="light"] .salepanel{background:linear-gradient(180deg,#ffffff,#f4f4f6);box-shadow:0 4px 16px rgba(0,0,0,.08)}
  html[data-theme="light"] .pcard{background:#ffffff}
  html[data-theme="light"] .bthph{background:#e4e4ea}
  html[data-theme="light"] .bprev{background:linear-gradient(180deg,#ffffff,#f7f7f9)}
  html[data-theme="light"] .bpchip{background:#e7e7ec;color:var(--sub)}
  html[data-theme="light"] .bpchip.sale{background:#4c6b22;color:#c8ec6e}
  html[data-theme="light"] .brow:nth-child(even){background:#f7f7f9}
  html[data-theme="light"] .brow:hover,html[data-theme="light"] .brow.sel{background:#e9e9ee}
  html[data-theme="light"] .sarrow{color:rgba(29,29,32,.55)}
  html[data-theme="light"] .smore button{background:#ffffff;color:var(--sub);border-color:var(--border2)}
  html[data-theme="light"] .smore button:hover{background:#eef0f2;color:var(--text)}
  html[data-theme="light"] .saleDots span{background:#cfcfd8}
  html[data-theme="light"] .saleDots span.on{background:#55555f}
  html[data-theme="light"] .railbar span{background:#a9a9b3}
  html[data-theme="light"] .htag{background:#e7e7ec}
  html[data-theme="light"] .tag.red{background:#fbe3e4;color:#b3352c}
  html[data-theme="light"] .cp-box{background:#ffffff}
  html[data-theme="light"] .pp-bmbtn.on{background:#fdf3d0;border-color:#d9a521;color:#c99700}
  html[data-theme="light"] .searchbox input{background:#ffffff}
  html[data-theme="light"] body::-webkit-scrollbar-track{background:#f4f4f6}
  html[data-theme="light"] .prow::-webkit-scrollbar-thumb:hover,html[data-theme="light"] .relrow::-webkit-scrollbar-thumb:hover{background:#b9b9c2}
  html[data-theme="light"] .hslide .hprice2 .price.free{color:var(--text)}
  html[data-theme="light"] .harrow{color:rgba(29,29,32,.55)}
  html[data-theme="light"] .card{box-shadow:0 1px 3px rgba(0,0,0,.07),0 3px 10px rgba(0,0,0,.05)}
  html[data-theme="light"] .card:hover{box-shadow:0 4px 14px rgba(0,0,0,.12)}
  html[data-theme="light"] .salepanel{box-shadow:0 2px 10px rgba(0,0,0,.06)}
  html[data-theme="light"] .bprev{box-shadow:0 2px 10px rgba(0,0,0,.07)}
  html[data-theme="light"] .langmenu,html[data-theme="light"] .spsortmenu{box-shadow:0 10px 28px rgba(0,0,0,.16)}
  html[data-theme="light"] #cmpTip,html[data-theme="light"] #cpCmpTip,html[data-theme="light"] .hvTip{box-shadow:0 6px 18px rgba(0,0,0,.14)}
  html[data-theme="light"] .tabbar button.fab{box-shadow:0 4px 12px rgba(0,0,0,.18)}
  html[data-theme="light"] #spPrice::-webkit-slider-thumb{box-shadow:0 1px 4px rgba(0,0,0,.25)}
  html[data-theme="light"] .tabbar button{color:#83838d}
  html[data-theme="light"] .tabbar button.on{color:var(--text)}
  html[data-theme="light"] .pp-booth:hover,html[data-theme="light"] .pp-booth:focus,html[data-theme="light"] .btn:hover,html[data-theme="light"] .btn:focus{color:#fff}
  html[data-theme="light"] .hero-dots button{background:rgba(29,29,32,.28)}
  html[data-theme="light"] .hero-dots button.on{background:#1d1d20}
</style>
<link rel="stylesheet" href="image-search.css?v=20261028-results-v3">
<script>
// DISCOUNT_DISPLAY_GUARD_START
// Presentation only: never alter sale classification, source prices or ranking pct.
function displayDiscountPercent(base, cur){
  if (!Number.isFinite(base) || !Number.isFinite(cur) || base <= 0 || cur < 0 || cur >= base) return null;
  if (cur === 0) return 100;
  return Math.min(99, Math.max(0, Math.round((1 - cur / base) * 100)));
}
function discountBadge(base, cur, cls, minus = "-"){
  const pct = displayDiscountPercent(base, cur);
  return pct === null || pct <= 0 ? "" : `<span class="${cls}">${minus}${pct}%</span>`;
}
function displayChangePercent(from, to){
  if (!Number.isFinite(from) || !Number.isFinite(to) || from <= 0 || to < 0) return "";
  let pct = Math.round((to - from) / from * 100);
  if (to > 0 && pct <= -100) pct = -99;
  return (to >= from ? "+" : "") + pct + "%";
}
// DISCOUNT_DISPLAY_GUARD_END
</script>
</head>
<body>
<div id="splash" hidden>
  <svg viewBox="0 0 120 120" aria-hidden="true">
    <circle cx="60" cy="60" r="55" fill="#ffffff"/>
    <circle class="spl-ring" cx="60" cy="60" r="55" fill="none" stroke="#002d6b" stroke-width="7"/>
    <path class="spl-line" d="M22 80 L46 60 L60 72 L90 44" fill="none" stroke="#e8383c" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
    <path class="spl-head" d="M78 40 L94 40 L94 56 L86 48 Z" fill="#e8383c"/>
    <g class="spl-tag">
      <rect x="76" y="62" width="13" height="24" rx="5" transform="rotate(18 82 74)" fill="#1b9ec4"/>
      <circle cx="83.5" cy="68.5" r="2.6" fill="#ffffff"/>
    </g>
  </svg>
  <div class="splogo">Boopa<span>DB</span></div>
</div>
<script>
(function(){
  var sp = document.getElementById('splash');
  var standalone = false;
  try { standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true; } catch (e) {}
  if (!standalone || !sp) { if (sp) sp.remove(); return; }
  try {
    if (sessionStorage.getItem('boopadb_splash')) { sp.remove(); return; }
    sessionStorage.setItem('boopadb_splash', '1');
  } catch (e) {}
  sp.hidden = false;
  document.documentElement.classList.add('splock');
  var t0 = performance.now(), done = false;
  function hide() {
    if (done) return; done = true;
    sp.classList.add('bye');
    document.documentElement.classList.remove('splock');
    setTimeout(function(){ sp.remove(); }, 420);
  }
  function hideAfterAnim() {
    var wait = Math.max(0, 1600 - (performance.now() - t0));
    setTimeout(hide, wait);
  }
  if (document.readyState === 'complete') hideAfterAnim();
  else addEventListener('load', hideAfterAnim);
  setTimeout(hide, 2800);
})();
</script>
<header>
  <div class="hwrap">
  <a class="logo" href="index.html" style="text-decoration:none;color:inherit">Boopa<span>DB</span></a>
  <nav><a href="#sale" data-i="nav_sale">セール中の商品</a><a href="#feat" data-i="nav_feat">注目の商品</a><a href="#browse2" data-i="nav_browse">新着・値下げ</a></nav>
  <button id="themeBtn" class="themebtn" type="button" data-i-al="th_toggle" aria-label="テーマ切替"><svg class="ic-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><svg class="ic-moon" viewBox="0 0 24 24"><path d="M20 13.5A8.5 8.5 0 1 1 10.5 4a7 7 0 0 0 9.5 9.5z"/></svg></button><div class="langsw"><button id="langBtn" type="button"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.7 3.8 9S14.5 18.4 12 21c-2.5-2.6-3.8-5.7-3.8-9S9.5 5.6 12 3z"/></svg><span id="langCur">日本語</span><svg class="lchev" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg></button><div class="langmenu" id="langMenu"></div></div>
  <div class="badge">PROTOTYPE</div>
  </div>
</header>
<main>
  <a class="topslot" href="https://chromewebstore.google.com/detail/mllcdeonfeaepajkkidjmgonfkibeokb" target="_blank" rel="noopener"><img decoding="async" src="/*__BANNER__*/" alt="Boopa – BOOTH Price Tracker for VRChat"></a>
  <h2 class="heroh" data-i="hero_title">注目＆おすすめ</h2>
  <div class="hero" id="hero"><div class="hero-view"><div class="hero-track" id="heroTrack"></div></div><button class="harrow prev" id="heroPrev" data-i-al="al_prev" aria-label="前へ">‹</button><button class="harrow next" id="heroNext" data-i-al="al_next" aria-label="次へ">›</button></div><div class="hero-dots" id="heroDots"></div>
  <div id="appPromo" style="display:none;align-items:center;gap:12px;background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:12px 16px;margin:2px 0 20px">
    <img decoding="async" src="icon-512.png" alt="" style="width:38px;height:38px;border-radius:10px;flex:none">
    <div style="flex:1;min-width:0"><div style="font-weight:800;font-size:14px" data-i="app_promo_t">BoopaDBをアプリとして使う</div><div style="font-size:12.5px;color:var(--sub)" data-i="app_promo_b">ホーム画面に追加すると、全画面で開けるようになります</div></div>
    <a href="app.html" style="flex:none;background:#fc4d50;color:#fff;font-weight:800;font-size:13px;padding:9px 14px;border-radius:10px;text-decoration:none" data-i="ft_app">アプリ</a>
    <button id="appPromoX" type="button" aria-label="close" style="flex:none;background:none;border:none;color:var(--faint);cursor:pointer;padding:6px"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M5 5l14 14M19 5L5 19"/></svg></button>
  </div>
  <div class="stats" id="stats"></div>
  <div class="stats-note" id="statsPriceBasis"></div>

  <div class="shead" id="sale"><h2 style="border:none;margin:0;padding:0" data-i="nav_sale">セール中の商品</h2>
    <div class="pilltabs" id="sortTabs"><span class="pill-ind"></span><button data-mode="new" class="on" data-i="sort_new">新着順</button><button data-mode="pop" data-i="sort_pop">人気順</button><button data-mode="pct" data-i="sort_pct">割引率順</button><button data-mode="amount" data-i="sort_amount">割引額順</button></div></div>
  <div class="chips" id="chips">
    <button class="chip on" data-f="all" data-i="chip_all">すべて</button>
    <button class="chip" data-f="lowest" data-i="chip_lowest">過去最安値</button>
    <button class="chip" data-f="free" data-i="free">無料</button>
    <button class="chip" data-f="half" data-i="chip_half">50%OFF以上</button>
  </div>
  <div class="salepanel hp">
    <div class="saleRail" id="saleRail"><div class="saleTrack" id="saleTrack"></div></div>
    <button class="sarrow prev" id="salePrev" data-i-al="al_prev" aria-label="前へ">‹</button>
    <button class="sarrow next" id="saleNext" data-i-al="al_next" aria-label="次へ">›</button>
    <div class="saleDots" id="saleDots"></div>
    <div class="railbar" id="saleBar"><span></span></div>
  </div>
  <div class="empty" id="saleEmpty" data-i="empty_none">該当する商品がありません</div>
  <div class="smore"><button id="saleMore" type="button" data-i="more">もっと見る</button></div>
  <p class="note" data-i="sale_note">※ 通常価格は観測期間中の最高価格。セール判定はBoopaの収集データに基づく推定を含みます。</p>

  <h2 id="feat" data-i="nav_feat">注目の商品</h2>
  <div class="featwrap"><div class="capgrid" id="featGrid"><div id="featTrack"></div></div><button class="sarrow prev" id="featPrev" data-i-al="al_prev" aria-label="前へ">‹</button><button class="sarrow next" id="featNext" data-i-al="al_next" aria-label="次へ">›</button><div class="saleDots" id="featDots"></div><div class="railbar" id="featBar"><span></span></div></div>
  <div id="personal"></div>

  <div class="browse2" id="browse2">
    <div class="btabs" id="bTabs">
      <button class="btab on" data-bt="new" data-i="bt_new">新着</button>
      <button class="btab" data-bt="rising" data-i="bt_rising">急上昇</button>
      <button class="btab" data-bt="sale" data-i="bt_special">スペシャル</button>
      <button class="btab" data-bt="drop" data-i="bt_drop">値下げ</button>
      <button class="btab" data-bt="free" data-i="free">無料</button>

    </div>
    <div class="bwrap">
      <div>
        <div id="bList"></div>
        <div class="smore"><button id="bMore" type="button" data-i="more">もっと見る</button></div>
      </div>
      <aside class="bprev" id="bPrev"></aside>
    </div>
  </div>

  <section class="catsec">
    <h2 data-i="cat_title">カテゴリー別に閲覧</h2>
    <div class="catwrap">
      <button class="catbtn prev" id="catPrev" data-i-al="al_prev" aria-label="前へ"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg></button>
      <div class="catrail" id="catRail"></div>
      <button class="catbtn next" id="catNext" data-i-al="al_next" aria-label="次へ"><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></button>
    </div>
    <div class="upddots" id="catDots"></div>
  </section>

  <section class="catsec" id="updSec" hidden>
    <h2 data-i="upd_title">最近のアップデート</h2>
    <div class="catwrap">
      <button class="catbtn prev" id="updPrev" data-i-al="al_prev" aria-label="前へ"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg></button>
      <div class="updrail" id="updRail"></div>
      <button class="catbtn next" id="updNext" data-i-al="al_next" aria-label="次へ"><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></button>
    </div>
    <div class="upddots" id="updDots"></div>
    <div class="smore" id="updMoreWrap" hidden><button id="updMore" type="button" data-i="more">もっと見る</button></div>
  </section>

  <section class="catsec" id="shopSec" hidden>
    <h2 data-i="shops_title">知っているショップの作品</h2>
    <div class="catwrap">
      <button class="catbtn prev" id="shopPrev" data-i-al="al_prev" aria-label="前へ"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg></button>
      <div class="updrail" id="shopRail"></div>
      <button class="catbtn next" id="shopNext" data-i-al="al_next" aria-label="次へ"><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></button>
    </div>
    <div class="upddots" id="shopDots"></div>
  </section>

</main>
<footer>
  <div data-i="ft_data">データは Boopa（BOOTH Price Tracker for VRChat）の収集基盤による実データです。価格は観測時点のもので、現在のBOOTH上の価格と異なる場合があります。</div>
  <div class="flegal">
    <span data-i="ft_legal">BoopaDB は BOOTH および pixiv株式会社とは関係のない非公式プロジェクトです。表示される時刻はすべて日本時間（JST）です。</span><a class="flink" href="terms.html" data-i="ft_terms">利用規約</a> · <a class="flink" href="privacy.html" data-i="ft_priv">プライバシー</a> · <a class="flink" href="app.html" data-i="ft_app">アプリ</a><br>
    <span data-i="ft_tm">BOOTH は pixiv株式会社の商標です。その他の商標および著作物は、各権利者に帰属します。</span>
  </div>
</footer>
<div class="spage" id="prodPage">
  <div class="sp-head"><button class="sp-back" id="ppBack" data-i-al="al_back" aria-label="戻る"><svg viewBox="0 0 24 24"><path d="M19 12H5m6 7-7-7 7-7"/></svg></button><div class="sp-title" data-i="pp_title">商品詳細</div><button class="sp-share" id="ppShareTop" data-i-al="pp_share" aria-label="共有"><svg viewBox="0 0 24 24"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="m16 6-4-4-4 4"/><path d="M12 2v13"/></svg></button></div>
  <div class="pp-inner" id="ppBody"></div>
</div>
<div id="chartPop" hidden>
  <div class="cp-box">
    <div class="cp-head"><span id="cpTitle"></span><button type="button" id="cpClose" data-i-al="al_close" aria-label="閉じる"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
    <div id="cpLegend"></div>
    <div id="cpOutl"></div>
    <div id="cpReadout"></div>
    <div class="cpchart" id="cpChart"></div>
    <div class="cmpranges" id="cpRanges"></div>
  </div>
</div>
<nav class="tabbar" id="tabbar">
  <svg id="barShape" aria-hidden="true"><path id="barPath" fill="#1e1e22" stroke="#2e2e35" stroke-width="1"/></svg>
  <button data-to="#hero" class="on"><svg viewBox="0 0 24 24"><path d="M4 11l8-7 8 7v9a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1z"/></svg><span class="tlabel" data-i="tab_home">ホーム</span></button>
  <button data-to="#sale"><svg viewBox="0 0 24 24"><path d="M3.5 3.5H12L20.5 12 12 20.5 3.5 12z"/><circle cx="8" cy="8" r="1.4"/></svg><span class="tlabel" data-i="tab_sale">セール</span></button>
  <span class="tspacer"></span>
  <button data-href="bookmarks.html"><svg viewBox="0 0 24 24"><path d="M17 3H7a2 2 0 0 0-2 2v16l7-4 7 4V5a2 2 0 0 0-2-2z"/></svg><span class="tlabel" data-i="tab_bm">ブックマーク</span></button>
  <button data-href="ranking.html"><svg viewBox="0 0 24 24"><path d="M5 20v-7M11 20V5M17 20v-10M22 20H2"/></svg><span class="tlabel" data-i="tab_ranking">ランキング</span></button>
  <button id="tabSearch" class="fab" data-i-al="al_search" aria-label="検索"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.8-3.8"/></svg></button>
</nav>
<div id="spImgDropError" class="image-drop-error" hidden><span id="spImgDropErrorText" role="status" aria-live="polite"></span><button id="spImgDropErrorClose" type="button" data-i-al="al_close" aria-label="閉じる">×</button></div>
<div id="lensView" hidden role="dialog" aria-modal="true" aria-label="画像検索" data-i-al="img_search">
  <div class="lv-head"><button id="lvBack" class="igs-x" type="button" data-i-al="al_back" aria-label="戻る"><svg viewBox="0 0 24 24"><path d="M19 12H5m6 7-7-7 7-7"/></svg></button><img id="lvThumb" alt=""><div class="lv-title" data-i="img_search">画像検索</div><div class="lv-count" id="lvCount"></div></div>
  <div class="lv-stage" id="lvStage"><div class="lv-wrap" id="lvWrap"><img id="lvImg" alt=""><svg id="lvSvg"></svg><canvas id="lvDraw"></canvas></div><button id="lvFitBtn" class="igs-btn lv-fitbtn" type="button" hidden data-i="lv_fit">全体を表示</button><span class="lv-hint" id="lvHint" data-i="img_trace_hint">探したいものを指やマウスでなぞって囲んでください</span></div>
  <div class="lv-tools" id="lvTools"><span class="lv-tbtns"><button id="lvWhole" class="igs-btn" type="button" data-i="img_use_whole">画像全体で検索</button><button id="lvRetake" class="igs-btn" type="button" data-i="img_retake">選び直す</button></span></div>
  <div class="lv-sheet" id="lvSheet"><div class="lv-grab" id="lvGrab"><span class="lv-grabbar"></span></div><div class="lv-sheetbody" id="lvSheetBody"><div class="lv-note" id="lvNote" hidden></div><div class="image-result-grid lv-results" id="lvResults"></div></div></div>
</div>
<div class="spage" id="searchPage">
  <div class="sp-head"><button class="sp-back" id="spBack" data-i-al="al_back" aria-label="戻る"><svg viewBox="0 0 24 24"><path d="M19 12H5m6 7-7-7 7-7"/></svg></button><div class="sp-title" data-i="sp_title">商品検索</div></div>
  <div class="sp-inner">
    <div class="sp-search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.8-3.8"/></svg><input id="spQ" type="text" data-i-ph="sp_ph" placeholder="商品名・ショップ名で検索" autocomplete="off"><button id="spClear" class="sp-clear" type="button" data-i-al="al_close" aria-label="閉じる" hidden><svg viewBox="0 0 24 24"><path d="M5 5l14 14M19 5L5 19"/></svg></button><button id="spImgBtn" class="sp-clear sp-imgbtn" type="button" data-i-al="img_search" aria-label="画像検索"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.6"/><path d="M21 16l-5-5-7 7"/></svg></button><input type="file" id="spImgFile" accept="image/*" hidden></div>
    <div class="sp-main"><div class="sp-side">
    <div class="sp-sidehead"><span data-i="sp_filter">絞り込み</span><button id="spSideX" class="sp-sidex" type="button" data-i-al="al_close" aria-label="閉じる"><svg viewBox="0 0 24 24"><path d="M5 5l14 14M19 5L5 19"/></svg></button></div>
    <div class="sp-sec" data-i="sp_filter">絞り込み</div>
    <div class="chips" id="spChips">
      <button class="chip on" data-f="all" data-i="chip_all">すべて</button>
      <button class="chip" data-f="sale" data-i="chip_onsale">セール中</button>
      <button class="chip" data-f="lowest" data-i="chip_lowest">過去最安値</button>
      <button class="chip" data-f="free" data-i="free">無料</button>
      <button class="chip" data-f="drop" data-i="bt_drop">値下げ</button>
    </div>
    <div class="sp-sec" data-i="sp_price_t">価格で絞り込む</div>
    <div class="sp-price"><input type="range" id="spPrice" min="0" max="12" step="1" value="12" data-i-al="sp_price_t" aria-label="価格で絞り込む"><div class="sp-price-val" id="spPriceVal"></div></div>
    <div class="sp-sec" data-i="sp_shops">ショップから探す</div>
    <div class="kwrap" id="spKw"></div>
    <div class="sp-sidefoot"><button id="spFilterReset" class="sp-freset" type="button" data-i="sp_reset">リセット</button><button id="spFilterShow" class="sp-fshow" type="button" data-i="sp_show_results">結果を表示</button></div>
    </div>
    <div class="sp-results">
    <div id="spCatalogStatus" role="status" hidden><span id="spCatalogMessage"></span> <button id="spCatalogRetry" type="button" hidden></button></div>
    <div class="sp-resbar"><div class="sp-count" id="spCount"></div><span class="spsortdd"><button id="spSortBtn" type="button"></button><span class="spsortmenu" id="spSortMenu" hidden></span></span><button id="spFilterBtn" type="button"></button></div>
    <div class="sp-mode" id="spMode" hidden><img id="spModeImg" hidden alt=""><span class="sp-mode-t" id="spModeT"></span><button class="sp-mode-x" id="spModeX" type="button" data-i-al="al_close" aria-label="閉じる"><svg viewBox="0 0 24 24"><path d="M5 5l14 14M19 5L5 19"/></svg></button></div>
    <div id="spImgNote" hidden></div>
    <div class="grid" id="spGrid"></div>
    <div class="smore" aria-hidden="true"></div>
    <div class="empty" id="spEmpty" data-i="empty_none">該当する商品がありません</div>
    </div></div>
  </div>
</div>
<script src="relationship-data.js?v=1e771e8fcebf4deb"></script>
<script src="relationship-search.js?v=e6fa3c5693bb1eca"></script>
<script src="relationship-ui-draft.js?v=f16647f479b29063"></script>
<script src="relationship-supplement.js?v=352aa3eed121bee9"></script>
<script src="image-drop.js"></script>
<script src="catalog-cache.js?v=56adbe78663321a8b4610bda5bbc1c10c58576b75459ad6556de1c9c390eb337-core-v1"></script>
<script src="catalog-images.js?v=20261029-core-v1"></script>
<script src="image-search-engine.js?v=20261028-results-v3"></script>
<script>
const P = /*__PAYLOAD__*/;
/*__VISIBILITY__*/
// ==== i18n: BOOTH locales (ja / en / ko / zh-Hans / zh-Hant) ====
const LANGS = [["ja", "日本語"], ["en", "English"], ["ko", "한국어"], ["zh-Hans", "简体中文"], ["zh-Hant", "繁體中文"]];
const I18N = {
ja: {
  doc_title: "BoopaDB — BOOTHのVRChat向け価格データベース（プロトタイプ）",
  nav_sale: "セール中の商品", nav_feat: "注目の商品", nav_browse: "新着・値下げ", cat_title: "カテゴリー別に閲覧", upd_title: "最近のアップデート", img_search: "画像検索", img_page_entry: "画像から商品を探す →", img_page_back: "戻る", img_page_title: "画像から、気になる商品を。", img_page_intro: "画像を選んで、似ているBOOTH商品を探しましょう。画像全体でも、気になる部分を囲んでも検索できます。", img_page_upload: "画像をアップロード", img_page_hint: "ここにドラッグ＆ドロップ、またはクリックして選択", img_page_formats: "PNG・JPEG・WebPなどの画像 ／ 1枚・20MBまで", img_drop: "画像をここにドロップ、またはクリックして選択（1枚・20MBまで）", img_file_empty: "画像ファイルを1枚選択してください", img_file_one: "一度に選択できる画像は1枚です", img_file_type: "画像ファイルを選択してください", img_file_size: "画像は空でない20MB以下のファイルを選択してください", img_file_decode: "この画像を読み込めません。PNG・JPEG・WebPなど別の形式で試してください", img_similar: "似た画像を探す", img_trace_hint: "探したいものを指やマウスでなぞって囲んでください", img_use_area: "この範囲で検索", img_use_whole: "画像全体で検索", img_retake: "選び直す", img_searching: "画像で検索中…", img_limit: "本日の無料上限（5回）に達しました。明日また利用できます", img_error: "画像検索に失敗しました。時間をおいてお試しください", img_notindexed: "この商品の画像はまだ収録されていません", lv_fit: "全体を表示", upd_newvar: "新バリエーション", shops_title: "知っているショップの作品", shops_n: "{n} 商品",
  hero_title: "注目＆おすすめ",
  feat_note: "セール中かどうかではなく、価格の動きの活発さと新着から選んでいます。",
  sort_pct: "割引率順", sort_amount: "割引額順", sort_cheap: "安い順", sort_pop: "人気順", sort_new: "新着順",
  chip_all: "すべて", chip_lowest: "過去最安値", rng_1d: "1日", rng_5d: "5日", rng_1m: "1か月", rng_6m: "6か月", rng_ytd: "年来初", rng_1y: "1年", rng_5y: "5年", rng_max: "最大", chip_half: "50%OFF以上", chip_onsale: "セール中",
  empty_none: "該当する商品がありません", loading: "読み込み中…", more: "もっと見る",
  sale_note: "※ 通常価格は観測期間中の最高価格。セール判定はBoopaの収集データに基づく推定を含みます。",
  bt_new: "新着", bt_special: "スペシャル", bt_drop: "値下げ", bt_active: "価格変更が活発", bt_rising: "急上昇", rising_note: "{likes} · +{g}/日",
  ft_data: "データは Boopa（BOOTH Price Tracker for VRChat）の収集基盤による実データです。価格は観測時点のもので、現在のBOOTH上の価格と異なる場合があります。",
  ft_legal: "BoopaDB は BOOTH および pixiv株式会社とは関係のない非公式プロジェクトです。表示される時刻はすべて日本時間（JST）です。",
  ft_terms: "利用規約", ft_priv: "プライバシー", ft_app: "アプリ", app_promo_t: "BoopaDBをアプリとして使う", app_promo_b: "ホーム画面に追加すると、全画面で開けるようになります",
  ft_tm: "BOOTH は pixiv株式会社の商標です。その他の商標および著作物は、各権利者に帰属します。",
  pp_title: "商品詳細", sp_title: "商品検索", sp_ph: "商品名・ショップ名で検索", sp_shops: "カテゴリーから探す", sp_filter: "絞り込み", sp_price_t: "価格で絞り込む", sp_price_any: "価格は問わない", sp_reset: "リセット", sp_show_results: "結果を表示", sp_sort_rel: "適合性", sp_sort_pop: "人気順", sp_sort_rising: "急上昇", sp_sort_new: "新着順", sp_sort_price_asc: "価格の安い順", sp_sort_price_desc: "価格の高い順", sp_sort_pct: "割引率の高い順", sp_sort_name: "名前順", th_toggle: "テーマ切替", sp_price_upto: "¥{n} 以下",
  tab_home: "ホーム", tab_sale: "セール", tab_news: "ニュース", tab_ranking: "ランキング", tab_bm: "ブックマーク",
  al_back: "戻る", al_prev: "前へ", al_next: "次へ", al_expand: "拡大表示", al_close: "閉じる", cmp_more: "ほか{n}件", al_search: "検索", al_slide: "スライド",
  st_total: "追跡中の商品", st_sale: "セール中（推定）", st_free: "現在無料", st_changed: "累計価格変更", st_changed_daily: "本日の価格変更", st_daily_date: "対象：{date}（JST・観測分）", st_daily_unknown: "未集計", st_daily_stale: "当日分は未集計（前回：{date}）", st_daily_updated: "集計更新：{time}（JST）", st_daily_update_unknown: "集計更新：未取得", st_change_basis: "価格変更は、各商品の記録数が最も多い代表バリエーションで判定。変更回数ではなく商品数です。", st_period: "観測開始日", st_stats_details: "集計条件・日付", st_daily_summary: "当日（{date} JST）：{state}", st_free_basis: "現在無料は、過去の価格が100円以上だった商品。",
  free: "無料", rib_sale: "セール",
  status_lowest: "過去最安値で販売中", save_note: "{v} お得",
  reason_lowest: "過去最安値を更新したためおすすめしています", reason_sale: "セール中の商品からおすすめしています",
  recent3w: "直近3週間で価格変更 {n}回", recent3w_short: "直近3週間で{n}回変更",
  reason_active: "最近よく価格が動いているためおすすめしています",
  added_on: "{d} 収録", alltime_changes: "全期間で{n}回変更",
  note_dropped: "{d} に値下げ", note_nowfree: "現在無料",
  pp_cur: "現在価格", pp_high: "最高価格", pp_avg: "平均価格", pp_saledays: "セール観測日数", pp_days: "観測日数", days_fmt: "{n}日",
  pp_chart: "価格推移", pp_history: "価格変更履歴", pp_same: "同じショップの商品", pp_parents: "親作品", pp_children: "子作品", rel_more: "もっと見る",
  pp_booth: "BOOTHで見る", pp_bm: "ブックマーク", pp_bmed: "ブックマーク済み", pp_rec: "おすすめできる", pp_reced: "おすすめ済み", pp_share: "共有", pp_copied: "コピーしました", bm_more: "もっと見る", pp_vars: "バリエーション（{n}件）", pp_compare: "価格推移を比較", pp_changes: "価格変更履歴", cmp_others: "ほか{n}件", outlier: "規格外", outlier_n: "▲ 規格外{n}件",
  pp_nodata: "価格データが不足しています。", pp_nochg: "価格変更は観測されていません。",
  pp_salenote: "ピンクの帯はセール中と推定された期間です。", pp_down: "値下げ", chg_date: "日付", chg_before: "変更前", chg_after: "変更後", chg_rate: "変化率", pp_up: "値上げ",
  sp_count: "{n} 件", sp_total: "全{n}件から検索", sec_recent: "最近見た商品", seen_drop: "見た時より -{v}",
  price_drop_label: "値下げ",
},
en: {
  doc_title: "BoopaDB — BOOTH Price Database for VRChat (Prototype)",
  nav_sale: "On Sale", nav_feat: "Featured", nav_browse: "New & Price Drops", cat_title: "Browse by Category", upd_title: "Recent Updates", img_search: "Image Search", img_page_entry: "Search products by image →", img_page_back: "Back", img_page_title: "Find your next discovery by image.", img_page_intro: "Choose an image to find similar BOOTH products. Search the whole image or draw around the part you like.", img_page_upload: "Upload an image", img_page_hint: "Drag and drop here, or click to choose", img_page_formats: "Images such as PNG, JPEG and WebP / one image, up to 20 MB", img_drop: "Drop an image here, or click to choose (one image, up to 20 MB)", img_file_empty: "Choose one image file", img_file_one: "Choose only one image at a time", img_file_type: "Please choose an image file", img_file_size: "Choose a non-empty image up to 20 MB", img_file_decode: "This image could not be opened. Try PNG, JPEG or WebP", img_similar: "Find Similar Images", img_trace_hint: "Trace around what you're looking for", img_use_area: "Search This Area", img_use_whole: "Search Whole Image", img_retake: "Choose Another", img_searching: "Searching by image…", img_limit: "You've reached today's free limit (5). Please try again tomorrow", img_error: "Image search failed. Please try again later", img_notindexed: "This item's images aren't indexed yet", lv_fit: "Show all", upd_newvar: "New variation", shops_title: "Works from Shops You Know", shops_n: "{n} items",
  hero_title: "Featured & Recommended",
  feat_note: "Chosen for active price movement and freshness, not just whether they are on sale.",
  sort_pct: "By discount %", sort_amount: "By amount saved", sort_cheap: "Price: low to high", sort_pop: "Most popular", sort_new: "Newest",
  chip_all: "All", chip_lowest: "Lowest ever", rng_1d: "1D", rng_5d: "5D", rng_1m: "1M", rng_6m: "6M", rng_ytd: "YTD", rng_1y: "1Y", rng_5y: "5Y", rng_max: "Max", chip_half: "50% off or more", chip_onsale: "On sale",
  empty_none: "No matching products", loading: "Loading…", more: "See more",
  sale_note: "* Regular price is the highest observed price. Sale status includes estimates based on Boopa's collected data.",
  bt_new: "New", bt_special: "Specials", bt_drop: "Price drops", bt_active: "Frequent price changes", bt_rising: "Trending", rising_note: "{likes} · +{g}/day",
  ft_data: "Data is real, collected by Boopa (BOOTH Price Tracker for VRChat). Prices are as observed and may differ from current BOOTH prices.",
  ft_legal: "BoopaDB is an unofficial project, not affiliated with BOOTH or pixiv Inc. All times are Japan Standard Time (JST).",
  ft_terms: "Terms", ft_priv: "Privacy", ft_app: "App", app_promo_t: "Use BoopaDB as an app", app_promo_b: "Add it to your home screen to open it full-screen",
  ft_tm: "BOOTH is a trademark of pixiv Inc. All other trademarks and works belong to their respective owners.",
  pp_title: "Product details", sp_title: "Search products", sp_ph: "Search by product or shop name", sp_shops: "Browse by category", sp_filter: "Filters", sp_price_t: "Filter by price", sp_price_any: "Any price", sp_reset: "Reset", sp_show_results: "Show results", sp_sort_rel: "Relevance", sp_sort_pop: "Popularity", sp_sort_rising: "Rising", sp_sort_new: "Newest", sp_sort_price_asc: "Price: low to high", sp_sort_price_desc: "Price: high to low", sp_sort_pct: "Biggest discount", sp_sort_name: "Name", th_toggle: "Toggle theme", sp_price_upto: "Up to ¥{n}",
  tab_home: "Home", tab_sale: "Sale", tab_news: "News", tab_ranking: "Rankings", tab_bm: "Bookmarks",
  al_back: "Back", al_prev: "Previous", al_next: "Next", al_expand: "Expand", al_close: "Close", cmp_more: "+{n} more", al_search: "Search", al_slide: "Slide",
  st_total: "Tracked products", st_sale: "On sale (est.)", st_free: "Free now", st_changed: "Changes · total", st_changed_daily: "Changes · today", st_daily_date: "Date: {date} (JST observations)", st_daily_unknown: "Not available", st_daily_stale: "Today unavailable (last date: {date})", st_daily_updated: "Stats updated: {time} (JST)", st_daily_update_unknown: "Stats update time unavailable", st_change_basis: "Price changes use each product’s variation with the most observations. Counts are unique products, not change events.", st_period: "Tracking since", st_stats_details: "Dates & definitions", st_daily_summary: "Daily ({date} JST): {state}", st_free_basis: "Free now counts products previously priced at ¥100 or more.",
  free: "Free", rib_sale: "Sale",
  status_lowest: "Now at its lowest price ever", save_note: "Save {v}",
  reason_lowest: "Recommended: it just hit a new all-time low", reason_sale: "Recommended from items on sale",
  recent3w: "{n} price changes in the last 3 weeks", recent3w_short: "{n} changes in 3 weeks",
  reason_active: "Recommended: its price has been moving a lot lately",
  added_on: "Added {d}", alltime_changes: "{n} changes all-time",
  note_dropped: "Price drop on {d}", note_nowfree: "Free now",
  pp_cur: "Current price", pp_high: "Highest price", pp_avg: "Average price", pp_saledays: "Days on sale (observed)", pp_days: "Days observed", days_fmt: "{n} days",
  pp_chart: "Price history", pp_history: "Price change history", pp_same: "More from this shop", pp_parents: "Parent works", pp_children: "Derivative works", rel_more: "Show more",
  pp_booth: "View on BOOTH", pp_bm: "Bookmark", pp_bmed: "Bookmarked", pp_rec: "Recommend", pp_reced: "Recommended", pp_share: "Share", pp_copied: "Copied", bm_more: "See more", pp_vars: "Variations ({n})", pp_compare: "Compare price histories", pp_changes: "Price change history", cmp_others: "+{n} more", outlier: "Outlier", outlier_n: "▲ Outliers: {n}",
  pp_nodata: "Not enough price data yet.", pp_nochg: "No price changes observed.",
  pp_salenote: "Pink bands are periods estimated to be on sale.", pp_down: "Drop", chg_date: "Date", chg_before: "Before", chg_after: "After", chg_rate: "Change", pp_up: "Rise",
  sp_count: "{n} items", sp_total: "Search all {n} products", sec_recent: "Recently viewed", seen_drop: "Down {v} since viewed",
  price_drop_label: "Price drop",
},
ko: {
  doc_title: "BoopaDB — BOOTH의 VRChat용 가격 데이터베이스(프로토타입)",
  nav_sale: "할인 중인 상품", nav_feat: "주목 상품", nav_browse: "신착·가격 인하", cat_title: "카테고리별 둘러보기", upd_title: "최근 업데이트", img_search: "이미지 검색", img_page_entry: "이미지로 상품 찾기 →", img_page_back: "뒤로", img_page_title: "이미지로 마음에 드는 상품을.", img_page_intro: "이미지와 비슷한 BOOTH 상품을 찾아보세요. 전체 이미지 또는 원하는 부분을 둘러싸서 검색할 수 있어요.", img_page_upload: "이미지 업로드", img_page_hint: "여기로 끌어 놓거나 클릭하여 선택", img_page_formats: "PNG, JPEG, WebP 등의 이미지 / 1개, 최대 20MB", img_drop: "이미지를 여기에 놓거나 클릭하여 선택 (1개, 최대 20MB)", img_file_empty: "이미지 파일을 선택해 주세요", img_file_one: "한 번에 이미지 1개만 선택해 주세요", img_file_type: "이미지 파일을 선택해 주세요", img_file_size: "비어 있지 않은 20MB 이하 이미지를 선택해 주세요", img_file_decode: "이미지를 열 수 없어요. PNG, JPEG, WebP 등으로 시도해 주세요", img_similar: "비슷한 이미지 찾기", img_trace_hint: "찾고 싶은 것을 손가락으로 따라 그어 주세요", img_use_area: "이 범위로 검색", img_use_whole: "이미지 전체로 검색", img_retake: "다시 선택", img_searching: "이미지로 검색 중…", img_limit: "오늘의 무료 한도(5회)에 도달했어요. 내일 다시 이용해 주세요", img_error: "이미지 검색에 실패했어요. 잠시 후 다시 시도해 주세요", img_notindexed: "이 상품의 이미지는 아직 수록되지 않았어요", lv_fit: "전체 보기", upd_newvar: "새 배리에이션", shops_title: "아는 숍의 작품", shops_n: "{n}개 상품",
  hero_title: "주목 & 추천",
  feat_note: "할인 여부가 아니라 가격 변동의 활발함과 신착을 기준으로 골랐습니다.",
  sort_pct: "할인율순", sort_amount: "할인액순", sort_cheap: "가격 낮은순", sort_pop: "인기순", sort_new: "최신순",
  chip_all: "전체", chip_lowest: "역대 최저가", rng_1d: "1일", rng_5d: "5일", rng_1m: "1개월", rng_6m: "6개월", rng_ytd: "연초부터", rng_1y: "1년", rng_5y: "5년", rng_max: "전체", chip_half: "50% 이상 할인", chip_onsale: "할인 중",
  empty_none: "해당하는 상품이 없습니다", loading: "불러오는 중…", more: "더 보기",
  sale_note: "※ 통상 가격은 관측 기간 중 최고가입니다. 할인 판정은 Boopa의 수집 데이터에 기반한 추정을 포함합니다.",
  bt_new: "신착", bt_special: "스페셜", bt_drop: "가격 인하", bt_active: "가격 변동 활발", bt_rising: "급상승", rising_note: "{likes} · +{g}/일",
  ft_data: "데이터는 Boopa(BOOTH Price Tracker for VRChat)의 수집 인프라로 모은 실제 데이터입니다. 가격은 관측 시점 기준이며 현재 BOOTH 가격과 다를 수 있습니다.",
  ft_legal: "BoopaDB는 BOOTH 및 pixiv 주식회사와 관계없는 비공식 프로젝트입니다. 모든 시간은 일본 시간(JST)입니다.",
  ft_terms: "이용약관", ft_priv: "개인정보", ft_app: "앱", app_promo_t: "BoopaDB를 앱으로 사용하기", app_promo_b: "홈 화면에 추가하면 전체 화면으로 열 수 있습니다",
  ft_tm: "BOOTH는 pixiv 주식회사의 상표입니다. 그 밖의 상표 및 저작물은 각 권리자에게 귀속합니다.",
  pp_title: "상품 상세", sp_title: "상품 검색", sp_ph: "상품명·샵 이름으로 검색", sp_shops: "카테고리로 찾기", sp_filter: "필터", sp_price_t: "가격으로 좁히기", sp_price_any: "가격 무관", sp_reset: "초기화", sp_show_results: "결과 표시", sp_sort_rel: "관련도", sp_sort_pop: "인기순", sp_sort_rising: "급상승", sp_sort_new: "최신순", sp_sort_price_asc: "가격 낮은 순", sp_sort_price_desc: "가격 높은 순", sp_sort_pct: "할인율 높은 순", sp_sort_name: "이름순", th_toggle: "테마 전환", sp_price_upto: "¥{n} 이하",
  tab_home: "홈", tab_sale: "세일", tab_news: "뉴스", tab_ranking: "랭킹", tab_bm: "북마크",
  al_back: "뒤로", al_prev: "이전", al_next: "다음", al_expand: "확대", al_close: "닫기", cmp_more: "외 {n}개", al_search: "검색", al_slide: "슬라이드",
  st_total: "추적 상품", st_sale: "할인 중(추정)", st_free: "현재 무료", st_changed: "누적 변동 상품", st_changed_daily: "오늘 변동 상품", st_daily_date: "대상: {date} (JST 관측분)", st_daily_unknown: "미집계", st_daily_stale: "당일 미집계 (이전: {date})", st_daily_updated: "집계 갱신: {time} (JST)", st_daily_update_unknown: "집계 갱신 시각 없음", st_change_basis: "가격 변동은 상품별 기록이 가장 많은 대표 옵션을 기준으로 판정합니다. 변경 횟수가 아닌 상품 수입니다.", st_period: "관측 시작일", st_stats_details: "날짜·집계 기준", st_daily_summary: "당일 ({date} JST): {state}", st_free_basis: "현재 무료는 과거 가격이 100엔 이상이었던 상품입니다.",
  free: "무료", rib_sale: "세일",
  status_lowest: "역대 최저가로 판매 중", save_note: "{v} 절약",
  reason_lowest: "역대 최저가를 갱신해 추천합니다", reason_sale: "할인 중인 상품에서 추천합니다",
  recent3w: "최근 3주간 가격 변동 {n}회", recent3w_short: "최근 3주간 {n}회 변경",
  reason_active: "최근 가격 변동이 잦아 추천합니다",
  added_on: "{d} 등록", alltime_changes: "전 기간 {n}회 변경",
  note_dropped: "{d} 가격 인하", note_nowfree: "현재 무료",
  pp_cur: "현재 가격", pp_high: "최고 가격", pp_avg: "평균 가격", pp_saledays: "할인 관측 일수", pp_days: "관측 일수", days_fmt: "{n}일",
  pp_chart: "가격 추이", pp_history: "가격 변동 이력", pp_same: "같은 샵의 상품", pp_parents: "부모 작품", pp_children: "파생 작품", rel_more: "더 보기",
  pp_booth: "BOOTH에서 보기", pp_bm: "북마크", pp_bmed: "북마크됨", pp_rec: "추천해요", pp_reced: "추천했어요", pp_share: "공유", pp_copied: "복사됨", bm_more: "더 보기", pp_vars: "바리에이션({n}종)", pp_compare: "가격 추이 비교", pp_changes: "가격 변동 내역", cmp_others: "외 {n}개", outlier: "이상치", outlier_n: "▲ 이상치 {n}건",
  pp_nodata: "가격 데이터가 부족합니다.", pp_nochg: "가격 변동이 관측되지 않았습니다.",
  pp_salenote: "분홍색 띠는 할인 중으로 추정되는 기간입니다.", pp_down: "인하", chg_date: "날짜", chg_before: "변경 전", chg_after: "변경 후", chg_rate: "변동률", pp_up: "인상",
  sp_count: "{n}건", sp_total: "전체 {n}건에서 검색", sec_recent: "최근 본 상품", seen_drop: "본 이후 -{v}",
  price_drop_label: "가격 인하",
},
"zh-Hans": {
  doc_title: "BoopaDB — BOOTH 的 VRChat 价格数据库（原型）",
  nav_sale: "促销中的商品", nav_feat: "精选商品", nav_browse: "新品·降价", cat_title: "按类别浏览", upd_title: "最近更新", img_search: "图像搜索", img_page_entry: "以图搜索商品 →", img_page_back: "返回", img_page_title: "用图片，寻找心仪商品。", img_page_intro: "选择图片以寻找相似的 BOOTH 商品。可搜索整张图片，也可圈选感兴趣的部分。", img_page_upload: "上传图片", img_page_hint: "拖放到这里，或点击选择", img_page_formats: "PNG、JPEG、WebP 等图片 / 1张，最大20MB", img_drop: "将图片拖到这里，或点击选择（1张，最大20MB）", img_file_empty: "请选择一张图片", img_file_one: "一次只能选择一张图片", img_file_type: "请选择图片文件", img_file_size: "请选择非空且不超过20MB的图片", img_file_decode: "无法打开这张图片，请尝试PNG、JPEG或WebP格式", img_similar: "查找相似图片", img_trace_hint: "用手指圈出要查找的物品", img_use_area: "搜索此区域", img_use_whole: "搜索整张图片", img_retake: "重新选择", img_searching: "正在用图像搜索…", img_limit: "已达到今日免费上限（5次），请明天再试", img_error: "图像搜索失败，请稍后再试", img_notindexed: "此商品的图片尚未收录", lv_fit: "显示全部", upd_newvar: "新增规格", shops_title: "认识的店铺作品", shops_n: "{n} 件商品",
  hero_title: "精选与推荐",
  feat_note: "并非按是否促销，而是按价格变动活跃度和上新来挑选。",
  sort_pct: "按折扣率", sort_amount: "按优惠金额", sort_cheap: "价格从低到高", sort_pop: "按人气", sort_new: "最新上架",
  chip_all: "全部", chip_lowest: "历史最低", rng_1d: "1天", rng_5d: "5天", rng_1m: "1个月", rng_6m: "6个月", rng_ytd: "年初至今", rng_1y: "1年", rng_5y: "5年", rng_max: "全部", chip_half: "5折及以上", chip_onsale: "促销中",
  empty_none: "没有符合条件的商品", loading: "加载中…", more: "查看更多",
  sale_note: "※ 原价为观测期内的最高价格。促销判定包含基于 Boopa 采集数据的推测。",
  bt_new: "新品", bt_special: "特价", bt_drop: "降价", bt_active: "价格变动频繁", bt_rising: "急升", rising_note: "{likes} · +{g}/日",
  ft_data: "数据为 Boopa（BOOTH Price Tracker for VRChat）采集的真实数据。价格为观测时点的价格，可能与 BOOTH 当前价格不同。",
  ft_legal: "BoopaDB 是与 BOOTH 及 pixiv 株式会社无关的非官方项目。所有时间均为日本时间（JST）。",
  ft_terms: "使用条款", ft_priv: "隐私", ft_app: "应用", app_promo_t: "将 BoopaDB 作为应用使用", app_promo_b: "添加到主屏幕后可以全屏打开",
  ft_tm: "BOOTH 是 pixiv 株式会社的商标。其他商标及作品归各权利方所有。",
  pp_title: "商品详情", sp_title: "搜索商品", sp_ph: "按商品名或店铺名搜索", sp_shops: "按类别浏览", sp_filter: "筛选", sp_price_t: "按价格筛选", sp_price_any: "不限价格", sp_reset: "重置", sp_show_results: "显示结果", sp_sort_rel: "相关性", sp_sort_pop: "人气顺", sp_sort_rising: "急升", sp_sort_new: "最新上架", sp_sort_price_asc: "价格从低到高", sp_sort_price_desc: "价格从高到低", sp_sort_pct: "折扣率最高", sp_sort_name: "名称", th_toggle: "切换主题", sp_price_upto: "¥{n} 以下",
  tab_home: "首页", tab_sale: "促销", tab_news: "动态", tab_ranking: "排行榜", tab_bm: "收藏",
  al_back: "返回", al_prev: "上一个", al_next: "下一个", al_expand: "放大显示", al_close: "关闭", cmp_more: "还有{n}个", al_search: "搜索", al_slide: "幻灯片",
  st_total: "追踪商品", st_sale: "促销中（估计）", st_free: "当前免费", st_changed: "累计价格变动", st_changed_daily: "今日价格变动", st_daily_date: "日期：{date}（JST 观测）", st_daily_unknown: "尚未统计", st_daily_stale: "当日尚未统计（上次：{date}）", st_daily_updated: "统计更新：{time}（JST）", st_daily_update_unknown: "统计更新时间未知", st_change_basis: "按每件商品记录最多的代表规格判断价格变动。统计商品数量，不是变动次数。", st_period: "观测开始日", st_stats_details: "日期与统计口径", st_daily_summary: "当日（{date} JST）：{state}", st_free_basis: "当前免费仅统计曾售价100日元及以上的商品。",
  free: "免费", rib_sale: "促销",
  status_lowest: "正以历史最低价销售", save_note: "省 {v}",
  reason_lowest: "推荐：刚刚刷新历史最低价", reason_sale: "从促销商品中推荐",
  recent3w: "最近3周内价格变动 {n} 次", recent3w_short: "最近3周变动 {n} 次",
  reason_active: "推荐：最近价格变动频繁",
  added_on: "{d} 收录", alltime_changes: "全部期间变动 {n} 次",
  note_dropped: "{d} 降价", note_nowfree: "当前免费",
  pp_cur: "当前价格", pp_high: "最高价格", pp_avg: "平均价格", pp_saledays: "促销观测天数", pp_days: "观测天数", days_fmt: "{n} 天",
  pp_chart: "价格走势", pp_history: "价格变动记录", pp_same: "同店铺的其他商品", pp_parents: "父作品", pp_children: "子作品", rel_more: "查看更多",
  pp_booth: "在 BOOTH 查看", pp_bm: "收藏", pp_bmed: "已收藏", pp_rec: "推荐", pp_reced: "已推荐", pp_share: "分享", pp_copied: "已复制", bm_more: "查看更多", pp_vars: "规格（{n}种）", pp_compare: "比较价格走势", pp_changes: "价格变更记录", cmp_others: "+{n} 个", outlier: "离群值", outlier_n: "▲ 离群值{n}条",
  pp_nodata: "价格数据不足。", pp_nochg: "尚未观测到价格变动。",
  pp_salenote: "粉色区间为推测的促销期间。", pp_down: "降价", chg_date: "日期", chg_before: "变更前", chg_after: "变更后", chg_rate: "变化率", pp_up: "涨价",
  sp_count: "{n} 件", sp_total: "从全部 {n} 件中搜索", sec_recent: "最近浏览", seen_drop: "浏览后降了 {v}",
  price_drop_label: "降价",
},
"zh-Hant": {
  doc_title: "BoopaDB — BOOTH 的 VRChat 價格數據庫（原型）",
  nav_sale: "促銷中的商品", nav_feat: "精選商品", nav_browse: "新品·降價", cat_title: "按類別瀏覽", upd_title: "最近更新", img_search: "圖片搜尋", img_page_entry: "以圖搜尋商品 →", img_page_back: "返回", img_page_title: "用圖片，尋找心儀商品。", img_page_intro: "選擇圖片以尋找相似的 BOOTH 商品。可搜尋整張圖片，也可圈選感興趣的部分。", img_page_upload: "上傳圖片", img_page_hint: "拖放到這裡，或點擊選擇", img_page_formats: "PNG、JPEG、WebP 等圖片 / 1張，最大20MB", img_drop: "將圖片拖到這裡，或點擊選擇（1張，最大20MB）", img_file_empty: "請選擇一張圖片", img_file_one: "一次只能選擇一張圖片", img_file_type: "請選擇圖片檔案", img_file_size: "請選擇非空且不超過20MB的圖片", img_file_decode: "無法開啟這張圖片，請嘗試PNG、JPEG或WebP格式", img_similar: "尋找相似圖片", img_trace_hint: "用手指圈出要尋找的物品", img_use_area: "搜尋此區域", img_use_whole: "搜尋整張圖片", img_retake: "重新選擇", img_searching: "正在用圖片搜尋…", img_limit: "已達到今日免費上限（5次），請明天再試", img_error: "圖片搜尋失敗，請稍後再試", img_notindexed: "此商品的圖片尚未收錄", lv_fit: "顯示全部", upd_newvar: "新增規格", shops_title: "認識的店鋪作品", shops_n: "{n} 件商品",
  hero_title: "精選與推薦",
  feat_note: "並非按是否促銷，而是按價格變動活躍度和上新來挑選。",
  sort_pct: "按折扣率", sort_amount: "按優惠金額", sort_cheap: "價格從低到高", sort_pop: "按人氣", sort_new: "最新上架",
  chip_all: "全部", chip_lowest: "歷史最低", rng_1d: "1天", rng_5d: "5天", rng_1m: "1個月", rng_6m: "6個月", rng_ytd: "年初至今", rng_1y: "1年", rng_5y: "5年", rng_max: "全部", chip_half: "5折及以上", chip_onsale: "促銷中",
  empty_none: "沒有符合條件的商品", loading: "載入中…", more: "查看更多",
  sale_note: "※ 原價為觀測期內的最高價格。促銷判定包含基於 Boopa 採集數據的推測。",
  bt_new: "新品", bt_special: "特價", bt_drop: "降價", bt_active: "價格變動頻繁", bt_rising: "急升", rising_note: "{likes} · +{g}/日",
  ft_data: "數據為 Boopa（BOOTH Price Tracker for VRChat）採集的真實數據。價格為觀測時點的價格，可能與 BOOTH 當前價格不同。",
  ft_legal: "BoopaDB 是與 BOOTH 及 pixiv 株式會社無關的非官方項目。所有時間均為日本時間（JST）。",
  ft_terms: "使用條款", ft_priv: "隱私", ft_app: "應用", app_promo_t: "將 BoopaDB 作為應用使用", app_promo_b: "新增到主畫面後可以全螢幕開啟",
  ft_tm: "BOOTH 是 pixiv 株式會社的商標。其他商標及作品歸各權利方所有。",
  pp_title: "商品詳情", sp_title: "搜尋商品", sp_ph: "按商品名或店舖名搜尋", sp_shops: "按類別瀏覽", sp_filter: "篩選", sp_price_t: "按價格篩選", sp_price_any: "不限價格", sp_reset: "重置", sp_show_results: "顯示結果", sp_sort_rel: "相關性", sp_sort_pop: "人氣順", sp_sort_rising: "急升", sp_sort_new: "最新上架", sp_sort_price_asc: "價格從低到高", sp_sort_price_desc: "價格從高到低", sp_sort_pct: "折扣率最高", sp_sort_name: "名稱", th_toggle: "切換主題", sp_price_upto: "¥{n} 以下",
  tab_home: "首頁", tab_sale: "促銷", tab_news: "動態", tab_ranking: "排行榜", tab_bm: "收藏",
  al_back: "返回", al_prev: "上一個", al_next: "下一個", al_expand: "放大顯示", al_close: "關閉", cmp_more: "還有{n}個", al_search: "搜尋", al_slide: "投影片",
  st_total: "追蹤商品", st_sale: "促銷中（估計）", st_free: "目前免費", st_changed: "累計價格變動", st_changed_daily: "今日價格變動", st_daily_date: "日期：{date}（JST 觀測）", st_daily_unknown: "尚未統計", st_daily_stale: "當日尚未統計（上次：{date}）", st_daily_updated: "統計更新：{time}（JST）", st_daily_update_unknown: "統計更新時間未知", st_change_basis: "依每件商品記錄最多的代表規格判定價格變動。統計商品數量，不是變動次數。", st_period: "觀測開始日", st_stats_details: "日期與統計方式", st_daily_summary: "當日（{date} JST）：{state}", st_free_basis: "目前免費僅統計曾售價100日圓以上的商品。",
  free: "免費", rib_sale: "促銷",
  status_lowest: "正以歷史最低價銷售", save_note: "省 {v}",
  reason_lowest: "推薦：剛剛刷新歷史最低價", reason_sale: "從促銷商品中推薦",
  recent3w: "最近3週內價格變動 {n} 次", recent3w_short: "最近3週變動 {n} 次",
  reason_active: "推薦：最近價格變動頻繁",
  added_on: "{d} 收錄", alltime_changes: "全部期間變動 {n} 次",
  note_dropped: "{d} 降價", note_nowfree: "當前免費",
  pp_cur: "當前價格", pp_high: "最高價格", pp_avg: "平均價格", pp_saledays: "促銷觀測天數", pp_days: "觀測天數", days_fmt: "{n} 天",
  pp_chart: "價格走勢", pp_history: "價格變動記錄", pp_same: "同店舖的其他商品", pp_parents: "父作品", pp_children: "子作品", rel_more: "查看更多",
  pp_booth: "在 BOOTH 查看", pp_bm: "收藏", pp_bmed: "已收藏", pp_rec: "推薦", pp_reced: "已推薦", pp_share: "分享", pp_copied: "已複製", bm_more: "查看更多", pp_vars: "規格（{n}種）", pp_compare: "比較價格走勢", pp_changes: "價格變更記錄", cmp_others: "+{n} 個", outlier: "離群值", outlier_n: "▲ 離群值{n}筆",
  pp_nodata: "價格數據不足。", pp_nochg: "尚未觀測到價格變動。",
  pp_salenote: "粉色區間為推測的促銷期間。", pp_down: "降價", chg_date: "日期", chg_before: "變更前", chg_after: "變更後", chg_rate: "變化率", pp_up: "漲價",
  sp_count: "{n} 件", sp_total: "從全部 {n} 件中搜尋", sec_recent: "最近瀏覽", seen_drop: "瀏覽後降了 {v}",
  price_drop_label: "降價",
},
};
let LANG = "ja";
try { for (const [o, n] of [["boothdb_bm","boopadb_bm"],["boothdb_hist","boopadb_hist"],["boothdb_lang","boopadb_lang"]]) { const v = localStorage.getItem(o); if (v !== null) { if (localStorage.getItem(n) === null) localStorage.setItem(n, v); localStorage.removeItem(o); } } } catch {}
try { const s = localStorage.getItem("boopadb_lang"); if (s && I18N[s]) LANG = s; else { const n = (navigator.language || "ja").toLowerCase(); if (n.startsWith("en")) LANG = "en"; else if (n.startsWith("ko")) LANG = "ko"; else if (n.startsWith("zh")) LANG = (n.includes("tw") || n.includes("hk") || n.includes("hant")) ? "zh-Hant" : "zh-Hans"; } } catch {}
let THEME = document.documentElement.dataset.theme === "light" ? "light" : "dark";
let C_GRID, C_AXIS, C_SUB, C_NOTE, CMP_COLORS;
function setThemeColors(){
  const L = THEME === "light";
  C_GRID = L ? "#d5d5dc" : "#26262c";
  C_AXIS = L ? "#8b8b94" : "#6f6f78";
  C_SUB = L ? "#5b5b64" : "#a2a2ab";
  C_NOTE = L ? "#c99700" : "#e8c547";
  CMP_COLORS = L ? ["#e04347", "#d97a1f", "#c99700", "#5c8a04", "#0e9594", "#7c4dff", "#d6336c", "#4c6ef5", "#a06a2c", "#2f9e44", "#d64550", "#5a9e3d"] : ["#fc4d50", "#f2994a", "#e8c547", "#a4d007", "#2dcccd", "#b388ff", "#ff7eb6", "#8d9eec", "#c98f4e", "#7fd08a", "#e06c75", "#98c379"];
}
setThemeColors();
const csMeta = document.querySelector('meta[name="color-scheme"]'); if (csMeta) csMeta.content = THEME;
const LOCALES = { ja: "ja-JP", en: "en-US", ko: "ko-KR", "zh-Hans": "zh-CN", "zh-Hant": "zh-TW" };
const LOCALE = LOCALES[LANG];
function tr(k, v){
  let s = (I18N[LANG] && I18N[LANG][k]) ?? I18N.ja[k] ?? k;
  if (v) for (const key in v) s = s.split("{" + key + "}").join(String(v[key]));
  return s;
}
document.documentElement.lang = LANG;
document.title = tr("doc_title");
document.querySelectorAll("[data-i]").forEach(el => { el.textContent = tr(el.dataset.i); });
document.querySelectorAll("[data-i-ph]").forEach(el => { el.placeholder = tr(el.dataset.iPh); });
document.querySelectorAll("[data-i-al]").forEach(el => { el.setAttribute("aria-label", tr(el.dataset.iAl)); });
{
  const menu = document.getElementById("langMenu");
  const cur = document.getElementById("langCur");
  if (menu && cur) {
    cur.textContent = LANGS.find(l => l[0] === LANG)[1];
    menu.innerHTML = LANGS.map(([c, n]) => `<button type="button" data-lang="${c}" class="${c === LANG ? "on" : ""}">${n}</button>`).join("");
    menu.querySelectorAll("button").forEach(b => b.onclick = () => {
      try { localStorage.setItem("boopadb_lang", b.dataset.lang); } catch {}
      location.reload();
    });
    document.getElementById("langBtn").onclick = e => { e.stopPropagation(); menu.classList.toggle("open"); };
    document.addEventListener("click", e => { if (!e.target.closest(".langsw")) menu.classList.remove("open"); });
  }
}

const yen = n => n === 0 ? tr("free") : "¥" + n.toLocaleString(LOCALE);
const wCls = amt => { if (amt == null) return ""; const n = yen(amt).length; return n >= 10 ? " wxl" : n >= 8 ? " wl" : ""; };
const PH_ICON = '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="1.5"/><path d="M3 16l5-4 4 3 3-2 6 4"/></svg>';
function imgPh(el, cls){ var s = document.createElement('span'); s.className = cls; s.innerHTML = PH_ICON; el.replaceWith(s); }
const esc = s => s.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const itemUrl = id => "https://booth.pm/" + LANG + "/items/" + id;

// ---- storage: browsing history + bookmarks ----
const store = {
  get(k, d){ try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v){ try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
};
let HIST = store.get("boopadb_hist", []);
let BMS = store.get("boopadb_bm", []);
const isBm = id => BMS.some(b => String(b.id) === String(id));
const BM_FLAG_SVG = '<svg viewBox="0 0 24 24"><path d="M17 3H7a2 2 0 0 0-2 2v16l7-4 7 4V5a2 2 0 0 0-2-2z"/></svg>';
const bmFlag = (id, cls) => `<span class="bmflag${cls ? " " + cls : ""}" data-bmflag="${id}"${isBm(id) ? "" : " hidden"}>${BM_FLAG_SVG}</span>`;
function syncBmFlags(){ document.querySelectorAll("[data-bmflag]").forEach(el => { el.hidden = !isBm(el.dataset.bmflag); }); }

// Daily figures are observation-day counts, never inferred from cumulative totals.
function statsJstDate(now = new Date()){
  const parts = new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
  const get = type => parts.find(p => p.type === type).value;
  return get('year')+'-'+get('month')+'-'+get('day');
}
function statsChangeSummary(st, now = new Date()){
  const target = statsJstDate(now), data = st && st.price_changes, daily = data && data.daily;
  const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value+'T00:00:00Z')) && new Date(value+'T00:00:00Z').toISOString().slice(0,10) === value;
  const date = daily && validDate(daily.date) ? daily.date : null;
  const stamp = daily && typeof daily.updated_at === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(daily.updated_at) ? Date.parse(daily.updated_at) : NaN;
  const knownUpdate = Number.isFinite(stamp) && stamp <= now.getTime()+300000;
  const complete = data && data.schema === 1 && daily && daily.status === 'complete' && daily.timezone === 'Asia/Tokyo' && daily.basis === 'representative-variation-history' && date === target && Number.isSafeInteger(daily.unique_products) && daily.unique_products >= 0 && daily.unique_products <= st.changed && knownUpdate && statsJstDate(new Date(stamp)) >= date;
  return {target,date,count:complete ? daily.unique_products : null,status:date && date !== target ? 'stale' : complete ? 'complete' : 'unavailable',updated:knownUpdate ? new Intl.DateTimeFormat(LOCALE,{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(stamp)) : null};
}
let STATS_LAST = null, STATS_TARGET_DAY = null;
function renderStats(st){
  if (!st) return;
  STATS_LAST = st;
  const day = statsChangeSummary(st);
  STATS_TARGET_DAY = day.target;
  const dailyState = day.status === 'stale' ? tr('st_daily_stale',{date:day.date}) : day.count === null ? tr('st_daily_unknown') : day.count.toLocaleString(LOCALE);
  document.getElementById("stats").innerHTML = [
    [st.total.toLocaleString(LOCALE), tr("st_total")],
    [st.sale_now.toLocaleString(LOCALE), tr("st_sale")],
    [st.free_now.toLocaleString(LOCALE), tr("st_free")],
    [st.changed.toLocaleString(LOCALE), tr("st_changed"), 'changed-cumulative'],
    [day.count === null ? '—' : day.count.toLocaleString(LOCALE), tr('st_changed_daily'), 'changed-daily'],
    [st.min_date, tr("st_period"), 'tracking-since'],
  ].map(([n, l, key]) => `<div class="stat"${key ? ` data-stat="${key}"` : ''}><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("");
  const range = /^\d{4}-\d{2}-\d{2}$/.test(st.min_date) && /^\d{4}-\d{2}-\d{2}$/.test(st.max_date) ? st.min_date + ' 〜 ' + st.max_date : '';
  const note = document.getElementById('statsPriceBasis'), wasOpen = !!note.querySelector('details[open]');
  note.innerHTML = `<p class="stats-status">${tr('st_daily_summary',{date:day.target,state:dailyState})}</p><details class="stats-details"${wasOpen ? ' open' : ''}><summary>${tr('st_stats_details')}</summary><p>${tr('st_changed')}${range ? ': '+range : ''}</p><p>${tr('st_daily_date',{date:day.target})}</p><p>${day.updated ? tr('st_daily_updated',{time:day.updated}) : tr('st_daily_update_unknown')}</p><p>${tr('st_change_basis')}</p><p>${tr('st_free_basis')}</p></details>`;
}
renderStats(P.stats);
function refreshStatsDay(){if(STATS_LAST && STATS_TARGET_DAY !== statsJstDate())renderStats(STATS_LAST);}
setInterval(refreshStatsDay,60000);
window.addEventListener('pageshow',refreshStatsDay);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshStatsDay();});

function ribOf(x){
  if (x.cur === 0) return ["free", tr("free")];
  if (x.at_lowest) return ["low", tr("chip_lowest")];
  if (x.sale) return ["sale", tr("rib_sale")];
  return null;
}
function htagsArr(x){
  const pct = displayDiscountPercent(x.base, x.cur);
  const t = [tr("chip_onsale"), ...(pct !== null && pct > 0 ? [`${pct}%OFF`] : [])];
  if (x.at_lowest) t.push(tr("chip_lowest"));
  if (x.shop) t.push(x.shop);
  return t;
}
function htags(x){
  return htagsArr(x).map(t => "#" + t.replace(/[\s　]+/g, "")).join(" ");
}
function htagsPlain(x){
  const t = [];
  if (x.at_lowest) t.push(tr("chip_lowest"));
  if (x.shop) t.push(x.shop);
  return t.map(t => "#" + t.replace(/[\s　]+/g, "")).join(" ");
}
function heroNormSale(x){
  return {...x, _pct: x.pct, _disc: x.pct, _rib: ribOf({...x, sale: true}), _tags: htagsArr(x),
    _status: x.at_lowest ? tr("status_lowest") : tr("save_note", {v: yen(x.base - x.cur)}),
    _reason: x.at_lowest ? tr("reason_lowest") : tr("reason_sale")};
}
function heroNormActive(x){
  const pct = x.base > x.cur ? Math.round((1 - x.cur / x.base) * 100) : 0;
  return {...x, _pct: pct, _disc: x.on_sale ? pct : 0, _rib: ["act", tr("bt_active")], _tags: [tr("bt_active"), tr("recent3w_short", {n: x.changes_recent})],
    _status: tr("recent3w", {n: x.changes_recent}),
    _reason: tr("reason_active")};
}
function heroNormNew(x){
  const pct = x.base > x.cur ? Math.round((1 - x.cur / x.base) * 100) : 0;
  const rib = x.cur === 0 ? ["free", tr("free")] : (x.at_lowest ? ["low", tr("chip_lowest")] : ["new", tr("bt_new")]);
  return {...x, _pct: pct, _disc: x.on_sale ? pct : 0, _rib: rib, _tags: [tr("bt_new")],
    _status: tr("bt_new"), _reason: ""};
}
// HERO_SELECTOR_START: shared by the browser and scripts/embed-hero.cjs.
// Freeze the six-hour UTC window for this visit; never replace products on a timer.
const HOME_ROTATION_WINDOW = Math.floor(Date.now() / (6 * 60 * 60 * 1000));
function homeCandidatePool(list){
  const seen = new Set();
  return (Array.isArray(list) ? list : []).filter(x => x && x.id != null && (typeof hiddenItem !== "function" || !hiddenItem(x.id)) && x.image &&
    Number.isFinite(x.likes) && x.likes >= 0 && Number.isFinite(x.base) &&
    Number.isFinite(x.cur) && x.base >= 0 && x.base <= 100000 && x.cur >= 0)
    .sort((a, b) => b.likes - a.likes || String(a.id).localeCompare(String(b.id)))
    .filter(x => { const id = String(x.id); if (seen.has(id)) return false; seen.add(id); return true; })
    .slice(0, 40);
}
function homeCandidatePools(f){
  return {newest: homeCandidatePool(f.newest), on_sale: homeCandidatePool(f.on_sale)};
}
function homeRotationRank(id, window, section){
  let hash = 2166136261;
  for (const c of `${window}:${section}:${id}`) hash = Math.imul(hash ^ c.charCodeAt(0), 16777619);
  return hash >>> 0;
}
function homeRotatedPool(list, window, section){
  return homeCandidatePool(list).sort((a, b) =>
    homeRotationRank(a.id, window, section) - homeRotationRank(b.id, window, section) ||
    String(a.id).localeCompare(String(b.id)));
}
function selectHeroEntries(f, window = HOME_ROTATION_WINDOW){
  const A = homeRotatedPool(f.newest, window, "hero-new");
  const B = homeRotatedPool(f.on_sale, window, "hero-sale");
  const picks = [], seen = new Set(), shops = new Map();
  const take = (pool, kind) => {
    const item = pool.find(x => !seen.has(String(x.id)) && (!x.shop || (shops.get(x.shop) || 0) < 2));
    if (!item || picks.length >= 6) return false;
    seen.add(String(item.id));
    if (item.shop) shops.set(item.shop, (shops.get(item.shop) || 0) + 1);
    picks.push({kind, item}); return true;
  };
  while (picks.length < 6) {
    const a = take(A, "new"), b = take(B, "sale");
    if (!a && !b) break;
  }
  return picks;
}
function selectFeaturedEntries(f, hero, window = HOME_ROTATION_WINDOW){
  const seen = new Set(hero.map(x => String(x.item ? x.item.id : x.id))), shops = new Map();
  return homeRotatedPool(f.newest, window, "featured").filter(x => {
    const id = String(x.id);
    if (seen.has(id) || (x.shop && (shops.get(x.shop) || 0) >= 2)) return false;
    seen.add(id); if (x.shop) shops.set(x.shop, (shops.get(x.shop) || 0) + 1);
    return true;
  }).slice(0, 10);
}
// HERO_SELECTOR_END
// Regenerate together with lists_full.json; no full-catalog fetch needed to paint.
const HERO_BOOTSTRAP = {"newest":[],"on_sale":[]}; // HERO_BOOTSTRAP_DATA
function normalizeHeroEntries(entries){
  return entries.map(x => x.kind === "sale" ? heroNormSale(x.item) : heroNormNew(x.item));
}
function heroSignature(items){
  // Keep an immutable render snapshot: fillHeroMetas enriches items asynchronously.
  return JSON.stringify(items.map(x => [String(x.id), x.name, x.image, x.shop,
    x.base, x.cur, x.likes, x.tags, x._rib, x._status, x._disc]));
}
const heroItems = normalizeHeroEntries(selectHeroEntries(HERO_BOOTSTRAP));
let heroRenderedSignature = "";
const track = document.getElementById("heroTrack");
const dotsEl = document.getElementById("heroDots");
const HEART_SVG = '<svg viewBox="0 0 24 24"><path d="M19.5 12.6 12 20l-7.5-7.4A5 5 0 1 1 12 6.1a5 5 0 1 1 7.5 6.5z"/></svg>';
function heroMetaHTML(x){
  const likes = typeof x.likes === "number" ? `<span class="pp-likes">${HEART_SVG}<span>${x.likes.toLocaleString()}</span></span>` : "";
  const tags = Array.isArray(x.tags) && x.tags.length ? x.tags.slice(0, 5).map(t => `<span class="htag">${esc(t)}</span>`).join("") : "";
  return likes + tags;
}
function heroRelHTML(parents, kids, kidTotal){
  parents = visibleItems(parents); kids = visibleItems(kids);
  const thumbs = list => `<span class="hthumbs">` + visibleItems(list).map(p => `<a class="hthumb" href="${itemUrl(p.id)}" target="_blank" rel="noopener" title="${esc(p.name || "")}">${p.img ? `<img decoding="async" src="${p.img}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}</a>`).join("") + `</span>`;
  let out = "";
  if (parents.length) out += `<div class="hrelrow"><span class="hrel-g">${tr("pp_parents")}</span>` + thumbs(parents) + `</div>`;
  if (kids.length) out += `<div class="hrelrow"><span class="hrel-g">${tr("pp_children")}（${kidTotal}）</span>` + thumbs(kids) + `</div>`;
  return out;
}
async function fillHeroMetas(){
  for (const x of heroItems) {
    const nodes = () => track.querySelectorAll(`[data-hmeta="${x.id}"]`);
    try {
      const m = await fetchMeta(x.id);
      if (!m) continue;
      if (typeof m.likes === "number") x.likes = m.likes;
      if (Array.isArray(m.tags)) x.tags = m.tags;
      let els = nodes(); if (!els.length) continue;
      els.forEach(el => { el.innerHTML = heroMetaHTML(x); });
      const parents = [], kidNames = [];
      let kidTotal = 0;
      const relIds = relationParentIds(m);
      for (const pid of relIds.ids) {
        if (parents.length >= 4) break;
        const pm = await fetchMeta(pid);
        if (!pm || !pm.name) continue;
        if (!relIds.strict && !isFallbackParent(m.category && m.category.name, pm)) continue;
        parents.push({id: pid, name: pm.name, img: pm.image_resized || pm.image || ""});
      }
      const shard = await fetchRelShard(Number(x.id) % 8);
      const ent = shard && shard[String(x.id)];
      if (ent) {
        kidTotal = ent[0];
        for (const cid of (ent[1] || []).slice(0, 4)) { const cm = await fetchMeta(cid); if (cm && cm.name) kidNames.push({id: cid, name: cm.name, img: cm.image_resized || cm.image || ""}); }
      }
      els = nodes(); if (!els.length) continue;
      els.forEach(el => { el.innerHTML = heroMetaHTML(x) + heroRelHTML(parents, kidNames, kidTotal); });
    } catch (e) {}
  }
}
function heroSlideHTML(x, i){
  if (hiddenItem(x.id)) return "";
  return `
  <div class="hslide">
    <a class="himg" href="${itemUrl(x.id)}" target="_blank" rel="noopener">${x.image ? `<img decoding="async"${i ? ' loading="lazy"' : ''} class="hbg" src="${x.image}" alt="" aria-hidden="true" referrerpolicy="no-referrer" onerror="const w = this.closest('.himg'); if (w) w.querySelectorAll('img').forEach(i => i.remove())"><img decoding="async"${i ? ' loading="lazy"' : ' fetchpriority="high"'} class="hfg" src="${x.image}" alt="" referrerpolicy="no-referrer" onerror="const w = this.closest('.himg'); if (w) w.querySelectorAll('img').forEach(i => i.remove())">` : ""}<span class="rib ${x._rib[0]}">${x._rib[1]}</span></a>${bmFlag(x.id)}
    <div class="hbody">
      <div class="hname"><a href="${itemUrl(x.id)}" target="_blank" rel="noopener">${esc(x.name)}</a></div>
      <div class="hsub"><span class="hstatus">${x._status}</span>${x.shop ? `<span class="hshop">${esc(x.shop)}</span>` : ""}</div>
      <div class="hmeta" data-hmeta="${x.id}">${heroMetaHTML(x)}</div>
      <div class="hprice2">${x._disc > 0 ? `${discountBadge(x.base, x.cur, "disc")}` : ""}${x.base > x.cur ? `<span class="was${wCls(x.base)}">${yen(x.base)}</span>` : ""}<span class="price${x.cur === 0 ? " free" : ""}">${x.cur === 0 ? tr("free") : yen(x.cur)}</span></div>
    </div>
  </div>`;
}
function buildHero(items, preserveCurrent = false){
  const currentId = preserveCurrent && heroItems[hi] ? String(heroItems[hi].id) : null;
  const src = visibleItems(items);
  heroRenderedSignature = heroSignature(src);
  heroItems.length = 0;
  src.forEach(x => heroItems.push(x));
  track.innerHTML = heroItems.map(heroSlideHTML).join("");
  // Enrichment depends on caches/constants declared later in this script.
  // Defer until initialization finishes; otherwise its catch hides TDZ errors.
  Promise.resolve().then(fillHeroMetas);
  const first = track.children[0], last = track.children[track.children.length - 1];
  if (first && last){
    const cFirst = first.cloneNode(true); cFirst.dataset.clone = "1"; cFirst.classList.remove("active");
    const cLast = last.cloneNode(true); cLast.dataset.clone = "1"; cLast.classList.remove("active");
    track.appendChild(cFirst);
    track.insertBefore(cLast, first);
  }
  dotsEl.innerHTML = heroItems.map((_, i) => `<button data-i="${i}" aria-label="${tr("al_slide")} ${i + 1}"></button>`).join("");
  dotsEl.querySelectorAll("button").forEach(d => d.onclick = () => { heroGo(Number(d.dataset.i)); heroPlay(); });
  HN = heroItems.length;
  hi = Math.max(0, heroItems.findIndex(x => String(x.id) === currentId));
  heroPos(hi + 1, false);
  dotsEl.querySelectorAll("button").forEach((d, j) => d.classList.toggle("on", j === hi));
}
document.getElementById("heroPrev").onclick = () => { heroStep(-1); heroPlay(); };
document.getElementById("heroNext").onclick = () => { heroStep(1); heroPlay(); };
let hi = 0, heroTimer = null;
let HN = heroItems.length;
function heroPos(p, animate){
  const slide = track.children[0];
  if (!slide) return;
  const w = slide.getBoundingClientRect().width;
  if (!w) { requestAnimationFrame(() => heroPos(p, animate)); return; }
  const center = (track.parentElement.clientWidth - w) / 2;
  if (animate) {
    track.style.transition = "";
    track.style.transform = `translateX(${Math.round(center - (w + 12) * p)}px)`;
  } else {
    // Instant reposition: kill the transition, commit the transform with a
    // forced reflow, and only restore the transition on the next frame —
    // restoring it in the same task lets some mobile browsers animate the
    // jump anyway (the visible "rewind" across all slides).
    track.style.transition = "none";
    track.style.transform = `translateX(${Math.round(center - (w + 12) * p)}px)`;
    void track.offsetWidth;
    requestAnimationFrame(() => { track.style.transition = ""; });
  }
  [...track.children].forEach((s, j) => s.classList.toggle("active", j === p));
}
function heroGo(i){
  i = ((i % HN) + HN) % HN;
  // Jumping between the last and first slides wraps instantly (no sweep
  // across all slides, no rewind animation).
  if (HN > 1 && hi === HN - 1 && i === 0) { heroStep(1); return; }
  if (HN > 1 && hi === 0 && i === HN - 1) { heroStep(-1); return; }
  hi = i;
  heroPos(hi + 1, true);
  dotsEl.querySelectorAll("button").forEach((d, j) => d.classList.toggle("on", j === hi));
}
function heroStep(dir){
  const target = hi + dir;
  if (target >= 0 && target < HN) { heroGo(target); return; }
  // Loop wrap: jump straight to the other end with NO animation. The old
  // clone-and-snap route still produced a visible rewind sweep on some
  // mobile browsers (the snap-back animated anyway), so the wrap is an
  // instant cut now.
  hi = ((target % HN) + HN) % HN;
  heroPos(hi + 1, false);
  dotsEl.querySelectorAll("button").forEach((d, j) => d.classList.toggle("on", j === hi));
}
window.addEventListener("resize", () => heroPos(hi + 1, false));
window.addEventListener("load", () => heroPos(hi + 1, false));
window.addEventListener("pageshow", () => heroPos(hi + 1, false));
document.addEventListener("visibilitychange", () => { if (!document.hidden) heroPos(hi + 1, false); });
// iPad Safari can settle its viewport/layout AFTER boot without firing any of
// the events above (chrome settling, returning to a frozen tab), leaving the
// hero positioned from a stale width — slides bleeding into each other until
// a reload. Refit on any hero-view size change and on a short timer ladder.
if (window.ResizeObserver) {
  let _heroRoT = null;
  const _heroRo = new ResizeObserver(() => {
    if (_heroRoT) return;
    _heroRoT = setTimeout(() => { _heroRoT = null; heroPos(hi + 1, false); }, 60);
  });
  _heroRo.observe(track.parentElement);
}
setTimeout(() => heroPos(hi + 1, false), 500);
setTimeout(() => heroPos(hi + 1, false), 1600);
window.addEventListener("orientationchange", () => { requestAnimationFrame(() => heroPos(hi + 1, false)); setTimeout(() => heroPos(hi + 1, false), 250); });
function heroPlay(){ heroStop(); heroTimer = setInterval(() => heroStep(1), 4200); }
function heroStop(){ if (heroTimer) clearInterval(heroTimer); }
dotsEl.querySelectorAll("button").forEach(d => d.onclick = () => { heroGo(Number(d.dataset.i)); heroPlay(); });
const heroEl = document.getElementById("hero");
heroEl.addEventListener("pointerdown", heroStop);
heroEl.addEventListener("pointerup", () => setTimeout(heroPlay, 2500));
let tx0 = null;
heroEl.addEventListener("touchstart", e => { tx0 = e.touches[0].clientX; }, {passive: true});
heroEl.addEventListener("touchend", e => {
  if (tx0 === null) return;
  const dx = e.changedTouches[0].clientX - tx0;
  if (Math.abs(dx) > 42) { heroStep(dx < 0 ? 1 : -1); heroPlay(); }
  tx0 = null;
}, {passive: true});
buildHero(heroItems);
heroPlay();

const tabBtns = [...document.querySelectorAll("#tabbar button[data-to]")];
const barPath = document.getElementById("barPath");
const searchBtn = document.getElementById("tabSearch");
const mqV = window.matchMedia("(min-width: 900px)");
const BAR_OFF = 30;
const NOTCH_R = 37, FILLET_R = 18;
const NOTCH_DY = Math.sqrt(NOTCH_R * NOTCH_R + 2 * NOTCH_R * FILLET_R);
const NOTCH_T = FILLET_R / (NOTCH_R + FILLET_R);
function notchSegs(cx, cy, vertical){
  // returns [fillet1, notchArc, fillet2] path fragments for a notch centered at (cx, cy)
  // on the bar's right edge (vertical rail) or top edge (mobile), traced as
  // edge -> tangent fillet arc -> main arc hugging the button -> fillet -> edge
  if (vertical){
    const x = cx, p = cy;
    const t1x = x - FILLET_R + NOTCH_T * FILLET_R, t1y = p - NOTCH_DY + NOTCH_T * NOTCH_DY;
    const t2x = t1x, t2y = 2 * p - t1y;
    return `L ${x} ${p - NOTCH_DY} A ${FILLET_R} ${FILLET_R} 0 0 1 ${t1x} ${t1y} A ${NOTCH_R} ${NOTCH_R} 0 0 0 ${t2x} ${t2y} A ${FILLET_R} ${FILLET_R} 0 0 1 ${x} ${p + NOTCH_DY} `;
  }
  const o = cy, p = cx;
  const t1x = p - NOTCH_DY + NOTCH_T * NOTCH_DY, t1y = o + FILLET_R - NOTCH_T * FILLET_R;
  const t2x = 2 * p - t1x, t2y = t1y;
  return `L ${p - NOTCH_DY} ${o} A ${FILLET_R} ${FILLET_R} 0 0 1 ${t1x} ${t1y} A ${NOTCH_R} ${NOTCH_R} 0 0 0 ${t2x} ${t2y} A ${FILLET_R} ${FILLET_R} 0 0 1 ${p + NOTCH_DY} ${o} `;
}
function drawBar(){
  const barEl = document.getElementById("tabbar");
  const W = barEl.clientWidth, H = barEl.clientHeight;
  if (mqV.matches){
    const R = 20, p = H / 2;
    barPath.setAttribute("d", `M ${W} ${R} ${notchSegs(W, p, true)}L ${W} ${H - R} A ${R} ${R} 0 0 1 ${W - R} ${H} L ${R} ${H} A ${R} ${R} 0 0 1 0 ${H - R} L 0 ${R} A ${R} ${R} 0 0 1 ${R} 0 L ${W - R} 0 A ${R} ${R} 0 0 1 ${W} ${R} Z`);
  } else {
    const R = 32, o = BAR_OFF, p = W / 2;
    barPath.setAttribute("d", `M ${R} ${o} ${notchSegs(p, o, false)}L ${W - R} ${o} A ${R} ${R} 0 0 1 ${W} ${o + R} L ${W} ${o + H - R} A ${R} ${R} 0 0 1 ${W - R} ${o + H} L ${R} ${o + H} A ${R} ${R} 0 0 1 0 ${o + H - R} L 0 ${o + R} A ${R} ${R} 0 0 1 ${R} ${o} Z`);
  }
}
function setTab(b){
  tabBtns.forEach(x => x.classList.toggle("on", x === b));
  b.classList.remove("pop"); void b.offsetWidth; b.classList.add("pop");
}
window.addEventListener("resize", drawBar);
window.addEventListener("load", drawBar);
window.addEventListener("orientationchange", () => { requestAnimationFrame(drawBar); setTimeout(drawBar, 250); });
window.addEventListener("pageshow", drawBar);
if (window.ResizeObserver) new ResizeObserver(drawBar).observe(document.getElementById("tabbar"));
drawBar();
let spyLock = false, spyLockTimer = null;
function lockSpy(){
  spyLock = true;
  clearTimeout(spyLockTimer);
  spyLockTimer = setTimeout(() => { spyLock = false; }, 1400);
}
tabBtns.forEach(b => b.onclick = () => {
  // On the standalone product page the tab jumps live on index.html.
  if (location.pathname.endsWith("item.html")) { location.href = "index.html" + (b.dataset.to || ""); return; }
  setTab(b);
  lockSpy();
  if (b.dataset.btab) setBTab(b.dataset.btab);
  const wasOpen = spage.classList.contains("open") || prodPage.classList.contains("open");
  if (spage.classList.contains("open")) closeSearch();
  if (prodPage.classList.contains("open")) closeProduct();
  setTimeout(() => {
    // ホーム goes to the very top of the page, not just the hero.
    if (b.dataset.to === "#hero") window.scrollTo({top: 0, behavior: "smooth"});
    else document.querySelector(b.dataset.to).scrollIntoView({behavior: "smooth", block: "start"});
  }, wasOpen ? 120 : 0);
});
// ニュース and ランキング live on their own pages now.
document.querySelectorAll("#tabbar button[data-href]").forEach(b => b.onclick = () => { location.href = b.dataset.href; });
const spage = document.getElementById("searchPage");
// While the search or product overlay is open, the home content leaves
// the render tree entirely (body.veil): with nothing behind the overlay
// there is no background scrollbar on any browser, and no background
// scroll. The home scroll position is saved and restored on close.
let veilY = null;
function veilSync(){
  const anyOpen = spage.classList.contains("open") || prodPage.classList.contains("open") || !document.getElementById("lensView").hidden;
  if (anyOpen) {
    if (veilY === null) veilY = window.scrollY;
    document.body.classList.add("veil");
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
  } else if (veilY !== null) {
    document.body.classList.remove("veil");
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
    const y = veilY; veilY = null;
    window.scrollTo(0, y);
  }
}
// Reconcile the same lock owner after viewport/lifecycle changes; never pin pixel widths.
let overlaySyncFrame = null;
function syncOverlayViewport(){
  if (overlaySyncFrame !== null) return;
  overlaySyncFrame = requestAnimationFrame(() => { overlaySyncFrame = null; veilSync(); });
}
window.addEventListener("resize", syncOverlayViewport);
window.addEventListener("orientationchange", syncOverlayViewport);
window.addEventListener("pageshow", syncOverlayViewport);
function openSearch(){
  loadFullIndex();
  prodPage.classList.remove("open");
  spage.classList.add("open");
  veilSync();
  spRender();
  searchBtn.classList.add("on");
  setTimeout(() => { if (spage.classList.contains("open")) document.getElementById("spQ").focus(); }, 380);
}
function closeSearch(){
  if(spCatalogImages)spCatalogImages.cancel();
  spRelClear();
  // Leaving search clears the relation/category filter modes, so the
  // next visit starts unfiltered instead of staying trapped in them.
  if (spRelId || spRelIds || spCatMode || spShopMode || spImgMode) {
    spRelId = null; spRelIds = null; spRelName = ""; spCatMode = null; spShopMode = null; imgClearMode(); spCatSync();
    try { history.replaceState(null, "", location.pathname); } catch {}
  }
  spSideSet(false);
  spage.classList.remove("open");
  veilSync();
  searchBtn.classList.remove("on");
  window.dispatchEvent(new Event("boopa:search-close"));
}
document.getElementById("tabSearch").addEventListener("pointerenter", loadFullIndex);
// Load the large text-search catalog on search intent, not during image-result metadata requests.
document.getElementById("tabSearch").onclick = () => {
  if (spage.classList.contains("open")) closeSearch(); else openSearch();
};
document.getElementById("spBack").onclick = closeSearch;

const spIndex = (() => {
  const map = new Map();
  P.on_sale.forEach(s => map.set(s.id, {...s, kind: "sale", sale: true}));
  P.drops.forEach(d => {
    if (!map.has(d.id)) map.set(d.id, {id: d.id, name: d.name, shop: d.shop, image: d.image, base: d.from, cur: d.to, pct: d.from ? Math.round((1 - d.to / d.from) * 100) : 0, at_lowest: d.at_lowest, kind: "drop", sale: !!d.on_sale});
    else { const mm = map.get(d.id); mm.kind = "sale"; mm.sale = true; }
  });
  P.charts.forEach(p => {
    if (map.has(p.id)) return;
    const keys = Object.keys(p.variations || {});
    if (!keys.length) return;
    const ser = p.variations[keys[0]];
    if (!ser.length) return;
    const prices = ser.map(r => r[1]);
    const cur = prices[prices.length - 1], base = Math.max(...prices);
    map.set(p.id, {id: p.id, name: p.name, shop: p.shop, image: p.image, base, cur, pct: base ? Math.round((1 - cur / base) * 100) : 0, at_lowest: cur === Math.min(...prices), kind: "item", sale: false});
  });
  (P.active || []).forEach(a => {
    const e = {id: a.id, name: a.name, shop: a.shop, image: a.image, base: a.base, cur: a.cur, pct: a.base > a.cur ? Math.round((1 - a.cur / a.base) * 100) : 0, at_lowest: a.at_lowest, first_date: a.first_date, changes_recent: a.changes_recent, kind: "active", sale: !!a.on_sale};
    if (map.has(a.id)) { const m = map.get(a.id); m.first_date = a.first_date; m.changes_recent = a.changes_recent; }
    else map.set(a.id, e);
  });
  (P.newest || []).forEach(a => {
    const e = {id: a.id, name: a.name, shop: a.shop, image: a.image, base: a.base, cur: a.cur, pct: a.base > a.cur ? Math.round((1 - a.cur / a.base) * 100) : 0, at_lowest: a.at_lowest, first_date: a.first_date, changes_recent: a.changes_recent, kind: "new", sale: !!a.on_sale};
    if (map.has(a.id)) { const m = map.get(a.id); m.first_date = a.first_date; if (m.kind === "item") m.kind = "new"; }
    else map.set(a.id, e);
  });
  return [...map.values()];
})();

function pxImg(v){ return !v ? "" : (String(v).includes("://") ? String(v) : "https://booth.pximg.net/c/620x620/" + v + "_base_resized.jpg"); }
function isoFD(n){ if (!n) return ""; const t = String(n); return t.slice(0, 4) + "-" + t.slice(4, 6) + "-" + t.slice(6, 8); }
// ---- full-catalog search (search_index.json: every tracked product) ----
let fullIndex = null, fullIndexLoading = false, spCatMap = new Map();
const SP_CATS = ["3D衣装 3Dモデル", "3D小道具 3Dモデル", "3Dテクスチャ 3Dモデル", "3D装飾品 3Dモデル", "3Dモデル（その他） 3Dモデル", "3Dキャラクター 3Dモデル", "3D環境・ワールド 3Dモデル", "VRoid 3Dモデル", "3Dツール・システム 3Dモデル", "3Dモーション・アニメーション 3Dモデル", "3D髪型 3Dモデル", "ソフトウェア ソフトウェア・ハードウェア", "3D靴 3Dモデル", "素材（その他） 素材データ", "ゲーム関連商品 ゲーム", "ヘアアクセサリー アクセサリー", "イラスト（その他） イラスト"];
/* BOOTH's official category names: BOOTH localizes them into English only
   (the ko/zh BOOTH sites show the English names too), so every non-ja
   display language uses these. Verified per category id on booth.pm/en. */
const CAT_EN = {"3D衣装":"3D Clothing","3D小道具":"3D Props","3Dテクスチャ":"3D Textures","3D装飾品":"3D Accessories","3Dモデル（その他）":"3D Models (Other)","3Dキャラクター":"3D Characters","3D環境・ワールド":"3D Environments / World","VRoid":"VRoid","3Dツール・システム":"3D Tools & Systems","3Dモーション・アニメーション":"3D Motion & Animation","3D髪型":"3D Hair","ソフトウェア":"Software","3D靴":"3D Shoes","素材（その他）":"Materials (Other)","ゲーム関連商品":"Game-related Items","ヘアアクセサリー":"Hair Accessories","イラスト（その他）":"Illustration (Other)"};
function catNameL(child){ return LANG !== "ja" && CAT_EN[child] ? CAT_EN[child] : child; }
function catLabelL(raw){ return catNameL(catLabel(raw)); }
function spEnrichFromIndex(){
  if (!fullIndex) return;
  const byId = new Map(fullIndex.map(e => [e[0], e]));
  const fill = x => { const e = byId.get(String(x.id)); if (!e) return; if (x.likes == null) x.likes = e[9]; if (!x.first_date) x.first_date = isoFD(e[11]); if (x.per_day == null) x.per_day = (e[12] || 0) / 10; if (x.from == null && x.to == null) x.at_lowest = !!e[7]; };
  spIndex.forEach(fill);
  if (FULL_LISTS) for (const k of Object.keys(FULL_LISTS)) { const v = FULL_LISTS[k]; if (Array.isArray(v)) v.forEach(fill); }
}
function spEnrichFromLists(){
  if (!FULL_LISTS) return;
  const byId = new Map();
  for (const k of Object.keys(FULL_LISTS)) {
    const v = FULL_LISTS[k];
    if (!Array.isArray(v)) continue;
    for (const x of v) {
      if (!x || x.id == null) continue;
      const cur = byId.get(String(x.id)) || {};
      if (x.likes != null) cur.likes = x.likes;
      if (x.first_date) cur.first_date = x.first_date;
      if (x.per_day != null) cur.per_day = x.per_day;
      if (x.from == null && k !== "free" && x.at_lowest != null) { cur._has = true; cur.at_lowest = !!x.at_lowest; }
      byId.set(String(x.id), cur);
    }
  }
  if (!byId.size) return;
  for (const x of spIndex) {
    const e = byId.get(String(x.id));
    if (!e) continue;
    if (x.likes == null && e.likes != null) x.likes = e.likes;
    if (!x.first_date && e.first_date) x.first_date = e.first_date;
    if (x.per_day == null && e.per_day != null) x.per_day = e.per_day;
    if (e._has) x.at_lowest = e.at_lowest;
  }
}
let spCatalogCache = { idx: null, hits: null };
function spCatalogHits(){
  if (spCatalogCache.idx !== fullIndex) {
    spCatalogCache = { idx: fullIndex, hits: fullIndex.map(e => ({id: e[0], name: e[1], shop: e[13] || "", image: e[10] || null, cur: e[3], base: e[4], lowest: e[5], sale: !!e[6], pct: e[4] > e[3] ? Math.round((1 - e[3] / e[4]) * 100) : 0, at_lowest: !!e[7], plain: e[3] === null || e[3] === undefined, likes: e[9] || 0, first_date: isoFD(e[11]), per_day: (e[12] || 0) / 10})) };
  }
  if (!spCatalogCache.byId) spCatalogCache.byId = new Map(spCatalogCache.hits.map(x=>[String(x.id),x]));
  return spCatalogCache.hits;
}
// Keep only the usable landing candidates; equal likes retain catalog order.
// Each catalog stream has unique IDs, so its first 3000 suffice for 3000
// deduplicated results even when history and the other streams overlap.
function spTopLiked(rows, limit = 3000, categories = null){
  const heap = [];
  const worse = (a, b) => a.likes < b.likes || (a.likes === b.likes && a.order > b.order);
  for (let order = 0; order < rows.length; order++) {
    const row = rows[order];
    if (categories && !categories.has(row[8])) continue;
    const likes = row[9] || 0;
    if (heap.length === limit && (likes < heap[0].likes || (likes === heap[0].likes && order > heap[0].order))) continue;
    const entry = {row, likes, order};
    if (heap.length < limit) {
      let i = heap.length; heap.push(entry);
      while (i > 0) {
        const parent = (i - 1) >> 1;
        if (!worse(entry, heap[parent])) break;
        heap[i] = heap[parent]; i = parent;
      }
      heap[i] = entry;
    } else {
      let i = 0;
      while (i * 2 + 1 < heap.length) {
        let child = i * 2 + 1;
        if (child + 1 < heap.length && worse(heap[child + 1], heap[child])) child++;
        if (!worse(heap[child], entry)) break;
        heap[i] = heap[child]; i = child;
      }
      heap[i] = entry;
    }
  }
  return heap.sort((a, b) => b.likes - a.likes || a.order - b.order).map(x => x.row);
}
let spLandingCache = { key: null, hits: null };
function spLandingHits(){
  const key = fullIndex.length + "|" + HIST.map(h => h.id).join(",") + "|" + BMS.map(b => b.id).join(",");
  if (spLandingCache.key === key) return spLandingCache.hits;
  const byIdF = new Map();
  for (const e of fullIndex) byIdF.set(e[0], e);
  const rich = new Map(spIndex.map(x => [String(x.id), x]));
  const plainOf = e => ({id: e[0], name: e[1], shop: e[13] || "", image: e[10] || null, cur: e[3], base: e[4], lowest: e[5], sale: !!e[6], pct: e[4] > e[3] ? Math.round((1 - e[3] / e[4]) * 100) : 0, at_lowest: !!e[7], plain: e[3] === null || e[3] === undefined, likes: e[9] || 0, first_date: isoFD(e[11]), per_day: (e[12] || 0) / 10});
  const objOf = id => rich.get(String(id)) || (byIdF.has(String(id)) ? plainOf(byIdF.get(String(id))) : null);
  const seen = new Set(), out = [];
  const push = x => { if (visibleItem(x) && !seen.has(String(x.id))) { seen.add(String(x.id)); out.push(x); } };
  visibleItems(HIST).slice(0, 12).forEach(h => push(objOf(h.id) || {id: h.id, name: h.name, shop: h.shop || "", image: h.image || null, cur: h.cur, base: h.cur, pct: 0, plain: true}));
  const bmCats = new Set(visibleItems(BMS).map(b => spCatMap.get(String(b.id))).filter(Boolean));
  const bmStream = bmCats.size ? spTopLiked(fullIndex, 3000, bmCats) : [];
  const popStream = spTopLiked(fullIndex);
  const newSeen = new Set(spIndex.map(x => String(x.id)));
  const newStream = [...spIndex, ...(chipSet("new") || []).filter(x => !newSeen.has(String(x.id)))];
  const streams = [
    bmStream.map(e => () => objOf(e[0])),
    popStream.map(e => () => objOf(e[0])),
    newStream.map(x => () => x)
  ].filter(st => st.length);
  const ptr = streams.map(() => 0);
  let progressed = true;
  while (progressed && out.length < 3000) {
    progressed = false;
    for (let s = 0; s < streams.length && out.length < 3000; s++) {
      if (ptr[s] < streams[s].length) { push(streams[s][ptr[s]++]()); progressed = true; }
    }
  }
  spLandingCache = { key, hits: out };
  return out;
}
const spCatalogParts=new Map();let spCatalogPromise=null,spCatalogFailed=false;
const spCatalogReader=typeof createBoopaCatalogReader==='function'?createBoopaCatalogReader(window,{core:typeof createBoopaCatalogImages==='function'}):null;
const spCatalogImages=spCatalogReader&&typeof spCatalogReader.image==='function'&&typeof createBoopaCatalogImages==='function'?createBoopaCatalogImages({reader:spCatalogReader,root:document.getElementById('spGrid'),resolve:pxImg,isOpen:()=>spage.classList.contains('open')}):null;
function spCatalogCopy(){return ({ja:['商品データを読み込み中','全件の取得が完了していません','再試行','暫定'],en:['Loading product catalog','Full catalog could not be loaded','Retry','Partial'],ko:['상품 목록 불러오는 중','전체 목록을 불러오지 못했습니다','다시 시도','일부'],"zh-Hans":['正在加载商品目录','未能加载完整目录','重试','部分'],"zh-Hant":['正在載入商品目錄','未能載入完整目錄','重試','部分']})[LANG] || ['Loading catalog','Catalog incomplete','Retry','Partial'];}
function spCatalogStatusSync(){
 const status=document.getElementById('spCatalogStatus'),retry=document.getElementById('spCatalogRetry');if(!status)return;
 status.hidden=!!fullIndex;status.dataset.loading=String(fullIndexLoading);
 document.getElementById('spCatalogMessage').textContent=spCatalogCopy()[spCatalogFailed?1:0]+' ('+(fullIndex?24:spCatalogParts.size)+'/24)';
 retry.hidden=!spCatalogFailed || fullIndexLoading;retry.textContent=spCatalogCopy()[2];
}
async function spFetchCatalogPart(i){
 const controller=new AbortController();let timer;
 try{return await Promise.race([(spCatalogReader?spCatalogReader.read(i,{signal:controller.signal}):fetch('search_index_'+i+'.json?v=20251027-2',{signal:controller.signal,cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('catalog');return r.json();})).then(rows=>{if(!Array.isArray(rows))throw new Error('catalog format');return visibleItems(rows);}),new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new Error('catalog timeout'));},30000);})]);}
 finally{clearTimeout(timer);}
}
function loadFullIndex(refresh = false){
 if(fullIndex)return Promise.resolve(fullIndex);if(spCatalogPromise)return spCatalogPromise;
 fullIndexLoading=true;spCatalogFailed=false;spCatalogStatusSync();
 spCatalogPromise=(async()=>{
  if(refresh === true && spCatalogReader && await spCatalogReader.refresh())spCatalogParts.clear();
  const missing=Array.from({length:24},(_,i)=>i).filter(i=>!spCatalogParts.has(i));let next=0;
  async function worker(){while(next<missing.length){const i=missing[next++];for(let attempt=0;attempt<2;attempt++){try{spCatalogParts.set(i,await spFetchCatalogPart(i));spCatalogStatusSync();break;}catch{if(attempt===1)spCatalogFailed=true;}}}}
  await Promise.all(Array.from({length:Math.min(4,missing.length)},worker));
  if(spCatalogParts.size===24){
   const raw=Array.from({length:24},(_,i)=>spCatalogParts.get(i)).flat();
   fullIndex = visibleItems(raw).map(([id, name, cur, base, lowest, sale, atlow, cat, likes, img, fd, pd, shop, tags]) => [String(id), name, String(name).normalize("NFKC").toLowerCase() + "\u0001" + String(shop || "").normalize("NFKC").toLowerCase() + "\u0001" + String(tags || "").normalize("NFKC").toLowerCase(), cur, base, lowest, sale, atlow, String(cat || "").normalize("NFKC").toLowerCase(), likes || 0, pxImg(img), fd || 0, pd || 0, shop || ""]); spCatMap = new Map(fullIndex.map(e => [e[0], e[8]])); for (const row of raw) { const c = row[7]; if (c) { const k = String(c).normalize("NFKC").toLowerCase(); if (!spCatNames.has(k)) spCatNames.set(k, String(c)); } } if (typeof spCatRender === "function") spCatRender(); spEnrichFromIndex();
   spCatalogParts.clear();spCatalogFailed=false;
  }else spCatalogFailed=true;
  return fullIndex;
 })().finally(()=>{fullIndexLoading=false;spCatalogPromise=null;spCatalogStatusSync();if(fullIndex)window.dispatchEvent(new Event('boopa:catalog-ready'));if(spage.classList.contains('open'))spRender(false);});
 return spCatalogPromise;
}
document.getElementById('spCatalogRetry').addEventListener('click',()=>loadFullIndex(true));
function thinPointsJS(rows){
  if (rows.length <= 2) return rows;
  const out = [rows[0]];
  for (let i = 1; i < rows.length - 1; i++) if (rows[i][1] !== rows[i - 1][1] || rows[i][2] !== rows[i - 1][2]) out.push(rows[i]);
  out.push(rows[rows.length - 1]);
  return out;
}
function outlierIdxJS(rows){
  const pos = rows.map((r, i) => i).filter(i => rows[i][1] > 0).sort((a, b) => rows[a][1] - rows[b][1]);
  const n = pos.length, out = new Set();
  for (let split = 5; split < n; split++) {
    if (rows[pos[split]][1] / rows[pos[split - 1]][1] >= 20 &&
        new Set(pos.slice(0, split).map(i => rows[i][0])).size >= 5) { pos.slice(split).forEach(i => out.add(i)); break; }
  }
  if (rows.some(r => r[1] === 0 || (r[1] > 0 && r[1] < 1000000))) rows.forEach((r, i) => { if (r[1] >= 1000000) out.add(i); });
  return out;
}
// Exact average sufficient statistics computed BEFORE graph thinning.
function averageSourceJS(rows){
  let sum = 0, count = 0, ordinarySum = 0, ordinaryCount = 0;
  for (const r of rows) {
    sum += r[1]; count++;
    if (!r[3]) { ordinarySum += r[1]; ordinaryCount++; }
  }
  const result = {sum: ordinaryCount ? ordinarySum : sum, count: ordinaryCount || count};
  if (!Number.isFinite(result.sum) || result.sum < 0 || result.sum > Number.MAX_SAFE_INTEGER || !Number.isSafeInteger(result.count)) throw new Error("Average statistics exceed safe numeric range");
  return result;
}
function hasAverageSource(ser){
  const a = ser && ser.average_source;
  return !!a && Number.isFinite(a.sum) && a.sum >= 0 && a.sum <= Number.MAX_SAFE_INTEGER && Number.isSafeInteger(a.count) && a.count > 0 && a.count <= ser.d;
}
function thinVarsJS(d){
  const vars = d.variations || {}, entries = {};
  for (const k in vars) {
    const series = vars[k];
    if (!Array.isArray(series) || series.length < 2) continue;
    const s = [...series].sort((a, b) => a.date < b.date ? -1 : 1);
    const rows = s.map(p => [p.date, p.price, p.is_sale ? 1 : 0]);
    const oi = outlierIdxJS(rows);
    rows.forEach((r, i) => { if (oi.has(i)) r.push(1); });
    entries[k] = {p: thinPointsJS(rows), d: rows.length, sd: rows.filter(r => r[2]).length, average_source: averageSourceJS(rows)};
  }
  const keys = Object.keys(entries);
  if (!keys.length) return null;
  const rep = keys.reduce((a, b) => entries[a].d >= entries[b].d ? a : b);
  const ordered = {[rep]: entries[rep]};
  keys.forEach(k => { if (k !== rep) ordered[k] = entries[k]; });
  return ordered;
}
function recordFromItem(d){
  let repSeries = null;
  const vk = d.variations || {};
  for (const k in vk) { if (Array.isArray(vk[k]) && (!repSeries || vk[k].length > repSeries.length)) repSeries = vk[k]; }
  if (!repSeries || !repSeries.length) return null;
  const s = [...repSeries].sort((a, b) => a.date < b.date ? -1 : 1);
  const prices = s.map(p => p.price);
  const cur = prices[prices.length - 1], base = Math.max(...prices), lowest = Math.min(...prices);
  const stride = Math.max(1, Math.floor(s.length / 24));
  const spark = s.filter((_, i) => i % stride === 0 || i === s.length - 1).map(p => [p.date, p.price]);
  let allLow = false;
  { let seen = false, okLow = true;
    for (const k in vk) { const arr = vk[k]; if (!Array.isArray(arr) || !arr.length) continue; seen = true; const ss2 = [...arr].sort((a, b) => a.date < b.date ? -1 : 1); const pp = ss2.map(p => p.price); if (pp[pp.length - 1] > Math.min(...pp)) { okLow = false; break; } }
    allLow = seen && okLow; }
  return {id: String(d.id), name: d.name || "", shop: "", image: null, cur, base, lowest,
    pct: base > cur ? Math.round((1 - cur / base) * 100) : 0, at_lowest: allLow,
    sale: !!s[s.length - 1].is_sale, spark, variations: thinVarsJS(d)};
}
const DATA_BASE = "https://mametarogg.github.io/booth-vrc-price-tracker/data/";
async function fetchItemRecord(id){
  id = String(id);
  if (hiddenItem(id)) return null;
  const meta = await fetchMeta(id).catch(() => null);
  if (hiddenItem(id)) return null;
  const r = await fetch(DATA_BASE + String(id).slice(0, 3) + "/" + id + ".json");
  if (!r.ok) return null;
  const raw = await r.json();
  if (!raw || String(raw.id) !== id || hiddenItem(id)) return null;
  noteVisibilityObservation(raw);
  const rec = recordFromItem(raw);
  if (rec && !rec.image) {
    const m = meta;
    if (m) {
      rec.image = m.image_resized || m.image || null;
      if (!rec.shop && m.shop) rec.shop = m.shop.name || "";
      if (m.name) rec.name = m.name;
      if (typeof m.likes === "number") rec.likes = m.likes;
      if (Array.isArray(m.tags)) rec.tags = m.tags;
      if (m.category && m.category.name) rec.category = m.category.name;
    }
  }
  return rec;
}
const META_BASE = "https://mametarogg.github.io/booth-vrc-price-tracker/meta/";
// Image-only correction; not a refresh of prices, names, variants or availability.
// Source: https://booth.pm/ja/items/5846349; verified 2026-10-30T14:12:49Z.
// JPEG SHA256: 642d34b389c4cbef6105d5f2a750fb69f723cf35e5cad2b33cc32692b401da10
function verifiedThumbnail(id){
  // Image-only proof: https://booth.pm/ja/items/2625416; SHA256 6e7f8f5dd29c15d64c7d4a59f3901fce7e280b54e04d5702689b3a3cfe3d525b
  if (String(id) === "2625416") return "https://booth.pximg.net/67ca34b5-0cd7-452e-a53a-f89794950c3d/i/2625416/24cc7397-56e4-4499-87b1-21fd0cae90a9_base_resized.jpg";
  return String(id) === "5846349" ? "https://booth.pximg.net/d6304d84-2a45-40c9-a097-1b6c352b8b18/i/5846349/15154d5d-200f-4282-a7f8-0fc0e84421c1_base_resized.jpg" : "";
}
const _metaCache = new Map();
function fetchMeta(id){
  id = String(id);
  if (hiddenItem(id)) return Promise.resolve(null);
  const cached = _metaCache.get(id);
  if (cached && cached.retryAt && Date.now() >= cached.retryAt) _metaCache.delete(id);
  if (!_metaCache.has(id)) {
    let timer;
    const request = Promise.race([fetch(META_BASE + id.slice(0, 3) + "/" + id + ".json", {cache: "no-cache"}), new Promise(resolve => { timer=setTimeout(() => resolve({ok:false}),8000); })])
      .then(r => r.ok ? r.json() : null).catch(() => null).finally(() => clearTimeout(timer))
      .then(meta => {
        meta = acceptVisibilityMeta(id, meta);
        if (hiddenItem(id)) return null;
        // Failed metadata must not stay unavailable for the entire page session.
        if (!meta || meta.unavailable) request.retryAt = Date.now() + 60000;
        const image = verifiedThumbnail(id);
        return image && !(meta && (meta.image_resized || meta.image))
          ? {...(meta || {}), image, image_resized: image, image_verified_at: String(id) === "2625416" ? "2026-10-31T00:54:24.326165+00:00" : "2026-10-30T14:12:49Z"} : meta;
      });
    _metaCache.set(id, request);
  }
  return _metaCache.get(id);
}
async function fillImgs(){
  if (window._filling) return;
  const els = [...document.querySelectorAll("[data-fill]")];
  if (!els.length) return;
  window._filling = true;
  try {
    await Promise.all(els.map(async el => {
      const id = el.getAttribute("data-fill");
      el.removeAttribute("data-fill");
      const m = await fetchMeta(id).catch(() => null);
      const img = m && (m.image_resized || m.image);
      if (img && el.isConnected) {
        const cls = el.classList.contains("bthph") ? "bthph" : el.classList.contains("pph") ? "pph" : "phcard";
        const im = document.createElement("img");
        if (cls === "bthph") im.className = "bth";
        im.src = img; im.alt = ""; im.loading = "lazy"; im.referrerPolicy = "no-referrer";
        im.onerror = () => imgPh(im, cls);
        el.replaceWith(im);
        const rec = PROD.get(String(id)); if (rec && !rec.image) rec.image = img;
        for (const k in LISTS) { const a = LISTS[k]; if (Array.isArray(a)) for (const s of a) if (String(s.id) === String(id) && !s.image) s.image = img; }
      }
    }));
  } finally { window._filling = false; if (document.querySelector("[data-fill]")) fillImgs(); }
}
new MutationObserver(() => { if (document.querySelector("[data-fill]")) fillImgs(); }).observe(document.body, {childList: true, subtree: true});
// ---- image stall watchdog: a hung image request never fires load or
// error, leaving a half-painted or blank image forever (seen on iPad).
// A pximg image that stays incomplete 9s+ while near the viewport is
// restarted by swapping in a fresh clone of itself. Elements sharing one
// URL join the same fetch, so a plain restart can rejoin the hung fetch;
// the second restart therefore fetches under a throwaway query key,
// which forces a genuinely new request. At most 2 restarts.
(function startImageWatchdog(){
  if (window.__wdOn) return;
  window.__wdOn = 1;
  const _wdImgs = new Map();
  function wdReg(img){
    if (_wdImgs.has(img)) return;
    const s = img.getAttribute && img.getAttribute("src");
    if (s && s.includes("pximg.net")) _wdImgs.set(img, { t: Date.now(), n: 0 });
  }
  function wdScanAll(root){
    if (!root || root.nodeType !== 1) return;
    if (root.tagName === "IMG") wdReg(root);
    if (root.querySelectorAll) root.querySelectorAll("img").forEach(wdReg);
  }
  setInterval(() => {
    const now = Date.now(), vh = innerHeight || 900;
    _wdImgs.forEach((st, img) => {
      if (!img.isConnected || img.complete) { _wdImgs.delete(img); return; }
      if (now - st.t < 9000 || st.n >= 2) return;
      const r = img.getBoundingClientRect();
      if (r.bottom < -vh || r.top > vh * 2 || r.width === 0) return;
      const c = img.cloneNode(false);
      if (st.n >= 1) {
        const s = c.getAttribute("src");
        if (s && !s.includes("wd=1")) c.setAttribute("src", s + (s.includes("?") ? "&" : "?") + "wd=1");
      }
      st.n++; st.t = now;
      _wdImgs.delete(img); _wdImgs.set(c, st);
      img.replaceWith(c);
    });
  }, 3000);
  new MutationObserver(ms => { for (const m of ms) if (m.addedNodes) m.addedNodes.forEach(wdScanAll); }).observe(document.documentElement, { childList: true, subtree: true });
  wdScanAll(document.body);
})();
const _relShardCache = {};
// Parent/child judgments are WITHDRAWN (user decision, 2026-10-25): the
// refs fallback and the scraper's heuristic base_refs are both unproven.
// Relations return when AI-judged base_refs land; flip this to enable.
const RELATIONS_LIVE = false;
function fetchRelShard(n){
  if (!RELATIONS_LIVE) return Promise.resolve({});
  if (!_relShardCache[n]) _relShardCache[n] = fetch("relations_children_" + n + ".json?v=20251025-9").then(r => r.ok ? r.json() : {}).catch(() => ({}));
  return _relShardCache[n];
}
function relationParentIds(m){
  if (!RELATIONS_LIVE) return { ids: [], strict: true };
  if (!m) return { ids: [], strict: false };
  if (Array.isArray(m.base_refs)) return { ids: m.base_refs.map(String).filter(id => !hiddenItem(id)), strict: true };
  return { ids: Array.isArray(m.refs) ? m.refs.map(String).filter(id => !hiddenItem(id)) : [], strict: false };
}
function isDependencyMeta(m){
  const c = m && m.category && m.category.name;
  return c === "3Dツール・システム" || c === "ソフトウェア";
}
// Fallback judgment for records the scraper could not context-judge:
// tools/software are dependencies, and a same-category link (other than
// character-to-character, i.e. a shared base body) is a sibling cross-sell,
// not a parent. Unknown categories stay.
function isFallbackParent(selfCat, m){
  if (!m) return false;
  if (isDependencyMeta(m)) return false;
  return true;
}
function relCard(id, m, i){
  if (hiddenItem(id)) return "";
  const img = m && (m.image_resized || m.image);
  const shop = m && m.shop ? (m.shop.name || "") : "";
  const likes = m && typeof m.likes === "number" ? `<div class="clikes">${HEART_SVG}${m.likes.toLocaleString()}</div>` : "";
  return `<div class="card" style="animation-delay:${((i || 0) % 30) * 45}ms">
    <a class="thumbwrap" href="${itemUrl(id)}" target="_blank" rel="noopener">${img ? `<img decoding="async" src="${img}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this,'phcard')">` : `<span class="phcard" data-fill="${id}">${PH_ICON}</span>`}${bmFlag(id)}</a>
    <div class="cbody">
      <div class="cname"><a href="${itemUrl(id)}" target="_blank" rel="noopener">${esc(m ? m.name : "")}</a></div>
      <div class="cshop"${shop ? ` data-shop="${esc(shop)}"` : ""}>${esc(shop)}</div>
      ${likes}
      <div class="crow" data-relcrow="${id}"><span class="price">—</span></div>
    </div>
  </div>`;
}
function relFillPrice(rec){
  document.querySelectorAll(`[data-relcrow="${rec.id}"]`).forEach(crow => {
    crow.innerHTML = rec.sale && rec.pct > 0
      ? `<span class="bprice">${discountBadge(rec.base, rec.cur, "discst")}<span class="bstack"><span class="was${wCls(rec.base)}">${yen(rec.base)}</span><span class="price">${rec.cur === 0 ? '<span class="free">' + tr("free") + '</span>' : yen(rec.cur)}</span></span></span>`
      : `<span class="price solo">${rec.cur === 0 ? '<span class="free">' + tr("free") + '</span>' : yen(rec.cur)}</span>`;
  });
}
let _relState = null;
async function relRenderCards(ids, opts = {}){
  ids = ids.filter(id => !hiddenItem(id));
  const metas = await Promise.all(ids.map(id => fetchMeta(id)));
  const cards = ids.map((id, i) => ({ id, m: metas[i] })).filter(o => !hiddenItem(o.id) && o.m && !(opts.parentFallback && !isFallbackParent(opts.selfCat, o.m)));
  return cards.map((o, i) => relCard(o.id, o.m, i)).join("");
}
let _relPriceObserver = null;
function relObservePrices(host){
  const targets = [...host.querySelectorAll("[data-relcrow]")];
  if (!targets.length) return;
  const load = el => {
    if (el.dataset.relLoading) return;
    el.dataset.relLoading = "1";
    fetchItemRecord(el.dataset.relcrow).then(rec => { if (rec) relFillPrice(rec); }).catch(() => {});
  };
  if (!("IntersectionObserver" in window)) { targets.forEach(load); return; }
  if (_relPriceObserver) _relPriceObserver.disconnect();
  _relPriceObserver = new IntersectionObserver(entries => {
    entries.forEach(e => { if (e.isIntersecting) { _relPriceObserver.unobserve(e.target); load(e.target); } });
  }, { rootMargin: "0px 500px 0px 500px" });
  targets.forEach(el => _relPriceObserver.observe(el));
}
const CHEV_L = '<svg viewBox="0 0 24 24"><path d="M14.5 5 7.5 12l7 7"/></svg>';
const CHEV_R = '<svg viewBox="0 0 24 24"><path d="M9.5 5l7 7-7 7"/></svg>';
function relBtns(rowId){ return `<button type="button" class="relbtn prev" data-relbtn="${rowId}|-1" aria-label="prev">${CHEV_L}</button><button type="button" class="relbtn next" data-relbtn="${rowId}|1" aria-label="next">${CHEV_R}</button>`; }
function relBtnSync(row){ if (row && row.parentElement) row.parentElement.classList.toggle("hasmore", row.scrollWidth - row.clientWidth > 8); }
document.addEventListener("click", e => {
  const b = e.target.closest("[data-relbtn]");
  if (!b) return;
  const [rowId, dir] = b.dataset.relbtn.split("|");
  const row = document.getElementById(rowId);
  if (row) row.scrollBy({ left: Number(dir) * row.clientWidth * 0.9, behavior: "smooth" });
});
// Reviewed snapshot UI gate: independent of withdrawn legacy refs/hero relations.
const RELATION_UI_LIVE = false;
const reviewedRelationData = typeof BoopaRelationshipData !== "undefined" ? BoopaRelationshipData.create({enabled:RELATION_UI_LIVE}) : null;
const reviewedRelationSupplement = typeof BoopaRelationshipSupplement !== "undefined" ? BoopaRelationshipSupplement.create() : null;
let reviewedRelationEpoch = 0;
function visibleRelationSnapshot(snapshot){
  if (!snapshot || snapshot.status !== "loaded") return snapshot;
  const entry = snapshot.entry ? {...snapshot.entry} : snapshot.entry;
  if (entry) for (const key of ["parents","prerequisites","thumbnail"]) if (Array.isArray(entry[key])) entry[key] = entry[key].filter(id => !hiddenItem(id));
  const children = (snapshot.children || []).filter(id => !hiddenItem(id));
  return {...snapshot,entry,children,childrenTotal:Math.max(0,(snapshot.childrenTotal || 0) - ((snapshot.children || []).length - children.length))};
}
function visibleRelationSupplement(result){ return result && result.status === "ready" ? {...result,references:(result.references || []).filter(visibleItem)} : result; }
async function loadRelations(x){
  if (hiddenItem(x.id)) return;
  const epoch = ++reviewedRelationEpoch;
  const host = document.getElementById("ppRel");
  if (!host || !RELATION_UI_LIVE || !reviewedRelationData || typeof BoopaRelationshipDraft === "undefined") return;
  const id = String(x.id);
  const isCurrent = () => epoch === reviewedRelationEpoch && document.getElementById("ppRel") === host && ppX && String(ppX.id) === id;
  if (reviewedRelationSupplement) BoopaRelationshipSupplement.clear(host);
  host.innerHTML = BoopaRelationshipDraft.render({status:"loading"},{},{lang:LANG});
  const snapshot = visibleRelationSnapshot(await reviewedRelationData.get(id));
  if (!isCurrent()) return;
  const supplemental = reviewedRelationSupplement ? reviewedRelationSupplement.get(id,snapshot.version) : null;
  const relationOptions = {
    lang:LANG, bookmarkHTML:bmFlag, isCurrent,
    onRender:()=>{if(reviewedRelationSupplement) BoopaRelationshipSupplement.sync(host);visibilityPrune(host);},
    fetchMeta:async target => {
      if (hiddenItem(target)) return null;
      const [meta,record] = await Promise.all([fetchMeta(target).catch(()=>null), Promise.resolve(PROD.get(target) || fetchItemRecord(target)).catch(()=>null)]);
      if (hiddenItem(target)) return null;
      return {...(meta || {}),name:meta && meta.name || record && record.name,price:record && typeof record.cur === "number" ? record.cur : null};
    }
  };
  const primary = BoopaRelationshipDraft.mountSnapshot(host,id,snapshot,relationOptions);
  const supplementalMount = supplemental && supplemental.then(result => { result=visibleRelationSupplement(result);BoopaRelationshipSupplement.mount(host,result,{...relationOptions,selfId:id}); return result; });
  await primary;
  if (supplementalMount) await BoopaRelationshipSupplement.mount(host,visibleRelationSupplement(await supplementalMount),{...relationOptions,selfId:id});
  visibilityPrune();
}
// DETAIL_HISTORY_HYDRATION_START
let detailHistoryEpoch = 0;
const detailHistoryInflight = new Map();
function hasDetailHistory(x){
  if (!x) return false;
  if (x._detailHistoryLoaded === true) return true;
  const entries = Object.values(x.variations || {});
  return entries.length > 0 && entries.every(v => { const rows = Array.isArray(v) ? v : v && v.p; return Array.isArray(rows) && rows.length >= 2 && hasAverageSource(v); });
}
function detailHistoryRequest(id){
  if (hiddenItem(id)) return Promise.reject(new Error("Unavailable item"));
  if (!detailHistoryInflight.has(id)) {
    let timer;
    const deadline = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('History request timeout')), 15000); });
    const request = Promise.race([Promise.resolve().then(() => fetchItemRecord(id)), deadline]).then(rec => {
      if (!rec || hiddenItem(id) || String(rec.id) !== id) throw new Error('Missing or mismatched item history');
      const old = PROD.get(id);
      const merged = {...rec, ...(old || {}), variations:rec.variations, spark:rec.spark, _detailHistoryLoaded:true};
      PROD.set(id, merged);
      return merged;
    }).finally(() => { clearTimeout(timer); detailHistoryInflight.delete(id); });
    detailHistoryInflight.set(id, request);
  }
  return detailHistoryInflight.get(id);
}
function detailHistoryStatus(id, failed){
  const chart = document.getElementById('ppChart');
  if (!chart) return;
  const labels = {ja:['価格履歴を読み込み中…','価格履歴を読み込めませんでした。','再試行'],en:['Loading price history…','Could not load price history.','Retry'],ko:['가격 기록 불러오는 중…','가격 기록을 불러오지 못했습니다.','다시 시도'],'zh-Hans':['正在加载价格历史…','无法加载价格历史。','重试'],'zh-Hant':['正在載入價格歷史…','無法載入價格歷史。','重試']};
  const text = labels[typeof LANG === 'string' ? LANG : 'ja'] || labels.ja;
  chart.innerHTML = `<p class="note" role="status">${failed ? text[1] : text[0]}</p>${failed ? `<button type="button" data-history-retry>${text[2]}</button>` : ''}`;
  const button = chart.querySelector('[data-history-retry]');
  if (button) button.onclick = () => openItemSmart(id);
}
function showHiddenProduct(){
  curProd = null; ppX = null;
  document.title = "BoopaDB";
  closeChartPop();
  document.getElementById('ppBody').innerHTML = '<p role="status" data-item-unavailable>商品が見つかりませんでした。 / Product unavailable.</p>';
  prodPage.classList.add('open'); veilSync();
}
function showPendingProduct(id){
  // A new navigation must not leave the previous product visible while
  // availability is checked. Keep cached names/prices private until then.
  const relationHost = document.getElementById('ppRel');
  if (relationHost && typeof BoopaRelationshipDraft !== 'undefined') BoopaRelationshipDraft.cancel(relationHost);
  curProd = {id}; ppX = null;
  document.title = "BoopaDB";
  closeChartPop();
  document.getElementById('ppBody').innerHTML = '<p role="status" data-item-pending>' + esc(tr('loading')) + '</p><div id="ppChart"></div>';
  prodPage.classList.add('open'); prodPage.scrollTop = 0; veilSync();
}
async function openItemSmart(id){
  id = String(id);
  if (!/^\d+$/.test(id)) return;
  const epoch = ++detailHistoryEpoch;
  if (hiddenItem(id)) { showHiddenProduct(); return; }
  showPendingProduct(id);
  // Check availability before opening cached cards or falling back to raw history.
  await fetchMeta(id).catch(() => null);
  if (epoch !== detailHistoryEpoch) return;
  if (hiddenItem(id)) { showHiddenProduct(); return; }
  const existing = PROD.get(id);
  if (existing) openProduct(id);
  else {
    curProd = null;
    ppX = null;
    document.getElementById('ppBody').innerHTML = '<div id="ppChart"></div>';
    prodPage.classList.add('open');
    veilSync();
  }
  if (hasDetailHistory(existing)) return;
  detailHistoryStatus(id, false);
  try {
    const rec = await detailHistoryRequest(id);
    if (epoch !== detailHistoryEpoch || !prodPage.classList.contains('open')) return;
    if (existing) { curProd = rec; renderProdPage(rec); }
    else openProduct(id);
  } catch {
    if (epoch === detailHistoryEpoch && prodPage.classList.contains('open')) { if (hiddenItem(id)) showHiddenProduct(); else detailHistoryStatus(id, true); }
  }
}
// DETAIL_HISTORY_HYDRATION_END
function plainCard(x, i){
  if (hiddenItem(x.id)) return "";
  return `<div class="card" data-pid="${x.id}">
    <a class="thumbwrap" href="${itemUrl(x.id)}" target="_blank" rel="noopener"><span class="noimg">${PH_ICON}</span>${bmFlag(x.id)}</a>
    <div class="cbody">
      <div class="cname"><a href="${itemUrl(x.id)}" target="_blank" rel="noopener">${esc(x.name)}</a></div>
      <div class="cshop"${x.shop ? ` data-shop="${esc(x.shop)}"` : ""}>${esc(x.shop || "")}</div>
      <div class="crow" data-crow="${x.id}"><span class="price">—</span></div>
    </div>
  </div>`;
}
function fillCardPrice(rec){
  const crow = document.querySelector(`[data-crow="${rec.id}"]`);
  if (!crow) return;
  crow.innerHTML = rec.sale && rec.pct > 0
    ? `<span class="bprice">${discountBadge(rec.base, rec.cur, "discst")}<span class="bstack"><span class="was${wCls(rec.base)}">${yen(rec.base)}</span><span class="price">${rec.cur === 0 ? '<span class="free">' + tr("free") + '</span>' : yen(rec.cur)}</span></span></span>`
    : `<span class="price solo">${rec.cur === 0 ? '<span class="free">' + tr("free") + '</span>' : yen(rec.cur)}</span>`;
  if (rec.at_lowest) {
    const card = crow.closest(".card");
    const tw = card && card.querySelector(".thumbwrap");
    if (tw && !tw.querySelector(".mlab")) {
      const m = document.createElement("span"); m.className = "mlab"; m.textContent = tr("chip_lowest"); tw.appendChild(m);
      const bf = tw.querySelector(".bmflag"); if (bf) bf.classList.add("u2");
    }
  }
}
const pricePending = new Set();
async function fillPriceLazy(id){
  if (hiddenItem(id)) return;
  if (PROD.has(String(id))) { fillCardPrice(PROD.get(String(id))); return; }
  if (pricePending.has(id)) return;
  pricePending.add(id);
  try { const rec = await fetchItemRecord(id); if (rec) { regP(rec); fillCardPrice(rec); } } catch {}
  pricePending.delete(id);
}

function chipSet(filter){
  if (!FULL_LISTS) return null;
  const F = FULL_LISTS, seen = new Map();
  const add = e => { if (!seen.has(String(e.id))) seen.set(String(e.id), e); };
  const pctOf = a => a.base > a.cur ? Math.round((1 - a.cur / a.base) * 100) : 0;
  if (filter === "sale") (F.on_sale || []).forEach(s => add({...s, kind: "sale", sale: true}));
  else if (filter === "free") (F.free || []).forEach(s => add({id: s.id, name: s.name, shop: s.shop, image: s.image, base: s.base, cur: 0, pct: 100, at_lowest: true, kind: "free", sale: !!s.on_sale}));
  else if (filter === "drop") (F.drops || []).forEach(d => add({id: d.id, name: d.name, shop: d.shop, image: d.image, base: d.from, cur: d.to, pct: d.from ? Math.round((1 - d.to / d.from) * 100) : 0, at_lowest: d.at_lowest, kind: "drop", sale: !!d.on_sale}));
  else if (filter === "new") (F.newest || []).forEach(a => add({id: a.id, name: a.name, shop: a.shop, image: a.image, base: a.base, cur: a.cur, pct: pctOf(a), at_lowest: a.at_lowest, first_date: a.first_date, kind: "new", sale: !!a.on_sale}));
  else if (filter === "rising") (F.rising || []).forEach(a => add({id: a.id, name: a.name, shop: a.shop, image: a.image, base: a.base, cur: a.cur, pct: pctOf(a), at_lowest: a.at_lowest, likes: a.likes, per_day: a.per_day, kind: "rising", sale: !!a.on_sale}));
  else if (filter === "lowest") {
    (F.on_sale || []).forEach(s => { if (s.at_lowest) add({...s, kind: "sale", sale: true}); });
    (F.drops || []).forEach(d => { if (d.at_lowest) add({id: d.id, name: d.name, shop: d.shop, image: d.image, base: d.from, cur: d.to, pct: d.from ? Math.round((1 - d.to / d.from) * 100) : 0, at_lowest: true, kind: "drop", sale: !!d.on_sale}); });
    (F.rising || []).forEach(a => { if (a.at_lowest) add({id: a.id, name: a.name, shop: a.shop, image: a.image, base: a.base, cur: a.cur, pct: pctOf(a), at_lowest: true, likes: a.likes, per_day: a.per_day, kind: "rising", sale: !!a.on_sale}); });
    (F.newest || []).forEach(a => { if (a.at_lowest) add({id: a.id, name: a.name, shop: a.shop, image: a.image, base: a.base, cur: a.cur, pct: pctOf(a), at_lowest: true, first_date: a.first_date, kind: "new", sale: !!a.on_sale}); });
  }
  return [...seen.values()];
}
let FULL_LISTS = null;
let spFilter = "all", spShown = 30, spTotal = 0, spRendered = 0, spKey = "";
let spShopMap = null, spShopMapSrc = undefined;
function buildShopMap(){
  spShopMap = new Map();
  const seen = new Set();
  const add = x => {
    if (!x || !x.shop || seen.has(String(x.id))) return;
    seen.add(String(x.id));
    const k = x.shop.toLowerCase();
    if (!spShopMap.has(k)) spShopMap.set(k, []);
    spShopMap.get(k).push(x);
  };
  spIndex.forEach(add);
  if (FULL_LISTS) ["sale", "free", "drop", "new", "rising", "lowest"].forEach(f => { const set = chipSet(f); if (set) set.forEach(add); });
  spShopMapSrc = FULL_LISTS;
}
const SP_CAPS = [500, 1000, 1500, 2000, 3000, 5000, 7000, 10000, 15000, 20000, 30000, 50000];
let spMaxPrice = null, spPriceT = null;
function spPriceLabel(){ document.getElementById("spPriceVal").textContent = spMaxPrice == null ? tr("sp_price_any") : tr("sp_price_upto", {n: spMaxPrice.toLocaleString(LOCALE)}); }
let SP_AFF = null;
function loadAff(){
  try {
    const o = store.get("boopadb_cat_aff", {}) || {};
    const es = Object.entries(o).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).slice(0, 8);
    if (!es.length) { SP_AFF = null; return; }
    const max = es[0][1];
    SP_AFF = es.map(([c, n]) => [String(c).normalize("NFKC").toLowerCase(), n / max]);
  } catch (e) { SP_AFF = null; }
}
function spAffRatio(cat){
  if (!cat || !SP_AFF) return 0;
  let best = 0;
  for (const [c, r] of SP_AFF) { if (r > best && (cat.includes(c) || c.includes(cat))) best = r; }
  return best;
}
function spRelSort(a, b){
  const ea = a._rank - 0.35 * spAffRatio(a._cat), eb = b._rank - 0.35 * spAffRatio(b._cat);
  return (ea - eb) || ((b._likes || 0) - (a._likes || 0));
}
function spRender(reset = true){
  if (reset) spShown = 30;
  const q = document.getElementById("spQ").value.trim().normalize("NFKC").toLowerCase();
  // Never paint the embedded sample as search results: its population, order
  // and prices differ from the verified full snapshot. Keep controls and the
  // explicit loading/error + retry region visible until one atomic commit.
  const pendingCatalog = !fullIndex && !spImgMode;
  const resultGrid = document.getElementById("spGrid");
  resultGrid.setAttribute("aria-busy", String(pendingCatalog));
  if (pendingCatalog) {
    resultGrid.replaceChildren(); spKey = ""; spRendered = 0; spTotal = 0;
    document.getElementById("spCount").textContent = "—";
    document.getElementById("spEmpty").style.display = "none";
    spCatalogStatusSync(); spModeSync(null); spRelStatusSync();
    spPriceLabel(); spFilterBtnLabel(); spSortSync();
    document.getElementById("spClear").hidden = !q;
    document.getElementById("spQ").parentElement.classList.toggle("has-query", !!q);
    return;
  }
  let hits, countOverride = null;
  if (spFilter !== "all") {
    const set = chipSet(spFilter);
    if (set) {
      hits = set.filter(x => !q || (x.name + " " + (x.shop || "")).toLowerCase().includes(q));
      if (spFilter === "new") hits.sort((a, b) => (b.first_date || "").localeCompare(a.first_date || ""));
      if (spFilter === "rising") hits.sort((a, b) => (b.per_day || 0) - (a.per_day || 0));
    }
  }
  if (spShopMode && fullIndex) {
    const rich = new Map(spIndex.map(x => [String(x.id), x]));
    hits = [];
    for (const e of fullIndex) {
      if (e[13] !== spShopMode) continue;
      const r = rich.get(e[0]);
      hits.push(r ? {...r, _likes: r.likes || e[9] || 0, likes: r.likes || e[9] || 0, first_date: r.first_date || isoFD(e[11]), per_day: r.per_day != null ? r.per_day : (e[12] || 0) / 10} : {id: e[0], name: e[1], shop: e[13], image: e[10] || null, cur: e[3], base: e[4], lowest: e[5], sale: !!e[6], pct: e[4] > e[3] ? Math.round((1 - e[3] / e[4]) * 100) : 0, at_lowest: !!e[7], plain: e[3] === null || e[3] === undefined, _likes: e[9] || 0, likes: e[9] || 0, first_date: isoFD(e[11]), per_day: (e[12] || 0) / 10});
    }
    hits.sort((a, b) => (b._likes || 0) - (a._likes || 0));
  }
  if (spImgMode) {
    hits = spImgHits;
  }
  if (spCatMode && fullIndex) {
    const target = spCatMode.normalize("NFKC").toLowerCase();
    const rich = new Map(spIndex.map(x => [String(x.id), x]));
    hits = [];
    for (const e of fullIndex) {
      if (e[8] !== target) continue;
      const r = rich.get(e[0]);
      hits.push(r ? {...r, _likes: r.likes || e[9] || 0, likes: r.likes || e[9] || 0, first_date: r.first_date || isoFD(e[11]), per_day: r.per_day != null ? r.per_day : (e[12] || 0) / 10} : {id: e[0], name: e[1], shop: e[13] || "", image: e[10] || null, cur: e[3], base: e[4], lowest: e[5], sale: !!e[6], pct: e[4] > e[3] ? Math.round((1 - e[3] / e[4]) * 100) : 0, at_lowest: !!e[7], plain: e[3] === null || e[3] === undefined, _likes: e[9] || 0, likes: e[9] || 0, first_date: isoFD(e[11]), per_day: (e[12] || 0) / 10});
    }
    hits.sort((a, b) => (b._likes || 0) - (a._likes || 0));
  }
  if (spRelIds && fullIndex) {
    const byId = new Map(fullIndex.map(e => [e[0], e]));
    const rich = new Map(spIndex.map(x => [String(x.id), x]));
    hits = [];
    for (const id of spRelIds) {
      const r = rich.get(id);
      if (r) { hits.push(r); continue; }
      const e = byId.get(id);
      if (!e) continue;
      hits.push({id, name: e[1], shop: e[13] || "", image: e[10] || null, cur: e[3], base: e[4], lowest: e[5], sale: !!e[6], pct: e[4] > e[3] ? Math.round((1 - e[3] / e[4]) * 100) : 0, at_lowest: !!e[7], plain: e[3] === null || e[3] === undefined, likes: e[9] || 0, first_date: isoFD(e[11]), per_day: (e[12] || 0) / 10});
    }
  }
  if (!hits && !q && spFilter === "all" && !spCatMode && !spRelIds && spSort !== "rel") {
    if (fullIndex) hits = spCatalogHits();
    else if(!spCatalogFailed && !fullIndexLoading)loadFullIndex();
  }
  if (!hits && q && spFilter === "all" && fullIndex) {
    loadAff();
    const rich = new Map(spIndex.map(x => [String(x.id), x]));
    hits = [];
    for (const [id, name, lower, icur, ibase, ilowest, isale, iatlow, icat, ilikes, iimg, ifd, ipd, ishop] of fullIndex) {
      const pos = lower.indexOf(q);
      const catHit = pos < 0 && !!icat && icat.indexOf(q) >= 0;
      if (pos < 0 && !catHit) continue;
      const r = rich.get(id);
      if (r) hits.push({...r, _rank: catHit ? 3.5 : (pos === 0 ? 0 : 2), _likes: r.likes || ilikes || 0, _cat: icat, likes: r.likes || ilikes || 0, first_date: r.first_date || isoFD(ifd), per_day: r.per_day != null ? r.per_day : (ipd || 0) / 10});
      else hits.push({id, name, shop: ishop || "", image: iimg || null, cur: icur, base: ibase, lowest: ilowest, sale: !!isale, pct: ibase > icur ? Math.round((1 - icur / ibase) * 100) : 0, at_lowest: !!iatlow, plain: icur === null || icur === undefined, _rank: catHit ? 3.5 : (pos === 0 ? 1 : 3), _likes: ilikes || 0, _cat: icat, likes: ilikes || 0, first_date: isoFD(ifd), per_day: (ipd || 0) / 10});
    }
    hits.sort(spRelSort);
    if (hits.length < 50) {
      const tokens = [...new Set(q.split(/[\s　]+/).filter(Boolean))];
      if (tokens.length >= 2) {
        const have = new Set(hits.map(h => String(h.id)));
        const extra = [];
        for (const [id, name, lower, cur, base, lowest, isale, atlow, icat, ilikes, img, ifd, ipd, ishop] of fullIndex) {
          if (have.has(String(id))) continue;
          let matched = 0;
          for (const t of tokens) if (lower.includes(t) || (icat && icat.includes(t))) matched++;
          const r = rich.get(String(id));
          if (matched === tokens.length) extra.push(r ? {...r, _rank: 4, _likes: r.likes || ilikes || 0, _cat: icat, likes: r.likes || ilikes || 0, first_date: r.first_date || isoFD(ifd), per_day: r.per_day != null ? r.per_day : (ipd || 0) / 10} : {id, name, shop: ishop || "", image: img || null, cur, base, lowest, sale: !!isale, pct: base > cur ? Math.round((1 - cur / base) * 100) : 0, at_lowest: !!atlow, plain: cur == null, _rank: 4, _likes: ilikes || 0, _cat: icat, likes: ilikes || 0, first_date: isoFD(ifd), per_day: (ipd || 0) / 10});
          else if (tokens.length >= 3 && matched >= 3 && matched >= tokens.length - 1) extra.push(r ? {...r, _rank: 5, _likes: r.likes || ilikes || 0, _cat: icat, likes: r.likes || ilikes || 0, first_date: r.first_date || isoFD(ifd), per_day: r.per_day != null ? r.per_day : (ipd || 0) / 10} : {id, name, shop: ishop || "", image: img || null, cur, base, lowest, sale: !!isale, pct: base > cur ? Math.round((1 - cur / base) * 100) : 0, at_lowest: !!atlow, plain: cur == null, _rank: 5, _likes: ilikes || 0, _cat: icat, likes: ilikes || 0, first_date: isoFD(ifd), per_day: (ipd || 0) / 10});
        }
        if (extra.length) hits = [...hits, ...extra].sort(spRelSort);
      }
    }
    if (spShopMapSrc !== FULL_LISTS) buildShopMap();
    const seenIds = new Set(hits.map(h => String(h.id)));
    const shopHits = [];
    for (const [shopLower, items] of spShopMap) {
      if (!shopLower.includes(q)) continue;
      for (const x of items) { const id = String(x.id); if (!seenIds.has(id)) { seenIds.add(id); shopHits.push({...x, _rank: 1.5, _likes: x.likes || 0, _cat: spCatMap.get(id) || ""}); } }
    }
    if (shopHits.length) hits = [...hits, ...shopHits].sort(spRelSort);
  } else if (!hits && !q && spFilter === "all" && FULL_LISTS && FULL_LISTS.newest && FULL_LISTS.newest.length) {
    // Landing with no query (relevance): personal blend — recently viewed
    // first, then bookmark-category picks, popular items and the newest
    // list woven round-robin. Pool fallback until the full index arrives.
    if (fullIndex) hits = spLandingHits();
    else { const seen = new Set(spIndex.map(x => String(x.id))); hits = [...spIndex, ...(chipSet("new") || []).filter(x => !seen.has(String(x.id)))]; }
  } else if (!hits) {
    hits = spIndex.filter(x => {
      if (q && !(x.name + " " + (x.shop || "")).toLowerCase().includes(q)) return false;
      if (spFilter === "sale") return x.kind === "sale";
      if (spFilter === "drop") return x.kind === "drop";
      if (spFilter === "lowest") return !!x.at_lowest;
      if (spFilter === "free") return x.cur === 0;
      if (spFilter === "new") return !!x.first_date;
      if (spFilter === "rising") return (x.per_day || 0) > 0;
      return true;
    });
    if (spFilter === "new") hits = hits.sort((a, b) => (b.first_date || "").localeCompare(a.first_date || ""));
    if (spFilter === "rising") hits = hits.sort((a, b) => (b.per_day || 0) - (a.per_day || 0));
  }
  if (!hits) hits = spIndex;
  hits = visibleItems(hits);
  if(fullIndex && !spImgMode){
    const broad=['all','sale','free','lowest'].includes(spFilter);
    if(spCatMode || spShopMode || spRelIds){
      const rel=spRelIds?new Set(spRelIds.map(String)):null;
      const category=spCatMode?spCatMode.normalize("NFKC").toLowerCase():null;
      hits=spCatalogHits().filter(x=>(!category||spCatMap.get(String(x.id))===category)&&(typeof spShopMode==="undefined"||!spShopMode||x.shop===spShopMode)&&(!rel||rel.has(String(x.id))));
    }
    if(broad && !spCatMode && !spShopMode && !spRelIds && (!q || spFilter!=='all')){
      hits=spCatalogHits();
      if(!q && spFilter==='all' && spSort==='rel' && spMaxPrice==null){
        const eligible=new Set(hits.map(x=>String(x.id))),front=spLandingHits().filter(x=>eligible.has(String(x.id))),seen=new Set(front.map(x=>String(x.id)));
        hits=[...front,...hits.filter(x=>!seen.has(String(x.id)))];
      }
    }
    // Embedded/home cards may contain older prices. Current catalog wins before filters.
    spCatalogHits();
    hits=hits.map(hit=>{const current=spCatalogCache.byId.get(String(hit.id));return !current||hit===current?hit:{...hit,...current,_likes:current.likes};});
    if(q && (spCatMode || spShopMode || spRelIds || spFilter!=='all')){
      const eligible=new Set(fullIndex.filter(e=>e[2].includes(q)||(e[8]&&e[8].includes(q))).map(e=>e[0]));
      hits=hits.filter(x=>eligible.has(String(x.id)));
    }
    if(spFilter==='free')hits=hits.filter(x=>x.cur===0);
    if(spFilter==='sale')hits=hits.filter(x=>!!x.sale);
    if(spFilter==='lowest')hits=hits.filter(x=>!!x.at_lowest);
    if(['drop','new','rising'].includes(spFilter) && (spCatMode || spShopMode || spRelIds)){
      const allowed=new Set((chipSet(spFilter)||[]).map(x=>String(x.id)));hits=hits.filter(x=>allowed.has(String(x.id)));
    }
  }
  if(spRelId && spRelLoadState==="ready" && fullIndex)hits=spRelHits(q);
  // While the child scope/catalog is incomplete, never fall back to unrelated items.
  if(spRelId && (spRelLoadState!=="ready" || !fullIndex))hits=[];
  hits = visibleItems(hits);
  if (spMaxPrice != null) hits = hits.filter(x => x.cur != null && x.cur <= spMaxPrice);
  if (spSort !== "rel") {
    const by = {
      pop: (a, b) => ((b._likes != null ? b._likes : (b.likes || 0)) - (a._likes != null ? a._likes : (a.likes || 0))),
      rising: (a, b) => ((b.per_day || 0) - (a.per_day || 0)) || ((b._likes != null ? b._likes : (b.likes || 0)) - (a._likes != null ? a._likes : (a.likes || 0))),
      price_asc: (a, b) => (a.cur == null ? Infinity : a.cur) - (b.cur == null ? Infinity : b.cur),
      price_desc: (a, b) => (b.cur == null ? -Infinity : b.cur) - (a.cur == null ? -Infinity : a.cur),
      pct: (a, b) => (b.pct || 0) - (a.pct || 0),
      name: (a, b) => a.name.localeCompare(b.name, LOCALE),
      new: (a, b) => (a.first_date || "") < (b.first_date || "") ? 1 : (a.first_date || "") > (b.first_date || "") ? -1 : 0
    }[spSort];
    if (by) hits = [...hits].sort(by);
  }
  if (!q && spFilter === "all" && fullIndex && spMaxPrice == null && !spRelIds && !spCatMode && !spShopMode && !spImgMode) countOverride = tr("sp_total", {n: fullIndex.length});
  document.getElementById("spCount").textContent = (!fullIndex && !spImgMode ? spCatalogCopy()[3]+" · " : "") + (countOverride || tr("sp_count", {n: hits.length}));
  spCatalogStatusSync();
  spModeSync(hits.length);
  spRelStatusSync();
  spPriceLabel();
  spFilterBtnLabel();
  spSortSync();
  document.getElementById("spClear").hidden = !q;
  document.getElementById("spQ").parentElement.classList.toggle("has-query", !!q);
  document.getElementById("spEmpty").style.display = (spRelId && (spRelLoadState!=="ready" || !fullIndex)) || hits.length ? "none" : "block";
  spTotal = hits.length;
  // Append-only: rebuilding the whole grid per batch repainted every card
  // and restarted every entrance animation, which is what turned fast
  // scrolling dark and stalled paging. A changed query/filter/data
  // generation still rebuilds from scratch.
  const key = (spRelId || "") + "|" + (spCatMode || "") + "|" + q + "|" + spFilter + "|" + (fullIndex ? "F" : "-") + "|" + (FULL_LISTS ? "L" : "-") + "|" + (spMaxPrice == null ? "A" : spMaxPrice) + "|" + spSort;
  const grid = document.getElementById("spGrid");
  const cardOf = (x, i) => {
    if (!x.image && verifiedThumbnail(x.id)) x = {...x, image: verifiedThumbnail(x.id)};
    let html=x.plain?plainCard(x,i):saleCard({...x,pct:x.pct},i);
    if(fullIndex&&!spImgMode&&spCatalogImages&&spCatalogReader.isCore()&&!x.image){
      html=html.replace('data-fill=', 'data-core-image=');
      if(x.plain)html=html.replace('class="noimg"','class="noimg" data-core-image="'+x.id+'"');
    }
    return html;
  };
  let fillFrom = -1;
  if (reset || key !== spKey || spRendered > spShown || spRendered > hits.length) {
    grid.innerHTML = hits.slice(0, spShown).map(cardOf).join("");
    spRendered = Math.min(spShown, hits.length);
    fillFrom = 0;
  } else if (spShown > spRendered) {
    fillFrom = spRendered;
    grid.insertAdjacentHTML("beforeend", hits.slice(fillFrom, spShown).map((x, j) => cardOf(x, fillFrom + j)).join(""));
    spRendered = Math.min(spShown, hits.length);
  }
  spKey = key;
  if (fillFrom >= 0) hits.slice(fillFrom, spRendered).forEach(x => { if (x.plain) fillPriceLazy(x.id); });
  if(spCatalogImages)spCatalogImages.hydrate();
}
let spRelId = null, spRelIds = null, spRelName = "";
let spRelEpoch = 0, spRelLoadState = "idle", spRelTotal = 0;
const completeRelationSearch = typeof BoopaRelationshipSearch !== "undefined" ? BoopaRelationshipSearch.create() : null;
function spRelCopy(){ return ({
  ja:["子作品データを読み込み中","子作品データを取得できませんでした。全件検索には切り替えていません。","再試行","子作品","商品データあり","未収録","商品データを読み込み中"],
  en:["Loading derivative works","Could not load derivative works. Search has not switched to the full catalog.","Retry","Derivative works","In catalog","Unavailable","Loading catalog"],
  ko:["파생 작품 불러오는 중","파생 작품을 불러오지 못했습니다. 전체 검색으로 전환하지 않았습니다.","다시 시도","파생 작품","상품 데이터 있음","미수록","상품 데이터 불러오는 중"],
  "zh-Hans":["正在加载子作品","无法加载子作品，未切换为全部商品搜索。","重试","子作品","有商品数据","未收录","正在加载商品数据"],
  "zh-Hant":["正在載入子作品","無法載入子作品，未切換為全部商品搜尋。","重試","子作品","有商品資料","未收錄","正在載入商品資料"]
})[LANG] || ["Loading derivative works","Could not load derivative works. Search remains scoped.","Retry","Derivative works","In catalog","Unavailable","Loading catalog"]; }
function spRelHits(q){
  const allowed=new Set(spRelIds),category=spCatMode?spCatMode.toLowerCase().normalize("NFKC"):null;
  const matching=q?new Set(fullIndex.filter(e=>e[2].includes(q)||(e[8]&&e[8].includes(q))).map(e=>e[0])):null;
  let hits=spCatalogHits().filter(x=>allowed.has(String(x.id))&&(!category||spCatMap.get(String(x.id))===category)&&(typeof spShopMode==="undefined"||!spShopMode||x.shop===spShopMode)&&(!matching||matching.has(String(x.id))));
  if(spFilter==="free")hits=hits.filter(x=>x.cur===0);
  if(spFilter==="sale")hits=hits.filter(x=>!!x.sale);
  if(spFilter==="lowest")hits=hits.filter(x=>!!x.at_lowest);
  if(["drop","new","rising"].includes(spFilter)){const chipIds=new Set((chipSet(spFilter)||[]).map(x=>String(x.id)));hits=hits.filter(x=>chipIds.has(String(x.id)));}
  if(spSort==="rel"){const order=new Map(spRelIds.map((id,i)=>[id,i]));hits.sort((a,b)=>order.get(String(a.id))-order.get(String(b.id)));}
  return hits;
}
function spRelStatusSync(){
  let el=document.getElementById("spRelStatus");
  if(!el){el=document.createElement("div");el.id="spRelStatus";el.setAttribute("role","status");el.style.cssText="margin:10px 0;overflow-wrap:anywhere;min-width:0";document.getElementById("spGrid").before(el);}
  el.hidden=!spRelId;if(!spRelId){el.textContent="";return;}
  const c=spRelCopy();el.textContent="";
  if(spRelLoadState==="error"){
    const msg=document.createElement("span");msg.textContent=c[1];el.appendChild(msg);
    const retry=document.createElement("button");retry.type="button";retry.textContent=c[2];retry.style.marginInlineStart="10px";retry.onclick=()=>spRelLoad(spRelId);el.appendChild(retry);
  }else if(spRelLoadState!=="ready")el.textContent=c[0];
  else if(!fullIndex)el.textContent=c[6]+" · "+c[3]+": "+spRelTotal.toLocaleString(LOCALE);
  else {
    const catalogIds=new Set(fullIndex.map(e=>String(e[0]))),available=spRelIds.filter(id=>catalogIds.has(id)).length;
    el.textContent=c[3]+": "+spRelTotal.toLocaleString(LOCALE)+" / "+c[4]+": "+available.toLocaleString(LOCALE)+(available<spRelTotal?" / "+c[5]+": "+(spRelTotal-available).toLocaleString(LOCALE):"");
  }
}
function spRelClear(updateURL=true){
  spRelEpoch++;spRelId=null;spRelIds=null;spRelName="";spRelLoadState="idle";spRelTotal=0;
  if(updateURL){try{const u=new URL(location.href);u.searchParams.delete("children");history.replaceState(null,"",u.pathname+u.search+u.hash);}catch{}}
}
async function spRelLoad(id){
  if(!/^[1-9]\d{0,15}$/.test(id || ""))return;
  if(hiddenItem(id)){showHiddenProduct();return;}
  const epoch=++spRelEpoch;spRelId=id;spRelIds=[];spRelName="#"+id;spRelTotal=0;spRelLoadState="loading";
  openSearch();
  const result=completeRelationSearch?await completeRelationSearch.get(id):{status:"error"};
  if(epoch!==spRelEpoch || spRelId!==id || !spage.classList.contains("open"))return;
  if(result.status!=="ready"){spRelLoadState="error";spRender();return;}
  spRelIds=result.ids.filter(id=>!hiddenItem(id));spRelTotal=spRelIds.length;spRelLoadState="ready";spRender();
  const m=await fetchMeta(id);
  if(epoch!==spRelEpoch || spRelId!==id || !spage.classList.contains("open"))return;
  if(m&&m.name)spRelName=m.name;spModeSync(spTotal);
}

let spCatMode = null, spCatNames = new Map(); let spShopMode = null; let spImgMode = false, spImgHits = [], spImgState = null, spImgThumb = null, spImgLabel = "";
function spModeSync(n){
  if (!fullIndex && !spImgMode) n = null;
  const bar = document.getElementById("spMode");
  if (!bar) return;
  let label = "";
  if (spRelIds) label = (spRelName ? spRelName + " \u2014 " : "") + tr("pp_children");
  else if (spCatMode) label = catLabelL(spCatMode);
  else if (spShopMode) label = spShopMode;
  else if (spImgMode) label = spImgLabel || tr("img_search");
  if (label && n != null) label += "\uFF08" + n + "\uFF09";
  const mi = document.getElementById("spModeImg");
  if (mi) { if (spImgMode && spImgThumb) { if (mi.getAttribute("src") !== spImgThumb) mi.src = spImgThumb; mi.hidden = false; } else { mi.hidden = true; mi.removeAttribute("src"); } }
  bar.hidden = !label;
  const cnt = document.getElementById("spCount");
  if (cnt) cnt.style.visibility = label ? "hidden" : "";
  if (label) document.getElementById("spModeT").textContent = label;
}
document.getElementById("spModeX").addEventListener("click", () => {
  spRelClear();
  spRelId = null; spRelIds = null; spRelName = ""; spCatMode = null; spShopMode = null; imgClearMode(); spCatSync();
  try { history.replaceState(null, "", location.pathname); } catch {}
  spRender();
});
async function spRelBoot(){
  const params=new URLSearchParams(location.search),cid=params.get("children"),shp=params.get("shop");
  if(cid && /^[1-9]\d{0,15}$/.test(cid)){if(shp && typeof spShopMode!=="undefined")spShopMode=shp;return spRelLoad(cid);}
  if(shp && typeof spShopMode!=="undefined"){spShopMode=shp;openSearch();}
}
window.addEventListener("popstate",()=>{
  const cid=new URLSearchParams(location.search).get("children");
  if(cid && /^[1-9]\d{0,15}$/.test(cid))spRelLoad(cid);
  else {spRelClear(false);if(spage.classList.contains("open"))spRender();}
});
document.getElementById("spQ").addEventListener("input",()=>{if(typeof spImgMode!=="undefined" && spImgMode){imgClearMode();spCatSync();spRender();}});
setTimeout(spRelBoot, 0);
const spSide = document.querySelector(".sp-side");
function spSideSet(open){ spSide.classList.toggle("open", open); document.body.classList.toggle("spfilter-open", open); }
function spFilterBtnLabel(){ const n = (spFilter !== "all" ? 1 : 0) + (spMaxPrice != null ? 1 : 0) + (spCatMode ? 1 : 0) + (spShopMode ? 1 : 0); document.getElementById("spFilterBtn").textContent = tr("sp_filter") + (n ? " (" + n + ")" : ""); }
document.getElementById("spFilterBtn").addEventListener("click", () => spSideSet(true));
document.getElementById("spSideX").addEventListener("click", () => spSideSet(false));
document.getElementById("spFilterShow").addEventListener("click", () => spSideSet(false));
document.getElementById("spFilterReset").addEventListener("click", () => {
  spCatMode=null;spShopMode=null;imgClearMode();spCatSync();
  spFilter = "all";
  document.querySelectorAll("#spChips .chip").forEach(y => y.classList.toggle("on", y.dataset.f === "all"));
  spMaxPrice = null;
  document.getElementById("spPrice").value = "12";
  spPriceLabel();
  spRender();
});
const SP_SORTS = [["rel", "sp_sort_rel"], ["pop", "sp_sort_pop"], ["new", "sp_sort_new"], ["rising", "sp_sort_rising"], ["price_asc", "sp_sort_price_asc"], ["price_desc", "sp_sort_price_desc"], ["pct", "sp_sort_pct"], ["name", "sp_sort_name"]];
let spSort = "rel";
const spSortMenu = document.getElementById("spSortMenu");
function spSortSync(){
  document.getElementById("spSortBtn").innerHTML = esc(tr("sp_sort_" + spSort)) + '<span class="spcaret"></span>';
  spSortMenu.querySelectorAll(".spsortmi").forEach(b => b.classList.toggle("on", b.dataset.sort === spSort));
}
spSortMenu.innerHTML = SP_SORTS.map(([v, k]) => `<button type="button" class="spsortmi" data-sort="${v}" data-i="${k}">${tr(k)}</button>`).join("");
spSortSync();
document.getElementById("spSortBtn").addEventListener("click", e => { e.stopPropagation(); spSortMenu.hidden = !spSortMenu.hidden; });
spSortMenu.addEventListener("click", e => {
  e.stopPropagation();
  const b = e.target.closest(".spsortmi");
  if (!b) return;
  spSort = b.dataset.sort;
  spSortMenu.hidden = true;
  spSortSync();
  spRender();
});
document.addEventListener("click", () => { spSortMenu.hidden = true; });
document.addEventListener("keydown", e => { if (e.key === "Escape") spSortMenu.hidden = true; });
document.getElementById("spClear").addEventListener("click", () => { const el = document.getElementById("spQ"); el.value = ""; spRender(); el.focus(); });
const spPriceEl = document.getElementById("spPrice");
spPriceEl.addEventListener("input", () => { const v = +spPriceEl.value; spMaxPrice = v >= SP_CAPS.length ? null : SP_CAPS[v]; spPriceLabel(); clearTimeout(spPriceT); spPriceT = setTimeout(() => spRender(), 180); });
spPriceLabel();
// Auto-load the next batch as the list end approaches, so paging never
// depends on the button alone (mobile taps on it proved unreliable).
let spTick = 0, spRetryT = null, spScrollT = null;
function spMaybeLoad(){
  if (spTotal <= spShown) return;
  const now = Date.now();
  if (now - spTick < 350) {
    // Never drop a load: a guarded call used to vanish, and at the bottom
    // of a fast scroll no further events arrive to retry it.
    if (!spRetryT) spRetryT = setTimeout(() => { spRetryT = null; spMaybeLoad(); }, 360);
    return;
  }
  spTick = now;
  spShown += 30; spRender(false);
  requestAnimationFrame(spChainCheck);
}
function spChainCheck(){
  const sp = document.getElementById("searchPage");
  if (!sp.classList.contains("open") || spTotal <= spShown) return;
  const r = document.querySelector("#searchPage .smore").getBoundingClientRect();
  if (r.top < window.innerHeight + 700 && r.bottom > -700) spMaybeLoad();
}
const spIO = new IntersectionObserver(es => {
  if (es.some(e => e.isIntersecting)) spMaybeLoad();
}, { root: document.getElementById("searchPage"), rootMargin: "700px 0px" });
spIO.observe(document.querySelector("#searchPage .smore"));
// Fallbacks if intersection observation does not fire on the user's
// browser: the overlay's own scroll position, and a geometry check on
// any scroll event (the home page under the overlay must not be able
// to take the detection away).
document.getElementById("searchPage").addEventListener("scroll", () => {
  const sp = document.getElementById("searchPage");
  if (spTotal > spShown && sp.scrollHeight - sp.scrollTop - sp.clientHeight < 900) spMaybeLoad();
  clearTimeout(spScrollT);
  spScrollT = setTimeout(spChainCheck, 180);
}, { passive: true });
document.addEventListener("scroll", () => {
  const sp = document.getElementById("searchPage");
  if (!sp.classList.contains("open") || spTotal <= spShown) return;
  const r = document.querySelector("#searchPage .smore").getBoundingClientRect();
  if (r.top < window.innerHeight + 700 && r.bottom > -700) spMaybeLoad();
}, { capture: true, passive: true });
function openSearchPreset(f){
  spFilter = f;
  document.getElementById("spChips").querySelectorAll(".chip").forEach(y => y.classList.toggle("on", y.dataset.f === f));
  document.getElementById("spQ").value = "";
  spRender();
  openSearch();
}
function openSearchShop(name){
  if (!fullIndex) loadFullIndex();
  spFilter = "all";
  document.getElementById("spChips").querySelectorAll(".chip").forEach(y => y.classList.toggle("on", y.dataset.f === "all"));
  spCatMode = null; spRelClear();
  spCatSync();
  document.getElementById("spQ").value = "";
  spShopMode = name;
  spRender();
  openSearch();
}
function openSearchTag(t){
  if (!fullIndex) loadFullIndex();
  spFilter = "all";
  document.getElementById("spChips").querySelectorAll(".chip").forEach(y => y.classList.toggle("on", y.dataset.f === "all"));
  spCatMode = null; spRelClear(); spShopMode = null; imgClearMode();
  spCatSync();
  document.getElementById("spQ").value = t;
  spRender();
  openSearch();
}
function openSearchCat(raw){
  if (!fullIndex) loadFullIndex();
  spFilter = "all";
  document.getElementById("spChips").querySelectorAll(".chip").forEach(y => y.classList.toggle("on", y.dataset.f === "all"));
  document.getElementById("spQ").value = "";
  spCatMode = raw; spRelClear(); spShopMode = null;
  spCatSync();
  spRender();
  openSearch();
}
let catCardsDone = false;
function loadCatCards(){
  if (catCardsDone) return;
  catCardsDone = true;
  fetch("cat_cards.json?v=20251026-1").then(r => { if (!r.ok) throw new Error("cat"); return r.json(); }).then(data => {
    const host = document.getElementById("catRail");
    if (!host) return;
    for (const raw of Object.keys(data)) data[raw] = visibleItems(data[raw]);
    const HUES = [210, 350, 28, 150, 265, 190, 320, 95, 0, 230, 45, 175, 285, 120, 15, 200, 255];
    host.innerHTML = Object.keys(data).filter(raw => (data[raw] || []).length).map((raw, ci) => {
      const items = data[raw].slice(0, 9);
      const filled = [];
      for (let k = 0; k < 9; k++) filled.push(items[k % items.length]);
      const imgs = filled.map(x => `<img data-pid="${x.id || ""}" loading="lazy" src="${esc(pxImg(x.i))}" alt="" onerror="imgPh(this)">`).join("");
      return `<button class="catcard" data-cat="${esc(raw)}" style="--h:${HUES[ci % HUES.length]}"><span class="ccflat n${items.length}">${imgs}</span><span class="cctint"></span><span class="cclabel">${esc(catLabelL(raw))}</span></button>`;
    }).join("");
    host.querySelectorAll(".catcard").forEach(c => { c.onclick = () => openSearchCat(c.dataset.cat); });
    requestAnimationFrame(catNavUpdate);
  }).catch(() => {});
}
function catNavUpdate(){
  const rail = document.getElementById("catRail");
  const pv = document.getElementById("catPrev"), nx = document.getElementById("catNext");
  if (!rail) return;
  const max = rail.scrollWidth - rail.clientWidth;
  if (pv) pv.classList.toggle("off", max <= 0);
  if (nx) nx.classList.toggle("off", max <= 0);
  catDotsSync();
}
function catDotsSync(){
  const rail = document.getElementById("catRail"), dots = document.getElementById("catDots");
  if (!rail || !dots) return;
  const step = Math.max(220, rail.clientWidth * 0.85);
  const max = rail.scrollWidth - rail.clientWidth;
  const pages = max > 0 ? Math.round(max / step) + 1 : 1;
  if (pages <= 1) { dots.innerHTML = ""; dots.style.display = "none"; return; }
  dots.style.display = "";
  const cur = Math.min(pages - 1, Math.round(rail.scrollLeft / step));
  if (dots.childElementCount !== pages) {
    dots.innerHTML = Array.from({ length: pages }, (_, i) => `<button type="button" data-p="${i}" aria-label="${i + 1}"></button>`).join("");
    dots.querySelectorAll("button").forEach(b => { b.onclick = () => rail.scrollTo({ left: Number(b.dataset.p) * step, behavior: "smooth" }); });
  }
  dots.querySelectorAll("button").forEach((b, i) => b.classList.toggle("on", i === cur));
}
(function(){
  const rail = document.getElementById("catRail");
  if (!rail) return;
  const step = () => Math.max(220, rail.clientWidth * 0.85);
  document.getElementById("catPrev").onclick = () => {
    const max = rail.scrollWidth - rail.clientWidth;
    if (rail.scrollLeft <= 2 && max > 0) rail.scrollTo({ left: max, behavior: "instant" });
    else rail.scrollBy({ left: -step(), behavior: "smooth" });
  };
  document.getElementById("catNext").onclick = () => {
    const max = rail.scrollWidth - rail.clientWidth;
    if (rail.scrollLeft >= max - 2 && max > 0) rail.scrollTo({ left: 0, behavior: "instant" });
    else rail.scrollBy({ left: step(), behavior: "smooth" });
  };
  rail.addEventListener("scroll", () => requestAnimationFrame(catNavUpdate), { passive: true });
  addEventListener("resize", catNavUpdate);
})();
(function(){
  const host = document.getElementById("catRail");
  if (!host) return;
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { loadCatCards(); io.disconnect(); } }, { rootMargin: "700px" });
    io.observe(host);
  } else loadCatCards();
})();
function updCard(s){
  if (hiddenItem(s.id)) return "";
  const pct = s.base > s.cur ? Math.round((1 - s.cur / s.base) * 100) : 0;
  let price;
  if (s.on_sale && pct > 0) price = `${discountBadge(s.base, s.cur, "udisc")}<span class="uwas"><span class="was">${yen(s.base)}</span></span><span class="upr">${yen(s.cur)}</span>`;
  else if (s.cur === 0) price = `<span class="upr solo free">${tr("free")}</span>`;
  else price = `<span class="upr solo">${yen(s.cur)}</span>`;
  const a0 = (s.added || [])[0] || {};
  const more = s.added_n > 1 ? `<span class="umore">+${s.added_n - 1}</span>` : "";
  return `<a class="ucard" href="${itemUrl(s.id)}" target="_blank" rel="noopener"><span class="uimg">${s.image ? `<img class="ubg" loading="lazy" src="${s.image}" alt="" aria-hidden="true" referrerpolicy="no-referrer" onerror="this.remove()"><img class="ufg" loading="lazy" src="${s.image}" alt="" referrerpolicy="no-referrer" onerror="imgPh(this,'phcard')">` : `<span class="phcard" data-fill="${s.id}">${PH_ICON}</span>`}${bmFlag(s.id)}</span><span class="ubody"><span class="uname">${esc(s.name)}</span><span class="ushop">${esc(s.shop || "")}</span><span class="uupd"><span class="uchip">${tr("upd_newvar")}</span><span class="uvar">${esc(a0.name || "")}</span>${more}</span><span class="udate">${tr("added_on", {d: s.date})}</span><span class="uprice">${price}</span></span></a>`;
}
const UPD_PAGE = 12;
let updShown = 0;
function renderUpdates(){
  const sec = document.getElementById("updSec"), rail = document.getElementById("updRail");
  if (!sec || !rail) return;
  const list = visibleItems(LISTS.updates);
  if (!list.length) { sec.hidden = true; return; }
  sec.hidden = false;
  updShown = Math.min(UPD_PAGE, list.length);
  rail.innerHTML = list.slice(0, updShown).map(updCard).join("");
  updMoreSync();
  requestAnimationFrame(updNavUpdate);
}
function updMoreSync(){
  const wrap = document.getElementById("updMoreWrap");
  if (wrap) wrap.hidden = (LISTS.updates || []).length <= updShown;
}
function updMore(){
  location.href = "updates.html";
}
function updNavUpdate(){
  const rail = document.getElementById("updRail");
  const pv = document.getElementById("updPrev"), nx = document.getElementById("updNext");
  if (!rail || !pv || !nx) return;
  const max = rail.scrollWidth - rail.clientWidth;
  pv.classList.toggle("off", max <= 0);
  nx.classList.toggle("off", max <= 0);
  updDotsSync();
}
function updDotsSync(){
  const rail = document.getElementById("updRail"), dots = document.getElementById("updDots");
  if (!rail || !dots) return;
  const step = Math.max(220, rail.clientWidth * 0.85);
  const max = rail.scrollWidth - rail.clientWidth;
  const pages = max > 0 ? Math.round(max / step) + 1 : 1;
  if (pages <= 1) { dots.innerHTML = ""; dots.style.display = "none"; return; }
  dots.style.display = "";
  const cur = Math.min(pages - 1, Math.round(rail.scrollLeft / step));
  if (dots.childElementCount !== pages) {
    dots.innerHTML = Array.from({ length: pages }, (_, i) => `<button type="button" data-p="${i}" aria-label="${i + 1}"></button>`).join("");
    dots.querySelectorAll("button").forEach(b => { b.onclick = () => rail.scrollTo({ left: Number(b.dataset.p) * step, behavior: "smooth" }); });
  }
  dots.querySelectorAll("button").forEach((b, i) => b.classList.toggle("on", i === cur));
}
(function(){
  const rail = document.getElementById("updRail");
  if (!rail) return;
  const step = () => Math.max(220, rail.clientWidth * 0.85);
  document.getElementById("updPrev").onclick = () => {
    const max = rail.scrollWidth - rail.clientWidth;
    if (rail.scrollLeft <= 2 && max > 0) rail.scrollTo({ left: max, behavior: "instant" });
    else rail.scrollBy({ left: -step(), behavior: "smooth" });
  };
  document.getElementById("updNext").onclick = () => {
    const max = rail.scrollWidth - rail.clientWidth;
    if (rail.scrollLeft >= max - 2 && max > 0) rail.scrollTo({ left: 0, behavior: "instant" });
    else rail.scrollBy({ left: step(), behavior: "smooth" });
  };
  const um = document.getElementById("updMore");
  if (um) um.onclick = updMore;
  rail.addEventListener("scroll", () => requestAnimationFrame(updNavUpdate), { passive: true });
  addEventListener("resize", updNavUpdate);
})();

/* ---------- Shops you know (from bookmarks + recommends) ---------- */
let SHOP_DIGEST = null, shopLoadP = null;
function shopHue(s){ let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360; return h; }
function shopPriceHTML(t){
  if (t.cur == null) return "";
  if (t.on_sale && t.cur === 0) return `<div class="spr"><span class="sgt">${tr("free")}</span><span class="scur">¥0</span></div>`;
  if (t.on_sale && t.base && t.base > t.cur){
    const pct = Math.round((1 - t.cur / t.base) * 100);
    if (pct > 0) return `<div class="spr">${discountBadge(t.base, t.cur, "sg", "−")}<span class="swas"><span class="ww">${yen(t.base)}</span></span><span class="scur">${yen(t.cur)}</span></div>`;
    return `<div class="spr"><span class="sg">${tr("rib_sale")}</span><span class="scur">${yen(t.cur)}</span></div>`;
  }
  if (t.on_sale) return `<div class="spr"><span class="sg">${tr("rib_sale")}</span><span class="scur">${yen(t.cur)}</span></div>`;
  if (t.cur === 0) return `<div class="spr solo"><span class="scur">${tr("free")}</span></div>`;
  return `<div class="spr solo"><span class="scur">${yen(t.cur)}</span></div>`;
}
function shopCardHTML(c){
  if (!c.top || hiddenItem(c.top.id)) return "";
  if (c.new && hiddenItem(c.new.id)) c = {...c,new:null};
  const t = c.top, img = t.image || "";
  const cover = img ? `<img class="sbg" src="${img}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this)"><img src="${img}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this)">` : `<span class="phcard" data-fill="${t.id}">${PH_ICON}</span>`;
  const cnt = c.n ? `<div class="scnt">${tr("shops_n", { n: c.n })}</div>` : "";
  const newl = c.new ? `<div class="snew" data-pid="${c.new.id}"><span class="stag">${tr("bt_new")}</span>${esc(c.new.name)}</div>` : "";
  return `<div class="shcard"><a class="simg" href="${esc(c.url)}" target="_blank" rel="noopener">${cover}</a><div class="sbody"><button type="button" class="srow" data-shop="${esc(c.name)}"><span class="sava" style="background:hsl(${shopHue(c.key)} 45% 42%)">${esc((c.name || "?").slice(0, 1))}</span><span style="min-width:0"><span class="snm">${esc(c.name)}</span>${cnt}</span></button>${newl}<a class="stop" href="${itemUrl(t.id)}" target="_blank" rel="noopener"><div class="tnm">${esc(t.name)}</div>${shopPriceHTML(t)}</a></div></div>`;
}
function shopStep(){ const rail = document.getElementById("shopRail"); return Math.max(220, rail.clientWidth * 0.85); }
function shopDotsSync(){
  const rail = document.getElementById("shopRail"), dots = document.getElementById("shopDots");
  if (!rail || !dots) return;
  const max = rail.scrollWidth - rail.clientWidth, st = shopStep();
  const pages = max > 4 ? Math.round(max / st) + 1 : 1, cur = Math.min(pages - 1, Math.round(rail.scrollLeft / st));
  if (dots.children.length !== pages) dots.innerHTML = Array.from({ length: pages }, () => "<button type=\"button\" tabindex=\"-1\"></button>").join("");
  [...dots.children].forEach((b, i) => { b.classList.toggle("on", i === cur); b.onclick = () => rail.scrollTo({ left: i * st, behavior: "smooth" }); });
}
function shopNavUpdate(){
  const rail = document.getElementById("shopRail"); if (!rail) return;
  const over = rail.scrollWidth - rail.clientWidth > 4;
  document.getElementById("shopPrev").classList.toggle("off", !over);
  document.getElementById("shopNext").classList.toggle("off", !over);
  shopDotsSync();
}
function renderShopSec(cards){
  cards = cards.filter(c => c.top && !hiddenItem(c.top.id));
  const sec = document.getElementById("shopSec"), rail = document.getElementById("shopRail");
  if (!cards.length) { sec.hidden = true; return; }
  rail.innerHTML = cards.map(shopCardHTML).join("");
  sec.hidden = false;
  fillImgs();
  requestAnimationFrame(shopNavUpdate);
}
async function ensureShopDigest(){
  if (!SHOP_DIGEST) { try { SHOP_DIGEST = await fetch("shop_digest.json?v=20251025-6").then(r => r.ok ? r.json() : {}); } catch { SHOP_DIGEST = {}; } }
  return SHOP_DIGEST;
}
function loadShopSec(){
  if (shopLoadP) return shopLoadP;
  shopLoadP = (async () => {
    const srcIds = [], seenId = new Set();
    const push = id => { id = String(id); if (id && !hiddenItem(id) && !seenId.has(id)) { seenId.add(id); srcIds.push(id); } };
    (BMS || []).forEach(b => push(b.id));
    try {
      const v = recVid();
      if (v) { const r = await fetch(REC_API + "/rec?v=" + encodeURIComponent(v)).then(x => x.json()); (r.items || []).forEach(push); }
    } catch {}
    if (!srcIds.length) return;
    const bmById = {}; (BMS || []).forEach(b => { bmById[String(b.id)] = b; });
    const scan = srcIds.slice(0, 160);
    const metasP = Promise.all(scan.map(id => fetchMeta(id).then(m => [id, m]).catch(() => [id, null])));
    await ensureShopDigest();
    const metas = await metasP;
    const cards = [], seenShop = new Set();
    for (const [id, m] of metas) {
      if (hiddenItem(id)) continue;
      if (cards.length >= 24) break;
      const sh = (m && m.shop) || {};
      const sub = sh.subdomain || "";
      const name = sh.name || (bmById[id] && bmById[id].shop) || "";
      if (!name && !sub) continue;
      const key = sub || ("n:" + name);
      if (seenShop.has(key)) continue;
      seenShop.add(key);
      const d = sub ? SHOP_DIGEST[sub] : null;
      if (d) {
        cards.push({ key, name: d[0] || name, n: d[1], url: "https://" + sub + ".booth.pm/",
          top: { id: d[2][0], name: d[2][1], image: pxImg(d[2][2]), cur: d[2][3], base: d[2][4], on_sale: !!d[2][5] },
          new: d[3] ? { id: d[3][0], name: d[3][1] } : null });
      } else {
        const bm = bmById[id];
        cards.push({ key, name, n: 0, url: sub ? "https://" + sub + ".booth.pm/" : itemUrl(id),
          top: { id: isNaN(+id) ? id : +id, name: (m && m.name) || (bm && bm.name) || "", image: (bm && bm.image) || (m && m.image) || "", cur: bm ? bm.cur : null, base: null, on_sale: false }, new: null });
      }
    }
    renderShopSec(cards);
  })();
  return shopLoadP;
}
(function(){
  const rail = document.getElementById("shopRail");
  document.getElementById("shopPrev").onclick = () => {
    const max = rail.scrollWidth - rail.clientWidth;
    if (rail.scrollLeft <= 2 && max > 0) rail.scrollTo({ left: max, behavior: "instant" });
    else rail.scrollBy({ left: -shopStep(), behavior: "smooth" });
  };
  document.getElementById("shopNext").onclick = () => {
    const max = rail.scrollWidth - rail.clientWidth;
    if (rail.scrollLeft >= max - 2 && max > 0) rail.scrollTo({ left: 0, behavior: "instant" });
    else rail.scrollBy({ left: shopStep(), behavior: "smooth" });
  };
  rail.addEventListener("scroll", () => requestAnimationFrame(shopNavUpdate), { passive: true });
  addEventListener("resize", shopNavUpdate);
})();
document.getElementById("spQ").addEventListener("input", spRender);
document.getElementById("spChips").querySelectorAll(".chip").forEach(ch => {
  ch.onclick = () => {
    document.getElementById("spChips").querySelectorAll(".chip").forEach(y => y.classList.toggle("on", y === ch));
    spFilter = ch.dataset.f; spCatSync(); spRender();
  };
});
function catLabel(raw){ const i = String(raw).lastIndexOf(" "); return i > 0 ? String(raw).slice(0, i) : String(raw); }
function spCatSync(){
  document.querySelectorAll("#spKw .kw").forEach(k => k.classList.toggle("on", !!spCatMode && k.dataset.cat === spCatMode));
}
function spCatRender(){
  const host = document.getElementById("spKw");
  if (!host) return;
  let raws;
  if (fullIndex) {
    const counts = new Map();
    for (const e of fullIndex) { if (e[8]) counts.set(e[8], (counts.get(e[8]) || 0) + 1); }
    raws = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([lower]) => spCatNames.get(lower) || lower);
  } else {
    // The index (tens of MB) can take a while on slow connections; the
    // category list itself is static taxonomy, so paint it immediately
    // and let the live render refine the order once the index arrives.
    raws = SP_CATS;
    for (const raw of raws) { const k = raw.normalize("NFKC").toLowerCase(); if (!spCatNames.has(k)) spCatNames.set(k, raw); }
  }
  host.innerHTML = raws.map(raw => `<button class="kw" data-cat="${esc(raw)}">${esc(catLabelL(raw))}</button>`).join("");
  host.querySelectorAll(".kw").forEach(k => {
    k.onclick = () => {
      if (!fullIndex) loadFullIndex();
      spCatMode = spCatMode === k.dataset.cat ? null : k.dataset.cat;
      spCatSync();
      spRender();
      spSideSet(false);
    };
  });
  spCatSync();
}
spCatRender();
spRender();
function repaintCharts(){
  const pp = document.getElementById("prodPage");
  if (ppX && pp && (pp.classList.contains("open") || location.pathname.endsWith("item.html"))) renderProdPage(ppX);
  document.querySelectorAll("#featTrack [data-fid]").forEach(ph => {
    const pr = bpChartCache.get(ph.dataset.fid);
    if (pr) pr.then(rec => { const ser = rec ? repSeriesOf(rec) : null; if (ser && ph.isConnected) ph.innerHTML = bpChartSVG(ser, 200, 64); });
  });
  const bp = document.querySelector("#bPrev [data-fid]");
  if (bp) { const pr = bpChartCache.get(bp.dataset.fid); if (pr) pr.then(rec => { const ser = rec ? repSeriesOf(rec) : null; if (ser && bp.isConnected) bp.innerHTML = `<div class="cap">${tr("pp_chart")}</div>${bpChartSVG(ser, 340, 118)}`; }); }
}
function applyTheme(next){
  THEME = next;
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("boopadb_theme", next); } catch {}
  if (csMeta) csMeta.content = next;
  setThemeColors();
  repaintCharts();
}
document.getElementById("themeBtn").addEventListener("click", () => applyTheme(THEME === "light" ? "dark" : "light"));
const tabbarEl = document.getElementById("tabbar");
let lastY = 0, scrollIdle = null;
// A late momentum-scroll event must not move the navigation out from under
// a finger. Keep the native click path; do not synthesize clicks on touchend.
const navPointers = new Set();
let navTapUntil = 0;
function navTapPending(){ return navPointers.size > 0 || Date.now() < navTapUntil; }
tabbarEl.addEventListener("pointerdown", e => {
  navPointers.add(e.pointerId);
  navTapUntil = 0;
  clearTimeout(scrollIdle);
  tabbarEl.classList.remove("hide");
}, {passive: true});
window.addEventListener("pointerup", e => {
  if (!navPointers.delete(e.pointerId)) return;
  if (!navPointers.size) navTapUntil = Date.now() + 400;
}, {passive: true});
window.addEventListener("pointercancel", e => {
  if (navPointers.delete(e.pointerId) && !navPointers.size) navTapUntil = 0;
}, {passive: true});
window.addEventListener("blur", () => { navPointers.clear(); navTapUntil = 0; });
function onAnyScroll(y, src){
  if (navTapPending()) { lastY = y; return; }
  if (spyLock) {
    clearTimeout(spyLockTimer);
    spyLockTimer = setTimeout(() => { spyLock = false; }, 300);
    tabbarEl.classList.remove("hide");
    lastY = y;
    return;
  }
  if (src === spage) return;
  if (y > lastY + 4 && y > 140 && !spage.classList.contains("open")) tabbarEl.classList.add("hide");
  else if (y < lastY - 4) tabbarEl.classList.remove("hide");
  lastY = y;
  clearTimeout(scrollIdle);
  scrollIdle = setTimeout(() => tabbarEl.classList.remove("hide"), 1100);
}
window.addEventListener("scroll", () => onAnyScroll(window.scrollY, null), {passive: true});
document.addEventListener("scroll", e => {
  const t = e.target;
  if (t === document || t === document.documentElement || t === document.body) onAnyScroll(window.scrollY, null);
  else onAnyScroll(t.scrollTop || 0, t);
}, {capture: true, passive: true});
let touchY = null;
document.addEventListener("touchstart", e => { touchY = e.touches[0].clientY; }, {passive: true});
document.addEventListener("touchmove", e => {
  if (touchY === null || navTapPending() || spage.classList.contains("open")) return;
  const dy = touchY - e.touches[0].clientY;
  if (dy > 26) { tabbarEl.classList.add("hide"); touchY = e.touches[0].clientY; clearTimeout(scrollIdle); scrollIdle = setTimeout(() => tabbarEl.classList.remove("hide"), 1100); }
  else if (dy < -14) { tabbarEl.classList.remove("hide"); touchY = e.touches[0].clientY; }
}, {passive: true});

const spy = new IntersectionObserver(es => {
  es.forEach(e => {
    if (e.isIntersecting) {
      if (spyLock) return;
      const b = tabBtns.find(x => x.dataset.to === "#" + e.target.id);
      if (b && !b.classList.contains("on")) setTab(b);
    }
  });
}, {rootMargin: "-35% 0px -55% 0px"});
["hero", "feat", "sale", "browse2"].forEach(id => { const el = document.getElementById(id); if (el) spy.observe(el); });

function saleCard(s, i){
  if (hiddenItem(s.id)) return "";
  return `
  <div class="card" style="animation-delay:${((i || 0) % 30) * 45}ms" data-pct="${s.pct}" data-free="${s.cur === 0 ? 1 : 0}" data-lowest="${s.at_lowest ? 1 : 0}" data-text="${esc((s.name + " " + (s.shop || "")).toLowerCase())}">
    <a class="thumbwrap" href="${itemUrl(s.id)}" target="_blank" rel="noopener">
      ${s.image ? `<img decoding="async" src="${s.image}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this,'phcard')">` : `<span class="phcard" data-fill="${s.id}">${PH_ICON}</span>`}
      ${s.at_lowest ? '<span class="mlab">' + tr("chip_lowest") + "</span>" : ""}
      ${bmFlag(s.id, s.at_lowest ? "u2" : "")}
    </a>
    <div class="cbody">
      <div class="cname"><a href="${itemUrl(s.id)}" target="_blank" rel="noopener">${esc(s.name)}</a></div>
      <div class="cshop"${s.shop ? ` data-shop="${esc(s.shop)}"` : ""}>${esc(s.shop || "")}</div>
      <div class="htags">${esc(s.sale === false ? htagsPlain(s) : htags(s))}</div>
      <div class="crow">${s.sale !== false && s.pct > 0 ? `<span class="bprice">${discountBadge(s.base, s.cur, "discst")}<span class="bstack"><span class="was${wCls(s.base)}">${yen(s.base)}</span><span class="price">${s.cur === 0 ? '<span class="free">' + tr("free") + '</span>' : yen(s.cur)}</span></span></span>` : `<span class="price solo">${s.cur === 0 ? '<span class="free">' + tr("free") + '</span>' : yen(s.cur)}</span>`}</div>
    </div>
  </div>`;
}
let sortMode = "new", chipFilter = "all";
function saleHit(s){
  if (chipFilter === "lowest") return !!s.at_lowest;
  if (chipFilter === "free") return s.cur === 0;
  if (chipFilter === "half") return s.pct >= 50;
  return true;
}
function mosaicCell(s, i){
  if (hiddenItem(s.id)) return "";
  return `<a class="card mcell m${i + 1}" href="${itemUrl(s.id)}" target="_blank" rel="noopener">
    ${s.image ? `<img decoding="async" src="${s.image}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this,'phcard')">` : `<span class="phcard" data-fill="${s.id}">${PH_ICON}</span>`}
    ${s.at_lowest ? '<span class="mlab">' + tr("chip_lowest") + '</span>' : (s.cur === 0 ? '<span class="mlab">' + tr("free") + '</span>' : "")}
    ${bmFlag(s.id, (s.at_lowest || s.cur === 0) ? "u2" : "")}
    <span class="scrim">${discountBadge(s.base, s.cur, "discst")}<span class="was${wCls(s.base)}">${yen(s.base)}</span><span class="price">${yen(s.cur)}</span></span>
  </a>`;
}
function steamCap(s){
  if (hiddenItem(s.id)) return "";
  return `<div class="card">
    <a class="capimg" href="${itemUrl(s.id)}" target="_blank" rel="noopener">${s.image ? `<img decoding="async" src="${s.image}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this,'phcard')">` : `<span class="phcard" data-fill="${s.id}">${PH_ICON}</span>`}${bmFlag(s.id)}</a>
    <div class="capbody">
      <div class="capname"><a href="${itemUrl(s.id)}" target="_blank" rel="noopener">${esc(s.name)}</a></div>
      <div class="capshop">${esc(s.shop || "")}</div>
      <div class="capbtm">${s.at_lowest ? '<div class="lowtx">' + tr("chip_lowest") + '</div>' : ""}<div class="caprow">${discountBadge(s.base, s.cur, "discst")}<span class="was${wCls(s.base)}">${yen(s.base)}</span><span class="price${wCls(s.cur)}">${s.cur === 0 ? tr("free") : yen(s.cur)}</span></div></div>
    </div>
  </div>`;
}
let SALE_HOME = P.on_sale || [];
let LISTS = { on_sale: P.on_sale || [], drops: P.drops || [], active: P.active || [], newest: P.newest || [], free: null };
function renderSale(){
  let arr = visibleItems(SALE_HOME);
  if (sortMode === "new") arr.sort((a,b) => (Number(b.id) - Number(a.id)) || ((b.likes ?? -1) - (a.likes ?? -1)));
  else if (sortMode === "pop") arr.sort((a,b) => ((b.likes ?? -1) - (a.likes ?? -1)) || b.pct - a.pct);
  else if (sortMode === "amount") arr.sort((a,b) => (b.base - b.cur) - (a.base - a.cur));
  else arr.sort((a,b) => b.pct - a.pct || (b.base - b.cur) - (a.base - a.cur));
  arr = arr.filter(saleHit);
  // Gag listings (joke base prices like ¥9,999,999) never headline the rail:
  // plausible prices first, both groups keep the chosen sort order.
  const ordered = [...arr.filter(s => s.base <= 100000), ...arr.filter(s => s.base > 100000)];
  const items = ordered.slice(0, 18);
  const PATTERN = [1, 1, 2, 1, 1, 2, 1, 1, 2, 2, 2, 2];
  let html = "", i = 0;
  for (const col of PATTERN) {
    if (i >= items.length) break;
    if (col === 2 && i + 1 < items.length) { html += `<div class="rstack">${railTile(items[i], true)}${railTile(items[i + 1], true)}</div>`; i += 2; }
    else { html += railTile(items[i], false); i++; }
  }
  document.getElementById("saleTrack").innerHTML = html;
  salePager.reset();
  requestAnimationFrame(saleBarUpdate);
  document.getElementById("saleEmpty").style.display = arr.length ? "none" : "block";
  document.getElementById("saleMore").style.display = arr.length ? "" : "none";
}
function makePager(railId, trackId, prevId, nextId, dotsId){
  const st = { page: 0, pages: [0], t: null };
  const el = id => document.getElementById(id);
  function draw(instant){
    const track = el(trackId), dots = el(dotsId);
    if (instant) track.style.transition = "none";
    track.style.transform = `translateX(${-st.pages[st.page]}px)`;
    if (instant) { void track.offsetWidth; requestAnimationFrame(() => { track.style.transition = ""; }); }
    dots.innerHTML = st.pages.map((_, i) => `<span class="${i === st.page ? "on" : ""}"></span>`).join("");
  }
  function layout(){
    const rail = el(railId), track = el(trackId), prev = el(prevId), next = el(nextId), dots = el(dotsId);
    if (!rail || !track) return;
    if (window.innerWidth < 900) { track.style.transform = ""; return; }
    const W = rail.clientWidth, cols = [...track.children];
    if (!cols.length) st.pages = [0];
    else {
      const starts = [0];
      let psi = 0;
      for (let k = 1; k < cols.length; k++) {
        if (cols[k].offsetLeft + cols[k].offsetWidth - cols[psi].offsetLeft > W) { starts.push(cols[k].offsetLeft); psi = k; }
      }
      const maxShift = Math.max(0, track.scrollWidth - W);
      st.pages = [...new Set(starts.map(s => Math.min(s, maxShift)))];
    }
    if (st.page >= st.pages.length) st.page = st.pages.length - 1;
    const multi = st.pages.length > 1;
    prev.style.display = next.style.display = multi ? "" : "none";
    dots.style.display = multi ? "" : "none";
    draw();
  }
  function go(d){
    if (st.pages.length < 2) return;
    const wrap = (d > 0 && st.page === st.pages.length - 1) || (d < 0 && st.page === 0);
    st.page = (st.page + d + st.pages.length) % st.pages.length;
    draw(wrap);
  }
  el(prevId).onclick = () => go(-1);
  el(nextId).onclick = () => go(1);
  window.addEventListener("resize", () => { clearTimeout(st.t); st.t = setTimeout(layout, 150); });
  return { layout, reset(){ st.page = 0; requestAnimationFrame(layout); } };
}
const salePager = makePager("saleRail", "saleTrack", "salePrev", "saleNext", "saleDots");
const featPager = makePager("featGrid", "featTrack", "featPrev", "featNext", "featDots");
function bindRailBar(railId, barId){
  const rail = document.getElementById(railId), bar = document.getElementById(barId);
  if (!rail || !bar) return () => {};
  const thumb = bar.querySelector("span");
  function update(){
    if (window.innerWidth >= 900) return;
    const sw = rail.scrollWidth, cw = rail.clientWidth;
    if (sw <= cw + 1) { bar.style.display = "none"; return; }
    bar.style.display = "";
    const bw = bar.clientWidth;
    const tw = Math.max(28, bw * cw / sw);
    const maxX = bw - tw;
    thumb.style.width = tw + "px";
    thumb.style.transform = `translateX(${maxX * (rail.scrollLeft / (sw - cw))}px)`;
  }
  rail.addEventListener("scroll", () => requestAnimationFrame(update), { passive: true });
  let dragging = false;
  function seek(e){
    const rect = bar.getBoundingClientRect();
    const sw = rail.scrollWidth, cw = rail.clientWidth;
    if (sw <= cw) return;
    const tw = Math.max(28, rect.width * cw / sw);
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left - tw / 2) / (rect.width - tw)));
    rail.scrollLeft = frac * (sw - cw);
  }
  bar.addEventListener("pointerdown", e => { dragging = true; bar.setPointerCapture(e.pointerId); seek(e); e.preventDefault(); });
  bar.addEventListener("pointermove", e => { if (dragging) seek(e); });
  bar.addEventListener("pointerup", () => { dragging = false; });
  bar.addEventListener("pointercancel", () => { dragging = false; });
  window.addEventListener("resize", () => setTimeout(update, 160));
  return update;
}
const saleBarUpdate = bindRailBar("saleRail", "saleBar");
const featBarUpdate = bindRailBar("featGrid", "featBar");
document.getElementById("saleMore").onclick = () => { location.href = "sale.html"; };
function railTile(s, sm){
  if (hiddenItem(s.id)) return "";
  const priceIn = s.cur === 0 ? '<span class="free">' + tr("free") + '</span>' : yen(s.cur);
  const strip = sm
    ? `<span class="pstrip"><span class="bprice">${discountBadge(s.base, s.cur, "discst")}<span class="bstack">${s.base > s.cur ? `<span class="was${wCls(s.base)}">${yen(s.base)}</span>` : ""}<span class="price">${priceIn}</span></span></span></span>`
    : `<span class="pstrip">${discountBadge(s.base, s.cur, "discst")}${s.base > s.cur ? `<span class="pwas"><span class="wasx">${yen(s.base)}</span></span>` : ""}<span class="pprice${s.cur === 0 ? " free" : ""}">${priceIn}</span></span>`;
  return `<a class="rtile${sm ? " sm" : ""}" href="${itemUrl(s.id)}" target="_blank" rel="noopener"><span class="rimg">${s.image ? `<img decoding="async" src="${s.image}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this,'phcard')">` : `<span class="phcard" data-fill="${s.id}">${PH_ICON}</span>`}${s.at_lowest ? '<span class="mlab">' + tr("chip_lowest") + '</span>' : ""}${bmFlag(s.id, s.at_lowest ? "u2" : "")}</span>${strip}</a>`;
}
const tabsEl = document.getElementById("sortTabs");
const ind = tabsEl.querySelector(".pill-ind");
function moveInd(btn){
  ind.style.width = btn.offsetWidth + "px";
  ind.style.transform = `translateX(${btn.offsetLeft}px)`;
}
tabsEl.querySelectorAll("button").forEach(b => {
  b.onclick = () => {
    tabsEl.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    moveInd(b); sortMode = b.dataset.mode; renderSale();
  };
});
moveInd(tabsEl.querySelector("button.on"));
renderSale();

document.getElementById("chips").querySelectorAll(".chip").forEach(ch => {
  ch.onclick = () => {
    document.getElementById("chips").querySelectorAll(".chip").forEach(x => x.classList.toggle("on", x === ch));
    chipFilter = ch.dataset.f; renderSale();
  };
});

// ---- Steam-style tabbed browse module (list + side preview) ----
function bNormSale(s){ return {id: s.id, name: s.name, shop: s.shop, image: s.image, cur: s.cur, base: s.base, pct: s.pct, at_lowest: s.at_lowest, spark: s.spark, sale: true, note: tr("chip_onsale"), chips: [tr("chip_onsale"), ...(s.at_lowest ? [tr("chip_lowest")] : [])]}; }
function bNormDrop(d){ return {id: d.id, name: d.name, shop: d.shop, image: d.image, cur: d.to, base: d.from, pct: d.from ? Math.round((1 - d.to / d.from) * 100) : 0, at_lowest: d.at_lowest, spark: d.spark, drop: true, sale: !!d.sale_event, note: tr("note_dropped", {d: d.date}), chips: [tr("bt_drop"), ...(d.at_lowest ? [tr("chip_lowest")] : [])]}; }
function bNormFeat(x, kind){
  const pct = x.base > x.cur ? Math.round((1 - x.cur / x.base) * 100) : 0;
  return {id: x.id, name: x.name, shop: x.shop, image: x.image, cur: x.cur, base: x.base, pct, at_lowest: x.at_lowest, spark: x.spark, sale: !!x.on_sale,
    note: kind === "new" ? tr("added_on", {d: x.first_date}) : tr("recent3w_short", {n: x.changes_recent}),
    chips: kind === "new" ? [tr("bt_new")] : [tr("bt_active"), tr("alltime_changes", {n: x.changes_total})]};
}
function dedupeNewest(){
  const seen = {}; const out = [];
  for (const x of (LISTS.newest || [])) {
    const s = x.shop || "";
    if (s && (seen[s] || 0) >= 2) continue;
    seen[s] = (seen[s] || 0) + 1;
    out.push(x);
  }
  return out;
}
const fmtGain = v => { const n = Number(v) || 0; return n >= 10 ? Math.round(n).toLocaleString() : String(Math.round(n * 10) / 10); };
const BTABS = {
  new: () => dedupeNewest().map(x => bNormFeat(x, "new")),
  sale: () => [...LISTS.on_sale].sort((a,b) => b.pct - a.pct).map(bNormSale),
  drop: () => LISTS.drops.map(bNormDrop),
  free: () => (LISTS.free || LISTS.on_sale.filter(s => s.cur === 0)).map(s => ({...bNormSale(s), sale: s.on_sale !== false, note: tr("note_nowfree"), chips: [tr("free"), ...(s.at_lowest ? [tr("chip_lowest")] : [])]})),
  rising: () => (LISTS.rising || []).map(x => ({...bNormSale(x), note: HEART_SVG.replace("<svg", '<svg class="hico"') + tr("rising_note", {likes: (x.likes || 0).toLocaleString(), g: fmtGain(x.per_day)}), chips: [...(x.at_lowest ? [tr("chip_lowest")] : [])]})),
};
let bTab = "new", bItems = [], bShown = 7, FULL_OK = false;
function browHTML(x, i){
  if (hiddenItem(x.id)) return "";
  return `<a class="brow${i === 0 ? " sel" : ""}" data-i="${i}" href="${itemUrl(x.id)}" target="_blank" rel="noopener">
    <span class="bthw">${x.image ? `<img decoding="async" src="${x.image}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this,'bthph')">` : `<span class="bthph" data-fill="${x.id}">${PH_ICON}</span>`}${bmFlag(x.id)}</span>
    <span class="bmain"><span class="bname">${esc(x.name)}</span><span class="bshop">${esc(x.shop || "")}</span><span class="bnote">${x.note || ""}</span></span>
    <span class="bprice">${x.pct > 0 && x.sale ? `${discountBadge(x.base, x.cur, "discst")}` : ""}${x.base > x.cur ? `<span class="bstack"><span class="was${wCls(x.base)}">${yen(x.base)}</span><span class="price">${yen(x.cur)}</span></span>` : `<span class="price">${yen(x.cur)}</span>`}</span>
  </a>`;
}
function repSeriesOf(x){
  const vs = x && (x.variations || x.vars);
  if (!vs) return null;
  let best = null;
  for (const k in vs) { const e = vs[k]; const p = Array.isArray(e) ? e : (e && e.p); if (p && p.length >= 2 && (!best || p.length > best.length)) best = p; }
  return best ? {p: best} : null;
}
function bpChartSVG(ser, W, H){
  const s = ser.p;
  const ordS = s.filter(p => !p[3]);
  const src = ordS.length ? ordS : s;
  const high = Math.max(...src.map(p => p[1]));
  const PL = 4, PR = 4, PT = 13, PB = 14;
  const iw = W - PL - PR, ih = H - PT - PB;
  const yMax = Math.ceil(high * 1.08 / 100) * 100 || 100;
  const dn = d => Date.parse(d) / 864e5;
  const t0 = dn(s[0][0]), t1 = Math.max(dn(s[s.length - 1][0]), t0 + 1);
  const X = i => PL + iw * ((dn(s[i][0]) - t0) / (t1 - t0));
  const Y = v => PT + ih * (1 - v / yMax);
  let path = "", area = "";
  s.forEach((p, i) => { const cx = X(i).toFixed(1), cy = Y(p[1]).toFixed(1); if (i === 0) { path = `M${cx},${cy}`; area = `M${cx},${PT + ih} L${cx},${cy}`; } else { path += ` H${cx} V${cy}`; area += ` H${cx} V${cy}`; } });
  area += ` H${X(s.length - 1).toFixed(1)} V${PT + ih} Z`;
  let saleRects = "", st = null;
  s.forEach((p, i) => { if (p[2] && st === null) st = i; if ((!p[2] || i === s.length - 1) && st !== null) { const en = p[2] ? i : i - 1; saleRects += `<rect x="${X(st).toFixed(1)}" y="${PT}" width="${Math.max(1.5, X(en) - X(st)).toFixed(1)}" height="${ih}" fill="#fc4d50" opacity="0.07"/>`; st = null; } });
  const outlN = s.length - ordS.length;
  const fs = W >= 300 ? 9.5 : 10;
  return `<svg viewBox="0 0 ${W} ${H}">${saleRects}<text x="${PL + 2}" y="10" fill="${C_AXIS}" font-size="${fs}">\u00a5${high.toLocaleString(LOCALE)}</text>${outlN ? `<text x="${W - PR - 2}" y="10" fill="${C_NOTE}" font-size="${fs}" font-weight="700" text-anchor="end">${tr("outlier_n", {n: outlN})}</text>` : ""}<path d="${area}" fill="#fc4d50" opacity="0.12"/><path d="${path}" fill="none" stroke="#fc4d50" stroke-width="1.8"/><text x="${PL + 2}" y="${H - 3}" fill="${C_AXIS}" font-size="${fs}">${s[0][0]}</text><text x="${W - PR - 2}" y="${H - 3}" fill="${C_AXIS}" font-size="${fs}" text-anchor="end">${s[s.length - 1][0]}</text></svg>`;
}
const bpChartCache = new Map();
async function fillFeatCharts(){
  const phs = [...document.querySelectorAll("#featTrack [data-fchart]")];
  for (const ph of phs) {
    const id = ph.getAttribute("data-fchart");
    ph.dataset.fid = id;
    ph.removeAttribute("data-fchart");
    if (!bpChartCache.has(id)) bpChartCache.set(id, (async () => { try { const r = await fetchItemRecord(id); if (r) regP(r); return r; } catch { return null; } })());
    const rec = await bpChartCache.get(id);
    const ser = rec ? repSeriesOf(rec) : null;
    if (ser && ph.isConnected) { ph.classList.add("kp"); ph.innerHTML = bpChartSVG(ser, 200, 64); }
  }
}
async function fillBpChart(){
  const ph = document.querySelector("#bPrev [data-bpchart]");
  if (!ph) return;
  const id = ph.getAttribute("data-bpchart");
  if (!bpChartCache.has(id)) bpChartCache.set(id, (async () => {
    if (PROD.has(id)) return PROD.get(id);
    try { const r = await fetchItemRecord(id); if (r) regP(r); return r; } catch { return null; }
  })());
  const rec = await bpChartCache.get(id);
  const cur = document.querySelector("#bPrev [data-bpchart]");
  if (!cur || cur.getAttribute("data-bpchart") !== id) return;
  const ser = rec ? repSeriesOf(rec) : null;
  if (ser) cur.innerHTML = `<div class="cap">${tr("pp_chart")}</div>${bpChartSVG(ser, 340, 118)}`;
  else cur.style.display = "none";
  cur.dataset.fid = id;
  cur.removeAttribute("data-bpchart");
}
function bPrevHTML(x){
  if (hiddenItem(x.id)) return "";
  if (!x) return "";
  return `<div class="bpname">${esc(x.name)}</div>
    <div class="bpmeta">${esc(x.shop || "")}</div>
    <div class="bpchips">${(x.chips || []).map(c => `<span class="bpchip">${esc(c)}</span>`).join("")}</div>
    ${x.image ? `<img decoding="async" class="bpimg" src="${x.image}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
    ${repSeriesOf(x) ? `<div class="bpspark bpchart"><div class="cap">${tr("pp_chart")}</div>${bpChartSVG(repSeriesOf(x), 340, 118)}</div>` : `<div class="bpspark bpchart" data-bpchart="${x.id}"><div class="cap">${tr("pp_chart")}</div><div class="bpchart-load"></div></div>`}
    <div class="bprow">${x.pct > 0 && x.sale ? `${discountBadge(x.base, x.cur, "discst")}` : ""}${x.base > x.cur ? `<span class="was${wCls(x.base)}">${yen(x.base)}</span>` : ""}<span class="price">${yen(x.cur)}</span>${x.at_lowest ? '<span class="lowest">' + tr("chip_lowest") + '</span>' : ""}</div>`;
}
function renderBList(){
  const list = document.getElementById("bList");
  list.innerHTML = bItems.slice(0, bShown).map(browHTML).join("") || '<div class="empty" style="display:block">' + (FULL_OK ? tr("empty_none") : tr("loading")) + '</div>';
  document.getElementById("bMore").style.display = "";
  document.getElementById("bPrev").innerHTML = bPrevHTML(bItems[0]); setTimeout(fillBpChart, 0);
  list.querySelectorAll(".brow").forEach(r => {
    // Touch compatibility mouse events must not replace preview DOM before click.
    r.addEventListener("pointerenter", e => {
      if (e.pointerType !== "mouse") return;
      list.querySelectorAll(".brow").forEach(y => y.classList.toggle("sel", y === r));
      document.getElementById("bPrev").innerHTML = bPrevHTML(bItems[+r.dataset.i]); setTimeout(fillBpChart, 0);
    });
  });
}
function setBTab(t){
  bTab = t; bShown = 7;
  document.querySelectorAll("#bTabs .btab").forEach(b => b.classList.toggle("on", b.dataset.bt === t));
  bItems = (BTABS[t] || BTABS.new)();
  renderBList();
}
document.querySelectorAll("#bTabs .btab").forEach(b => { b.onclick = () => setBTab(b.dataset.bt); });
const BMORE = {new: "new.html", sale: "sale.html", drop: "drops.html", free: "free.html", rising: "rising.html"};
document.getElementById("bMore").onclick = () => { location.href = BMORE[bTab] || "sale.html"; };
setBTab("new");
// Full lists swap-in: the home sale section and browse tabs run on the
// whole catalog once lists_full.json arrives (the sample paints first).
function loadFullLists(n){
  fetch("lists_full.json?v=20251025-6").then(r => { if (!r.ok) throw new Error("lists"); return r.json(); }).then(f => {
  f = filterVisibleLists(f);
  FULL_LISTS = f; FULL_OK = true;
  spEnrichFromLists();
  if (fullIndex) spEnrichFromIndex();
  if (f.stats) renderStats(f.stats);
  if (f.on_sale && f.on_sale.length) { SALE_HOME = f.on_sale; LISTS.on_sale = f.on_sale; renderSale(); }
  if (f.drops) LISTS.drops = f.drops;
  if (f.active) LISTS.active = f.active;
  if (f.newest) LISTS.newest = f.newest;
  if (f.rising) LISTS.rising = f.rising;
  try { renderHeroFromLists(f); } catch {}
  try { renderFeatFromNewest(f.newest); } catch {}
  if (f.free) LISTS.free = f.free;
  if (f.updates) { LISTS.updates = f.updates; try { renderUpdates(); } catch {} }
  setBTab(bTab);
  if (spage.classList.contains("open")) spRender(false);
  }).catch(() => { if (n < 2) setTimeout(() => loadFullLists(n + 1), 2500); else { FULL_OK = true; setBTab(bTab); } });
}
loadFullLists(0);
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => loadShopSec());
else loadShopSec();

function renderHeroFromLists(f){
  const picks = normalizeHeroEntries(selectHeroEntries(f));
  if (picks.length >= 3 && heroSignature(picks) !== heroRenderedSignature) {
    // Preserve a user's current product when genuine data changes; unchanged
    // data must not replace image nodes, reset the slide, or restart animation.
    buildHero(picks, true);
  }
}
function renderFeatFromNewest(list){
  const top = selectFeaturedEntries({newest: list}, heroItems);
  const signature = JSON.stringify(top);
  const track = document.getElementById("featTrack");
  if (track.dataset.selection === signature) return;
  track.dataset.selection = signature;
  document.getElementById("featTrack").innerHTML = top.map(x => featCap(x, tr("bt_new"), "", " new")).join("");
  fillFeatCharts();
  featPager.reset();
  requestAnimationFrame(featBarUpdate);
}
function sparkSVG(spark){
  if (!spark || spark.length < 2) return "";
  const ps = spark.map(p => p[1]);
  const mn = Math.min(...ps), mx = Math.max(...ps), rg = (mx - mn) || 1;
  const pts = spark.map((p, i) => `${(i / (spark.length - 1) * 100).toFixed(1)},${(25 - (p[1] - mn) / rg * 22).toFixed(1)}`).join(" ");
  const col = ps[ps.length - 1] < ps[0] ? "#a4d007" : (ps[ps.length - 1] > ps[0] ? "#fc4d50" : "#a2a2ab");
  return `<svg viewBox="0 0 100 28" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.6"/></svg>`;
}
function featCap(x, tag, meta, cls){
  if (hiddenItem(x.id)) return "";
  const pct = x.base > x.cur ? Math.round((1 - x.cur / x.base) * 100) : 0;
  const fser = repSeriesOf(x);
  return `<div class="card">
    <a class="capimg" href="${itemUrl(x.id)}" target="_blank" rel="noopener">${x.image ? `<img decoding="async" src="${x.image}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this,'phcard')">` : `<span class="phcard" data-fill="${x.id}">${PH_ICON}</span>`}${bmFlag(x.id, (cls || "").includes("new") ? "" : "u2")}</a>${(cls || "").includes("new") ? "" : `<span class="ftag${cls || ""}">${tag}</span>`}
    <div class="capbody">
      <div class="capname"><a href="${itemUrl(x.id)}" target="_blank" rel="noopener">${esc(x.name)}</a></div>
      <div class="capshop">${esc(x.shop || "")}</div>
      <div class="spark${fser ? " kp" : ""}"${fser ? "" : ` data-fchart="${x.id}"`}>${fser ? bpChartSVG(fser, 200, 64) : sparkSVG(x.spark)}</div>
      <div class="caprow">${(cls || "").includes("new") ? `<span class="newtag">${tag}</span>` : ""}${pct > 0 && x.on_sale ? `${discountBadge(x.base, x.cur, "discst")}<span class="was${wCls(x.base)}"><span class="wasx">${yen(x.base)}</span></span>` : (x.on_sale ? `<span class="saletag">${tr("rib_sale")}</span>` : "")}<span class="price${wCls(x.cur)}">${x.cur === 0 ? tr("free") : yen(x.cur)}</span></div>
    </div>
  </div>`;
}
// Use the same compact candidate pool before and after the catalog arrives.
// No unrelated sample products or duplicate hero cards flash during loading.
renderFeatFromNewest(HERO_BOOTSTRAP.newest);




// ---- product registry ----
const PROD = new Map();
function regP(x){ if (visibleItem(x) && x.id != null && !PROD.has(String(x.id))) PROD.set(String(x.id), x); }
P.on_sale.forEach(s => regP({id: s.id, name: s.name, shop: s.shop, image: s.image, cur: s.cur, base: s.base, pct: s.pct, at_lowest: s.at_lowest, lowest: s.lowest, spark: s.spark, sale: true, variations: s.vars}));
P.drops.forEach(d => regP({id: d.id, name: d.name, shop: d.shop, image: d.image, cur: d.to, base: d.from, pct: d.from ? Math.round((1 - d.to / d.from) * 100) : 0, at_lowest: d.at_lowest, lowest: d.lowest, spark: d.spark, sale: !!d.on_sale, variations: d.vars}));
(P.active || []).forEach(a => regP({id: a.id, name: a.name, shop: a.shop, image: a.image, cur: a.cur, base: a.base, pct: a.base > a.cur ? Math.round((1 - a.cur / a.base) * 100) : 0, at_lowest: a.at_lowest, lowest: a.lowest, spark: a.spark, sale: !!a.on_sale, variations: a.vars}));
(P.newest || []).forEach(a => regP({id: a.id, name: a.name, shop: a.shop, image: a.image, cur: a.cur, base: a.base, pct: a.base > a.cur ? Math.round((1 - a.cur / a.base) * 100) : 0, at_lowest: a.at_lowest, lowest: a.lowest, spark: a.spark, sale: !!a.on_sale, variations: a.vars}));
P.charts.forEach(p => {
  const ex = PROD.get(String(p.id)) || {id: p.id, name: p.name, shop: p.shop, image: p.image};
  ex.variations = p.variations;
  const keys = Object.keys(p.variations || {});
  if (keys.length) {
    const ser = p.variations[keys[0]];
    const rows = Array.isArray(ser) ? ser : ser.p;
    const prices = rows.map(r => r[1]);
    if (ex.cur == null) { ex.cur = prices[prices.length - 1]; ex.base = Math.max(...prices); }
    ex.lowest = Math.min(...prices);
    ex.pct = ex.base ? Math.round((1 - ex.cur / ex.base) * 100) : 0;
    ex.at_lowest = ex.cur === ex.lowest;
  }
  PROD.set(String(p.id), ex);
});


// ---- product page ----
const prodPage = document.getElementById("prodPage");
let curProd = null, curVarKey = null;
function seriesOf(x, key){
  if (x.variations && key && x.variations[key]) {
    const e = x.variations[key];
    if (Array.isArray(e)) return {p: e, d: e.length, sd: e.filter(p => p[2]).length};
    return e;
  }
  const sp = (x.spark || []).map(p => [p[0], p[1], 0]);
  return {p: sp, d: sp.length, sd: 0};
}
function statsHTML(ser){
  const s = ser.p, prices = s.map(p => p[1]);
  const curP = prices[prices.length - 1], low = Math.min(...prices);
  const ord = s.filter(p => !p[3]);
  const ordPrices = (ord.length ? ord : s).map(p => p[1]);
  const high = Math.max(...ordPrices);
  // Legacy/thinned-only inputs cannot reconstruct the true average.
  const avg = hasAverageSource(ser) ? Math.round(ser.average_source.sum / ser.average_source.count) : null;
  const curCell = yen(curP) + (s[s.length - 1][3] ? ' <span class="outlb">' + tr("outlier") + '</span>' : "");
  return [
    [historyObservationLabel(), curCell + `<small class="vhistorydate">${esc(s[s.length - 1][0])}</small>`], [tr("chip_lowest"), yen(low)], [tr("pp_high"), yen(high)],
    [tr("pp_avg"), avg === null ? "—" : yen(avg)], [tr("pp_saledays"), tr("days_fmt", {n: ser.sd})], [tr("pp_days"), tr("days_fmt", {n: ser.d})],
  ].map(([k, v]) => `<div><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
}
const DAYMS = 86400000;
const dnum = ds => Date.parse(ds + "T00:00:00Z") / DAYMS;
const diso = t => new Date(Math.round(t) * DAYMS).toISOString().slice(0, 10);
function chartSVG(ser, H){
  const s = ser.p;
  const prices = s.map(p => p[1]);
  const ordS = s.filter(p => !p[3]);
  const high = Math.max(...(ordS.length ? ordS : s).map(p => p[1]));
  const outlN = ser.outl != null ? ser.outl : s.length - ordS.length;
  const W = 980, PL = 64, PR = 14, PT = 14, PB = 26;
  const iw = W - PL - PR, ih = H - PT - PB;
  const yMax = Math.ceil(high * 1.08 / 100) * 100 || 100;
  const t0c = dnum(s[0][0]), t1c = Math.max(dnum(s[s.length - 1][0]), t0c + 1);
  const X = i => PL + iw * ((dnum(s[i][0]) - t0c) / (t1c - t0c));
  const Y = v => PT + ih * (1 - v / yMax);
  let path = "", area = "";
  s.forEach((p, i) => {
    const cx = X(i), cy = Y(p[1]);
    if (i === 0) { path = `M${cx},${cy}`; area = `M${cx},${PT + ih} L${cx},${cy}`; }
    else { path += ` H${cx} V${cy}`; area += ` H${cx} V${cy}`; }
  });
  area += ` H${X(s.length - 1)} V${PT + ih} Z`;
  let saleRects = "", st = null;
  s.forEach((p, i) => {
    if (p[2] && st === null) st = i;
    if ((!p[2] || i === s.length - 1) && st !== null) {
      const en = p[2] ? i : i - 1;
      saleRects += `<rect x="${X(st)}" y="${PT}" width="${Math.max(1.5, X(en) - X(st))}" height="${ih}" fill="#fc4d50" opacity="0.07"/>`;
      st = null;
    }
  });
  let grid = "";
  for (let g = 0; g <= 4; g++) {
    const v = yMax * g / 4, gy = Y(v);
    grid += `<line x1="${PL}" y1="${gy}" x2="${W - PR}" y2="${gy}" stroke="${C_GRID}" stroke-width="1"/>` +
            `<text x="${PL - 6}" y="${gy + 4}" fill="${C_AXIS}" font-size="11" text-anchor="end">¥${Math.round(v).toLocaleString(LOCALE)}</text>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}">${saleRects}${grid}<line class="hvGuide" y1="${PT}" y2="${PT + ih}" stroke="${C_AXIS}" stroke-width="1" opacity="0"/>${outlN ? `<text x="${W - PR}" y="${PT + 3}" fill="${C_NOTE}" font-size="11" font-weight="700" text-anchor="end">${tr("outlier_n", {n: outlN})}</text>` : ""}<path d="${area}" fill="#fc4d50" opacity="0.12"/><path d="${path}" fill="none" stroke="#fc4d50" stroke-width="2" pathLength="1" style="stroke-dasharray:1;stroke-dashoffset:1;animation:dash .9s ease forwards"/>` +
    `<text x="${PL}" y="${H - 6}" fill="${C_AXIS}" font-size="11">${s[0][0]}</text>` +
    `<text x="${W - PR}" y="${H - 6}" fill="${C_AXIS}" font-size="11" text-anchor="end">${s[s.length - 1][0]}</text></svg>` +
    (ser.sd ? `<p class="note">${tr("pp_salenote")}</p>` : "");
}
function changesHTML(ser){
  const s = ser.p, chgs = [];
  for (let i = 1; i < s.length; i++) if (s[i][1] !== s[i - 1][1]) chgs.push({date: s[i][0], from: s[i - 1][1], to: s[i][1], outl: !!(s[i][3] || s[i - 1][3])});
  if (!chgs.length) return {n: 0, html: '<p class="note">' + tr("pp_nochg") + '</p>'};
  const rows = chgs.slice(-8).reverse().map(c => {
    const d = c.to - c.from, pc = c.from ? Math.round(d / c.from * 100) : 0;
    return `<span class="cd">${c.date}</span><span class="${d < 0 ? "down" : "up"}">${d < 0 ? tr("pp_down") : tr("pp_up")}</span><span class="cb">${yen(c.from)}</span><span class="ca">${yen(c.to)}</span><span class="cr ${d < 0 ? "down" : "up"}">${displayChangePercent(c.from, c.to)}${c.outl ? ' <span class="outlb">' + tr("outlier") + '</span>' : ""}</span>`;
  }).join("");
  const html = `<div class="chgtable"><span class="chh">${tr("chg_date")}</span><span class="chh"></span><span class="chh cb">${tr("chg_before")}</span><span class="chh ca">${tr("chg_after")}</span><span class="chh cr">${tr("chg_rate")}</span>` + rows + `</div>`;
  return {n: Math.min(chgs.length, 8), html};
}
function historyObservationLabel(){return ({ja:'最終観測価格',en:'Last observed price',ko:'마지막 관측 가격','zh-Hans':'最后观测价格','zh-Hant':'最後觀測價格'})[typeof LANG==='string'?LANG:'ja']||'Last observed price';}
function historySaleLabel(){return ({ja:'セール観測',en:'Sale observed',ko:'세일 관측','zh-Hans':'促销观测','zh-Hant':'促銷觀測'})[typeof LANG==='string'?LANG:'ja']||'Sale observed';}
function varBlockHTML(x, key, idx){
  const ser = seriesOf(x, key);
  const s = ser.p;
  if (!s || s.length < 2) return key ? "" : '<p class="note">' + tr("pp_nodata") + '</p>';
  const prices = s.map(p => p[1]);
  const curP = prices[prices.length - 1], low = Math.min(...prices);
  const onSaleNow = !!s[s.length - 1][2];
  const head = `<div class="pp-varhead">${key ? `<span class="pp-varname">${esc(key)}</span>${s[s.length - 1][3] ? '<span class="outlb">' + tr("outlier") + '</span>' : ""}${onSaleNow ? `<span class="bpchip">${historySaleLabel()}</span>` : ""}${curP <= low ? `<span class="bpchip">${tr("chip_lowest")}</span>` : ""}` : ""}<button type="button" class="chExpand" data-exp="${idx || 0}" aria-label="${tr("al_expand")}">${EXPAND_SVG}</button></div>`;
  const chg = changesHTML(ser);
  const chgSec = chg.n ? `<div class="pp-changes"><button type="button" class="pp-toggle" data-chgbtn>${tr("pp_changes")}（${chg.n}）<span class="car"></span></button><div class="pp-chgbody" hidden>${chg.html}</div></div>` : `<div class="pp-changes">${chg.html}</div>`;
  return `<div class="pp-varblock">${head}<div class="pstats">${statsHTML(ser)}</div><div class="chartbox">${chartSVG(windowSeries(ser), key ? 210 : 300)}</div><div class="hvTip charttip"></div>${chgSec}</div>`;
}
function renderPPBody(x){
  const keys = x.variations ? Object.keys(x.variations) : [];
  const statsEl = document.getElementById("ppStats");
  const chartEl = document.getElementById("ppChart");
  if (keys.length) {
    statsEl.innerHTML = statsHTML(seriesOf(x, keys[0]));
    cmpDefaults(x, keys);
    renderCompare(x);
    chartEl.innerHTML = `<div class="cmpranges pp-ranges">${rangeBtnsHTML()}</div>` + keys.map((k, i) => varBlockHTML(x, k, i)).join("");
  } else {
    const ser = seriesOf(x, null);
    statsEl.innerHTML = ser.p && ser.p.length >= 2 ? statsHTML(ser) : (Number.isFinite(x.cur) && x.cur >= 0 ? `<div><div class="k">${tr("pp_cur")}</div><div class="v">${yen(x.cur)}</div></div>` : "");
    chartEl.innerHTML = `<div class="cmpranges pp-ranges">${rangeBtnsHTML()}</div>` + varBlockHTML(x, null, 0);
  }
  chartEl.querySelectorAll("[data-cr]").forEach(b => b.onclick = () => { ppRange = b.dataset.cr; renderPPBody(x); wireBlockHovers(x); });
  chartEl.querySelectorAll("[data-chgbtn]").forEach(b => b.onclick = () => {
    const body = b.parentElement.querySelector(".pp-chgbody");
    if (!body) return;
    body.hidden = !body.hidden;
    b.classList.toggle("open", !body.hidden);
  });
}
let cmpOn = {};
let cmpOpen = false;
const CMP_RANGES = {"1d": 1, "5d": 5, "1m": 30, "6m": 182, "1y": 365, "5y": 1825};
const CMP_RANGE_KEYS = ["1d", "5d", "1m", "6m", "ytd", "1y", "5y", "max"];
let ppRange = "max";
function rangeBtnsHTML(){ return CMP_RANGE_KEYS.map(k => `<button type="button" class="cmprange ${ppRange === k ? "on" : ""}" data-cr="${k}">${tr("rng_" + k)}</button>`).join(""); }
function windowSeries(ser){
  const s = ser && ser.p;
  if (!s || s.length < 2 || ppRange === "max") return ser;
  const t1 = dnum(s[s.length - 1][0]), t0f = dnum(s[0][0]);
  const w0 = ppRange === "ytd" ? Math.max(t0f, dnum(diso(t1).slice(0, 4) + "-01-01")) : Math.max(t0f, t1 - CMP_RANGES[ppRange]);
  if (w0 <= t0f) return ser;
  const disp = [];
  const ap = pricePtAt(ser, w0);
  if (ap && dnum(ap[0]) < w0) disp.push([diso(w0), ap[1], ap[2], ap[3]]);
  s.forEach(p => { const t = dnum(p[0]); if (t >= w0 && t <= t1) disp.push(p); });
  if (!disp.length) return ser;
  if (disp.length === 1) disp.push([diso(t1), disp[0][1], disp[0][2], disp[0][3]]);
  return {p: disp, d: ser.d, sd: disp.filter(p => p[2]).length, outl: s.filter(p => p[3]).length};
}
let CMP_GROUPS = [];
function cmpSig(ser){ return ser.p.map(p => p[1] + (p[2] ? "s" : "")).join(","); }
function cmpDefaults(x, keys){
  cmpOn = {};
  keys.forEach(k => { cmpOn[k] = true; });
}
function cmpDomain(x, keys){
  let t0 = Infinity, t1 = -Infinity;
  keys.forEach(k => { if (!cmpOn[k]) return; seriesOf(x, k).p.forEach(p => { const t = dnum(p[0]); if (t < t0) t0 = t; if (t > t1) t1 = t; }); });
  if (!isFinite(t0)) { t0 = 0; t1 = 1; }
  if (t1 <= t0) t1 = t0 + 1;
  // Period filter, same ranges as the Boopa extension: the window ends at
  // the newest data point; "max" keeps the full span.
  let w0 = t0;
  if (ppRange === "ytd") w0 = Math.max(t0, dnum(diso(t1).slice(0, 4) + "-01-01"));
  else if (ppRange !== "max") w0 = Math.max(t0, t1 - CMP_RANGES[ppRange]);
  let high = 0;
  keys.forEach(k => { if (!cmpOn[k]) return; const ser = seriesOf(x, k); ser.p.forEach(p => { if (!p[3] && dnum(p[0]) >= w0 && p[1] > high) high = p[1]; }); const ap = pricePtAt(ser, w0); if (ap && !ap[3] && ap[1] > high) high = ap[1]; });
  return {high, t0: w0, t1};
}
function compareSVG(x, keys){
  const act = keys.filter(k => cmpOn[k]);
  const W = 980, H = 300, PL = 64, PR = 14, PT = 14, PB = 26;
  const iw = W - PL - PR, ih = H - PT - PB;
  const {high, t0, t1} = cmpDomain(x, keys);
  const yMax = Math.ceil(high * 1.08 / 100) * 100 || 100;
  const X = t => PL + iw * ((t - t0) / (t1 - t0));
  const Y = v => PT + ih * (1 - v / yMax);
  let grid = "";
  for (let gI = 0; gI <= 4; gI++) {
    const v = yMax * gI / 4, gy = Y(v);
    grid += `<line x1="${PL}" y1="${gy}" x2="${W - PR}" y2="${gy}" stroke="${C_GRID}" stroke-width="1"/>` +
            `<text x="${PL - 6}" y="${gy + 4}" fill="${C_AXIS}" font-size="11" text-anchor="end">¥${Math.round(v).toLocaleString(LOCALE)}</text>`;
  }
  let lines = "";
  act.forEach(k => {
    const ser = seriesOf(x, k), s = ser.p, col = CMP_COLORS[keys.indexOf(k) % CMP_COLORS.length];
    const disp = [];
    const ap = pricePtAt(ser, t0);
    if (ap && dnum(ap[0]) < t0) disp.push([diso(t0), ap[1], ap[2], ap[3]]);
    s.forEach(p => { const t = dnum(p[0]); if (t >= t0 && t <= t1) disp.push(p); });
    if (!disp.length) return;
    let path = "";
    disp.forEach((p, j) => { const cx = X(dnum(p[0])), cy = Y(p[1]); path += j === 0 ? `M${cx},${cy}` : ` H${cx} V${cy}`; });
    path += ` H${X(t1)}`;
    lines += `<path d="${path}" fill="none" stroke="${col}" stroke-width="2"/>`;
  });
  const dates = `<text x="${PL}" y="${H - 6}" fill="${C_AXIS}" font-size="11">${diso(t0)}</text><text x="${W - PR}" y="${H - 6}" fill="${C_AXIS}" font-size="11" text-anchor="end">${diso(t1)}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}">${grid}${lines}<line id="cmpGuide" y1="${PT}" y2="${PT + ih}" stroke="${C_AXIS}" stroke-width="1" opacity="0"/>${dates}</svg>`;
}
function priceAt(ser, t){
  let v = ser.p.length ? ser.p[0][1] : 0;
  for (const p of ser.p) { if (dnum(p[0]) <= t) v = p[1]; else break; }
  return v;
}
function pricePtAt(ser, t){
  if (!ser.p.length || dnum(ser.p[0][0]) > t) return null;
  let pt = ser.p[0];
  for (const p of ser.p) { if (dnum(p[0]) <= t) pt = p; else break; }
  return pt;
}
function chartTouch(svg, move, hide){
  const box = svg.parentElement;
  let timer = null, scrubbing = false, sx = 0, sy = 0, downAt = 0, lastE = null;
  const edgePan = e => {
    const max = box.scrollWidth - box.clientWidth;
    if (max <= 0) return;
    const br = box.getBoundingClientRect(), vx = e.clientX - br.left;
    if (vx > br.width - 36 && box.scrollLeft < max) { box.scrollLeft = Math.min(max, box.scrollLeft + 14); move(e); }
    else if (vx < 36 && box.scrollLeft > 0) { box.scrollLeft = Math.max(0, box.scrollLeft - 14); move(e); }
  };
  svg.addEventListener("contextmenu", e => e.preventDefault());
  svg.addEventListener("pointerdown", e => {
    if (e.pointerType !== "touch") { move(e); return; }
    hide();
    sx = e.clientX; sy = e.clientY; lastE = e; downAt = Date.now(); scrubbing = false;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => { timer = null; scrubbing = true; if (lastE) move(lastE); }, 200);
  });
  svg.addEventListener("pointermove", e => {
    if (e.pointerType !== "touch") { move(e); return; }
    lastE = e;
    if (scrubbing) { move(e); edgePan(e); return; }
    const dx = Math.abs(e.clientX - sx), dy = Math.abs(e.clientY - sy);
    if (dx >= 8 && dx > dy) { if (timer) { clearTimeout(timer); timer = null; } scrubbing = true; move(e); }
    else if (dy > 10 && timer) { clearTimeout(timer); timer = null; }
  });
  svg.addEventListener("pointerup", e => {
    if (timer) { clearTimeout(timer); timer = null; }
    if (e.pointerType !== "touch") return;
    if (!(scrubbing && Date.now() - downAt >= 400)) hide();
    scrubbing = false;
  });
  svg.addEventListener("pointercancel", () => { if (timer) { clearTimeout(timer); timer = null; } scrubbing = false; hide(); });
  svg.addEventListener("pointerleave", e => { if (e.pointerType !== "touch") hide(); });
}
function wireHover(box, ser, tipEl){
  const host = box.closest(".pp-varblock") || box;
  const tip = tipEl || host.querySelector(".hvTip");
  const svg = box.querySelector("svg");
  if (!tip || !svg || !ser || !ser.p || !ser.p.length) return;
  const pts = ser.p;
  const t0 = dnum(pts[0][0]), t1 = Math.max(dnum(pts[pts.length - 1][0]), t0 + 1);
  const hide = () => { tip.style.display = "none"; const gd = svg.querySelector(".hvGuide"); if (gd) gd.setAttribute("opacity", "0"); };
  const move = e => {
    const r = svg.getBoundingClientRect();
    const W = 980, PL = 64, PR = 14;
    const fx = (e.clientX - r.left) / r.width;
    const vx = fx * W;
    if (vx < PL || vx > W - PR) { hide(); return; }
    const t = t0 + (vx - PL) / (W - PL - PR) * (t1 - t0);
    const pt = pricePtAt(ser, t);
    const v = pt ? pt[1] : 0;
    const sale = !!(pt && pt[2]);
    tip.innerHTML = `<div class="cmtd">${diso(t)}</div><div class="cmtr"><b>${yen(v)}</b>${pt && pt[3] ? ' <span class="outlb">' + tr("outlier") + '</span>' : ""}${sale ? '<span class="cmpdot" style="background:#fc4d50"></span><span>' + tr("chip_onsale") + '</span>' : ""}</div>`;
    tip.style.display = "block";
    if (tipEl) {
      tip.style.left = ""; tip.style.top = "";
    } else {
      const block = tip.offsetParent || host;
      const br = block.getBoundingClientRect();
      const cr = box.getBoundingClientRect();
      tip.style.left = Math.min(Math.max(e.clientX - br.left + 14, 4), Math.max(4, br.width - tip.offsetWidth - 4)) + "px";
      tip.style.top = Math.max(0, cr.top - br.top - tip.offsetHeight - 6) + "px";
    }
    const gd = svg.querySelector(".hvGuide");
    if (gd) { gd.setAttribute("x1", vx); gd.setAttribute("x2", vx); gd.setAttribute("opacity", "0.5"); }
  };
  chartTouch(svg, move, hide);
}
function wireBlockHovers(x){
  const keys = x.variations ? Object.keys(x.variations) : [];
  const all = keys.length ? keys.map(k => windowSeries(seriesOf(x, k))) : [windowSeries(seriesOf(x, null))];
  const sers = all.filter(ser => ser.p && ser.p.length >= 2);
  document.querySelectorAll("#ppBody .chartbox").forEach((box, i) => { if (sers[i]) wireHover(box, sers[i]); box.scrollLeft = box.scrollWidth; });
  document.querySelectorAll("#ppBody [data-exp]").forEach(b => { b.onclick = () => openChartPop("var", +b.dataset.exp); });
}
function wireCmpTip(x, wrap, tip){
  wrap = wrap || document.getElementById("cmpChart");
  tip = tip || document.getElementById("cmpTip");
  const svg = wrap && wrap.querySelector("svg");
  if (!wrap || !svg || !tip) return;
  const hide = () => { tip.style.display = "none"; const gd = svg.querySelector("#cmpGuide"); if (gd) gd.setAttribute("opacity", "0"); };
  const move = e => {
    const r = svg.getBoundingClientRect();
    const W = 980, PL = 64, PR = 14;
    const fx = (e.clientX - r.left) / r.width;
    const vx = fx * W;
    if (vx < PL || vx > W - PR) { hide(); return; }
    const keys = Object.keys(x.variations || {});
    const {t0, t1} = cmpDomain(x, keys);
    const t = t0 + (vx - PL) / (W - PL - PR) * (t1 - t0);
    const allRows = keys.filter(k => cmpOn[k])
      .map(k => { const pt = pricePtAt(seriesOf(x, k), t); return pt ? {name: k, col: CMP_COLORS[keys.indexOf(k) % CMP_COLORS.length], v: pt[1], outl: !!pt[3]} : null; })
      .filter(Boolean)
      .sort((p, q) => q.v - p.v);
    const rows = allRows.slice(0, 10).map(rw => `<div class="cmtr"><span class="cmpdot" style="background:${rw.col}"></span><span class="cmtn">${esc(rw.name)}</span><b>${yen(rw.v)}</b>${rw.outl ? ' <span class="outlb">' + tr("outlier") + '</span>' : ""}</div>`).join("")
      + (allRows.length > 10 ? `<div class="cmtr cmmore">${tr("cmp_more", {n: allRows.length - 10})}</div>` : "");
    tip.innerHTML = `<div class="cmtd">${diso(t)}</div><div class="cmtrows">` + rows + `</div>`;
    tip.style.display = "block";
    const block = tip.parentElement;
    const br = block.getBoundingClientRect();
    const cr = wrap.getBoundingClientRect();
    const px = e.clientX - br.left + 14;
    tip.style.left = Math.min(Math.max(px, 4), Math.max(4, br.width - tip.offsetWidth - 4)) + "px";
    const above = block !== wrap;
    tip.classList.toggle("wide", above && allRows.length > 5);
    tip.style.top = (above ? Math.max(0, cr.top - br.top - tip.offsetHeight - 6) : Math.max(0, cr.top - br.top + 8)) + "px";
    const gd = svg.querySelector("#cmpGuide");
    if (gd) { gd.setAttribute("x1", vx); gd.setAttribute("x2", vx); gd.setAttribute("opacity", "0.5"); }
  };
  chartTouch(svg, move, hide);
  wrap.scrollLeft = wrap.scrollWidth;
}
function cmpLegendHTML(x, keys){
  return keys.map((k, i) => {
    const s = seriesOf(x, k).p;
    const cur = s.length ? s[s.length - 1][1] : 0;
    const col = CMP_COLORS[i % CMP_COLORS.length];
    const on = !!cmpOn[k];
    return `<button type="button" class="cmpchip ${on ? "on" : ""}" data-ck="${i}" style="${on ? `border-color:${col};background:${col}26` : ""}"><span class="cmpdot" style="background:${col}"></span>${esc(k)} — ${yen(cur)}</button>`;
  }).join("");
}
function renderCompare(x){
  const el = document.getElementById("ppCompare");
  if (!el) return;
  const keys = Object.keys(x.variations || {});
  if (keys.length < 2) { el.innerHTML = ""; return; }
  const legend = cmpLegendHTML(x, keys);
  const rangeBtns = rangeBtnsHTML();
  const outlTotal = keys.reduce((n, k) => n + seriesOf(x, k).p.filter(p => p[3]).length, 0);
  el.innerHTML = `<div class="pp-varblock"><div class="pp-varhead"><span class="pp-varname">${tr("pp_compare")}</span><button type="button" class="chExpand" data-cmp-exp aria-label="${tr("al_expand")}">${EXPAND_SVG}</button><button type="button" class="pp-toggle ${cmpOpen ? "open" : ""}" id="cmpTgl"><span class="car"></span></button></div><div id="cmpBody"${cmpOpen ? "" : " hidden"}><div class="cmplegend">${legend}</div>${outlTotal ? `<div class="cmpoutl">${tr("outlier_n", {n: outlTotal})}</div>` : ""}<div id="cmpChart">${compareSVG(x, keys)}</div><div class="cmpranges">${rangeBtns}</div></div><div id="cmpTip"></div></div>`;
  const cmpTgl = el.querySelector("#cmpTgl"), cmpBody = el.querySelector("#cmpBody");
  if (cmpTgl && cmpBody) cmpTgl.onclick = () => { cmpOpen = !cmpOpen; cmpBody.hidden = !cmpOpen; cmpTgl.classList.toggle("open", cmpOpen); };
  el.querySelectorAll("[data-cr]").forEach(b => b.onclick = () => { ppRange = b.dataset.cr; renderPPBody(x); wireBlockHovers(x); });
  el.querySelectorAll("[data-ck]").forEach(b => b.onclick = () => {
    const k = keys[+b.dataset.ck];
    if (cmpOn[k] && keys.filter(kk => cmpOn[kk]).length <= 1) return;
    cmpOn[k] = !cmpOn[k];
    renderCompare(x);
  });
  wireCmpTip(x);
  const eb = el.querySelector("[data-cmp-exp]");
  if (eb) eb.onclick = () => openChartPop("cmp", 0);
}
const EXPAND_SVG = '<svg viewBox="0 0 24 24"><path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5"/></svg>';
function expandBtn(onclick){
  const b = document.createElement("button");
  b.type = "button"; b.className = "chExpand"; b.setAttribute("aria-label", tr("al_expand"));
  b.innerHTML = EXPAND_SVG; b.onclick = onclick;
  return b;
}
let cpState = null;
function openChartPop(kind, idx){
  const x = ppX; if (!x) return;
  cpState = {kind, idx};
  const pop = document.getElementById("chartPop");
  const title = document.getElementById("cpTitle");
  const chart = document.getElementById("cpChart");
  const legend = document.getElementById("cpLegend");
  const outl = document.getElementById("cpOutl");
  legend.innerHTML = ""; outl.innerHTML = "";
  const roEl = document.getElementById("cpReadout"); roEl.className = ""; roEl.innerHTML = "";
  if (kind === "cmp") {
    const keys = Object.keys(x.variations || {});
    title.textContent = tr("pp_compare");
    legend.innerHTML = `<div class="cmplegend">${cmpLegendHTML(x, keys)}</div>`;
    const ot = keys.reduce((n, k) => n + seriesOf(x, k).p.filter(p => p[3]).length, 0);
    if (ot) outl.innerHTML = `<div class="cmpoutl">${tr("outlier_n", {n: ot})}</div>`;
    chart.innerHTML = compareSVG(x, keys) + '<div id="cpCmpTip"></div>';
    wireCmpTip(x, chart, document.getElementById("cpCmpTip"));
    legend.querySelectorAll("[data-ck]").forEach(b => b.onclick = () => {
      const k = keys[+b.dataset.ck];
      if (cmpOn[k] && keys.filter(kk => cmpOn[kk]).length <= 1) return;
      cmpOn[k] = !cmpOn[k];
      renderCompare(x);
      openChartPop("cmp", 0);
    });
  } else {
    const key = ppKeys[idx] != null ? ppKeys[idx] : "";
    const ws = windowSeries(seriesOf(x, key));
    title.textContent = key || x.name;
    chart.innerHTML = chartSVG(ws, 380);
    const ro = document.getElementById("cpReadout");
    ro.className = "on"; ro.innerHTML = '<div class="hvTip"></div>';
    const rtip = ro.querySelector(".hvTip");
    wireHover(chart, ws, rtip);
    const lp = ws.p[ws.p.length - 1];
    if (lp) { rtip.innerHTML = `<div class="cmtd">${lp[0]}</div><div class="cmtr"><b>${yen(lp[1])}</b>${lp[3] ? ' <span class="outlb">' + tr("outlier") + '</span>' : ""}</div>`; rtip.style.display = "block"; }
  }
  document.getElementById("cpRanges").innerHTML = rangeBtnsHTML();
  pop.querySelectorAll("[data-cr]").forEach(b => b.onclick = () => { ppRange = b.dataset.cr; renderPPBody(ppX); wireBlockHovers(ppX); openChartPop(cpState.kind, cpState.idx); });
  document.getElementById("cpClose").onclick = closeChartPop;
  pop.onclick = e => { if (e.target === pop) closeChartPop(); };
  pop.hidden = false;
  const pp = document.getElementById("prodPage");
  if (pp) pp.style.overflowY = "hidden";
}
function closeChartPop(){ const p = document.getElementById("chartPop"); if (p) p.hidden = true; cpState = null; const pp = document.getElementById("prodPage"); if (pp) pp.style.overflowY = ""; }
document.addEventListener("keydown", e => { if (e.key === "Escape" && cpState) closeChartPop(); });
let ppX = null, ppKeys = [];
function renderProdPage(x){
  if (hiddenItem(x.id)) { showHiddenProduct(); return; }
  const oldRelationHost=document.getElementById("ppRel");
  if(oldRelationHost && typeof BoopaRelationshipDraft!=="undefined") BoopaRelationshipDraft.cancel(oldRelationHost);
  ppX = x;
  const bm = isBm(x.id);
  const keys = x.variations ? Object.keys(x.variations) : [];
  ppKeys = keys;
  document.getElementById("ppBody").innerHTML = `
  <div class="pp-top">
    <div class="pp-viscol"><div class="pp-imgwrap">${x.image ? `<img decoding="async" class="hbg" src="${x.image}" alt="" aria-hidden="true" referrerpolicy="no-referrer"><img decoding="async" class="hfg" src="${x.image}" alt="" referrerpolicy="no-referrer"><span class="pp-imgcount" id="ppImgCount" hidden></span>` : ""}</div><div class="pp-thumbs" id="ppThumbs" hidden></div></div>
    <div style="flex:1;min-width:0">
      <div class="pp-name">${esc(x.name)}</div>
      <div class="pp-shop"${x.shop ? ` data-shop="${esc(x.shop)}"` : ""}>${esc(x.shop || "")}</div>
      <div class="pp-meta" id="ppMeta">${ppMetaHTML(x)}</div>
      <div class="bpchips">${x.cur === 0 ? `<span class="bpchip">${tr("free")}</span>` : ""}${x.sale ? `<span class="bpchip sale">${tr("chip_onsale")}${displayDiscountPercent(x.base, x.cur) > 0 ? ` -${displayDiscountPercent(x.base, x.cur)}%` : ""}</span>` : ""}${x.at_lowest ? `<span class="bpchip">${tr("chip_lowest")}</span>` : ""}</div>
      <div class="pstats" id="ppStats"></div>
      <div class="pp-actions">
        <a class="pp-booth" data-ext href="${itemUrl(x.id)}" target="_blank" rel="noopener">${tr("pp_booth")}</a>
        <button class="pp-bmbtn ${bm ? "on" : ""}" id="ppBmBtn" type="button"><svg viewBox="0 0 24 24"><path d="M17 3H7a2 2 0 0 0-2 2v16l7-4 7 4V5a2 2 0 0 0-2-2z"/></svg>${bm ? tr("pp_bmed") : tr("pp_bm")}</button>
        <button class="pp-recbtn" id="ppRecBtn" type="button"><svg viewBox="0 0 24 24"><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/><path d="M7 10v12"/></svg><span id="ppRecLabel">${tr("pp_rec")}</span><span class="pp-recn" id="ppRecN" hidden></span></button>
        <button class="pp-recbtn" id="ppSimilarBtn" type="button"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.6"/><path d="M21 16l-5-5-7 7"/></svg><span>${tr("img_similar")}</span></button>
      </div>
    </div>
  </div>
  <div id="ppRel"></div>
  <div class="pp-sec">${tr("pp_chart")}</div>
  ${keys.length > 1 ? `<div class="pp-varlabel">${tr("pp_vars", {n: keys.length})}</div><div id="ppCompare"></div>` : ""}
  <div id="ppChart"></div>
  <div class="pp-sec" id="ppSameSec">${tr("pp_same")}<button type="button" class="pp-more" id="ppSameMore" hidden>${tr("rel_more")}</button></div>
  <div class="relrow" id="ppSame"></div>`;
  renderPPBody(x);
  wireBlockHovers(x);
  document.getElementById("ppBmBtn").onclick = () => toggleBm(x);
  const _smb = document.getElementById("ppSameMore"); if (_smb) _smb.onclick = () => { const sec = document.getElementById("ppSameSec"); if (sec && sec.dataset.shop) openSearchShop(sec.dataset.shop); };
  const _sb2 = document.getElementById("ppSimilarBtn"); if (_sb2) _sb2.onclick = () => imgSimilar(x);
  document.getElementById("ppRecBtn").onclick = () => toggleRec(x);
  loadRec(x.id);
  const same = [...PROD.values()].filter(y => y.shop && y.shop === x.shop && String(y.id) !== String(x.id)).slice(0, 24);
  document.getElementById("ppSame").innerHTML = same.map(y => saleCard(y, 0)).join("");
  document.getElementById("ppSameSec").style.display = same.length ? "" : "none";
  document.getElementById("ppSame").style.display = same.length ? "" : "none";
  const _ssx = document.getElementById("ppSameSec"); if (_ssx && x.shop) _ssx.dataset.shop = x.shop; fillSameShop(x, same.length);
  fillGallery(x);
  loadRelations(x);
  fillPPMeta(x);
  prodPage.scrollTop = 0;
}
async function fillGallery(x){
  const box = document.getElementById("ppThumbs");
  if (!box) return;
  let urls = [];
  try {
    const m = await fetchMeta(x.id);
    if (ppX !== x) return;
    urls = (m && Array.isArray(m.images) && m.images) || [];
    // A summary may have no image even after fresh metadata becomes available.
    const primary = x.image || (m && (m.image_resized || m.image)) || urls.find(Boolean);
    const wrap = document.querySelector("#ppBody .pp-imgwrap");
    if (primary && wrap && !wrap.querySelector(".hfg")) {
      x.image = primary;
      for (const cls of ["hbg", "hfg"]) {
        const img = document.createElement("img");
        img.className = cls; img.src = primary; img.alt = "";
        img.decoding = "async"; img.referrerPolicy = "no-referrer";
        if (cls === "hbg") img.setAttribute("aria-hidden", "true");
        wrap.appendChild(img);
      }
      if (!document.getElementById("ppImgCount")) {
        const count = document.createElement("span");
        count.className = "pp-imgcount"; count.id = "ppImgCount"; count.hidden = true;
        wrap.appendChild(count);
      }
    }
  } catch { return; }
  if (ppX !== x) return;
  const main = x.image || "";
  const list = [];
  if (main) list.push(main);
  for (const u of urls) if (u && u !== main) list.push(u);
  if (list.length <= 1) return;
  box.innerHTML = list.map((u, i) => `<button type="button" data-gi="${i}" class="${i === 0 ? "on" : ""}" aria-label="${i + 1}"><img loading="lazy" src="${u}" alt="" referrerpolicy="no-referrer"></button>`).join("");
  box.hidden = false;
  const cnt = document.getElementById("ppImgCount");
  if (cnt) { cnt.hidden = false; cnt.textContent = "1 / " + list.length; }
  box.querySelectorAll("[data-gi]").forEach(b => b.addEventListener("click", () => {
    const u = list[+b.dataset.gi];
    const w = document.querySelector("#ppBody .pp-imgwrap");
    if (!w || !u) return;
    const bg = w.querySelector(".hbg"), fg = w.querySelector(".hfg");
    if (bg) bg.src = u;
    if (fg) fg.src = u;
    box.querySelectorAll("[data-gi]").forEach(o => o.classList.toggle("on", o === b));
    if (cnt) cnt.textContent = (+b.dataset.gi + 1) + " / " + list.length;
  }));
}
const _shopShardCache = {};
function shopShardIdx(sub){
  let h = 5381;
  for (let i = 0; i < sub.length; i++) h = (Math.imul(h, 33) ^ sub.charCodeAt(i)) >>> 0;
  return h % 24;
}
async function ensureShopItems(sub){
  const idx = shopShardIdx(sub);
  if (!_shopShardCache[idx]) {
    try { _shopShardCache[idx] = await fetch("shop_items_" + idx + ".json?v=20251028-1").then(r => r.ok ? r.json() : {}); }
    catch { _shopShardCache[idx] = {}; }
  }
  return _shopShardCache[idx][sub] ? visibleItems(_shopShardCache[idx][sub]) : null;
}
async function fillSameShop(x, initialCount){
  /* Same-shop rail: the sync pass only sees items already loaded into PROD.
     The per-shop shard (full catalog, likes order) fills the rail properly;
     the shop digest merge below stays as the fallback if the shard fails. */
  try {
    const m = await fetchMeta(x.id);
    const sub = m && m.shop && m.shop.subdomain;
    if (!sub) return;
    const dg = await ensureShopDigest();
    const d = dg && dg[sub];
    const shopName = (d && d[0]) || x.shop || "";
    let rows = null;
    try { rows = await ensureShopItems(sub); } catch {}
    if (!curProd || String(curProd.id) !== String(x.id)) return;
    const grid = document.getElementById("ppSame"), sec = document.getElementById("ppSameSec");
    if (!grid || !sec) return;
    if (rows && rows.length) {
      const same = rows.filter(r => String(r[0]) !== String(x.id)).slice(0, 24).map(r => ({
        id: r[0], name: r[1], shop: shopName, image: pxImg(r[2]), cur: r[3], base: r[4],
        pct: r[4] > r[3] ? Math.round((1 - r[3] / r[4]) * 100) : 0, sale: !!r[5], at_lowest: !!r[6]
      }));
      if (same.length) {
        grid.innerHTML = same.map(y => saleCard(y, 0)).join("");
        sec.style.display = ""; grid.style.display = "";
        sec.dataset.shop = shopName;
        const mb = document.getElementById("ppSameMore"); if (mb) mb.hidden = !(((d && d[1]) || rows.length) > same.length + 1);
        fillImgs();
      }
      return;
    }
    if (!d) return;
    const have = new Map();
    [...PROD.values()].filter(y => y.shop && y.shop === x.shop && String(y.id) !== String(x.id)).forEach(y => have.set(String(y.id), y));
    const t = d[2];
    if (!hiddenItem(t[0]) && String(t[0]) !== String(x.id) && !have.has(String(t[0])))
      have.set(String(t[0]), { id: t[0], name: t[1], shop: d[0], image: pxImg(t[2]), cur: t[3], base: t[4], pct: t[4] > t[3] ? Math.round((1 - t[3] / t[4]) * 100) : 0, sale: !!t[5] });
    if (d[3] && !hiddenItem(d[3][0]) && String(d[3][0]) !== String(x.id) && !have.has(String(d[3][0]))) {
      const nid = String(d[3][0]);
      let cur = null, sale = false;
      try {
        const dd = await fetch(DATA_BASE + nid.slice(0, 3) + "/" + nid + ".json").then(r => r.ok ? r.json() : null);
        if (dd && dd.variations) {
          let best = null;
          for (const k in dd.variations) { const s = dd.variations[k]; if (s && s.length && (!best || s.length > best.length)) best = s; }
          if (best) { const last = best[best.length - 1]; cur = last.price; sale = !!last.is_sale; }
        }
      } catch {}
      if (cur != null) {
        const nm = await fetchMeta(nid);
        if (hiddenItem(nid)) return;
        have.set(nid, { id: d[3][0], name: d[3][1], shop: d[0], image: (nm && (nm.image_resized || nm.image)) || "", cur, base: cur, pct: 0, sale });
      }
    }
    if (have.size <= initialCount) return;
    if (!curProd || String(curProd.id) !== String(x.id)) return;
    const same = visibleItems([...have.values()]).slice(0, 24);
    grid.innerHTML = same.map(y => saleCard(y, 0)).join("");
    sec.style.display = ""; grid.style.display = "";
    sec.dataset.shop = d[0];
    const _mb2 = document.getElementById("ppSameMore"); if (_mb2) _mb2.hidden = !(d[1] > same.length + 1);
    fillImgs();
  } catch {}
}
function ppMetaHTML(src){
  const likes = src && typeof src.likes === "number" ? `<span class="pp-likes">${HEART_SVG}<span>${src.likes.toLocaleString()}</span></span>` : "";
  const cat = src && src.category ? `<button type="button" class="pp-tag cat" data-cat="${esc(src.category)}">${esc(catNameL(src.category))}</button>` : "";
  const tags = src && Array.isArray(src.tags) && src.tags.length ? src.tags.map(t => `<button type="button" class="pp-tag" data-tag="${esc(t)}">${esc(t)}</button>`).join("") : "";
  return likes + cat + tags;
}
function bumpCatAff(cat){
  if (!cat) return;
  try {
    const o = store.get("boopadb_cat_aff", {}) || {};
    o[cat] = (o[cat] || 0) + 1;
    let total = 0; for (const k in o) total += o[k];
    if (total > 300) for (const k in o) o[k] = Math.max(1, Math.round(o[k] / 2));
    const ks = Object.keys(o);
    if (ks.length > 40) { ks.sort((a, b) => o[b] - o[a]); for (const k of ks.slice(40)) delete o[k]; }
    store.set("boopadb_cat_aff", o);
  } catch (e) {}
}
function fillPPMeta(x){
  let bumped = false;
  if (x.category) { bumpCatAff(x.category); bumped = true; }
  if (typeof x.likes === "number" && Array.isArray(x.tags) && x.category) return;
  fetchMeta(x.id).then(m => {
    if (!m || ppX !== x) return;
    if (typeof m.likes === "number") x.likes = m.likes;
    if (Array.isArray(m.tags)) x.tags = m.tags;
    if (m.category && m.category.name) { x.category = m.category.name; if (!bumped) bumpCatAff(m.category.name); }
    const el = document.getElementById("ppMeta");
    if (el) el.innerHTML = ppMetaHTML(x);
  }).catch(() => {});
}
// ---- recommend (good) button: one vote per anonymous device id,
// served by the same mini-PC service as the site stats. The count is
// shown only when it is at least 1, so no product ever displays a 0.
const REC_API = "https://nucbox-m7.tailb48431.ts.net";
function recVid(){ try { return localStorage.getItem("boopadb_vid") || null; } catch (e) { return null; } }
function paintRec(st){
  const btn = document.getElementById("ppRecBtn");
  if (!btn || !st) return;
  btn.classList.toggle("on", !!st.mine);
  const label = document.getElementById("ppRecLabel");
  if (label) { label.hidden = st.count > 0; label.textContent = st.mine ? tr("pp_reced") : tr("pp_rec"); }
  const n = document.getElementById("ppRecN");
  if (n) { n.hidden = !(st.count > 0); n.textContent = st.count > 0 ? String(st.count) : ""; }
}
function loadRec(id){
  if (hiddenItem(id)) return;
  const v = recVid();
  if (!v) return;
  fetch(REC_API + "/rec?item=" + encodeURIComponent(id) + "&v=" + encodeURIComponent(v))
    .then(r => r.json())
    .then(st => { if (curProd && String(curProd.id) === String(id)) paintRec(st); })
    .catch(() => {});
}
function shareItem(x){
  if (!visibleItem(x)) return;
  const url = "https://nucbox-m7.tailb48431.ts.net/i/" + x.id;
  if (navigator.share) {
    navigator.share({ title: x.name + " | BoopaDB", url }).catch(() => {});
    return;
  }
  const done = () => {
    const b = document.getElementById("ppShareTop");
    if (!b || b.dataset.done) return;
    b.dataset.done = "1";
    const orig = b.innerHTML;
    b.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>';
    setTimeout(() => { b.innerHTML = orig; delete b.dataset.done; }, 1600);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, done);
  else done();
}
function toggleRec(x){
  if (!visibleItem(x)) return;
  const v = recVid();
  if (!v) return;
  const btn = document.getElementById("ppRecBtn");
  const on = !(btn && btn.classList.contains("on"));
  fetch(REC_API + "/rec", { method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify({ v, item: String(x.id), on }) })
    .then(r => r.json())
    .then(st => { if (curProd && String(curProd.id) === String(x.id)) paintRec(st); shopLoadP = null; loadShopSec(); })
    .catch(() => {});
}
function toggleBm(x){
  if (!visibleItem(x)) return;
  if (isBm(x.id)) BMS = BMS.filter(b => String(b.id) !== String(x.id));
  else BMS = [{id: x.id, name: x.name, shop: x.shop, image: x.image, cur: x.cur}, ...BMS];
  store.set("boopadb_bm", BMS);
  syncBmFlags();
  const btn = document.getElementById("ppBmBtn");
  if (btn && curProd && String(curProd.id) === String(x.id)) {
    const on = isBm(x.id);
    btn.classList.toggle("on", on);
    btn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M17 3H7a2 2 0 0 0-2 2v16l7-4 7 4V5a2 2 0 0 0-2-2z"/></svg>${on ? tr("pp_bmed") : tr("pp_bm")}`;
  }
  lvSyncBookmarkButtons();
  renderPersonal();
  shopLoadP = null; loadShopSec();
}
function openProduct(id){
  if (hiddenItem(id)) { showHiddenProduct(); return; }
  const x = PROD.get(String(id));
  if (!x) return;
  curProd = x;
  renderProdPage(x);
  prodPage.classList.add("open");
  veilSync();
  HIST = [{id: x.id, name: x.name, shop: x.shop, image: x.image, cur: x.cur, at: Date.now()}, ...HIST.filter(h => String(h.id) !== String(x.id))].slice(0, 100);
  store.set("boopadb_hist", HIST);
  renderPersonal();
}
function closeProduct(){
  detailHistoryEpoch++;
  reviewedRelationEpoch++;
  const relationHost=document.getElementById("ppRel");
  if(relationHost && typeof BoopaRelationshipDraft!=="undefined") BoopaRelationshipDraft.cancel(relationHost);
  prodPage.classList.remove("open");
  veilSync();
}
document.getElementById("ppBack").onclick = closeProduct;
document.addEventListener("click", e => {
  if (!e.target.closest) return;
  const sh = e.target.closest("[data-shop]");
  if (sh && sh.dataset.shop) { e.preventDefault(); e.stopPropagation(); openSearchShop(sh.dataset.shop); }
}, true);
const IMG_API = "https://nucbox-m7.tailb48431.ts.net:8443";
function imgClearMode(){
  spImgMode = false; spImgHits = []; spImgState = null; spImgThumb = null; spImgLabel = "";
  const nt = document.getElementById("spImgNote"); if (nt) nt.hidden = true;
}
function imgNoteUpdate(){
  const nt = document.getElementById("spImgNote");
  if (!nt) return;
  if (!spImgMode || spImgState === "ok") { nt.hidden = true; return; }
  nt.hidden = false;
  nt.textContent = spImgState === "loading" ? tr("img_searching")
    : spImgState === "limit" ? tr("img_limit")
    : spImgState === "notindexed" ? tr("img_notindexed")
    : tr("img_error");
  const se = document.getElementById("spEmpty"); if (se) se.style.display = "none";
}
function imgHitsFromApi(results){
  const byId = new Map();
  if (fullIndex) for (const e of fullIndex) byId.set(e[0], e);
  return (results || []).filter(r => !hiddenItem(r.item_id)).map(r => {
    const e = byId.get(String(r.item_id));
    if (e) return {_catalog:true,id: e[0], name: e[1], shop: e[13] || "", image: r.image || e[10] || null, cur: e[3], base: e[4], lowest: e[5], sale: !!e[6], pct: e[4] > e[3] ? Math.round((1 - e[3] / e[4]) * 100) : 0, at_lowest: !!e[7], plain: e[3] === null || e[3] === undefined, _likes: e[9] || 0, likes: e[9] || 0, first_date: isoFD(e[11]), per_day: (e[12] || 0) / 10, _score: r.score};
    return {id: String(r.item_id), name: "BOOTH #" + String(r.item_id), shop: "", image: r.image || null, cur: null, base: null, lowest: null, sale: false, pct: 0, at_lowest: false, plain: true, _likes: 0, likes: 0, first_date: "", per_day: 0, _score: r.score};
  });
}
function imgSetMode(label, thumb){
  spCatMode = null; spRelClear(); spShopMode = null;
  spCatSync();
  spFilter = "all";
  document.getElementById("spChips").querySelectorAll(".chip").forEach(y => y.classList.toggle("on", y.dataset.f === "all"));
  document.getElementById("spQ").value = "";
  spImgMode = true; spImgLabel = label || ""; spImgThumb = thumb || null;
  spImgState = "loading"; spImgHits = [];
  if (!fullIndex) loadFullIndex();
  openSearch();
  spRender(); imgNoteUpdate();
}
// Both hosts use the shared image-result template; bookmark storage stays unchanged.
let lvBookmarkHits = new Map();
function lvCatalogUpdated(){BMS=store.get("boopadb_bm",[]);lvSyncBookmarkButtons();}
function lvResultCard(x){if(hiddenItem(x.id))return "";return imageResultCard(x,isBm(x.id),itemUrl(x.id));}
function lvSyncBookmarkButtons(){
  document.querySelectorAll('#lvResults [data-bookmark]').forEach(button => {
    const saved = isBm(button.dataset.bookmark);
    button.setAttribute("aria-pressed", String(saved));
    button.textContent = tr(saved ? "pp_bmed" : "pp_bm");
  });
}
function lvDecorateResults(hits){
  BMS = store.get("boopadb_bm", []);
  lvBookmarkHits = new Map(hits.map(x => [String(x.id), x]));
  lvSyncBookmarkButtons();
}
document.getElementById("lvResults").addEventListener("click", e => {
  const button = e.target.closest('[data-bookmark]'); if (!button) return;
  e.preventDefault(); e.stopPropagation();
  const id = button.dataset.bookmark, hit = lvBookmarkHits.get(id); if (!hit) return;
  toggleBm(hit._catalog ? hit : (PROD.get(id) || hit));
});
window.addEventListener("storage", e => { if (e.key === "boopadb_bm") { BMS = store.get("boopadb_bm", []); syncBmFlags(); lvSyncBookmarkButtons(); } });
if (typeof initImageLens === "function") initImageLens();
else window.imgSimilar = () => {
  document.getElementById("spImgDropError").hidden = false;
  document.getElementById("spImgDropErrorText").textContent = tr("img_error");
  document.getElementById("spImgDropErrorClose").onclick = () => { document.getElementById("spImgDropError").hidden = true; };
};
// Legacy shared links keep working, but the upload screen is a separate document.
if (location.hash === "#image-search") location.replace("image-search.html" + location.search);
document.getElementById("spImgBtn").addEventListener("click", () => { location.href = "image-search.html"; });

document.addEventListener("click", e => {
  if (!e.target.closest) return;
  const tg = e.target.closest("#ppMeta [data-tag]");
  if (tg) { openSearchTag(tg.dataset.tag); return; }
  const ct = e.target.closest("#ppMeta [data-cat]");
  if (ct) openSearchCat(ct.dataset.cat);
});
document.getElementById("ppShareTop").onclick = () => { if (ppX) shareItem(ppX); };
document.addEventListener("click", e => {
  const a = e.target.closest('a[href*="/items/"]');
  if (!a || a.hasAttribute("data-ext")) return;
  const _lvv = document.getElementById("lensView"); if (_lvv && !_lvv.hidden) lvClose();
  const sl = a.closest(".hslide");
  if (sl && !sl.classList.contains("active")) { e.preventDefault(); heroGo([...track.children].indexOf(sl) - 1); heroPlay(); return; }
  const m = (a.getAttribute("href") || "").match(/items\/(\d+)/);
  if (m) { e.preventDefault(); openItemSmart(m[1]); }
});

// ---- personal strips (history / bookmarks) ----
let _saleIds = null, _saleSrc = null;
function saleIds(){
  const src = LISTS.on_sale || [];
  if (src !== _saleSrc) { _saleSrc = src; _saleIds = new Set(src.map(s => String(s.id))); }
  return _saleIds;
}
function pcardHTML(h){
  if (hiddenItem(h.id)) return "";
  const now = PROD.get(String(h.id));
  const cur = now ? now.cur : h.cur;
  const img = h.image || (now ? now.image : "") || "";
  const drop = cur != null && h.cur != null && cur < h.cur;
  const onSale = !!(now && now.base > cur && (now.on_sale || now.sale || saleIds().has(String(h.id))));
  const pct = onSale ? (now.pct != null ? now.pct : Math.round((1 - cur / now.base) * 100)) : 0;
  const priceHTML = onSale
    ? `<span class="bprice">${discountBadge(now.base, cur, "discst")}<span class="bstack"><span class="was${wCls(now.base)}">${yen(now.base)}</span><span class="price">${cur === 0 ? '<span class="free">' + tr("free") + '</span>' : yen(cur)}</span></span></span>`
    : `<span class="price solo">${cur === 0 ? '<span class="free">' + tr("free") + '</span>' : yen(cur)}</span>`;
  return `<a class="pcard" href="${itemUrl(h.id)}">
    <span class="pimgw">${img ? `<img decoding="async" src="${img}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this,'pph')">` : `<span class="pph" data-fill="${h.id}">${PH_ICON}</span>`}${bmFlag(h.id)}</span>
    <span class="pb"><span class="pn">${esc(h.name)}</span>
    <span class="pp2">${!onSale && drop ? `<span class="vchip">${tr("seen_drop", {v: yen(h.cur - cur)})}</span>` : ""}${priceHTML}</span></span></a>`;
}
function bmCardHTML(h){
  if (hiddenItem(h.id)) return "";
  const now = PROD.get(String(h.id));
  const cur = now ? now.cur : h.cur;
  const img = h.image || (now ? now.image : "") || "";
  const onSale = !!(now && now.base > cur && (now.on_sale || now.sale || saleIds().has(String(h.id))));
  const pct = onSale ? (now.pct != null ? now.pct : Math.round((1 - cur / now.base) * 100)) : 0;
  const priceTxt = cur === 0 ? `<span class="free">${tr("free")}</span>` : (cur == null ? "—" : yen(cur));
  const strip = onSale
    ? `<span class="bmstrip">${pct > 0 ? `${discountBadge(now.base, cur, "discst")}` : `<span class="saletag">${tr("rib_sale")}</span>`}<span class="bmvals"><span class="was${wCls(now.base)}">${yen(now.base)}</span><span class="price${wCls(cur)}">${priceTxt}</span></span></span>`
    : `<span class="bmstrip"><span class="bmvals"><span class="price${wCls(cur)}">${priceTxt}</span></span></span>`;
  return `<a class="bmcard" href="${itemUrl(h.id)}" title="${esc(h.name)}">
    <span class="bmimg">${img ? `<img decoding="async" src="${img}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgPh(this,'pph')">` : `<span class="pph" data-fill="${h.id}">${PH_ICON}</span>`}${bmFlag(h.id)}</span>
    ${strip}<span class="bmname">${esc(h.name)}</span></a>`;
}
function renderPersonal(){
  const visibleBms = visibleItems(BMS), visibleHist = visibleItems(HIST);
  const el = document.getElementById("personal");
  const mods = [];
  if (visibleBms.length) mods.push(`<section class="pmod"><div class="pmod-h"><h2>${tr("pp_bm")}</h2></div><div class="bmpanel"><div class="bmgrid">${visibleBms.slice(0, 4).map(bmCardHTML).join("")}</div></div><div class="pmod-f"><a class="bmmore" href="bookmarks.html">${tr("bm_more")}</a></div></section>`);
  if (visibleHist.length) mods.push(`<section class="pmod"><div class="pmod-h"><h2>${tr("sec_recent")}</h2></div><div class="bmpanel"><div class="bmgrid${visibleHist.length > 4 ? " frozen" : ""}" id="histGrid">${visibleHist.slice(0, 12).map(bmCardHTML).join("")}</div></div>${visibleHist.length > 4 ? `<div class="pmod-f"><a class="bmmore" href="history.html">${tr("bm_more")}</a></div>` : ""}</section>`);
  el.innerHTML = mods.length ? `<div class="pmods">${mods.join("")}</div>` : "";
}
window.addEventListener('boopa:visibility', () => {
  Object.assign(P, filterVisibleLists(P));
  LISTS = filterVisibleLists(LISTS);
  SALE_HOME = visibleItems(SALE_HOME);
  bItems = visibleItems(bItems);
  if (FULL_LISTS) FULL_LISTS = filterVisibleLists(FULL_LISTS);
  if (fullIndex) fullIndex = visibleItems(fullIndex);
  spLandingCache = {key:null,hits:null};
  buildHero(visibleItems(heroItems), true);
  renderSale(); renderBList(); renderUpdates();
  if (curProd && hiddenItem(curProd.id)) showHiddenProduct();
  if (spRelId && hiddenItem(spRelId)) { spRelClear(); closeSearch(); }
  renderPersonal();
  if (spage.classList.contains('open')) spRender(true);
  visibilityPrune();
});
/* deep link from other pages: index.html#item-<id> opens the product view */
const _hm = location.hash.match(/^#item-(\d+)$/);
if (_hm) openItemSmart(_hm[1]);
{ const ap = document.getElementById("appPromo");
  if (ap) {
    const standalone = (window.matchMedia && matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true;
    let dismissed = false; try { dismissed = !!localStorage.getItem("boopadb_apppromo_off"); } catch {}
    if (!standalone && !dismissed) { ap.style.display = "flex"; }
    document.getElementById("appPromoX").onclick = () => { ap.style.display = "none"; try { localStorage.setItem("boopadb_apppromo_off", "1"); } catch {} };
  } }
renderPersonal();
</script>
<!-- stats snippet: keep the three copies in sync (build_prototype.py, build_pages_extra.py, build_sale.py) -->
<style>
.site-stats{padding:16px 12px 6px}
.site-stats .ss-box{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--border,#26262c);border:1px solid var(--border,#26262c);border-radius:10px;overflow:hidden;max-width:1080px;margin:0 auto;text-align:left}
.site-stats .ss-item{background:var(--panel,#151517);padding:13px 16px}
.site-stats .ss-num{display:block;font-family:'Orbitron',sans-serif;font-size:22px;font-weight:700;color:#f2f2f5;line-height:1.3;font-variant-numeric:tabular-nums;white-space:nowrap}
.site-stats .ss-label{display:block;font-size:11px;color:var(--faint,#8b8b94);letter-spacing:.05em;margin-top:2px;white-space:nowrap}
.site-stats .ss-live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#7ee787;margin-right:6px;vertical-align:3px;animation:ssPulse 2s ease-out infinite}
@keyframes ssPulse{0%{box-shadow:0 0 0 0 rgba(126,231,135,.45)}70%{box-shadow:0 0 0 7px rgba(126,231,135,0)}100%{box-shadow:0 0 0 0 rgba(126,231,135,0)}}
@media (prefers-reduced-motion: reduce){.site-stats .ss-live{animation:none}}
html[data-theme="light"] .site-stats .ss-num{color:#17171c}
</style>
<script>
(function () {
  var API = "https://nucbox-m7.tailb48431.ts.net";
  var vid = null;
  try {
    vid = localStorage.getItem("boopadb_vid");
    if (!vid) {
      vid = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : "v" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
      localStorage.setItem("boopadb_vid", vid);
    }
  } catch (e) {}
  function post(path) {
    try {
      var body = JSON.stringify({ v: vid });
      if (navigator.sendBeacon) {
        navigator.sendBeacon(API + path, new Blob([body], { type: "text/plain;charset=UTF-8" }));
      } else {
        fetch(API + path, { method: "POST", body: body, headers: { "Content-Type": "text/plain" }, keepalive: true }).catch(function () {});
      }
    } catch (e) {}
  }
  post("/pv");
  function ping() { if (!document.hidden) post("/ping"); }
  ping();
  setInterval(ping, 25000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) ping(); });
  window.addEventListener("pagehide", function () { post("/ping"); });
  function markInstall() {
    try {
      if (localStorage.getItem("boopadb_installed")) return;
      localStorage.setItem("boopadb_installed", "1");
    } catch (e) {}
    post("/install");
  }
  window.addEventListener("appinstalled", markInstall);
  try {
    if ((window.matchMedia && matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone) markInstall();
  } catch (e) {}
  var L = {
    ja: ["総アクセス", "今日", "現在オンライン", "インストール"],
    en: ["Total views", "Today", "Online now", "Installs"],
    ko: ["총 조회수", "오늘", "현재 접속", "설치"],
    "zh-Hans": ["总访问量", "今日", "当前在线", "安装"],
    "zh-Hant": ["總瀏覽量", "今日", "目前線上", "安裝"]
  };
  var lang = "ja";
  try { lang = localStorage.getItem("boopadb_lang") || navigator.language || "ja"; } catch (e) {}
  if (!L[lang]) {
    if (lang.indexOf("zh") === 0) lang = (lang.indexOf("TW") > -1 || lang.indexOf("HK") > -1 || lang.indexOf("Hant") > -1) ? "zh-Hant" : "zh-Hans";
    else lang = L[lang.slice(0, 2)] ? lang.slice(0, 2) : "ja";
  }
  var lab = L[lang] || L.ja;
  function fmt(n) { return Number(n || 0).toLocaleString("en-US"); }
  function item(i, numHtml) {
    return '<div class="ss-item"><span class="ss-num">' + numHtml + '</span><span class="ss-label">' + lab[i] + '</span></div>';
  }
  function render() {
    fetch(API + "/stats").then(function (r) { return r.json(); }).then(function (s) {
      var el = document.getElementById("siteStats");
      if (!el) {
        el = document.createElement("div");
        el.id = "siteStats";
        el.className = "site-stats";
        var f = document.querySelector("footer");
        if (f) f.appendChild(el); else document.body.appendChild(el);
      }
      el.innerHTML = '<div class="ss-box">'
        + item(0, fmt(s.total_pv))
        + item(1, fmt(s.today_pv))
        + item(2, '<span class="ss-live"></span>' + fmt(s.online))
        + item(3, fmt(s.installs))
        + '</div>';
    }).catch(function () {});
  }
  render();
  setTimeout(render, 3000);
  setInterval(render, 20000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) render(); });
})();
</script>
</body>
</html>
"""

TEMPLATE = TEMPLATE.replace("/*__VISIBILITY__*/", VISIBILITY_JS)

# Index-only instrumentation. Keep out of TEMPLATE because build_item derives
# shared markup from it. Production assembly should call this after derivation.
INDEX_DIAGNOSTICS = r"""<script id="boopadb-diagnostics">
// Opt-in, local-only troubleshooting. No storage, cookies, or telemetry.
(function () {
  if (new URLSearchParams(location.search).get('diagnostics') !== '1') return;
  var errors = [], panel;
  function record(message, line) {
    if (errors.length < 4) errors.push(String(message).slice(0, 180) + (line ? ' @' + line : ''));
    render();
  }
  window.addEventListener('error', function (e) {
    if (e.message) record(e.message, e.lineno);
  });
  window.addEventListener('unhandledrejection', function (e) {
    record(e.reason && e.reason.message || 'Unhandled promise rejection');
  });
  function size(el) {
    if (!el) return 'missing';
    var r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return Math.round(r.width) + 'x' + Math.round(r.height) + ' display=' + s.display + ' opacity=' + s.opacity + ' visibility=' + s.visibility;
  }
  function render() {
    if (!panel) return;
    var lines = ['BoopaDB diagnostics v1 (local only)', navigator.userAgent,
      'viewport=' + innerWidth + 'x' + innerHeight + ' screen=' + screen.width + 'x' + screen.height,
      'document=' + document.readyState + ' online=' + navigator.onLine,
      'SW=' + !!(navigator.serviceWorker && navigator.serviceWorker.controller),
      'errors=' + errors.length];
    errors.forEach(function (e) { lines.push(e); });
    var vv = window.visualViewport;
    if (vv) lines.push('visualViewport=' + Math.round(vv.width) + 'x' + Math.round(vv.height) + ' offset=' + Math.round(vv.offsetLeft) + ',' + Math.round(vv.offsetTop) + ' scale=' + vv.scale);
    ['#searchPage', '#searchPage .sp-inner', '#searchPage .sp-search', '#spQ', '#spImgBtn', '#spClear', '#spImgDrop', '#searchPage .sp-main'].forEach(function (selector) {
      var el = document.querySelector(selector);
      if (!el) return;
      var r = el.getBoundingClientRect(), s = getComputedStyle(el);
      lines.push(selector + ': x=' + Math.round(r.left) + '..' + Math.round(r.right) + ' w=' + Math.round(r.width) + ' client/scroll=' + el.clientWidth + '/' + el.scrollWidth + ' minW=' + s.minWidth + ' box=' + s.boxSizing + ' display=' + s.display);
    });

    ['heroTrack', 'saleTrack', 'featTrack', 'bList', 'bPrev', 'catRail'].forEach(function (id) {
      var el = document.getElementById(id);
      lines.push(id + ': count=' + (el ? el.children.length : '-') + ' ' + size(el));
      if (el && el.firstElementChild) lines.push('  first: ' + size(el.firstElementChild));
    });
    panel.textContent = lines.join('\n');
  }
  document.addEventListener('DOMContentLoaded', function () {
    var box = document.createElement('aside');
    box.style.cssText = 'position:fixed;z-index:2147483647;left:8px;right:8px;top:8px;max-height:65vh;overflow:auto;padding:10px;background:#fff;color:#111;border:2px solid #147;font:12px/1.4 monospace;text-align:left;box-shadow:0 2px 12px #0008';
    var refresh = document.createElement('button'); refresh.textContent = '診断を更新'; refresh.onclick = render;
    var close = document.createElement('button'); close.textContent = '閉じる'; close.onclick = function () { box.remove(); };
    panel = document.createElement('pre'); panel.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 0;font:inherit';
    box.appendChild(refresh); box.appendChild(close); box.appendChild(panel); document.body.appendChild(box);
    render(); setTimeout(render, 2000); setTimeout(render, 10000);
  });
})();
</script>


"""

def add_index_diagnostics(html):
    # Freshness and diagnostics are index-only in the published baseline.
    # Do not change item.html's registration when deriving it from TEMPLATE.
    legacy = '<script>if("serviceWorker" in navigator){navigator.serviceWorker.register("sw.js").catch(function(){})}</script>'
    html = html.replace(legacy, '')
    if 'src="site-update.js?' not in html:
        html = html.replace('</body>', '<script src="site-update.js?v=20261028-search-v4" defer></script>\n</body>', 1)
    if 'id="boopadb-diagnostics"' not in html:
        html = html.replace('<meta charset="UTF-8">', '<meta charset="UTF-8">\n' + INDEX_DIAGNOSTICS, 1)
    return html


if __name__ == "__main__":
    main()
