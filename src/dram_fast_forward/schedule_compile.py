"""Compile guarded FIFO regions from affine DMA and static timing semantics.

The compiler never consumes a command trace. The supported semantic fragment is
one row-preserving final command, a shared serialization resource, and bounded
private resources. Unsupported fragments produce a rejection, not an estimate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import time
from .polyhedral import prove_recurrence


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_region(program: dict, model: dict) -> tuple[str, dict]:
    policy = program['controller']
    if policy['scheduler'] != 'ready_then_oldest_stable':
        raise ValueError('Unsupported scheduling semantics')
    if policy['priorities'] != ['active', 'maintenance', 'selected_read_or_write']:
        raise ValueError('Unsupported queue priority')
    mapper = program['mapper']
    if mapper != dict(line_bytes=256, bank_row_bytes=1024, banks=8):
        raise ValueError('This adapter supports the explicit eight-bank fixture')
    if not model['shared_bus']:
        raise ValueError('A shared resource is required for this proof rule')
    commands = model['commands']
    kernels, proofs, dispatch = [], [], []
    for loop in program['loops']:
        name = {'READ': 'RD', 'WRITE': 'WR'}[loop['operation']]
        cmd = commands.index(name)
        edges = [x for x in model['constraints'] if x[1] == cmd]
        if any(x[4] != 1 or x[5] or x[6] > 0 for x in edges):
            raise ValueError('Region command has unsupported history/sibling timing')
        if any(x[0] not in (0, 3) for x in edges):
            raise ValueError('Unexpected shared/private resource layout')
        shared = max([1] + [x[3] for x in edges if x[0] == 0 and x[2] == cmd])
        private = max([0] + [x[3] for x in edges if x[0] == 3 and x[2] == cmd])
        if shared < private:
            raise ValueError('Shared serialization does not dominate private recurrence')
        induction=prove_recurrence(shared,private)
        if not all(x['empty'] for x in induction.values()):
            raise ValueError('Recurrence proof contains a counterexample')
        patterns = []
        for stride in loop['strides_bytes']:
            if stride < 0 or stride % mapper['line_bytes']:
                raise ValueError('Unsupported DMA stride')
            period_bytes = mapper['bank_row_bytes'] * mapper['banks']
            period = period_bytes // math.gcd(stride, period_bytes)
            word = [((i * stride) // mapper['bank_row_bytes']) % mapper['banks']
                    for i in range(period)]
            patterns.append(dict(stride=stride, period=period, banks=word))
        # The derivation produces one condition per distinct private resource.
        # At the first issue no younger request may already be ready earlier.
        # Thereafter the shared self-edge excludes ALL commands of this family
        # before first+i*delta. Only the oldest candidate's readiness remains.
        guards = [
            dict(kind='first_winner', lhs='max(now+1, shared_ready, private_ready[b])',
                 relation='>=', rhs='first', for_each='present bank b'),
            dict(kind='first_visit_ready', lhs='private_ready[b]', relation='<=',
                 rhs=f'first + first_position[b] * {shared}', for_each='present bank b'),
        ]
        effects = {}
        for level, _, following, latency, *_ in edges:
            key = (level, following)
            effects[key] = max(effects.get(key, 0), latency)
        stores = []
        for level in (0, 3):
            body = [f'if (!node->m_cmd_history[{cmd}].empty()) node->m_cmd_history[{cmd}].front() = last;']
            for (lev, following), latency in sorted(effects.items()):
                if lev == level:
                    body.append(f'node->m_cmd_ready_clk[{following}] = std::max<Clk_t>(node->m_cmd_ready_clk[{following}], last + {latency});')
            stores.append(f'if (node->m_level == {level}) {{\n' + '\n'.join(body) + '\n}')
        # Code emission from the guard/effect IR; there are no request-specific
        # constants or manually supplied per-stream timing formulae.
        tests = []
        for guard in guards:
            if guard['kind'] == 'first_winner':
                tests.append('if (std::max({entry.now + 1, entry.shared_ready, entry.private_ready[b]}) < first) return false;')
            else:
                tests.append(f'if (entry.private_ready[b] > first + positions[b] * {shared}) return false;')
        kernels.append(f'''
inline bool certify_{name}(const Entry& entry, const std::array<long long,8>& positions,
                          int first_bank, long long& first) {{
  first = std::max({{entry.now + 1, entry.shared_ready, entry.private_ready[first_bank]}});
  for (int b=0;b<8;++b) if (positions[b]>=0) {{
    {chr(10).join(tests)}
  }}
  return true;
}}
template<class Node> inline void update_{name}(Node* node, long long last) {{
  {chr(10).join(stores)}
}}
''')
        dispatch.append((cmd, name, shared))
        proofs.append(dict(command=name,command_id=cmd,shared_self_latency=shared,
                           private_self_latency=private,guards=guards,patterns=patterns,induction=induction,
                           recurrence='issue(i) = first + i * shared_self_latency',
                           state_summary='last issue per physical resource; max-plus monotonicity',
                           static_obligations=['command preserves row state (checked by adapter)',
                             'all outgoing timing windows are one and have no sibling effects',
                             'shared self-edge dominates private self-edge'],
                           boundary_obligations=['selected queue remains selected',
                             'no active/maintenance request', 'no unvalidated arrival',
                             'stop at refresh and externally observable callbacks']))
    certify = '\n'.join(f'case {c}: return certify_{n}(entry,positions,first_bank,first);' for c,n,d in dispatch)
    update = '\n'.join(f'case {c}: update_{n}(node,last); return;' for c,n,d in dispatch)
    deltas = '\n'.join(f'case {c}: return {d};' for c,n,d in dispatch)
    strides = sorted(set(x for loop in program['loops'] for x in loop['strides_bytes']))
    words=[]
    for proof in proofs:
        for pattern in proof['patterns']:
            if pattern['banks'] not in words:words.append(pattern['banks'])
    for region in program.get('resource_regions',[]):
        word=region['projection']['word']
        if word not in words:words.append(word)
    word_cpp=','.join('{'+','.join(map(str,w))+'}' for w in words)
    header = '''#pragma once
// GENERATED by schedule_compile.py. Source of truth is the input IR and timing
// semantics; this file contains no reference command order or expected times.
namespace compiled_schedule {
struct Entry { long long now,shared_ready; std::array<long long,8> private_ready; };
''' + '\n'.join(kernels) + f'''
inline constexpr std::array<long long,{len(strides)}> strides = {{{','.join(map(str,strides))}}};
inline const std::vector<std::vector<int>> resource_words = {{{word_cpp}}};
inline long long delta(int command) {{ switch(command) {{ {deltas} default:return 0; }} }}
inline bool certify(int command,const Entry& entry,const std::array<long long,8>& positions,
                    int first_bank,long long& first) {{
  switch(command) {{ {certify} default:return false; }}
}}
template<class Node> inline void update(int command,Node* node,long long last) {{
  switch(command) {{ {update} default:throw std::runtime_error("Unsupported compiled command"); }}
}}
inline constexpr const char* model_constraints = R"MODEL({json.dumps(model['constraints'],separators=(',',':'))})MODEL";
}}
'''
    certificate = dict(version=1, status='compiled', input_kind='affine DMA + static DRAM semantics',
                       policy=policy, regions=proofs, oracle_inputs=[],resource_words=words,
                       resource_source=program.get('source'),projection_cpu_s=program.get('projection_cpu_s',0),
                       scope='Automatic sufficient conditions for homogeneous row-preserving regions; cross-row and mixed-command regions use exact fallback')
    return header, certificate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--program', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    start = time.process_time()
    header, certificate = compile_region(json.loads(a.program.read_text()), json.loads(a.model.read_text()))
    certificate.update(compiler_cpu_s=time.process_time()-start,
                       program_sha256=sha(a.program), model_sha256=sha(a.model),
                       compiler_sha256=sha(Path(__file__)))
    (a.output/'generated_schedule.hh').write_text(header)
    certificate['generated_header_sha256'] = sha(a.output/'generated_schedule.hh')
    (a.output/'certificate.json').write_text(json.dumps(certificate,indent=2)+'\n')
    print(json.dumps(certificate))


if __name__ == '__main__':
    main()
