"""Verify extracted solver identity and immutable historical measurement hashes."""
from pathlib import Path
import hashlib
import json


def main():
    root=Path(__file__).resolve().parents[1]
    origin=json.loads((root/'docs/ORIGIN.json').read_text())
    # Build input location/CLI plumbing may evolve; the measured solver does not.
    for name in ('poc.cc','poc_hooks.hh','run.py'):
        relative='src/dram_fast_forward/'+name
        assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==origin['extracted_sources'][relative]['sha256'],name
    evidence=root/'results/20261023/evidence';summary=json.loads((evidence/'summary_v10.json').read_text())
    assert summary['status']=='pass' and summary['differential_cases']==40
    for relative,expected in summary['artifacts_sha256'].items():
        assert hashlib.sha256((evidence/relative).read_bytes()).hexdigest()==expected,relative
    print('PASS: original solver/driver identity and all 40-case archive hashes')


if __name__=='__main__':main()
