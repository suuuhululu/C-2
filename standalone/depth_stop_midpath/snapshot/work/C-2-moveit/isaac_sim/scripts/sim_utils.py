from pathlib import Path
import json,numpy as np
from scipy.spatial.transform import Rotation
def load(path):return json.loads(Path(path).read_text())
def save(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
def pose_matrix(pose):
 t=np.eye(4);t[:3,3]=pose['xyz_m'];t[:3,:3]=Rotation.from_quat(pose['quaternion_xyzw']).as_matrix();return rigid(t)
def error(a,b):return [float(np.linalg.norm(a[:3,3]-b[:3,3])),float(Rotation.from_matrix(b[:3,:3].T@a[:3,:3]).magnitude())]

def rigid(value):
    value = np.asarray(value, dtype=float)
    if value.shape != (4, 4) or not np.isfinite(value).all():
        raise ValueError('Expected a finite 4x4 rigid transform')
    if not np.allclose(value[3], [0, 0, 0, 1], atol=1e-9):
        raise ValueError('Invalid homogeneous transform row')
    rotation = value[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-9) or not np.isclose(np.linalg.det(rotation), 1, atol=1e-9):
        raise ValueError('Expected a proper rotation, without scale/reflection')
    return value

def matrix_pose(t):
 return {"frame_id":"base_link","xyz_m":t[:3,3].tolist(),"quaternion_xyzw":Rotation.from_matrix(t[:3,:3]).as_quat().tolist()}
