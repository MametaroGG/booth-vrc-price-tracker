"""Explicitly approved relation bundle copy; legacy withdrawn shards untouched."""
import hashlib
import json
from pathlib import Path
import re
import shutil


def preserve(bundle, approval_file, output):
    bundle=Path(bundle).resolve();output=Path(output)
    raw=Path(approval_file).read_bytes();approval=json.loads(raw)
    if approval.get('schema')!=1 or approval.get('status')!='approved' or not approval.get('version'):
        raise ValueError('Explicit version-bound relation approval required')
    files=approval.get('files')
    required={'relationship-ui-draft.js','relationship-data.js','relation-data/manifest.json'}
    required|={f'relation-data/items_{i}.json' for i in range(64)}
    required|={f'relation-data/children_{i}.json' for i in range(8)}
    if not isinstance(files,dict) or set(files)!=required:
        raise ValueError('Approved relation inventory must contain exactly modules, manifest, 64 item and 8 child shards')
    staged={}
    for name,digest in files.items():
        path=bundle/name
        if any(p.is_symlink() for p in (path,*path.parents)) or bundle not in path.resolve().parents:
            raise ValueError('Unsafe relation source path')
        if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Invalid relation digest')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Relation bundle hash mismatch: '+name)
        if name.endswith('.json'):
            record=json.loads(data)
            if record.get('schema')!='boopadb-relations-v1' or record.get('version')!=approval['version']:
                raise ValueError('Relation bundle schema/version mismatch')
        staged[name]=data
    manifest=json.loads(staged['relation-data/manifest.json'])
    if manifest.get('shards')!=64: raise ValueError('Expected 64 relation item shards')
    for name,data in staged.items():
        target=output/name
        if target.exists():raise FileExistsError('Refusing relation overwrite: '+name)
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    return {'status':'approved-bundle','version':approval['version'],
            'approval_sha256':hashlib.sha256(raw).hexdigest(),'files':files,'legacy_relations':'withdrawn',
            'activate':approval.get('activate') is True, 'scope':approval.get('scope','unspecified')}


def activate_hook(html, provenance):
    """Enable only a fully reviewed exact template hook with explicit activation."""
    if not provenance.get('activate'):return html
    pattern=r'const RELATION_UI_LIVE\s*=\s*false;'
    if len(re.findall(pattern,html))!=1:
        raise ValueError('Expected exactly one disabled reviewed relation UI hook')
    if not all(name in html for name in ('relationship-data.js','relationship-ui-draft.js')):
        raise ValueError('Relation UI hook is missing required module imports')
    for name in ('relationship-data.js','relationship-ui-draft.js'):
        digest = provenance.get('files',{}).get(name,'')
        imports = re.findall(r'<script src="(' + re.escape(name) + r'(?:\?[^"]*)?)"></script>',html)
        if not re.fullmatch('[0-9a-f]{64}',digest) or imports != [name+'?v='+digest[:16]]:
            raise ValueError('Relation UI import content hash does not match approved module: '+name)
    return re.sub(pattern,'const RELATION_UI_LIVE = true;',html,count=1)


def strip_relation_imports(html):
    """Remove only our two known local module tags, optionally content-hash versioned."""
    for name in ('relationship-data.js','relationship-ui-draft.js'):
        pattern = r'<script src="' + re.escape(name) + r'(?:\?v=[0-9a-f]{16,64})?"></script>\n?'
        html = re.sub(pattern,'',html)
    return html
