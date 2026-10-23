"""Independent trace check for command/data bus, turnarounds and rank windows."""
import argparse
from collections import defaultdict,Counter
import gzip
import hashlib
import json
from pathlib import Path
import struct


def check(events,timing):
    if not timing['shared_bus']:raise ValueError('Requires explicit shared-bus profile')
    incoming=defaultdict(list)
    for level,previous,following,delay,window,sibling,offset in timing['constraints']:
        if level==0:
            assert not sibling and offset<=0
            incoming[following].append((previous,delay,window))
    history=defaultdict(list);serial={};data_end={};last_data={};counts=Counter();fmt=struct.Struct('<12q')
    opener=gzip.open if events.suffix=='.gz' else open
    with opener(events,'rb') as stream:
        while raw:=stream.read(fmt.size):
            row=fmt.unpack(raw)
            if row[0]!=2:continue
            _,device,channel,cycle,command,*_=row;key=(device,channel)
            assert cycle>serial.get(key,-1),('command bus collision',key,cycle)
            serial[key]=cycle;counts['commands']+=1
            for previous,delay,window in incoming[command]:
                old=history[key,previous]
                if len(old)>=window:
                    assert cycle>=old[-window]+delay,('rank/bus timing violation',key,command,cycle,previous,window,old[-window],delay)
                    counts['window4_checks' if window==4 else 'window1_checks']+=1
            history[key,command].append(cycle)
            if command in (3,4):
                start=cycle+(timing['nCL'] if command==3 else timing['nCWL'])
                assert start>=data_end.get(key,-1),('overlapping data bursts',key,start,data_end.get(key))
                data_end[key]=start+timing['nBL'];counts['data_commands']+=1
                if key in last_data:
                    previous_command,previous_bank=last_data[key]
                    if previous_command!=command:counts['read_write_turnarounds']+=1
                    if previous_bank!=row[8]:counts['cross_bank_data_transitions']+=1
                last_data[key]=(command,row[8])
            if command==7:counts['refreshes']+=1
    return dict(status='pass',checks=dict(counts),scope=__doc__)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['events','timing','output']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();result=check(a.events,json.loads(a.timing.read_text()))
    result['events_file']=str(a.events);result['events_file_sha256']=hashlib.sha256(a.events.read_bytes()).hexdigest()
    result['timing_file_sha256']=hashlib.sha256(a.timing.read_bytes()).hexdigest()
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
