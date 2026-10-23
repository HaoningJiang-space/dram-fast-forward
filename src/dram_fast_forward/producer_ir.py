"""Extract finite producer prefixes through the actual frozen CRC endpoint map.

The original 64-core hash is a bit-vector function, not claimed affine. Only
bounded addresses are lowered here. The endpoint-local bank/row mapping is then
identical to the eight-bank shared fixture (the shared bus is a test topology).
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def route(address, shift=9):
    residue=0; value=address>>shift
    for i in range(63,-1,-1):
        residue=(residue<<1)|((value>>i)&1)
        if residue&64: residue^=0x43
    return residue,((address>>(shift+6))<<shift)|(address&((1<<shift)-1))


def extract(tiles, spec, count=4, endpoint=0):
    if spec['hardware']['cores']!=64 or spec['hardware']['domains']!=32 or spec['hardware']['dram_layers']!=2:
        raise ValueError('This extraction fixes D32/C64/L2, eight banks per endpoint')
    if spec.get('bank_color_shift',-1)!=-1 or 'placement_regions' in spec or 'bank_group_regions' in spec:
        raise ValueError('Not the frozen CRC placement')
    shift=spec.get('mapping_stripe_bytes',512).bit_length()-1
    if spec.get('mapping_weight_stripe',512)!=(1<<shift) or spec.get('mapping_data_stripe',512)!=(1<<shift):
        raise ValueError('Mixed stripe policy needs its own mapping contract')
    producers=[]
    with tiles.open('rb') as stream:
        for _ in range(count):
            size=struct.unpack('<I',stream.read(4))[0]; tile=json.loads(stream.read(size))
            base,width,rows,stride=tile['reads'][1]
            pairs=[]
            for r in range(rows):
                for line in range(0,width,256):
                    a=base+r*stride+line; home,local=route(a,shift)
                    if home==endpoint: pairs.append([a,local])
            producers.append(dict(tile=tile['execution']['id'],dma=[base,width,rows,stride],
                                  logical_addresses=[a for a,_ in pairs],local_addresses=[a for _,a in pairs]))
    return dict(source=dict(tiles_sha256=hashlib.sha256(tiles.read_bytes()).hexdigest(),endpoint=endpoint,
                            mapping='CRC6(0x43,address>>9), remove six endpoint bits; bank=local//1024%8,row=local//8192',
                            scope='Actual mapped weight DMA prefixes; externally parameterized arrival times, not full accelerator execution'),
                producers=producers,arrival_gap=1)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('tiles','spec','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--producers',type=int,choices=[2,3,4],default=2)
    p.add_argument('--independent-offsets',action='store_true')
    p.add_argument('--offset-max',type=int,default=128)
    a=p.parse_args(); result=extract(a.tiles,json.loads(a.spec.read_text()))
    # The first and third real tile overlap bank ownership after their first
    # eight requests. This exposes PRE/ACT instead of disjoint-bank-only tests.
    order=[0,2,1,3]; result['producers']=[result['producers'][i] for i in order[:a.producers]]
    dimension=a.producers-1 if a.independent_offsets else 1
    result['bounds']=[[0,a.offset_max] for _ in range(dimension)]
    for i,producer in enumerate(result['producers']):
        producer['offset_coefficients']=[int(i==j+1) for j in range(dimension)] if a.independent_offsets else [i]
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
