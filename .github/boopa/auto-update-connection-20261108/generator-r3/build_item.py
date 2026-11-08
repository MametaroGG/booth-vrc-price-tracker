#!/usr/bin/env python3
"""Build prod/item.html: the standalone per-product page (item.html?id=<id>).

Derived from the built prod/index.html — same styles, payload and product
view — plus a boot script that opens the requested product immediately.
In-site navigation keeps using the overlay on index.html; this page is the
shareable / externally linkable URL (e.g. from the Boopa extension).

Run AFTER build_prod.py.
"""
import argparse
import re
from pathlib import Path


BOOT = """
<script>
/* item.html boot: open the product named by ?id= as a standalone page */
(function(){
  var id = new URLSearchParams(location.search).get('id');
  if (!id || !/^\\d+$/.test(id)) { location.replace('index.html'); return; }
  document.addEventListener('click', function(e){
    if (e.target.closest && e.target.closest('#ppBack')) {
      e.preventDefault(); e.stopPropagation();
      location.href = 'index.html';
    }
  }, true);
  if (typeof hiddenItem === 'function' && hiddenItem(id)) { showHiddenProduct(); return; }
  var opened = false;
  var mo = new MutationObserver(function(){
    if (document.querySelector('[data-item-unavailable]')) { opened = true; mo.disconnect(); return; }
    var n = document.querySelector('.pp-name');
    if (n && n.textContent) { document.title = n.textContent + ' | BoopaDB'; opened = true; mo.disconnect(); }
  });
  mo.observe(document.body, { childList: true, subtree: true });
  setTimeout(function(){
    if (!opened) {
      mo.disconnect();
      var d = document.createElement('div');
      d.style.cssText = 'position:fixed;inset:0;z-index:90;background:#101012;color:#ececee;display:flex;flex-direction:column;gap:14px;align-items:center;justify-content:center;font-size:15px;padding:24px;text-align:center';
      d.innerHTML = '商品が見つかりませんでした。<br><a href="index.html" style="color:#fc4d50">BoopaDB トップへ</a>';
      document.body.appendChild(d);
    }
  }, 9000);
  var tries = 0;
  var t = setInterval(function(){
    if (typeof openItemSmart === 'function') { clearInterval(t); openItemSmart(id); }
    else if (++tries > 100) clearInterval(t);
  }, 100);
})();
</script>
"""

def build_item(src):
    # These are index-only in the published baseline, even though this page is
    # derived from index. Restore item's original SW registration explicitly.
    src = re.sub(r'<script id="boopadb-diagnostics">.*?</script>\s*', '', src, flags=re.S)
    src = re.sub(r'<script src="site-update\.js(?:\?[^\"]*)?"[^>]*></script>\s*', '', src)
    legacy = '<script>if("serviceWorker" in navigator){navigator.serviceWorker.register("sw.js").catch(function(){})}</script>'
    if legacy not in src:
        src = src.replace('</head>', legacy + '\n</head>', 1)
    html = src.replace(
        "<title>BoopaDB — BOOTHのVRChat向け価格データベース（プロトタイプ）</title>",
        "<title>BoopaDB</title>",
    )
    assert html != src, "title anchor not found"
    assert "</body>" in html
    html = html.replace("</body>", BOOT + "</body>", 1)
    return html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "prod")
    out = parser.parse_args().output_dir
    html = build_item((out / "index.html").read_text(encoding="utf-8"))
    target = out / "item.html"
    target.write_text(html, encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
