"""기하 기반 모의 백엔드. ROS/장치 API를 import하거나 호출하지 않는다."""
from copy import deepcopy
import math
from .robot_adapter import StepResult, apply_tool_offset


class SimulatedWorkpieceAdapter:
    measurement_contract_version = 1
    source_mode = "SIMULATION"

    def __init__(self, workcell, *, center_xy_m=None, radius_m=None, top_z_m=None, clock):
        self.workcell=deepcopy(workcell)
        self.center=center_xy_m or workcell["simulation"]["axis_xy_m"]
        self.radius=radius_m if radius_m is not None else workcell["simulation"]["radius_m"]
        self.top_z=top_z_m if top_z_m is not None else workcell["simulation"]["top_z_m"]
        self.pose=apply_tool_offset(workcell["simulation"]["initial_tcp_pose"],workcell["tool_offset_m"])
        self.clock=clock
        self.calls=[]

    def observe_measurement(self):
        return dict(tip_pose=list(self.pose),joints_rad=[0.,0.2,1.2,0.,1.5,0.],
                    frame_id="c2_base",quality="VALID",robot_state=1,motion_status=0,
                    measured_at_monotonic_s=self.clock())

    def preflight_measurement(self,steps,workcell,profiles,context):
        self.calls.append(("preflight",deepcopy(steps)))
        return StepResult("SUCCEEDED",observed_state=dict(
            all_segments_checked=True,probe_envelopes_checked=True,ownership_confirmed=True,
            tcp_load_match=True,
            validation_level="SIMULATED_GEOMETRY_ONLY",physical_ik_checked=False,
            full_collision_checked=False))

    def execute_measurement_step(self,step,profile,context,timeout_s):
        self.calls.append(("execute",deepcopy(step)))
        if context.cancel.is_set():
            return StepResult("STOPPED","CANCELLED")
        if step["kind"]=="MOVE":
            self.pose=list(step["target_pose"])
            return StepResult("SUCCEEDED",observed_state={"stop_confirmed":True})
        start=list(self.pose); direction=step["direction"]
        if step["profile"]=="top_touch":
            tcp=apply_tool_offset(start,self.workcell["tool_offset_m"],-1)
            contact=apply_tool_offset(tcp,self.workcell["top"]["contact_offset_tool_m"])
            travel=contact[2]-self.top_z
        else:
            x,y=start[0]-self.center[0],start[1]-self.center[1]
            b=x*direction[0]+y*direction[1]
            disc=b*b-(x*x+y*y-self.radius*self.radius)
            travel=-b-math.sqrt(disc) if disc>=0 else math.inf
        if not 0<=travel<=step["max_m"]:
            return StepResult("FAILED","CONTACT_NOT_FOUND","모의 표면이 탐색 범위 밖")
        for k in range(3):
            self.pose[k]+=travel*direction[k]
        return StepResult("SUCCEEDED",observed_state=dict(stop_confirmed=True,contact=dict(
            detected=True,tip_pose=list(self.pose),frame_id="c2_base",
            normal_force_n=profile["contact_force_n"]+0.01,
            measured_at_monotonic_s=self.clock(),operator_confirmed=False)))

    def stop_measurement(self,profile):
        self.calls.append(("stop",deepcopy(profile)))
        return StepResult("SUCCEEDED",observed_state={"stop_confirmed":True})
