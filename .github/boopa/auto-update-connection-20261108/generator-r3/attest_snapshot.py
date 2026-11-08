#!/usr/bin/env python3
"""Offline attestation entrypoint; caller must verify actual checkout HEAD first."""
import argparse
import json
from pathlib import Path
from snapshot_contract import attest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tracker-root',required=True);p.add_argument('--tracker-commit',required=True)
    p.add_argument('--inventory',required=True);p.add_argument('--minimum-source-date',required=True)
    p.add_argument('--max-source-age-days',type=int,required=True);p.add_argument('--output',required=True)
    p.add_argument('--fixture',action='store_true',help='Explicit non-production synthetic fixture attestation')
    a=p.parse_args()
    result=attest(a.tracker_root,a.tracker_commit,a.inventory,a.minimum_source_date,max_age_days=a.max_source_age_days,fixture=a.fixture)
    with Path(a.output).open('x') as f: json.dump(result,f,indent=2);f.write('\n')
if __name__=='__main__': main()
