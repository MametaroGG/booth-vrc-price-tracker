#!/usr/bin/env python3
"""Read-only remote reconciliation after uncertain publication; NEVER retries push."""
import argparse,json
from pathlib import Path
from publication_journal import reconcile
from publish_snapshot import run_git
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--journal',type=Path,required=True);p.add_argument('--target-repo',type=Path,required=True)
    a=p.parse_args();print(json.dumps(reconcile(a.journal,a.target_repo,run_git),indent=2))
