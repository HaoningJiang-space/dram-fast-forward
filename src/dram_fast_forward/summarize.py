"""Collect completed PoC evidence without reading or scanning large traces."""
import argparse
import hashlib
import json
from pathlib import Path


GROUPS=('strict_v10_10k','strict_v10_100k','strict_v10_1m','strict_v10_real_window')


def markdown(result):
    lines=['# 全部实测结果','',
           '以下为三次新进程 CPU 中位数；所有比值均相对于同 case 的 reference。小于 1 表示变慢。',
           '命令、接纳/回压、回调和退出状态的逐字节差分全部通过。',
           'E 的 1万/10万是实际窗口前缀，224,896 为完整窗口，100万是周期扩展。',
           'B/C/D 的 symbolic 关闭批量，约 1× 的差异属于精确回退和计时波动。','',
           '| Case | 请求规模 | event 循环加速 | incremental 循环加速 | symbolic 循环加速 | symbolic 整进程加速 | 安全READ覆盖 | 平均段长 |',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in result['cases']:
        speed=row['cpu_speedups'];whole=row['whole_process_cpu_speedups']
        lines.append(f"| {row['pattern']} | {row['count']:,} | {speed['event']:.3f}× | {speed['incremental']:.3f}× | {speed['symbolic']:.3f}× | {whole['symbolic']:.3f}× | {100*row['safe_read_coverage']:.3f}% | {row['average_segment_length']:.2f} |")
    lines.extend(['',f"主矩阵 20 case，另有 {result['fuzz_seeds']} 个随机种子，共 {result['differential_cases']} 个差分 case。",
                  f"主矩阵比较了 {result['literal_symbolic_exit_states']:,} 次实际 fast-exit 的完整状态；随机测试额外执行 {result['fuzz_bulk_reads']:,} 次批量 READ。",'',
                  '规模列不含 synthetic 的64项付费恢复 suffix，也不含闭环新增请求；实际 accepted 数在 summary.json。',
                  '完整 per-mode CPU/wall 样本、range、原始trace SHA 和 reference档案身份见 evidence 中的 results.json。',''])
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--markdown',type=Path)
    a=p.parse_args();rows=[];artifacts={}
    for group in GROUPS:
        path=a.root/group/'results.json';result=json.loads(path.read_text())
        if result['status']!='pass':raise ValueError(('Incomplete experiment',group))
        artifacts[str(path.relative_to(a.root))]=hashlib.sha256(path.read_bytes()).hexdigest()
        for item in result['cases']:
            if item['status']!='pass':raise ValueError('Failed case')
            keep=('pattern','count','status','binary_sha256','config_sha256','median_cpu_s',
                  'cpu_speedups','median_whole_process_cpu_s','whole_process_cpu_speedups',
                  'safe_read_coverage','average_segment_length','raw_trace_sha256')
            row={k:item[k] for k in keep};row['group']=group
            row['reference_end_cycle']=item['audit']['reference']['end_cycle']
            row['commands']=item['audit']['reference']['commands']
            row['accepted']=item['audit']['reference']['accepted']
            row['rejected_attempts']=item['audit']['reference']['rejected_attempts']
            row['symbolic_segments']=item['audit']['symbolic']['bulk_segments']
            row['literal_exit_states']=item['audit']['symbolic']['bulk_segments']
            row['median_scope']='Three fresh-process runs per mode, alternating order, audit off'
            row['loop_cpu_range_s']={mode:[min(x['host_cpu_seconds'] for x in samples),max(x['host_cpu_seconds'] for x in samples)]
                                     for mode,samples in item['benchmark'].items()}
            row['audit_invariants']=item['exact']
            row['validation_reference']=item.get('reused_validation_reference')
            rows.append(row)
    if len(rows)!=20 or len({row['binary_sha256'] for row in rows})!=1 or len({row['config_sha256'] for row in rows})!=1:
        raise ValueError('Incomplete or mixed final experiment matrix')
    fuzz_path=a.root/'fuzz_v10/results.json';fuzz=json.loads(fuzz_path.read_text())
    if fuzz['status']!='pass' or len(fuzz['cases'])!=20:raise ValueError('Incomplete fuzz')
    artifacts[str(fuzz_path.relative_to(a.root))]=hashlib.sha256(fuzz_path.read_bytes()).hexdigest()
    result=dict(status='pass',scope=__doc__,root=str(a.root),cases=rows,
                differential_cases=len(rows)+len(fuzz['cases']),
                literal_symbolic_exit_states=sum(x['literal_exit_states'] for x in rows),
                fuzz_seeds=len(fuzz['cases']),fuzz_bulk_reads=sum(x['bulk_reads'] for x in fuzz['cases']),
                artifacts_sha256=artifacts)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    if a.markdown:a.markdown.write_text(markdown(result))
    print(json.dumps(dict(status=result['status'],cases=len(rows),fuzz_seeds=result['fuzz_seeds'],
                          literal_exit_states=result['literal_symbolic_exit_states'])))


if __name__=='__main__':main()
