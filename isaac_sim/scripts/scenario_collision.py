"""Configured nominal geometry, with complete 2x2 and 2x3 Current stud grids."""
from route_collision import Scene as OriginalScene,fcl,np,Rotation
class Scene(OriginalScene):
 def __init__(self,model):
  super().__init__(model)
  for name in list(self.static):
   if name.startswith('Current') and '_stud_' in name:self.static.pop(name);self.static_vertices.pop(name)
  for i,b in enumerate(model['current_models']):
   nx,ny=[round(v/.016) for v in b['size_m'][:2]]
   for ix in range(nx):
    for iy in range(ny):
     size=[.01,.01,.0045];rot=Rotation.from_euler('z',b['yaw_rad']).as_matrix();c=np.array(b['centre_m'])+rot@np.array([(ix-(nx-1)/2)*.016,(iy-(ny-1)/2)*.016,.0095+.00225]);n=f'Current{i}_stud_{ix}_{iy}'
     self.static[n]=fcl.CollisionObject(fcl.Box(*size),fcl.Transform(rot,c));v=np.array([[x,y,z] for x in [-.005,.005] for y in [-.005,.005] for z in [-.00225,.00225]])
     self.static_vertices[n]=v@rot.T+c
  self.report['nominal_environment']=list(self.static)

  for i,b in enumerate(model.get('obstacle_models',[])+([model['tray_model']] if 'tray_model' in model else [])):
   size=np.array(b['size_m']);c=np.array(b['centre_m']);rot=Rotation.from_euler('z',b['yaw_rad']).as_matrix();n=b.get('id','HandoverTraySurface')
   self.static[n]=fcl.CollisionObject(fcl.Box(*size),fcl.Transform(rot,c));v=np.array([[x,y,z] for x in [-size[0]/2,size[0]/2] for y in [-size[1]/2,size[1]/2] for z in [-size[2]/2,size[2]/2]])
   self.static_vertices[n]=v@rot.T+c
  self.report['nominal_environment']=list(self.static)

 def state(self,q,grip,held=False,phase='',poses_override=None,held_transform=None):
  # Explicit temporary inner-finger / selected block contact during the mock tray reset.
  # All other robot/environment pairs remain checked. This is not precision release validation.
  if phase=='MOCK_TRAY_RELEASE':phase='CLOSE_GRIPPER'
  return super().state(q,grip,held,phase,poses_override,held_transform)
