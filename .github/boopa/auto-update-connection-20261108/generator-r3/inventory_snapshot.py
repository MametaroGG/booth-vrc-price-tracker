#!/usr/bin/env python3
"""Offline inventory writer: every regular data/meta file, exact deterministic bytes."""
import argparse
from pathlib import Path
from snapshot_contract import snapshot, inventory_bytes

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tracker-root',required=True);p.add_argument('--output',required=True)
    a=p.parse_args()
    raw=inventory_bytes(snapshot(a.tracker_root))
    with Path(a.output).open('xb') as f: f.write(raw)
if __name__=='__main__': main()
