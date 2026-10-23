"""Check the full accepted-stream replay against the actual native capture.

Independent memory instances may be visited in a different host order at the
same cycle. Compare literal per-device event sequences; no timestamps, command
addresses or admission/callback identities are relaxed within a device.
"""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import struct


def records(path):
    opener=gzip.open if path.suffix=='.gz' else open
    fmt=struct.Struct('<12q')
    with opener(path,'rb') as stream:
        while True:
            data=stream.read(fmt.size)
            if not data:break
            yield list(fmt.unpack(data))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('capture','replay','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();source=json.loads((a.capture/'accepted_requests.json').read_text())
    mapping={i:row[3] for i,row in enumerate(source['requests'])}
    original=defaultdict(list);replayed=defaultdict(list)
    for row in records(a.capture/'dram_events.bin'):original[row[1]].append(row)
    for row in records(a.replay/'reference_events.bin.gz'):
        if row[0] in (1,3):row[4]=mapping[row[4]]
        replayed[row[1]].append(row)
    assert set(original)==set(replayed)
    for device in original:
        if original[device]!=replayed[device]:
            mismatch=next((i for i,(x,y) in enumerate(zip(original[device],replayed[device])) if x!=y),min(len(original[device]),len(replayed[device])))
            raise AssertionError(('Native replay mismatch',device,mismatch,original[device][mismatch:mismatch+1],replayed[device][mismatch:mismatch+1]))
    result=dict(status='pass',scope=__doc__,devices=len(original),events=sum(len(x) for x in original.values()),
                checks=['all commands/cycles/addresses','all accepted arrivals/cycles','all callback cycles/IDs'],
                limitation='Host order between independent devices at equal cycles is canonicalized; this remains an open-loop replay.')
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
