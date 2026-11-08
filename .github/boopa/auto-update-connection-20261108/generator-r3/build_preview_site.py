#!/usr/bin/env python3
"""Preserves original build_site.py's embedded two-page preview purpose, offline."""
import argparse
import json
from pathlib import Path
import tempfile
from build_site import rename_new_directory
from build_prod import script_json


def build(payload_file, banner_file, output):
    from build_prototype import TEMPLATE, add_index_diagnostics
    from build_sale import SALE_TEMPLATE
    output=Path(output).absolute()
    if output.exists(): raise FileExistsError(output)
    payload=script_json(json.loads(Path(payload_file).read_text()))
    banner=Path(banner_file).read_text().strip()
    if not banner.startswith('data:image/jpeg;base64,'): raise ValueError('Expected JPEG data URI')
    output.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'-preview-',dir=output.parent))
    html=add_index_diagnostics(TEMPLATE.replace('/*__PAYLOAD__*/',payload)).replace('/*__BANNER__*/',banner)
    css=TEMPLATE.split('<style>',1)[1].split('</style>',1)[0]
    (stage/'index.html').write_text(html,encoding='utf-8')
    (stage/'sale.html').write_text(SALE_TEMPLATE.replace('/*__CSS__*/',css).replace('/*__PAYLOAD__*/',payload),encoding='utf-8')
    rename_new_directory(stage,output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--payload-file',type=Path,required=True);p.add_argument('--banner-file',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args();build(a.payload_file,a.banner_file,a.output_dir)
