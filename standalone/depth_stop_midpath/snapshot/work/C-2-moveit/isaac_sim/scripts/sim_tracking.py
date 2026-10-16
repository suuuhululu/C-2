"""Isolated SIM controller trials and read-only PhysX/controller telemetry."""
from copy import deepcopy
import json
import numpy as np


def controller_trial(original, rate, servo):
    """Copy only: velocity PI is an explicit SIM trial, never a REAL preset."""
    if rate not in (60,120) or servo not in ('position','velocity-pi'):
        raise ValueError('Unsupported isolated controller trial')
    if servo=='velocity-pi' and rate!=120:
        raise ValueError('Velocity PI trial requires physics-matched 120Hz')
    trial=deepcopy(original)
    trial['/sim/m0609/controller_manager']['ros__parameters']['update_rate']=rate
    arm=trial['/sim/m0609/arm_controller']['ros__parameters']
    arm['state_publish_rate']=rate
    if servo=='velocity-pi':
        arm['command_interfaces']=['velocity']
        # 5/s proportional, 10/s^2 integral; ff preserves planned velocity.
        # Integral cancels steady load bias. These clamps bound the PID term;
        # JTC adds velocity feed-forward afterwards, so total output is audited.
        arm['gains']={name:dict(p=5.,i=10.,d=0.,ff_velocity_scale=1.,
            i_clamp=.1,i_clamp_min=-.1,i_clamp_max=.1,
            u_clamp_min=-.35,u_clamp_max=.35,antiwindup_strategy='conditional_integration')
            for name in arm['joints']}
    return trial


def install_tracking(world, robot, node, out, arm):
    import omni.physics.core
    from control_msgs.msg import JointTrajectoryControllerState
    from rosgraph_msgs.msg import Clock
    physics_trace=(out/'physics_tracking.jsonl').open('x')
    controller_trace=(out/'controller_tracking.jsonl').open('x')
    state=dict(physics_step=0,callback_time_s=world.current_time,ros_clock_ns=None,enabled=True)
    handles=[]
    view=robot._articulation_view._physics_view
    def snapshot():
        def vector(getter):return np.asarray(getter(),dtype=float)[0,arm].copy().tolist()
        return dict(physics_step=state['physics_step'],callback_time_s=state['callback_time_s'],
            ros_clock_ns=state['ros_clock_ns'],physics_q_rad=vector(view.get_dof_positions),
            physics_v_rad_s=vector(view.get_dof_velocities),
            drive_target_q_rad=vector(view.get_dof_position_targets),
            drive_target_v_rad_s=vector(view.get_dof_velocity_targets),
            root_pose_xyz_xyzw=np.asarray(view.get_root_transforms(),dtype=float)[0].copy().tolist(),
            controller_states=deepcopy(state.get('controller_states',[])))
    def physics(dt, context):
        if not state['enabled']:return
        state['physics_step']+=1;state['callback_time_s']+=float(dt)
        row=snapshot();row.update(dt_s=float(dt),world_time_s=world.current_time)
        physics_trace.write(json.dumps(row)+'\n')
    handles.append(omni.physics.core.get_physics_simulation_interface().subscribe_physics_on_step_events(
        pre_step=False,order=1000,on_update=physics))
    def clock(message):state['ros_clock_ns']=message.clock.sec*1_000_000_000+message.clock.nanosec
    handles.append(node.create_subscription(Clock,'/clock',clock,10))
    def controller(message):
        if not state['enabled']:return
        row=dict(header_ns=message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec,
                 received_world_time_s=world.current_time,joint_names=list(message.joint_names))
        for name in ('reference','feedback','error','output'):
            point=getattr(message,name)
            row[name]=dict(positions=list(point.positions),velocities=list(point.velocities),
                accelerations=list(point.accelerations),
                time_from_start_s=(point.time_from_start.sec*10**9+point.time_from_start.nanosec)/1e9,
                time_from_start_ns=point.time_from_start.sec*10**9+point.time_from_start.nanosec)
        history=state.setdefault('controller_states',[])
        # Preserve distinct original reference evidence when duplicate header/PVA
        # callbacks arrive; ALL raw messages, including conflicts, stay in trace.
        duplicate=(bool(history) and row['header_ns']==history[-1]['header_ns'] and
            row['joint_names']==history[-1]['joint_names'] and
            all(row['reference'][k]==history[-1]['reference'][k]
                for k in ('positions','velocities','accelerations')))
        if not duplicate:
            history.append(deepcopy(row));state['controller_states']=history[-2:]
        controller_trace.write(json.dumps(row)+'\n')
    handles.append(node.create_subscription(JointTrajectoryControllerState,
        '/sim/m0609/arm_controller/controller_state',controller,10))
    def close():
        state['enabled']=False;handles.clear();physics_trace.close();controller_trace.close()
    return snapshot,close
