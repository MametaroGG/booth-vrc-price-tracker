#!/usr/bin/env python3
"""Search/card sale badge independent of lowest-price and percentage availability."""
from pathlib import Path
import sys,re
STYLE='<style id="sale-card-labels-style">.card-status-labels{position:absolute;top:0;left:0;display:flex;flex-wrap:wrap;gap:2px;max-width:calc(100% - 32px);z-index:2}.card .thumbwrap .card-status-labels .mlab{position:static;max-width:100%;box-sizing:border-box;white-space:normal;overflow-wrap:anywhere}.card .thumbwrap .card-status-labels .sale-label{background:var(--accent,#d94051);color:#fff}.card .bmflag,.hslide>.bmflag,.pcard .bmflag,.bmcard .bmflag,.rimg .bmflag,.uimg .bmflag{top:0;left:auto;right:0;border-radius:0 0 0 4px}.card>.mlab,.card>.ftag,.card .thumbwrap>.mlab,.rimg>.mlab{max-width:calc(100% - 32px);box-sizing:border-box;white-space:normal;overflow-wrap:anywhere}</style>'

def transform(s):
 match=re.search(r'function saleCard(?:VariantOriginal)?\(s, i\)\{',s)
 start=match.start() if match else -1;end=s.find('\nlet sortMode',start)
 if start<0 or end<0:
  if 'bmflag' not in s:return s
  if 'id="sale-card-labels-style"' in s:return re.sub(r'<style id="sale-card-labels-style">.*?</style>',lambda _:STYLE,s,flags=re.S)
  return s.replace('</head>',STYLE+'\n</head>',1)
 part=s[start:end]
 old='${s.at_lowest ? \'<span class="mlab">\' + tr("chip_lowest") + "</span>" : ""}'
 new='${s.sale !== false || s.at_lowest ? `<span class="card-status-labels">${s.sale !== false ? `<span class="mlab sale-label">${tr("rib_sale")}</span>` : ""}${s.at_lowest ? `<span class="mlab">${tr("chip_lowest")}</span>` : ""}</span>` : ""}'
 part=part.replace(old,new)
 # The price renderer must really emit a numeric percentage; suppressed or zero rates retain Sale.
 numeric='s.sale !== false && s.pct > 0 && displayDiscountPercent(s.base, s.cur, s.id) > 0'
 part=part.replace('s.sale !== false || s.at_lowest ? `<span class="card-status-labels">', 's.sale !== false && !('+numeric+') || s.at_lowest ? `<span class="card-status-labels">')
 part=part.replace('${s.sale !== false ? `<span class="mlab sale-label">','${s.sale !== false && !('+numeric+') ? `<span class="mlab sale-label">')
 part=part.replace('bmFlag(s.id, s.at_lowest ? "u2" : "")','bmFlag(s.id, s.sale !== false || s.at_lowest ? "u2" : "")')
 s=s[:start]+part+s[end:]
 # Hero ribbons follow their own price-rendering condition, not the catalog flag alone.
 hero='<span class="rib ${x._rib[0]}">${x._rib[1]}</span>'
 replacement='${x._rib[0] === "sale" && x._disc > 0 && displayDiscountPercent(x.base, x.cur, x.id) > 0 ? "" : `<span class="rib ${x._rib[0]}">${x._rib[1]}</span>`}'
 if replacement not in s:s=s.replace(hero,replacement)
 if 'id="sale-card-labels-style"' in s:s=re.sub(r'<style id="sale-card-labels-style">.*?</style>',lambda _:STYLE,s,flags=re.S)
 else:s=s.replace('</head>',STYLE+'\n</head>',1)
 return s
def main(root):
 for p in Path(root).glob('*.html'):
  old=p.read_text();new=transform(old)
  if new!=old:p.write_text(new)
if __name__=='__main__':main(sys.argv[1])
