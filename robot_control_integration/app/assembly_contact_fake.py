"""Deterministic contact surrogate for runner tests; no hardware imports/network.

This tests the actual trial state machine, not physical snap-fit or collision.
"""
from copy import deepcopy
import time

import numpy as np
from scipy.spatial.transform import Rotation


class ContactFake:
    mode="FAKE"
    def __init__(self,c, *, error=None, allow_force_moves=False):
        self.config=c;self.pos=c["reference"]["posx"].copy();self.calls=[]
        self.force=False;self.compliance=False;self.free_pose=self.pos.copy()
        self.force_requests=[];self.force_target_n=0.;self.relative_force=True
        self.error=np.array(error if error is not None else [.4,-.25,.25,-.2,.1])
        self.modify=lambda s:None;self.closed=False;self.allow_force_moves=allow_force_moves

    def check_pose(self,p,**kwargs):return p.copy()
    def robot_system(self):return 1
    def check_contact_services(self, **kwargs):return []
    def close(self):self.closed=True

    def motion_feedback(self):
        return dict(posx=self.pos.copy(),velx=[0.]*6,motion_status=0,query_duration_s=.001)

    def sample(self):
        s=self.motion_feedback()
        s.update(robot_state=1,robot_mode=1,drl_state=3,tcp=self.config["connection"]["tcp"],
                 tool=self.config["connection"]["tool"],gripper_status=2,
                 gripper_width_mm=self.config["reference"]["width_mm"],wrench=[0.,0.,4.,0.,0.,0.])
        if self.force:s["wrench"][2]=(4. if self.relative_force else 0.)+self.force_target_n
        self.modify(s);return s

    def move_line_async(self,p,vel,acc):
        if self.force and not self.allow_force_moves:raise AssertionError("POSITION_CHANGE_WHILE_FORCE_ACTIVE")
        if self.force and abs(p[2]-self.pos[2])>1e-8:raise AssertionError("POSITION_Z_COMMAND_WHILE_FORCE_ACTIVE")
        self.calls.append(("move",p.copy()));self.pos=p.copy()
        if self.force:self.apply_depth()

    def enable_compliance(self,stiffness,transition):
        self.calls.append(("compliance",));self.compliance=True

    def set_downward_force(self,force,transition, *, relative=True):
        assert self.compliance
        self.force_target_n=force;self.relative_force=relative
        self.force_requests.append(dict(force_n=force,relative=relative))
        self.calls.append(("force",force));self.force=True;self.free_pose=self.pos.copy()
        self.apply_depth()

    def apply_depth(self):
        r=self.config["reference"]["posx"]
        rot=Rotation.from_euler("ZYZ",self.pos[3:],degrees=True)*Rotation.from_euler("ZYZ",r[3:],degrees=True).inv()
        q=np.array([self.pos[0]-r[0],self.pos[1]-r[1],*np.rad2deg(rot.as_rotvec())])
        e=q+self.error
        # A smooth depth response below the force window but above the floor.
        remaining=.3+min(2.,float(np.dot(e[:2],e[:2])*.6+np.dot(e[2:],e[2:])*.4))
        self.pos[2]=self.config["floor_z_mm"]+remaining

    def release_force(self,transition):self.calls.append(("release_force",));self.force=False
    def stop(self):self.calls.append(("stop",))
    def release_compliance(self):self.calls.append(("release_compliance",));self.compliance=False


def fake_config(template):
    c=deepcopy(template);c.update(mode="FAKE",floor_z_mm=16.,reviewed=True)
    c["reference"]=dict(posx=[300.,0.,26.,0.,180.,0.],width_mm=40.1,
                        captured_at_unix_s=time.time(),source="SYNTHETIC_TEST_FIXTURE",noncontact_verified=True)
    return c
