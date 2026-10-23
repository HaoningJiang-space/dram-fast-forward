import copy
import itertools
import json
from pathlib import Path
import random
import unittest

from dram_fast_forward.polyhedral import prove_recurrence, resource_projection
from dram_fast_forward.schedule_compile import compile_region

ROOT=Path(__file__).resolve().parents[1]


class ScheduleCompilation(unittest.TestCase):
    def setUp(self):
        self.program=json.loads((ROOT/'configs/read_write_dma_ir.json').read_text())
        self.model=json.loads((ROOT/'results/interference_20261023/evidence/shared_timing.json').read_text())

    def test_parameterized_resource_projection(self):
        a=resource_projection(0,4096,1,16384)
        b=resource_projection(8192*3571,4096,1000000,16384)
        self.assertEqual(a['bank_projection'],b['bank_projection'])
        self.assertTrue(a['bank_period_proved_for_all_R'])

    def test_induction_and_negative_control(self):
        self.assertTrue(all(x['empty'] for x in prove_recurrence(8,8).values()))
        self.assertFalse(prove_recurrence(4,8)['private_recurrence']['empty'])

    def test_nonlocal_and_history_effects_are_rejected(self):
        for field,value in ((4,2),(5,True),(6,1)):
            model=copy.deepcopy(self.model)
            edge=next(x for x in model['constraints'] if x[1]==3)
            edge[field]=value
            with self.assertRaises(ValueError):compile_region(self.program,model)

    def test_model_changes_recompile_effects(self):
        source,proof=compile_region(self.program,self.model)
        model=copy.deepcopy(self.model)
        for edge in model['constraints']:
            if edge[:3]==[0,3,3]:edge[3]=16
        changed,newproof=compile_region(self.program,model)
        self.assertNotEqual(source,changed)
        self.assertEqual(newproof['regions'][0]['shared_self_latency'],16)
        self.assertFalse(proof['oracle_inputs'])

    def test_guards_against_independent_ready_scheduler(self):
        rng=random.Random(712358)
        accepted=0
        for _ in range(5000):
            banks=[rng.randrange(4) for _ in range(rng.randrange(2,20))]
            private=[rng.randrange(-1,40) for _ in range(4)]
            shared=rng.randrange(-1,30);now=rng.randrange(20)
            first=max(now+1,shared,private[banks[0]])
            pos={bank:banks.index(bank) for bank in set(banks)}
            certified=all(max(now+1,shared,private[b])>=first and
                          private[b]<=first+i*8 for b,i in pos.items())
            if not certified:continue
            accepted+=1
            # Independent tick/ready/oldest simulation, not the affine formula.
            ready=private[:];bus=shared;pending=list(enumerate(banks));t=now;actual=[]
            while pending:
                t+=1
                choices=[(i,b) for i,b in pending if max(bus,ready[b])<=t]
                if choices:
                    i,b=min(choices);pending.remove((i,b));actual.append((i,t))
                    bus=t+8;ready[b]=t+8
            self.assertEqual(actual,[(i,first+i*8) for i in range(len(banks))])
        self.assertGreater(accepted,100)


if __name__=='__main__':unittest.main()
