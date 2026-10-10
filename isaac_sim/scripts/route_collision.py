"""SIM collision model: source URDF convex collision parts + nominal environment.
Explicit connected-link and grasp contact exclusions. No hardware access.
"""
from pathlib import Path
import struct,xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from scipy.spatial import ConvexHull
HERE=Path(__file__).resolve().parents[1]
ROBOT_ASSETS=HERE/'assets/original_robot'
import fcl,collada
from sim_utils import pose_matrix,matrix_pose

def origin(item):
 t=np.eye(4);o=item.find('origin')
 if o is not None:
  t[:3,3]=np.array(o.get('xyz','0 0 0').split(),float);t[:3,:3]=Rotation.from_euler('xyz',np.array(o.get('rpy','0 0 0').split(),float)).as_matrix()
 return t

def convex(vertices):
 v=np.unique(vertices.reshape(-1,3),axis=0);h=ConvexHull(v);faces=h.simplices.copy()
 for i,face in enumerate(faces):
  if np.dot(np.cross(v[face[1]]-v[face[0]],v[face[2]]-v[face[0]]),h.equations[i,:3])<0:faces[i,[1,2]]=faces[i,[2,1]]
 polys=np.c_[np.full(len(faces),3,dtype=np.int32),faces].reshape(-1)
 return fcl.Convex(v,len(faces),polys),v[h.vertices]

class Scene:
 def __init__(self,model):
  self.model=model;self.urdf=ET.parse(ROBOT_ASSETS/'m0609_rg2.urdf').getroot();self.joints=self.urdf.findall('joint');self.parts=[];self.exclusions=[]
  self.parent={j.find('child').get('link'):j.find('parent').get('link') for j in self.joints}
  # Connected links can intersect at their bearing/joint. Fixed links collapse into one body.
  self.body={l.get('name'):l.get('name') for l in self.urdf.findall('link')}
  for j in self.joints:
   if j.get('type')=='fixed':self.body[j.find('child').get('link')]=self.body[j.find('parent').get('link')]
  self.adjacent={frozenset([self.body[j.find('parent').get('link')],self.body[j.find('child').get('link')]]) for j in self.joints}
  for link in self.urdf.findall('link'):
   for idx,col in enumerate(link.findall('collision')):
    m=col.find('geometry/mesh')
    if m is None:continue
    p=ROBOT_ASSETS/m.get('filename')
    if p.suffix=='.dae':
     cm=collada.Collada(str(p));vertices=[]
     for ob in cm.scene.objects('geometry'):
      for pr in ob.primitives():
       ts=pr.triangleset() if hasattr(pr,'triangleset') else pr;vertices.extend(ts.vertex[ts.vertex_index].reshape(-1,3))
     vertices=np.array(vertices)
    else:
     data=p.read_bytes();n=struct.unpack_from('<I',data,80)[0];vertices=np.array([struct.unpack_from('<9f',data,84+50*i+12) for i in range(n)]).reshape(-1,3)
    vertices*=np.array(m.get('scale','1 1 1').split(),float);o=origin(col);vertices=vertices@o[:3,:3].T+o[:3,3];geometry,v=convex(vertices)
    self.parts.append({'name':link.get('name')+'#'+str(idx),'link':link.get('name'),'geometry':geometry,'v':v,'radius':float(np.linalg.norm(v,axis=1).max())})
  self.self_pairs=[]
  for i,a in enumerate(self.parts):
   for b in self.parts[i+1:]:
    if self.body[a['link']]==self.body[b['link']] or frozenset([self.body[a['link']],self.body[b['link']]]) in self.adjacent:
     self.exclusions.append([a['name'],b['name'],'SAME_OR_DIRECTLY_CONNECTED_BODY']);continue
    if frozenset([a['link'],b['link']]) in [frozenset(['rg2_left_inner_knuckle','rg2_left_inner_finger']),frozenset(['rg2_right_inner_knuckle','rg2_right_inner_finger']),frozenset(['rg2_left_outer_knuckle','rg2_left_inner_knuckle']),frozenset(['rg2_right_outer_knuckle','rg2_right_inner_knuckle'])]:
     self.exclusions.append([a['name'],b['name'],'RG2_PARALLEL_LINKAGE_MECHANICAL_HINGE']);continue
    self.self_pairs.append((a['name'],b['name']))
  self.static={};self.static_vertices={}
  def box(name,c,size,yaw=0):
   t=np.eye(4);t[:3,3]=c;t[:3,:3]=Rotation.from_euler('z',yaw).as_matrix();self.static[name]=fcl.CollisionObject(fcl.Box(*size),fcl.Transform(t[:3,:3],t[:3,3]));self.static_vertices[name]=np.array([[x,y,z] for x in [-size[0]/2,size[0]/2] for y in [-size[1]/2,size[1]/2] for z in [-size[2]/2,size[2]/2]])@t[:3,:3].T+t[:3,3]
  points=np.array(model['supply']['outline_m']);lo=points.min(0);hi=points.max(0)
  box('SupplySurface',[(lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2]-.002],[hi[0]-lo[0],hi[1]-lo[1],.004])
  points=np.array(model['assembly_grid_lines_m']).reshape(-1,3);lo=points.min(0);hi=points.max(0)
  box('AssemblySurface',[(lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2]-.002],[hi[0]-lo[0]+.016,hi[1]-lo[1]+.016,.004])
  for s in model['supply']['slots']:box(s['slot_id'],s['centre_m'],s['size_m'],s['yaw_rad'])
  for i,b in enumerate(model['current_models']):
   box('Current'+str(i),b['centre_m'],b['size_m'],b['yaw_rad'])
   for dx in (-.008,.008):
    for dy in (-.008,.008):
     c=np.array(b['centre_m'])+Rotation.from_euler('z',b['yaw_rad']).apply([dx,dy,.0095+.00225]);box(f'Current{i}_stud_{dx}_{dy}',c,[.01,.01,.0045],b['yaw_rad'])
  self.selected=next(s for s in model['supply']['slots'] if s['selected']);self.held_geom=fcl.Box(*self.selected['size_m'])
  pickup=pose_matrix(self.selected['pickup_tcp_pose']);bt=np.eye(4);bt[:3,3]=self.selected['centre_m'];bt[:3,:3]=Rotation.from_euler('z',self.selected['yaw_rad']).as_matrix();self.attachment=np.linalg.inv(pickup)@bt
  self.tcp=np.eye(4);self.tcp[2,3]=.228
  self.report={'geometry':'Convex hull of each original URDF collision mesh part; exact FCL box/convex proximity. Matches nominal PhysX convex-hull importer policy.', 'excluded_self_pairs':self.exclusions,'additional_exclusions':['Intentional selected-block contact with inner fingers during PICK_TCP/CLOSE_GRIPPER and while held; original supply support contact at lift start allowed only within 0.3mm nominal plane tolerance; connected body hinge geometry; no arm/gripper-vs-other-block contact allowed'], 'nominal_environment':list(self.static),'source_tcp_block_transform_verified':False}

 def frames(self,q,grip):
  poses={'base_link':np.eye(4),'world':np.eye(4)};vals={f'joint_{i+1}':q[i] for i in range(6)};vals['rg2_finger_joint']=grip
  for j in self.joints:
   parent=j.find('parent').get('link');child=j.find('child').get('link');m=np.eye(4)
   if j.get('type')=='revolute':
    mi=j.find('mimic');a=vals[j.get('name')] if mi is None else grip*float(mi.get('multiplier','1'))+float(mi.get('offset','0'));axis=np.array(j.find('axis').get('xyz').split(),float);m[:3,:3]=Rotation.from_rotvec(axis*a).as_matrix()
   poses[child]=poses[parent]@origin(j)@m
  return poses

 def state(self,q,grip,held=False,phase='',poses_override=None,held_transform=None):
  poses=self.frames(q,grip) if poses_override is None else poses_override;objects={};vertices={}
  for p in self.parts:
   t=poses[p['link']];objects[p['name']]=fcl.CollisionObject(p['geometry'],fcl.Transform(t[:3,:3],t[:3,3]));vertices[p['name']]=p['v']@t[:3,:3].T+t[:3,3]
  pairs=self.self_pairs.copy();static=self.static.copy();vstatic=self.static_vertices.copy();chosen=self.selected['slot_id']
  if held:
   static.pop(chosen);vstatic.pop(chosen);t=poses['link_6']@self.tcp@self.attachment if held_transform is None else held_transform;objects['HeldBlock']=fcl.CollisionObject(self.held_geom,fcl.Transform(t[:3,:3],t[:3,3]));half=np.array(self.selected['size_m'])/2;v=np.array([[x,y,z] for x in [-half[0],half[0]] for y in [-half[1],half[1]] for z in [-half[2],half[2]]]);vertices['HeldBlock']=v@t[:3,:3].T+t[:3,3]
   for p in self.parts:
    if p['link'] in ['rg2_left_inner_finger','rg2_right_inner_finger']:continue # intentional held grasp contact
    pairs.append(('HeldBlock',p['name']))
  for name in objects:
   for other in static:
    if name.startswith(('rg2_left_inner_finger#','rg2_right_inner_finger#')) and other==chosen and phase in ['PICK_TCP','CLOSE_GRIPPER']:continue
    if name=='HeldBlock' and other=='SupplySurface' and phase in ['LIFT_HOLDING','LIFT_HOLDING_SAFE','CLOSE_GRIPPER']:
     if vertices[name][:,2].min()>=self.static_vertices[other][:,2].max()-.0003 and vertices[name][:,2].min()<=self.static_vertices[other][:,2].max()+.002:continue # explicit initial board support contact, no deep penetration
    pairs.append((name,other))
  objects.update(static);vertices.update(vstatic);return objects,vertices,pairs

 def check(self,q,grip,held=False,phase='',margin=.002,poses_override=None,held_transform=None):
  objects,vertices,pairs=self.state(q,grip,held,phase,poses_override,held_transform);hits=[];minimum=float('inf');nearest=None
  bounds={n:(v.min(0),v.max(0)) for n,v in vertices.items()}
  for a,b in pairs:
   lo1,hi1=bounds[a];lo2,hi2=bounds[b];sep=np.maximum(0,np.maximum(lo1-hi2,lo2-hi1));lower=float(np.linalg.norm(sep))
   if lower>max(margin,minimum):continue
   distance=float(fcl.distance(objects[a],objects[b],fcl.DistanceRequest(),fcl.DistanceResult()))
   pairmargin=0.0 if a.startswith('rg2_') and b.startswith('rg2_') else margin
   if pairmargin>0 and distance<minimum:minimum=distance;nearest=[a,b]
   if distance<pairmargin:hits.append({'pair':[a,b],'distance_m':distance})
  return {'hits':hits,'min_clearance_m':minimum,'nearest_pair':nearest}
