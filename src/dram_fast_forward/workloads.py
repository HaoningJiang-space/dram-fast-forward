"""Reproducible synthetic workloads and explicit real-trace windows."""
import random
if __package__:
    from .common import load,sha
else:
    from common import load,sha

def synthetic(label,count,channels=8):
    rng=random.Random(28419);requests=[]
    for i in range(count):
        if label.startswith('A'):
            cycle=1000+(i//64)*700;address=(i%4)*256 if label=='A_affine4' else 0;kind=0
        elif label=='B':cycle=(i//64)*4000;address=(i%2)*channels*1024;kind=0
        elif label=='C':cycle=(i//128)*1000;address=(i%channels)*1024+((i//channels)%4)*256;kind=0
        elif label=='D':
            cycle=(i//128)*1000;address=(rng.randrange(32)*channels+rng.randrange(channels))*1024+rng.randrange(4)*256;kind=int(i%4==0)
        else:raise ValueError(label)
        requests.append([cycle,address,kind,i])
    if label=='A_pressure':
        for row in requests:row[0]=0
    if label=='A_interrupt':requests.append([1250,channels*1024,1,count])
    requests.sort(key=lambda x:x[0])
    followups={}
    if label=='A_closed':
        followups={str(i):[0,(i%channels)*1024,1,count+i] for i in range(min(count,64))}
    # A paid, different-row/read-write suffix tests recovery and final timing.
    start=requests[-1][0]+10000
    for i in range(64):requests.append([start+i*80,(rng.randrange(64)*channels+rng.randrange(channels))*1024, i%2,count*3+1000+i])
    return dict(requests=requests,closed_loop=label=='A_closed',followups=followups,
                allow_symbolic=label.startswith('A'),workload_requests=count)


def real_workload(path,count):
    trace=load(path);source=trace['requests'];requests=[]
    if not source:raise ValueError('Empty actual trace')
    period=source[-1][0]-source[0][0]+1000
    for i in range(count):
        row=source[i%len(source)];cycle=row[0]+(i//len(source))*period
        requests.append([cycle,row[1],row[2],i,row[4]])
    return dict(requests=requests,devices=trace['devices'],allow_symbolic=True,
                workload_requests=count,source_trace=str(path),source_trace_sha256=sha(path),
                source_request_count=len(source),periodic_extension=count>len(source),
                scope='Actual accelerator accepted request stream, open-loop; larger-than-source windows repeat the measured window, with no claim of a longer native workload. No synthetic recovery suffix.')
