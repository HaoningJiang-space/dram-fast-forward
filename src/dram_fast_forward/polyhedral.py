"""Small ownership-safe binding to the existing system libisl.

Used for exact integer resource projection and proof obligations. No Python
environment or islpy installation is needed. It is an optional compiler input
dependency, never a dependency of the generated simulation kernel.
"""
import ctypes as C
from ctypes.util import find_library


class ISL:
    def __init__(self):
        name = find_library('isl')
        if not name:
            raise RuntimeError('System libisl is required for resource projection')
        self.lib = C.CDLL(name)
        self.c = C.CDLL(None)
        self.c.free.argtypes = [C.c_void_p]
        self.c.free.restype = None
        signatures = {
            'isl_ctx_alloc': (C.c_void_p, []),
            'isl_ctx_free': (None, [C.c_void_p]),
            'isl_version': (C.c_char_p, []),
            'isl_set_read_from_str': (C.c_void_p, [C.c_void_p,C.c_char_p]),
            'isl_set_is_empty': (C.c_int, [C.c_void_p]),
            'isl_set_free': (C.c_void_p, [C.c_void_p]),
            'isl_map_read_from_str': (C.c_void_p, [C.c_void_p,C.c_char_p]),
            'isl_map_is_equal': (C.c_int, [C.c_void_p,C.c_void_p]),
            'isl_map_coalesce': (C.c_void_p, [C.c_void_p]),
            'isl_map_to_str': (C.c_void_p, [C.c_void_p]),
            'isl_map_free': (C.c_void_p, [C.c_void_p]),
        }
        for name,(result,args) in signatures.items():
            fn=getattr(self.lib,name);fn.restype=result;fn.argtypes=args
        self.ctx=self.lib.isl_ctx_alloc()
        if not self.ctx:
            raise RuntimeError('isl context allocation failed')

    def close(self):
        if self.ctx:
            self.lib.isl_ctx_free(self.ctx);self.ctx=None

    def __enter__(self): return self
    def __exit__(self,*args): self.close()

    def _read(self,kind,text):
        ptr=getattr(self.lib,'isl_'+kind+'_read_from_str')(self.ctx,text.encode())
        if not ptr: raise ValueError('Invalid Presburger expression: '+text)
        return ptr

    def empty(self,text):
        p=self._read('set',text)
        try:
            answer=self.lib.isl_set_is_empty(p)
            if answer<0: raise RuntimeError('isl emptiness check failed')
            return bool(answer)
        finally: self.lib.isl_set_free(p)

    def equal(self,left,right):
        a=self._read('map',left);b=self._read('map',right)
        try:
            answer=self.lib.isl_map_is_equal(a,b)
            if answer<0: raise RuntimeError('isl equality check failed')
            return bool(answer)
        finally:
            self.lib.isl_map_free(a);self.lib.isl_map_free(b)

    def canonical(self,text):
        p=self.lib.isl_map_coalesce(self._read('map',text))
        if not p: raise RuntimeError('isl coalesce failed')
        raw=self.lib.isl_map_to_str(p)
        try: return C.string_at(raw).decode()
        finally: self.c.free(raw);self.lib.isl_map_free(p)


def resource_projection(base,width,rows,stride):
    if base%8192 or width%256 or stride%8192:
        raise ValueError('Initial symbolic projection supports aligned full-period row strides')
    lines=width//256
    address=f'8192*B + {stride}*r + 256*l'
    domain=f'R>=1 and B>=0 and 0<=r<R and 0<=l<{lines}'
    joint=f'[R,B] -> {{ [r,l] -> [bank,row] : {domain} and 0<=bank<8 and 8192*row+1024*bank <= {address} < 8192*row+1024*bank+1024 }}'
    bank=f'[R,B] -> {{ [r,l] -> [bank] : {domain} and 0<=bank<8 and exists (row : 8192*row+1024*bank <= {address} < 8192*row+1024*bank+1024) }}'
    expected=f'[R,B] -> {{ [r,l] -> [bank] : {domain} and bank=(floor(l/4)) mod 8 }}'
    with ISL() as isl:
        assert isl.equal(bank,expected),'Resource projection proof failed'
        return dict(backend=isl.lib.isl_version().decode(),joint_relation=isl.canonical(joint),
                    bank_projection=isl.canonical(bank),bank_period_proved_for_all_R=True,
                    parameters=dict(R=rows,B=base//8192),word=[(i//4)%8 for i in range(lines)])


def prove_recurrence(shared,private):
    # Unsatisfiable counterexamples to the induction steps. Integer symbolic
    # variables cover every iteration count and entry clock, not sampled N.
    conditions={
        'first_visit':f'{{ [f,r,p,i] : 0<=p<=i and r<=f+{shared}*p and r>f+{shared}*i }}',
        'private_recurrence':f'{{ [f,j,i] : 0<=j<i and f+{shared}*j+{private}>f+{shared}*i }}',
        'shared_exclusion':f'{{ [f,i,t] : i>=1 and t>=f+{shared}*(i-1)+{shared} and t<f+{shared}*i }}',
    }
    with ISL() as isl:
        return {name:dict(counterexample_set=formula,empty=isl.empty(formula))
                for name,formula in conditions.items()}
