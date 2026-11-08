#!/usr/bin/env python3
"""Idempotent presentation-only guard. Run after page generation, before manifest hashing."""
from pathlib import Path
import re,sys
HELPER = '''// DISCOUNT_DISPLAY_GUARD_START
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
'''

def transform(s):
    had_helper = 'DISCOUNT_DISPLAY_GUARD_START' in s
    s = re.sub(r'<script>\n// DISCOUNT_DISPLAY_GUARD_START.*?// DISCOUNT_DISPLAY_GUARD_END\n</script>\n', '', s, flags=re.S)
    lines=s.splitlines(keepends=True);out=[];func='';count=0
    for line in lines:
        m=re.search(r'^function (\w+)\(',line)
        if m:func=m[1]
        def sub(m):
            nonlocal count
            cls,minus,expr=m.groups()
            if expr in ('s.pct','x.pct','x._disc','rec.pct'):
                obj=expr.split('.')[0];pair=f'{obj}.base, {obj}.cur'
            elif expr=='pct':
                if func in ('updCard','rkCluster'):pair='s.base, s.cur'
                elif func=='shopPriceHTML':pair='t.base, t.cur'
                elif func=='clusterCB':pair='base, cur'
                elif func=='clusterDrop':pair='x.from, x.to'
                elif 'now.base' in line:pair='now.base, cur'
                elif 'x.base' in line:pair='x.base, x.cur'
                else:raise ValueError(f'Unknown percent context {func}: {line[:140]}')
            else: return m[0]
            count+=1
            suffix=', "−"' if minus=='−' else ''
            return '${discountBadge('+pair+', "'+cls+'"'+suffix+')}'
        line=re.sub(r'<span class="(discst|disc|udisc|sg)">([-−])\$\{([^}]+)\}%</span>',sub,line)
        line=line.replace('const t = [tr("chip_onsale"), `${x.pct}%OFF`];','const pct = displayDiscountPercent(x.base, x.cur);\n  const t = [tr("chip_onsale"), ...(pct !== null && pct > 0 ? [`${pct}%OFF`] : [])];')
        line=line.replace('${x.pct > 0 ? ` -${x.pct}%` : ""}', '${displayDiscountPercent(x.base, x.cur) > 0 ? ` -${displayDiscountPercent(x.base, x.cur)}%` : ""}')
        line=line.replace('${d < 0 ? "" : "+"}${pc}%', '${displayChangePercent(c.from, c.to)}')
        out.append(line)
    s=''.join(out)
    if count or had_helper:
        # Inline helper avoids an extra request and is inherited by derived templates.
        if '</head>' not in s:raise ValueError('No head boundary')
        s=s.replace('</head>','<script>\n'+HELPER+'</script>\n</head>',1)
    return s

def main(root):
    root=Path(root);changed=[]
    for p in sorted(root.glob('*.html')):
        old=p.read_text();new=transform(old)
        if new!=old:p.write_text(new);changed.append(p.name)
    # Checked-in primary template; the same guard is also run on derived output.
    p=root/'generator-tools/build_prototype.py'
    if p.exists():
        old=p.read_text();new=transform(old)
        if new!=old:p.write_text(new);changed.append(str(p.relative_to(root)))
    print('\n'.join(changed))
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else '.')
