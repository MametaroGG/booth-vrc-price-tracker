#!/usr/bin/env python3
"""Explicit-path self-contained preview builder; never writes production paths by default."""
import argparse
import json
from pathlib import Path


def build(payload_file, output_file, banner_file=None):
    from build_prototype import TEMPLATE, add_index_diagnostics
    from build_prod import script_json
    payload = json.loads(Path(payload_file).read_text(encoding='utf-8'))
    banner = Path(banner_file).read_text(encoding='utf-8').strip() if banner_file else ''
    if banner and not banner.startswith('data:image/jpeg;base64,'):
        raise ValueError('Expected JPEG banner data URI')
    html = add_index_diagnostics(TEMPLATE.replace('/*__PAYLOAD__*/', script_json(payload)))
    html = html.replace('/*__BANNER__*/', banner)
    output_file = Path(output_file)
    if output_file.exists():
        raise FileExistsError(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--payload-file', type=Path, required=True)
    p.add_argument('--output-file', type=Path, required=True)
    p.add_argument('--banner-file', type=Path)
    a = p.parse_args()
    build(a.payload_file, a.output_file, a.banner_file)


if __name__ == '__main__':
    main()
