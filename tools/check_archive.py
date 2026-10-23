"""Verify extracted solver identity and immutable historical measurement hashes."""
from pathlib import Path
import argparse
import hashlib
import json


def main():
    root=Path(__file__).resolve().parents[1]
    origin=json.loads((root/'docs/ORIGIN.json').read_text())
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-extracted-source',action='store_true',help='Use only on the original extraction baseline, before algorithm changes')
    args=parser.parse_args()
    if args.check_extracted_source:
        for name in ('poc.cc','poc_hooks.hh','run.py'):
            relative='src/dram_fast_forward/'+name
            path=root/relative
            if not path.exists():path=root/'src/dram_fast_forward/native'/name
            assert hashlib.sha256(path.read_bytes()).hexdigest()==origin['extracted_sources'][relative]['sha256'],name
    evidence=root/'results/20261023/evidence';summary=json.loads((evidence/'summary_v10.json').read_text())
    assert summary['status']=='pass' and summary['differential_cases']==40
    for relative,expected in summary['artifacts_sha256'].items():
        assert hashlib.sha256((evidence/relative).read_bytes()).hexdigest()==expected,relative
    current=root/'results/interference_20261023/evidence'
    if current.exists():
        study=json.loads((current/'summary_v4_final.json').read_text())
        assert study['status']=='pass' and study['logical_cases']==66 and study['exact_plan_reference_comparisons']==198
        for relative,expected in study['artifacts_sha256'].items():
            assert hashlib.sha256((current/relative).read_bytes()).hexdigest()==expected,relative
        graph=json.loads((current/'graph_shared_full_ablation_v2/results.json').read_text())['results']
        assert graph['with_policy']['mismatches']==0
        assert graph['bus_omitted_negative_control']['mismatches']>0
        print('PASS: frozen interference matrix, exact policy graph, shared-bus negative control')
    print('PASS: immutable 40-case archive hashes'+('; extracted solver identity' if args.check_extracted_source else ''))


if __name__=='__main__':main()
