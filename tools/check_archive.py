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
    compiler=root/'results/compiler_20261023/evidence'
    if compiler.exists():
        manifest=json.loads((compiler/'evidence_manifest.json').read_text())
        for relative,expected in manifest.items():
            assert hashlib.sha256((compiler/relative).read_bytes()).hexdigest()==expected,relative
        summary=json.loads((compiler/'summary_v5.json').read_text())
        assert summary['status']=='pass' and summary['cases']==39 and summary['comparisons']==117
        certificate=json.loads((compiler/'generated_v2/certificate.json').read_text())
        assert certificate['oracle_inputs']==[]
        for region in certificate['regions']:
            assert all(x['empty'] for x in region['induction'].values())
        print('PASS: frozen compiler evidence, 117 differential comparisons and conditional proof certificates')
    parametric=root/'results/parametric_20261023/evidence'
    if parametric.exists():
        manifest=json.loads((parametric/'manifest.json').read_text())
        for relative,expected in manifest.items():
            assert hashlib.sha256((parametric/relative).read_bytes()).hexdigest()==expected,relative
        summary=json.loads((parametric/'summary.json').read_text())
        assert (summary['cases'],summary['compiled'],summary['fallback'])==(474,283,191)
        for name in ('two','three','four'):
            result=json.loads((parametric/f'measurements/{name}.json').read_text())
            assert result['status']=='pass'
            for row in result['comparisons']:
                if row['fast']['parametric']['admitted']:assert row['fast']['preq_scans']==0
        print('PASS: parametric evidence; 474 exact comparisons, 283 compiled and 191 fallback')
    print('PASS: immutable 40-case archive hashes'+('; extracted solver identity' if args.check_extracted_source else ''))


if __name__=='__main__':main()
