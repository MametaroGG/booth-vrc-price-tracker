"""Durable own-file publication receipts; never delete or overwrite other journals."""
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone


ALLOWED_ORIGINS = ('https://github.com/MametaroGG/boopadb.git','https://github.com/MametaroGG/boopadb','git@github.com:MametaroGG/boopadb.git')


def save(path, receipt, create=False):
    path=Path(path)
    receipt['updated_at']=datetime.now(timezone.utc).isoformat()
    data=(json.dumps(receipt,indent=2)+'\n').encode()
    path.parent.mkdir(parents=True,exist_ok=True)
    if create:
        with path.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    else:
        if not path.is_file() or path.is_symlink():raise ValueError('Existing owned journal required')
        fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def reconcile(path, repo, run_git):
    path=Path(path);receipt=json.loads(path.read_text())
    if receipt.get('schema')!=1 or not receipt.get('expected_parent_commit'):
        raise ValueError('Invalid publication journal')
    if receipt.get('repository')!='MametaroGG/boopadb' or receipt.get('branch')!='main':
        raise ValueError('Journal repository/branch is not authorized')
    origin=run_git(repo,'remote','get-url','origin')
    if origin not in ALLOWED_ORIGINS:
        raise ValueError('Reconciliation origin differs from authorized journal repository')
    # Read-only remote observation; this function NEVER pushes or retries.
    try:
        actual=run_git(repo,'ls-remote','--exit-code','origin','refs/heads/main').split()[0]
    except Exception as exc:
        receipt.update(status='reconciliation-uncertain',error=str(exc));save(path,receipt);raise
    receipt['observed_remote_head']=actual
    if receipt.get('commit') and actual==receipt['commit']:
        receipt['status']='remote-commit-verified'
    elif actual==receipt['expected_parent_commit']:
        receipt['status']='expected-parent-still-current'
    else:receipt['status']='remote-conflict'
    save(path,receipt)
    return receipt
