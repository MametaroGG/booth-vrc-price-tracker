#!/usr/bin/env python3
"""Offline frozen input preparation; inventory and expected commit are mandatory."""
import argparse
from snapshot_contract import prepare

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tracker-root',required=True);p.add_argument('--tracker-commit',required=True)
    p.add_argument('--inventory',required=True);p.add_argument('--attestation',required=True)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--generate-charts',action='store_true');group.add_argument('--charts-file')
    p.add_argument('--output-dir',required=True)
    a=p.parse_args()
    prepare(a.tracker_root,a.inventory,a.attestation,a.output_dir,expected_commit=a.tracker_commit,charts=a.charts_file)
if __name__=='__main__': main()
