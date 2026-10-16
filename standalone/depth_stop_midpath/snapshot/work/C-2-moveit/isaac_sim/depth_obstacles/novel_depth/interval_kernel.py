"""Pinned explicit CPU-only interval candidate; no build or SDK at runtime."""
from pathlib import Path
from hashlib import sha256
import ctypes
import numpy as np


class IntervalKernel:
    def __init__(self,path,expected_sha256,*,sim_scope):
        if sim_scope!='EXPLICIT_ISOLATED_SIM_NUMERICAL_TRIAL':
            raise ValueError('EXPLICIT_SIM_INTERVAL_SCOPE_REQUIRED')
        self.path=Path(path).resolve()
        if sha256(self.path.read_bytes()).hexdigest()!=expected_sha256:
            raise ValueError('INTERVAL_LIBRARY_SHA_MISMATCH')
        self.library=ctypes.CDLL(str(self.path))
        arr=lambda dtype,ndim:np.ctypeslib.ndpointer(dtype=dtype,ndim=ndim,flags='C_CONTIGUOUS')
        out=lambda dtype:np.ctypeslib.ndpointer(dtype=dtype,ndim=2,flags=('C_CONTIGUOUS','WRITEABLE'))
        i=ctypes.c_int64;d=ctypes.c_double
        self.tail=self.library.interval_tail_f64
        self.tail.argtypes=[arr(np.float64,1),arr(np.float64,1),arr(np.float64,3),arr(np.float64,3),
            arr(np.float64,1),arr(np.float64,2),arr(np.int64,2),arr(np.int64,1),i,i,i,i,i,d,d,
            out(np.float64),out(np.int64),out(np.float64)]
        self.tail.restype=ctypes.c_int
        self.slab=self.library.slab_f64
        self.slab.argtypes=[arr(np.float64,1),arr(np.float64,1),arr(np.float64,3),arr(np.float64,3),i,
            out(np.float64),out(np.float64),out(np.int64),out(np.float64),out(np.float64)]
        self.slab.restype=ctypes.c_int
        self.binding=dict(path=str(self.path),sha256=expected_sha256,scope=sim_scope,
            ctypes_loader='CDLL_GIL_RELEASE',arithmetic='FLOAT64_ORIGINAL_ORDER_FMA_DISABLED',
            scope_of_compilation='SLAB_AND_ELEMENTWISE_INTERVAL_TAIL_ONLY_NUMPY_MATMUL_RETAINED')

    def _inputs(self,size,origin,direction,direction_error):
        values=[np.ascontiguousarray(x) for x in (size,origin,direction,direction_error)]
        s,o,d,e=values
        if (any(x.dtype!=np.float64 for x in values) or s.shape!=(3,) or o.shape!=(3,) or
                d.ndim!=3 or d.shape[-1]!=3 or e.shape!=d.shape):
            raise ValueError('INTERVAL_FLOAT64_INPUT_SHAPE_REQUIRED')
        return s,o,d,e

    def finish(self,size,origin,direction,direction_error,numerator_error,expected_z,owner,rows,
               component,box_index,near,far,nearest,face,bound):
        s,o,d,e=self._inputs(size,origin,direction,direction_error)
        ne=np.ascontiguousarray(numerator_error);z=np.ascontiguousarray(expected_z)
        owner=np.ascontiguousarray(owner);rows=np.ascontiguousarray(rows)
        if (ne.dtype!=np.float64 or ne.shape!=(3,) or z.dtype!=np.float64 or z.shape!=d.shape[:2] or
                owner.dtype!=np.int64 or owner.shape!=z.shape or rows.dtype!=np.int64 or rows.shape!=(len(z),)):
            raise ValueError('INTERVAL_ROW_GRID_REQUIRED')
        if (type(component) is not int or component not in (0,2) or type(box_index) is not int or box_index<0 or
                not np.isfinite([near,far]).all() or not 0<near<far):
            raise ValueError('INTERVAL_ORIGINAL_BOX_DOMAIN_REQUIRED')
        for a,dtype in ((nearest,np.float64),(face,np.int64),(bound,np.float64)):
            if (a.dtype!=dtype or a.ndim!=2 or a.shape!=nearest.shape or a.shape[1]!=z.shape[1] or
                    not a.flags.c_contiguous or not a.flags.writeable):
                raise ValueError('INTERVAL_WRITABLE_OUTPUT_GRID_REQUIRED')
        code=self.tail(s,o,d,e,ne,z,owner,rows,len(z),z.shape[1],nearest.shape[0],component,box_index,
                       near,far,nearest,face,bound)
        if code:raise ValueError('INTERVAL_KERNEL_REJECTED:'+str(code))

    def slab_intersection(self,size,origin,direction,direction_error):
        s,o,d,e=self._inputs(size,origin,direction,direction_error)
        shape=d.shape[:2];z=np.empty(shape);exit=np.empty(shape);axis=np.empty(shape,np.int64)
        den=np.empty(shape);de=np.empty(shape)
        code=self.slab(s,o,d,e,d.shape[0]*d.shape[1],z,exit,axis,den,de)
        if code:raise ValueError('SLAB_KERNEL_REJECTED:'+str(code))
        return z,exit,axis,den,de
