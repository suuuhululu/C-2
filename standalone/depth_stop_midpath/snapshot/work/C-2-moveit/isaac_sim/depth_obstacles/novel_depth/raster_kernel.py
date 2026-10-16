"""Optional pinned CPU fragment kernel. No compilation/SDK/threads at runtime."""
from pathlib import Path
from hashlib import sha256
import ctypes
import numpy as np

class RasterKernel:
    def __init__(self,path,expected_sha256,*,sim_scope):
        if sim_scope!='EXPLICIT_ISOLATED_SIM_NUMERICAL_TRIAL':
            raise ValueError('EXPLICIT_SIM_NATIVE_RASTER_SCOPE_REQUIRED')
        self.path=Path(path).resolve()
        if sha256(self.path.read_bytes()).hexdigest()!=expected_sha256:
            raise ValueError('NATIVE_RASTER_LIBRARY_SHA_MISMATCH')
        self.library=ctypes.CDLL(str(self.path))
        self.call=self.library.raster_bbox_f64
        array=lambda dtype,ndim:np.ctypeslib.ndpointer(dtype=dtype,ndim=ndim,flags='C_CONTIGUOUS')
        self.call.argtypes=[array(np.float64,3),array(np.float64,2),array(np.int64,2),array(np.int64,2),ctypes.c_int64,ctypes.c_int64,ctypes.c_int64,np.ctypeslib.ndpointer(dtype=np.float64,ndim=1,flags=('C_CONTIGUOUS','WRITEABLE'))]
        self.call.restype=ctypes.c_int
        self.binding=dict(path=str(self.path),sha256=expected_sha256,scope=sim_scope,
            ctypes_loader='CDLL_GIL_RELEASE',arithmetic='FLOAT64_ORIGINAL_ORDER_FMA_DISABLED')

    def raster(self,uv,triangles,low,high,buffer,h,w):
        if triangles.shape!=(len(uv),3,3):
            raise ValueError('NATIVE_RASTER_TRIANGLE_SHAPE_MISMATCH')
        # Original NumPy reciprocal is retained, including its exact f64 bits.
        inverse_z=np.ascontiguousarray(1/triangles[:,:,2])
        uv=np.ascontiguousarray(uv,dtype=np.float64)
        low=np.ascontiguousarray(low,dtype=np.int64);high=np.ascontiguousarray(high,dtype=np.int64)
        if uv.shape!=(len(triangles),3,2) or low.shape!=high.shape or low.shape!=(len(triangles),2):
            raise ValueError('NATIVE_RASTER_ARRAY_SHAPE_MISMATCH')
        if buffer.dtype!=np.float64 or buffer.shape!=(h*w,) or not buffer.flags.c_contiguous or not buffer.flags.writeable:
            raise ValueError('NATIVE_RASTER_BUFFER_REQUIRED')
        code=self.call(uv,inverse_z,low,high,len(triangles),h,w,buffer)
        if code:raise ValueError('NATIVE_RASTER_REJECTED:'+str(code))
