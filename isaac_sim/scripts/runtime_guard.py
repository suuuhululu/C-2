"""Independent FCL checks using actual USD rigid-body and held-block poses."""
import numpy as np
from scipy.spatial.transform import Rotation
from route_collision import fcl
from scenario_collision import Scene as BaseScene

class Scene(BaseScene):
    def __init__(self,model):
        super().__init__(model)
        centre=np.array([.417561,-.184622,-.002]);size=np.array([.18,.14,.004])
        self.static['HandoverTray']=fcl.CollisionObject(fcl.Box(*size),fcl.Transform(np.eye(3),centre))
        self.static_vertices['HandoverTray']=np.array([[x,y,z] for x in [-size[0]/2,size[0]/2] for y in [-size[1]/2,size[1]/2] for z in [-size[2]/2,size[2]/2]])+centre
        self.supply_studs={}
        for slot in model['supply']['slots']:
            size=slot['size_m'];nx,ny=[round(x/.016) for x in size[:2]]
            rot=Rotation.from_euler('z',slot['yaw_rad']).as_matrix()
            for x in range(nx):
                for y in range(ny):
                    offset=np.array([(x-(nx-1)/2)*.016,(y-(ny-1)/2)*.016,.01175])
                    name=slot['slot_id']+f'_stud_{x}_{y}'
                    self.supply_studs[name]=(slot['slot_id'],offset)
                    self.static[name]=fcl.CollisionObject(fcl.Box(.01,.01,.0045),fcl.Transform(rot,np.array(slot['centre_m'])+rot@offset))
                    v=np.array([[i,j,k] for i in (-.005,.005) for j in (-.005,.005) for k in (-.00225,.00225)])
                    self.static_vertices[name]=v@rot.T+np.array(slot['centre_m'])+rot@offset
        self.slot_id=self.selected['slot_id']
        for obj in model.get('extra_models',[]):
            size=np.array(obj['size_m']);t=np.eye(4);t[:3,:3]=Rotation.from_euler('z',obj['yaw_rad']).as_matrix();t[:3,3]=obj['centre_m'];name=obj['id']
            self.static[name]=fcl.CollisionObject(fcl.Box(*size),fcl.Transform(t[:3,:3],t[:3,3]));v=np.array([[x,y,z] for x in [-size[0]/2,size[0]/2] for y in [-size[1]/2,size[1]/2] for z in [-size[2]/2,size[2]/2]])
            self.static_vertices[name]=v@t[:3,:3].T+t[:3,3]
            if obj.get('studs',True):
                nx,ny=[round(x/.016) for x in size[:2]]
                for ix in range(nx):
                    for iy in range(ny):
                        offset=np.array([(ix-(nx-1)/2)*.016,(iy-(ny-1)/2)*.016,.01175]);key=name+f'_stud_{ix}_{iy}';centre=t[:3,3]+t[:3,:3]@offset
                        self.static[key]=fcl.CollisionObject(fcl.Box(.01,.01,.0045),fcl.Transform(t[:3,:3],centre));v=np.array([[x,y,z] for x in (-.005,.005) for y in (-.005,.005) for z in (-.00225,.00225)])
                        self.static_vertices[key]=v@t[:3,:3].T+centre

    def update_world(self,objects):
        for obj in objects:
            name=obj['id']
            if name not in self.static:continue
            q=obj['pose'];rot=Rotation.from_quat(q['quaternion_xyzw']).as_matrix();centre=np.array(q['xyz_m']);size=np.array(obj['size_m'])
            self.static[name].setTransform(fcl.Transform(rot,centre));v=np.array([[x,y,z] for x in (-size[0]/2,size[0]/2) for y in (-size[1]/2,size[1]/2) for z in (-size[2]/2,size[2]/2)])
            self.static_vertices[name]=v@rot.T+centre
            for key,(slot,offset) in self.supply_studs.items():
                if slot!=name:continue
                c=centre+rot@offset;self.static[key].setTransform(fcl.Transform(rot,c));v=np.array([[x,y,z] for x in (-.005,.005) for y in (-.005,.005) for z in (-.00225,.00225)])
                self.static_vertices[key]=v@rot.T+c

    def update_selected(self,transform):
        size=self.selected['size_m'];vertices=np.array([[x,y,z] for x in [-size[0]/2,size[0]/2] for y in [-size[1]/2,size[1]/2] for z in [-size[2]/2,size[2]/2]])
        self.static[self.slot_id].setTransform(fcl.Transform(transform[:3,:3],transform[:3,3]))
        self.static_vertices[self.slot_id]=vertices@transform[:3,:3].T+transform[:3,3]
        for name,(slot,offset) in self.supply_studs.items():
            if slot==self.slot_id:
                centre=transform[:3,3]+transform[:3,:3]@offset
                self.static[name].setTransform(fcl.Transform(transform[:3,:3],centre))
                v=np.array([[i,j,k] for i in (-.005,.005) for j in (-.005,.005) for k in (-.00225,.00225)])
                self.static_vertices[name]=v@transform[:3,:3].T+centre

    def check(self,q,grip,held=False,phase='',margin=.002,poses_override=None,held_transform=None,allow_touch_world_id=None):
        self._temporary_check_touch=allow_touch_world_id
        try:
            return super().check(q,grip,held,phase,margin,poses_override,held_transform)
        finally:
            self._temporary_check_touch=None

    def state(self,q,grip,held=False,phase='',poses_override=None,held_transform=None,allow_touch_world_id=None):
        allow_touch_world_id=allow_touch_world_id or getattr(self,'_temporary_check_touch',None)
        actual_phase='LIFT_HOLDING' if phase=='LIFT' else ('PICK_TCP' if phase=='PICKUP_DOWN' else phase)
        objects,vertices,pairs=super().state(q,grip,held,actual_phase,poses_override,held_transform)
        chosen_studs={n for n,(slot,_) in self.supply_studs.items() if slot==self.slot_id}
        if held:
            for name in chosen_studs:objects.pop(name,None);vertices.pop(name,None)
            pairs=[(a,b) for a,b in pairs if a not in chosen_studs and b not in chosen_studs]
            for index,(_,offset) in enumerate(self.supply_studs[n] for n in sorted(chosen_studs)):
                name=f'HeldStud_{index}';centre=held_transform[:3,3]+held_transform[:3,:3]@offset
                objects[name]=fcl.CollisionObject(fcl.Box(.01,.01,.0045),fcl.Transform(held_transform[:3,:3],centre))
                v=np.array([[i,j,k] for i in (-.005,.005) for j in (-.005,.005) for k in (-.00225,.00225)])
                vertices[name]=v@held_transform[:3,:3].T+centre
                for other in list(objects):
                    if other==name or other.startswith(('Held','rg2_left_inner_finger#','rg2_right_inner_finger#')):continue
                    pairs.append((name,other))
        elif phase in ('PICKUP_DOWN','CLOSE_GRIPPER'):
            pairs=[(a,b) for a,b in pairs if not (a.startswith(('rg2_left_inner_finger#','rg2_right_inner_finger#')) and b in chosen_studs)]
        if allow_touch_world_id:
            touch={n for n in objects if n==allow_touch_world_id or n.startswith(allow_touch_world_id+'_stud_')}
            pairs=[(a,b) for a,b in pairs if not (a.startswith(('rg2_left_inner_finger#','rg2_right_inner_finger#')) and b in touch)]
        return objects,vertices,pairs
