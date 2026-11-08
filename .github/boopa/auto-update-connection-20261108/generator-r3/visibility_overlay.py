"""Build-time output overlay; approved static input packages stay byte-identical."""
import hashlib
import json
from pathlib import Path


def replace_one(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Visibility overlay preimage anchor mismatch: ' + old[:70])
    return text.replace(old, new, 1)


def apply_image_visibility(site):
    from build_prototype import VISIBILITY_JS
    from build_prod import script_json
    from visibility_contract import validate_public_visibility
    site = Path(site)
    lists = json.loads((site/'lists_full.json').read_text())
    visibility = lists['visibility']
    validate_public_visibility(visibility)
    html_path = site/'image-search.html'
    html = html_path.read_text()
    injection = '<script>const P=' + script_json({'visibility': visibility, 'stats': {'max_date': lists.get('stats',{}).get('max_date')}}) + ';\n' + VISIBILITY_JS + '\n</script>\n'
    html = replace_one(html, '<script src="image-search-page.js?', injection + '<script src="image-search-page.js?')
    html_path.write_text(html)
    path = site/'image-search-engine.js'; text = path.read_text()
    guard = 'window.BoopaVisibility'
    text = replace_one(text, 'function imageResultCard(x, saved, detailUrl){', 'function imageResultCard(x, saved, detailUrl){\n if('+guard+'.isHidden(x.id))return "";')
    text = replace_one(text, 'return imgHitsFromApi(lvRawResults).map(hit=>{', 'return '+guard+'.filter(imgHitsFromApi(lvRawResults)).map(hit=>{')
    text = replace_one(text, 'async function imageFetchRecord(id){', 'async function imageFetchRecord(id){\n if('+guard+'.isHidden(id))return null;')
    text = replace_one(text, "if(String(data.id)!==id)throw new Error('Unexpected product id');", "if(String(data.id)!==id)throw new Error('Unexpected product id');\n     if(kind==='meta' && !"+guard+".acceptMeta(id,data)){imageResultMetadata.delete(id);"+guard+".prune();lvRefreshCatalog();return null;}\n     if("+guard+".isHidden(id))return null;")
    text = replace_one(text, "[...imageResultMetadata.values()].filter(r=>r.name)", guard+".filter([...imageResultMetadata.values()]).filter(r=>r.name)")
    path.write_text(text)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    # Version new output without changing the frozen original static manifest.
    for page in site.glob('*.html'):
        body = page.read_text()
        body = body.replace('image-search-engine.js?v=20261028-results-v3', 'image-search-engine.js?v='+digest)
        page.write_text(body)
    return {'visibility_stage_engine_sha256': digest}


def derived_static_hashes(visibility, source_date):
    """Reproduce changed static bytes from trusted inputs, never trust source code."""
    import tempfile
    from static_assets import STATIC_HASHES
    here = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='visibility-static-proof-') as d:
        root = Path(d)
        for name in ('image-search.html','image-search-engine.js'):
            raw = (here/'pinned-static'/name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != STATIC_HASHES[name]:
                raise ValueError('Original static pin mismatch: '+name)
            (root/name).write_bytes(raw)
        (root/'lists_full.json').write_text(json.dumps({'visibility': visibility,'stats':{'max_date':source_date}}))
        apply_image_visibility(root)
        return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('image-search.html','image-search-engine.js')}
