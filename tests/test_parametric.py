import json
from pathlib import Path
import unittest
from dram_fast_forward.parametric import compile_program, emit_header, SymbolicPath
from dram_fast_forward.polyhedral import ISL
from dram_fast_forward.producer_ir import route


class ParametricCompilation(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]
        self.model=json.loads((root/'results/compiler_20261023/evidence/static_model/timing.json').read_text())
        self.program=dict(bounds=[[0,16]],arrival_gap=1,producers=[
            dict(local_addresses=[0,8192],offset_coefficients=[0]),
            dict(local_addresses=[8192,0],offset_coefficients=[1])])

    def test_nontrivial_paths_partition_all_integer_parameters(self):
        result=compile_program(self.program,self.model,[2],['closed'],max_regions=100)
        self.assertFalse(result['unresolved'])
        self.assertGreater(len(result['regions']),1)
        sequences={tuple((x[0],x[1]) for x in r['commands']) for r in result['regions']}
        self.assertGreater(len(sequences),1)
        self.assertTrue(any(x[1]==1 for r in result['regions'] for x in r['commands']))
        with ISL() as isl:
            guards=['('+' and '.join('('+c+')' for c in r['guard'])+')' for r in result['regions']]
            self.assertTrue(isl.empty('{ [x0] : 0<=x0<=16 and not ('+' or '.join(guards)+') }'))
            for i,left in enumerate(guards):
                for right in guards[i+1:]:self.assertTrue(isl.empty('{ [x0] : '+left+' and '+right+' }'))
        header=emit_header(result)
        self.assertNotIn('schedule_request',header)
        self.assertNotIn('check_ready',header)

    def test_budget_returns_explicit_uncovered_domains(self):
        result=compile_program(self.program,self.model,[2],['closed'],max_regions=1)
        self.assertEqual(len(result['regions']),1)
        self.assertTrue(result['unresolved'])

    def test_unsupported_effect_rejected(self):
        self.model['constraints'].append([0,0,3,2,1,True,-1])
        with self.assertRaises(ValueError):compile_program(self.program,self.model,[2],['closed'])

    def test_original_mapping_is_not_identity(self):
        self.assertEqual(route(34304),(0,512))
        self.assertEqual(route(403456),(0,6144))


if __name__=='__main__':unittest.main()
