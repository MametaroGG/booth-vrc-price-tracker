"""Preserve an approved complete-child-search bundle separately from capped previews."""
import hashlib
import json
from pathlib import Path
import re

REQUIRED={'relationship-search.js','relation-search/manifest.json'}|{f'relation-search/children_{i}.json' for i in range(8)}
SCHEMA='boopadb-children-search-v1'

def sha(data):return hashlib.sha256(data).hexdigest()

def valid_id(value):return isinstance(value,str) and re.fullmatch('[1-9][0-9]{0,15}',value) is not None

def validate(root, approval, relation_status):
    root=Path(root)
    if not isinstance(approval,dict) or approval.get('schema')!=1 or approval.get('status') not in ('approved','approved-bundle') or approval.get('activate') is not True:
        raise ValueError('Explicit activated complete-search approval required')
    if not isinstance(relation_status,dict) or not relation_status.get('activate') or relation_status.get('status')!='approved-bundle':
        raise ValueError('Complete search requires approved active relationship bundle')
    if not re.fullmatch('[0-9a-f]{64}',approval.get('version','')) or approval.get('sourceVersion')!=relation_status.get('version'):
        raise ValueError('Complete-search approval source version mismatch')
    files=approval.get('files')
    if not isinstance(files,dict) or set(files)!=REQUIRED:raise ValueError('Complete-search inventory must have exactly10 files')
    for name,expected in files.items():
        p=root/name
        if p.is_symlink() or root.resolve() not in p.resolve().parents or not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected) or sha(p.read_bytes())!=expected:
            raise ValueError('Complete-search file integrity failure: '+name)
    m=json.loads((root/'relation-search/manifest.json').read_text());source=json.loads((root/'relation-data/manifest.json').read_text())
    if m.get('schema')!=SCHEMA or m.get('version')!=approval['version'] or m.get('sourceVersion')!=relation_status['version'] or m.get('shards')!=8 or m.get('complete') is not True:
        raise ValueError('Complete-search manifest schema/version/completeness mismatch')
    if source.get('version')!=m['sourceVersion'] or m.get('masterSha256')!=source.get('sourceSha256',{}).get('verdicts_corrected.json'):
        raise ValueError('Complete search is not bound to approved master/source bundle')
    expected={}
    for i in range(64):
        name=f'relation-data/items_{i}.json';data=(root/name).read_bytes()
        if sha(data)!=relation_status.get('files',{}).get(name):raise ValueError('Approved outgoing shard changed')
        shard=json.loads(data)
        for child,entry in shard['items'].items():
            if not valid_id(child) or not isinstance(entry,dict) or not isinstance(entry.get('parents'),list):raise ValueError('Invalid approved outgoing relationship row')
            for parent in entry['parents']:
                if not valid_id(parent) or parent==child:raise ValueError('Invalid approved parent ID')
                expected.setdefault(parent,set()).add(child)
    seen={};shard_entries=m.get('files')
    if not isinstance(shard_entries,dict) or set(shard_entries)!={f'children_{i}.json' for i in range(8)}:raise ValueError('Complete-search internal inventory mismatch')
    for i in range(8):
        name=f'children_{i}.json';data=(root/'relation-search'/name).read_bytes();record=shard_entries[name]
        if record.get('sha256')!=sha(data) or record.get('bytes')!=len(data):raise ValueError('Complete-search internal shard digest/size mismatch')
        shard=json.loads(data)
        if shard.get('schema')!=SCHEMA or shard.get('version')!=m['version'] or shard.get('sourceVersion')!=m['sourceVersion'] or not isinstance(shard.get('items'),dict):raise ValueError('Complete-search shard generation mismatch')
        for parent,value in shard['items'].items():
            if not valid_id(parent) or int(parent)%8!=i or parent in seen or not isinstance(value,list) or len(value)!=2 or type(value[0]) is not int or not isinstance(value[1],list):raise ValueError('Invalid complete-search parent row')
            count,children=value
            if count!=len(children) or count!=len(set(children)) or not all(valid_id(c) and c!=parent for c in children):raise ValueError('Truncated/duplicate complete child scope')
            seen[parent]=set(children)
    if seen!=expected or m.get('parents')!=len(expected) or m.get('edges')!=sum(map(len,expected.values())):
        raise ValueError('Complete search differs from exact approved outgoing inverse')
    return m


def strip_import(html):
    return re.sub(r'<script src="relationship-search\.js(?:\?v=[0-9a-f]{16,64})?"></script>\n?','',html)


def configure(candidate, bundle, approval_file, relation_status):
    candidate=Path(candidate);index=candidate/'index.html';html=index.read_text()
    if bool(bundle)!=bool(approval_file):raise ValueError('Complete-search bundle and approval must be supplied together')
    if not bundle:
        if isinstance(relation_status,dict) and relation_status.get('activate') and 'const completeRelationSearch' in html:
            raise ValueError('Active new relationship UI requires approved complete-child-search bundle')
        index.write_text(strip_import(html));return 'disabled'
    raw=Path(approval_file).read_bytes();approval=json.loads(raw)
    if not isinstance(approval.get('files'),dict) or set(approval['files'])!=REQUIRED:raise ValueError('Complete-search approval inventory mismatch')
    for name,expected in approval['files'].items():
        source=Path(bundle)/name
        if source.is_symlink() or Path(bundle).resolve() not in source.resolve().parents:raise ValueError('Unsafe complete-search bundle path')
        data=source.read_bytes()
        if sha(data)!=expected:raise ValueError('Complete-search bundle hash mismatch: '+name)
        target=candidate/name
        if target.exists():raise FileExistsError('Refusing complete-search overwrite: '+name)
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    validate(candidate,approval,relation_status)
    expected_tag=f'<script src="relationship-search.js?v={approval["files"]["relationship-search.js"][:16]}"></script>'
    if html.count(expected_tag)!=1:raise ValueError('Complete-search module import does not match approved content hash')
    return {'schema':1,'status':'approved-bundle','activate':True,'version':approval['version'],
            'sourceVersion':approval['sourceVersion'],'files':approval['files'],
            'approval_sha256':sha(raw),'scope':approval.get('scope','unspecified')}
