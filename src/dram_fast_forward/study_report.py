"""Collect the frozen interference study; never scan unrelated experiment trees."""
import argparse
import hashlib
import json
from pathlib import Path


def load(path):return json.loads(path.read_text())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();profiles={};files={};all_cases=[]
    for profile in ['independent','shared']:
        groups={}
        for tag in ['smoke','full','fuzz','guards']:
            path=a.root/f'{profile}_{tag}_v4/results.json';data=load(path)
            assert data['status']=='pass'
            files[str(path.relative_to(a.root))]=hashlib.sha256(path.read_bytes()).hexdigest()
            groups[tag]=data
            cases=data['cases']
            if tag=='fuzz':
                cases=[load(path.parent/f"seed{x['seed']}_512/results.json") for x in cases]
            for case in cases:
                assert case['status']=='pass' and len(case['audit'])==3
                all_cases.append(dict(profile=profile,group=tag,pattern=case['pattern'],count=case['count'],
                                      binary_sha256=case['binary_sha256'],
                                      exact_comparisons=len(case['audit']),
                                      exit_states=sum(x['exit_state_count'] for x in case['audit'].values())))
        full=groups['full']['cases'][0];variants={}
        reads=211456  # accepted READ requests in the complete frozen actual trace
        for variant,audit in full['audit'].items():
            stats=audit['fast']['bank_symbolic'];hist=dict(stats['lengths']);n=stats['segments']-hist.get(1,0)
            variants[variant]=dict(stats=stats,request_read_coverage=stats['reads_in_segments_ge2']/reads,
                                   mean_segment_ge2=stats['reads_in_segments_ge2']/max(1,n),
                                   exit_states=audit['exit_state_count'])
        profiles[profile]=dict(loop_cpu_s=full['median_cpu_s'],whole_cpu_s=full['median_whole_cpu_s'],
                               loop_speedups=full['loop_speedups'],whole_speedups=full['whole_speedups'],
                               variants=variants,full_raw_trace_sha256=full['audit']['bank_affine']['raw_trace_sha256'])
    assert len(all_cases)==66 and len({x['binary_sha256'] for x in all_cases})==1
    graphs={}
    for profile in ['independent','shared']:
        path=a.root/f'graph_{profile}_full_v1/results.json';data=load(path)
        graphs[profile]=data;files[str(path.relative_to(a.root))]=hashlib.sha256(path.read_bytes()).hexdigest()
    bus_path=a.root/'shared_full_bus_check_v4.json'
    bus=load(bus_path);assert bus['status']=='pass'
    files[str(bus_path.relative_to(a.root))]=hashlib.sha256(bus_path.read_bytes()).hexdigest()
    result=dict(status='pass',root=str(a.root),scope=__doc__,cases=all_cases,
                logical_cases=len(all_cases),exact_plan_reference_comparisons=sum(x['exact_comparisons'] for x in all_cases),
                compared_resource_exit_states=sum(x['exit_states'] for x in all_cases),
                profiles=profiles,oracle_graphs=graphs,shared_bus_check=bus,artifacts_sha256=files)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['status','logical_cases','exact_plan_reference_comparisons','compared_resource_exit_states']}))


if __name__=='__main__':main()
