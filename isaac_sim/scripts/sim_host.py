"""Native ros2_control SIM host. No arm trajectory loop in Python.

Only initial pose initialization precedes controller ownership. Dynamic contact
grasp is observed; no block teleport/constraint attachment during transport.
"""
import argparse
from pathlib import Path
import json, time, traceback, sys
from collections import deque
import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]
ALIGN = ROOT/'assets'
parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,required=True)
parser.add_argument('--headless',action='store_true');parser.add_argument('--auto-start',action='store_true')
args=parser.parse_args();out=args.run_dir.resolve();out.mkdir(parents=True,exist_ok=True)
cfg=json.loads((ROOT/'config/contact.sim.json').read_text())
model=json.loads((out/'initial.model.json').read_text())
selected=next(s for s in model['supply']['slots'] if s['selected'])

from isaacsim import SimulationApp
app=SimulationApp({'headless':args.headless,'width':1440,'height':900})
status={'scope':'ISOLATED_SIM_MOVEIT_NATIVE_CONTROL','ready':False,'direct_arm_trajectory_loop':False,
        'virtual_block_attachment_used':False,'current_revision':model['current']['current_revision']}
import importlib.metadata
try:
    status['isaac_version']=importlib.metadata.version('isaacsim')
except importlib.metadata.PackageNotFoundError:
    import os
    version=Path(os.environ['ISAAC_SIM_ROOT'])/'VERSION'
    status['isaac_version']=version.read_text().strip() if version.is_file() else 'UNAVAILABLE'

def save(name,data):
    path=out/name;temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(path)

def main():
    import omni.usd,omni.kit.app,omni.graph.core as og,omni.timeline
    from pxr import Usd,UsdGeom,UsdPhysics,UsdShade,UsdLux,Gf,PhysxSchema
    from isaacsim.core.api import World
    from isaacsim.core.prims import SingleArticulation,SingleRigidPrim
    from isaacsim.core.utils.types import ArticulationAction
    manager=omni.kit.app.get_app().get_extension_manager()
    for name in ('isaacsim.ros2.core','isaacsim.ros2.bridge','isaacsim.ros2.control'):
        manager.set_extension_enabled_immediate(name,True);app.update()
    from isaacsim.ros2.control import Ros2ControlManager
    from native_compat import apply as apply_native_compat
    apply_native_compat()
    from isaacsim.ros2.control.bindings import _isaacsim_ros2_control as backend
    import rclpy
    from std_msgs.msg import String
    from action_msgs.srv import CancelGoal
    from controller_manager_msgs.srv import LoadController,ConfigureController,SwitchController
    rclpy.init();node=rclpy.create_node('isaac_moveit_state_host')
    state_pub=node.create_publisher(String,'/sim/review_state',10)
    cancel=node.create_client(CancelGoal,'/sim/m0609/arm_controller/follow_joint_trajectory/_action/cancel_goal')
    cancel_grip=node.create_client(CancelGoal,'/sim/m0609/gripper_controller/follow_joint_trajectory/_action/cancel_goal')
    ctx=omni.usd.get_context();ctx.open_stage(str(ALIGN/'aligned_robot.sim.usda'))
    stage=ctx.get_stage();world=World(stage_units_in_meters=1,physics_dt=1/60,rendering_dt=1/60)
    prim=stage.GetPrimAtPath('/World/Robot')
    # Exporter requires rigid body targets. Keep tool0 as a fixed Xform,
    # retarget its RG2 mount joint to link_6 with the identical anchor transform.
    rigid={p.GetName():p for p in Usd.PrimRange(prim) if p.HasAPI(UsdPhysics.RigidBodyAPI)}
    mount=UsdPhysics.Joint(stage.GetPrimAtPath('/World/Robot/Physics/joint0'))
    parent=stage.GetPrimAtPath(mount.GetBody0Rel().GetTargets()[0])
    if not parent.HasAPI(UsdPhysics.RigidBodyAPI):
        def wm(p):return np.asarray(UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T
        original=np.eye(4);original[:3,3]=np.asarray(mount.GetLocalPos0Attr().Get())
        quat=mount.GetLocalRot0Attr().Get();original[:3,:3]=Rotation.from_quat([*quat.GetImaginary(),quat.GetReal()]).as_matrix()
        corrected=np.linalg.inv(wm(rigid['link_6']))@wm(parent)@original
        qmount=Rotation.from_matrix(corrected[:3,:3]).as_quat()
        mount.GetBody0Rel().SetTargets([rigid['link_6'].GetPath()])
        mount.GetLocalPos0Attr().Set(Gf.Vec3f(*corrected[:3,3]));mount.GetLocalRot0Attr().Set(Gf.Quatf(float(qmount[3]),Gf.Vec3f(*qmount[:3])))
        save('fixed_mount_compatibility.json',{'old_parent':str(parent.GetPath()),'new_parent':str(rigid['link_6'].GetPath()),'same_mount_transform':corrected.tolist(),'reason':'Native live URDF exporter requires rigid joint-body targets'})
    material=UsdShade.Material.Define(stage,'/World/ContactMaterial')
    mat=UsdPhysics.MaterialAPI.Apply(material.GetPrim());mat.CreateStaticFrictionAttr(.6);mat.CreateDynamicFrictionAttr(.6);mat.CreateRestitutionAttr(0)
    objects=[]
    def box(name,centre,size,yaw=0,color=(.5,.5,.5),dynamic=False):
        path='/World/Environment/'+name;x=UsdGeom.Xform.Define(stage,path)
        x.AddTranslateOp().Set(Gf.Vec3d(*centre));x.AddRotateZOp().Set(float(np.rad2deg(yaw)))
        c=UsdGeom.Cube.Define(stage,path+'/Body');c.CreateSizeAttr(1);c.AddScaleOp().Set(Gf.Vec3d(*size));c.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        UsdPhysics.CollisionAPI.Apply(c.GetPrim());UsdShade.MaterialBindingAPI.Apply(c.GetPrim()).Bind(material,materialPurpose='physics')
        if dynamic:
            UsdPhysics.RigidBodyAPI.Apply(x.GetPrim());UsdPhysics.MassAPI.Apply(x.GetPrim()).CreateMassAttr(.02)
        objects.append({'id':name,'path':path,'size_m':size,'studs':False})
        return x
    def studs(x,size,color):
        nx,ny=[round(v/.016) for v in size[:2]]
        for ix in range(nx):
            for iy in range(ny):
                c=UsdGeom.Cube.Define(stage,str(x.GetPath())+f'/Stud_{ix}_{iy}')
                c.CreateSizeAttr(1);c.AddTranslateOp().Set(Gf.Vec3d((ix-(nx-1)/2)*.016,(iy-(ny-1)/2)*.016,.01175))
                c.AddScaleOp().Set(Gf.Vec3d(.01,.01,.0045));c.CreateDisplayColorAttr([Gf.Vec3f(*color)])
                UsdPhysics.CollisionAPI.Apply(c.GetPrim());UsdShade.MaterialBindingAPI.Apply(c.GetPrim()).Bind(material,materialPurpose='physics')
        objects[-1]['studs']=True
    outline=np.asarray(model['supply']['outline_m']);lo=outline.min(0);hi=outline.max(0)
    box('SupplySurface',[(lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2]-.002],[hi[0]-lo[0],hi[1]-lo[1],.004],color=(.2,.5,.3))
    ap=np.asarray(model['assembly_grid_lines_m']).reshape(-1,3);lo=ap.min(0);hi=ap.max(0)
    box('AssemblySurface',[(lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2]-.002],[hi[0]-lo[0]+.016,hi[1]-lo[1]+.016,.004])
    box('HandoverTray',[.417561,-.184622,-.002],[.18,.14,.004],color=(.7,.45,.15))
    for i,b in enumerate(model['current_models']):
        color=(1,.8,.1) if b['block']['color']=='yellow' else ((.9,.04,.04) if b['block']['color']=='red' else (.1,.3,.9))
        x=box(f'Current_{i}',b['centre_m'],b['size_m'],b['yaw_rad'],color=color);studs(x,b['size_m'],color)
    for s in model['supply']['slots']:
        color=(1,.8,.1) if s['color']=='yellow' else ((.9,.04,.04) if s['color']=='red' else (.1,.3,.9))
        x=box(s['slot_id'],s['centre_m'],s['size_m'],s['yaw_rad'],color=color,dynamic=True)
        studs(x,s['size_m'],color)
    # Allocate immutable kinematic mock bodies before physics initialization.
    # Changing a live body's kinematic flag can reparse the PhysX scene and
    # reset the unrelated robot articulation. Mock completion swaps bodies,
    # without changing physics topology or writing robot joints.
    mock_twins={};supply_handles={};mock_handles={}
    for i,s in enumerate(model['supply']['slots']):
        color=(1,.8,.1) if s['color']=='yellow' else ((.9,.04,.04) if s['color']=='red' else (.1,.3,.9))
        x=box('Mock_'+s['slot_id'],[3+i*.1,3,-3],s['size_m'],s['yaw_rad'],color=color,dynamic=True);studs(x,s['size_m'],color);objects.pop()
        UsdPhysics.RigidBodyAPI(x.GetPrim()).CreateKinematicEnabledAttr(True);UsdGeom.Imageable(x).MakeInvisible();mock_twins[s['slot_id']]=x.GetPrim()
        supply_handles[s['slot_id']]=SingleRigidPrim('/World/Environment/'+s['slot_id'],name='source_'+s['slot_id'])
        mock_handles[s['slot_id']]=SingleRigidPrim(str(x.GetPath()),name='mock_'+s['slot_id'])
    block=stage.GetPrimAtPath('/World/Environment/'+selected['slot_id'])
    for p in Usd.PrimRange(prim,Usd.TraverseInstanceProxies()):
        if p.IsA(UsdGeom.Mesh) and p.HasAPI(UsdPhysics.CollisionAPI) and not p.IsInstanceProxy():
            UsdShade.MaterialBindingAPI.Apply(p).Bind(material,materialPurpose='physics')
    light=UsdLux.DomeLight.Define(stage,'/World/Light');light.CreateIntensityAttr(1000)
    camera=UsdGeom.Camera.Define(stage,'/World/Camera');camera.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(0,-1.35,.95),Gf.Vec3d(0,.05,.25),Gf.Vec3d(0,0,1)).GetInverse())
    def view(name):
        eye,target={'Overview':((0,-1.35,.95),(0,.05,.25)), 'Supply':((-.42,-.55,.5),(-.45,.03,.065)), 'Assembly':((.65,-.35,.38),(.391,.008,.07)), 'Tray':((.64,-.48,.30),(.417561,-.184622,.04))}[name]
        camera.GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse())
    camera.CreateFocalLengthAttr(28);camera.CreateClippingRangeAttr(Gf.Vec2f(.001,100))
    if not args.headless:
        from omni.kit.viewport.utility import get_active_viewport
        viewport=get_active_viewport();viewport.set_active_camera('/World/Camera')
    keys=og.Controller.Keys
    og.Controller.edit({'graph_path':'/Clock','evaluator_name':'execution'}, {
        keys.CREATE_NODES:[('Tick','omni.graph.action.OnPlaybackTick'),('Time','isaacsim.core.nodes.IsaacReadSimulationTime'),('Clock','isaacsim.ros2.bridge.ROS2PublishClock')],
        keys.CONNECT:[('Tick.outputs:tick','Clock.inputs:execIn'),('Time.outputs:simulationTime','Clock.inputs:timeStamp')]})
    roots=[p for p in Usd.PrimRange(prim) if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
    articulation=PhysxSchema.PhysxArticulationAPI.Apply(roots[0]);articulation.CreateSolverPositionIterationCountAttr(64);articulation.CreateSolverVelocityIterationCountAttr(4)
    robot=SingleArticulation(prim_path=str(roots[0].GetPath()),name='m0609_native_sim');world.scene.add(robot)
    world.reset();robot.initialize();names=robot.dof_names
    for handle in [*supply_handles.values(),*mock_handles.values()]:handle.initialize()
    indices=np.array([names.index(f'joint_{i}') for i in range(1,7)]);grip=names.index('rg2_finger_joint')
    # Initialization only; no Python arm writes after CM setup.
    initial_q=json.loads((out/'fixture_seed.json').read_text())['initial_q_rad'] if (out/'fixture_seed.json').exists() else cfg['initial_q_rad']
    q=np.zeros(len(names));q[indices]=initial_q;q[grip]=cfg['gripper']['open_q_rad']
    for name in names:
        if name.startswith('rg2_') and name!='rg2_finger_joint':
            q[names.index(name)]=cfg['gripper']['open_q_rad']*(1 if 'inner_finger' in name else -1)
    robot.set_joint_positions(q);robot.set_joint_velocities(np.zeros(len(q)));robot.apply_action(ArticulationAction(joint_positions=q))
    # USD physics gear constraints own RG2 followers; retain passive follower drives.
    for _ in range(60):world.step(render=not args.headless)
    timeline=omni.timeline.get_timeline_interface();timeline.pause();app.update()
    if not backend.is_ready():raise RuntimeError('Native ros2_control backend not ready')
    from isaacsim.ros2.control.urdf_synth import build_full_urdf
    original_control_xml=build_full_urdf(stage,'/World/Robot')
    (out/'synthesized_control.before_mimic.urdf').write_text(original_control_xml)
    from native_compat import physics_mimic_control_xml
    native_xml=physics_mimic_control_xml(original_control_xml);(out/'synthesized_control.urdf').write_text(native_xml)
    from isaacsim.ros2.control import ros2_control_manager
    ros2_control_manager.build_full_urdf=lambda *args,**kwargs:native_xml
    rc=Ros2ControlManager.setup('/World/Robot',str(ROOT/'config/controllers.yaml'),namespace='sim/m0609',publish_robot_description=False,use_sim_time=True)
    if rc!=0:raise RuntimeError('Native CM setup return '+str(rc))
    timeline.play()
    def tick():
        rclpy.spin_once(node,timeout_sec=0);world.step(render=True)
    def call(service,request):
        types={'load_controller':LoadController,'configure_controller':ConfigureController,'switch_controller':SwitchController}
        client=node.create_client(types[service],'/sim/m0609/controller_manager/'+service)
        deadline=time.monotonic()+30
        while not client.service_is_ready() and time.monotonic()<deadline:tick()
        if not client.service_is_ready():raise RuntimeError('CM service unavailable: '+service)
        future=client.call_async(request)
        while not future.done() and time.monotonic()<deadline:tick()
        if not future.done():raise RuntimeError('CM service timeout: '+service)
        response=future.result()
        if not response.ok:raise RuntimeError('CM rejected '+service+' '+str(request))
        return response
    for controller in ('joint_state_broadcaster','arm_controller','gripper_controller'):
        call('load_controller',LoadController.Request(name=controller));call('configure_controller',ConfigureController.Request(name=controller))
    request=SwitchController.Request();request.activate_controllers=['joint_state_broadcaster','arm_controller','gripper_controller'];request.strictness=2
    request.timeout.sec=15
    call('switch_controller',request)
    bindings={p.GetName():p for p in Usd.PrimRange(prim) if p.HasAPI(UsdPhysics.RigidBodyAPI)}
    tcp_prim=stage.GetPrimAtPath(str(bindings['link_6'].GetPath())+'/GripperDA_v4_tcp')
    def matrix(p):return np.asarray(UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T
    def pose(t):return {'xyz_m':t[:3,3].tolist(),'quaternion_xyzw':Rotation.from_matrix(t[:3,:3]).as_quat().tolist(),'frame_id':'base_link'}
    started=args.auto_start
    if not args.headless:
        import omni.ui as ui
        window=ui.Window('A chair / MoveIt / mock assembly — SIM',width=610,height=410)
        def start():
            nonlocal started;started=True;button.enabled=False
        with window.frame:
            with ui.VStack(spacing=8):
                ui.Label('Red1x2 / 36 supply blocks / small-side grip / SIM only',height=30)
                label=ui.Label('Ready: controller feedback active. Run starts pickup and transport.',height=70,word_wrap=True)
                button=ui.Button('Run MoveIt scenario',clicked_fn=start,height=40,enabled=not started)
                with ui.HStack():
                    for name in ('Overview','Supply','Assembly','Tray'):ui.Button(name,clicked_fn=lambda n=name:view(n))
                ui.Label('At wait: mock insertion. Human mode: tray delivery and mock human response. Physical fitting is not executed.',height=55,word_wrap=True)
                def respond():
                    path=out/'hmi.pending.json'
                    if path.exists():
                        pending=json.loads(path.read_text());save('hmi.response.json',{'request_id':pending['request_id'],'kind':pending['kind'],'plan_id':pending['plan_id'],'step_id':pending['step_id'],'current_revision':pending['current_revision'],'source':'USER_MOCK_CONFIRMATION'})
                help_label=ui.Label('No pending human request.',height=75,word_wrap=True)
                ui.Button('Confirm pending mock support / human assembly',clicked_fn=respond,height=35)
    save('host_status.json',{**status,'ready':True,'control_backend':'isaacsim.ros2.control','dof_names':names})
    from runtime_guard import Scene
    guard_scene=Scene(model)
    current_revision=model['current']['current_revision'];last_command=None;temporary_touch=None
    def replace_guard(new_model,phase='EMPTY',touch=None):
        global model,selected
        nonlocal guard_scene,block,current_revision,temporary_touch
        model=new_model;selected=next(v for v in model['supply']['slots'] if v['selected']);current_revision=model['current']['current_revision']
        block=stage.GetPrimAtPath('/World/Environment/'+selected['slot_id']);guard_scene=Scene(model);temporary_touch=touch
        save('guard_context.json',{'phase':phase,'held':False,'attachment':None,'selected_slot_id':selected['slot_id'],'allow_touch_world_id':touch})
    def process_command():
        nonlocal last_command,objects
        path=out/'host_command.json'
        if not path.exists():return
        command=json.loads(path.read_text());ident=command['command_id']
        if ident==last_command:return
        last_command=ident
        if (out/'execution.active.json').exists() or guard_failed:raise RuntimeError('Mock boundary rejected during active execution or guard failure')
        state=json.loads((out/'live_state.json').read_text())
        if not state.get('observed_stopped'):raise RuntimeError('Mock boundary requires actual stopped arm')
        if command['expected_revision']!=current_revision:raise RuntimeError('Mock boundary stale Current')
        kind=command['kind']
        if kind=='SELECT':
            replace_guard(command['model'])
        elif kind in ('MOCK_ASSEMBLE','MOCK_TRAY_PLACE','MOCK_HUMAN_ASSEMBLE'):
            from sim_utils import pose_matrix,error
            if kind!='MOCK_HUMAN_ASSEMBLE':
                if command['slot_id']!=selected['slot_id']:raise RuntimeError('Mock boundary selected slot mismatch')
                pe,re=error(matrix(tcp_prim),pose_matrix(command['goal']))
                drift=error(np.linalg.inv(matrix(tcp_prim))@matrix(block),np.array(command['attachment']))
                if pe>.002 or re>np.deg2rad(1) or drift[0]>.005 or drift[1]>.15:raise RuntimeError('Mock boundary requires reached goal and actual grasp')
            slot_id=command['slot_id'];moving=mock_twins[slot_id];target=command['target'];half=target['yaw_rad']/2
            # Kinematic targets must also update their existing USD pose ops;
            # changing transforms alone is overwritten by the old target.
            for op in UsdGeom.Xformable(moving).GetOrderedXformOps():
                if op.GetOpType()==UsdGeom.XformOp.TypeTranslate:
                    op.Set(Gf.Vec3d(*target['centre_m']) if op.GetPrecision()==UsdGeom.XformOp.PrecisionDouble else Gf.Vec3f(*target['centre_m']))
                elif op.GetOpType()==UsdGeom.XformOp.TypeOrient:
                    op.Set(Gf.Quatd(float(np.cos(half)),Gf.Vec3d(0,0,float(np.sin(half)))) if op.GetPrecision()==UsdGeom.XformOp.PrecisionDouble else Gf.Quatf(float(np.cos(half)),Gf.Vec3f(0,0,float(np.sin(half)))))
            mock_handles[slot_id].set_world_pose(np.array(target['centre_m']),np.array([np.cos(half),0,0,np.sin(half)]))
            UsdGeom.Imageable(moving).MakeVisible()
            if kind!='MOCK_HUMAN_ASSEMBLE':
                old=stage.GetPrimAtPath('/World/Environment/'+slot_id)
                supply_handles[slot_id].set_world_pose(np.array([3.,4.,-4.]),np.array([1.,0,0,0]))
                supply_handles[slot_id].set_linear_velocity(np.zeros(3));supply_handles[slot_id].set_angular_velocity(np.zeros(3));UsdGeom.Imageable(old).MakeInvisible()
                record=next(v for v in objects if v['path']==str(old.GetPath()));record['source_slot_id']=slot_id
            else:record=next(v for v in objects if v.get('source_slot_id')==slot_id)
            record['id']=command['world_object_id'];record['path']=str(moving.GetPath())
            replace_guard(command['model'],phase='RETREAT_FROM_TRAY' if kind=='MOCK_TRAY_PLACE' else 'EMPTY',touch=command['world_object_id'] if kind=='MOCK_TRAY_PLACE' else None)
        else:raise RuntimeError('Unknown host command '+kind)
        save('host_command.receipt.json',{'command_id':ident,'kind':kind,'current_revision':current_revision,'selected_slot_id':selected['slot_id'],'sim_time_s':world.current_time,'physical_insertion':False,'real_B_observation':False,'success':True})
    trace=(out/'measured_sim.jsonl').open('w');collision_trace=(out/'runtime_collisions.jsonl').open('w');counter=0;guard_failed=False;position_history=deque(maxlen=21);capture=None;rgb=None;path_drawn=set()
    try:
        while app.is_running() and not (out/'shutdown.request').exists():
            tick();counter+=1
            if counter>6:process_command()
            if counter%3==0:
                all_q=robot.get_joint_positions();mimic_error=max(abs(all_q[names.index(n)]-all_q[grip]*(1 if 'inner_finger' in n else -1)) for n in names if n.startswith('rg2_') and n!='rg2_finger_joint')
                arm_q=robot.get_joint_positions(joint_indices=indices);v=robot.get_joint_velocities(joint_indices=indices)
                env=[]
                for obj in objects:
                    env.append({**obj,'pose':pose(matrix(stage.GetPrimAtPath(obj['path'])))})
                position_history.append((world.current_time,arm_q.copy()))
                derived=(arm_q-position_history[0][1])/max(world.current_time-position_history[0][0],1e-9)
                stopped=len(position_history)==21 and max(abs(derived))<.02 and np.max(np.ptp(np.array([row[1] for row in position_history]),axis=0))<.002
                state={'gripper_mimic_max_error_rad':float(mimic_error),'all_joint_positions_rad':all_q.tolist(),'observed_stopped':bool(stopped),'position_derived_velocity_rad_s':derived.tolist(),'sequence':counter,'sim_time_s':world.current_time,'q_rad':arm_q.tolist(),'velocity_rad_s':v.tolist(),
                       'grip_rad':float(robot.get_joint_positions()[grip]),'tcp_pose':pose(matrix(tcp_prim)),
                       'block_pose':pose(matrix(block)),'world_objects':env,'selected_slot_id':selected['slot_id'],
                       'current_revision':current_revision,'started':started,'control_backend':'isaacsim.ros2.control'}
                state_pub.publish(String(data=json.dumps(state)));save('live_state.json',state)
                trace.write(json.dumps({k:v for k,v in state.items() if k!='world_objects'})+'\n')
                if (out/'guard_context.json').exists() and counter%6==0 and not guard_failed:
                    contract=json.loads((out/'guard_context.json').read_text());phase=contract['phase'];held=contract['held']
                    actual_block=matrix(block);guard_scene.update_world(env)
                    guard_scene.update_selected(actual_block)
                    verdict=guard_scene.check(arm_q,state['grip_rad'],held,phase,margin=.0005,
                        poses_override={name:matrix(p) for name,p in bindings.items()},held_transform=actual_block if held else None,allow_touch_world_id=contract.get('allow_touch_world_id'))
                    context_error=None
                    if (out/'execution.active.json').exists() and (out/'scene_context.json').exists():
                        context=json.loads((out/'scene_context.json').read_text());execution_context=json.loads((out/'execution.active.json').read_text())
                        if any(execution_context.get(k)!=context.get(k) for k in ('current_revision','world_revision','profile_version','reservation_id')):context_error='STALE_CONTEXT_DURING_EXECUTION'
                    drift=[0.0,0.0]
                    if held and contract.get('attachment') is not None:
                        relative=np.linalg.inv(matrix(tcp_prim))@actual_block;reference=np.array(contract['attachment'])
                        drift=[float(np.linalg.norm(relative[:3,3]-reference[:3,3])),float(Rotation.from_matrix(reference[:3,:3].T@relative[:3,:3]).magnitude())]
                    row={'context_error':context_error,'sequence':counter,'phase':phase,'holding_drift_m_rad':drift,**verdict}
                    collision_trace.write(json.dumps(row)+'\n')
                    if context_error or verdict['hits'] or drift[0]>.005 or drift[1]>.15:
                        guard_failed=True;save('runtime_guard_failure.json',row)
                        if cancel.service_is_ready():cancel.call_async(CancelGoal.Request())
                        if cancel_grip.service_is_ready():cancel_grip.call_async(CancelGoal.Request())
                if guard_failed and (out/'execution.active.json').exists():
                    # Retry cancellation so a goal accepted after the first cancel cannot escape the latch.
                    if cancel.service_is_ready():cancel.call_async(CancelGoal.Request())
                    if cancel_grip.service_is_ready():cancel_grip.call_async(CancelGoal.Request())
                if counter%60==0:collision_trace.flush()
                if counter%60==0:trace.flush()
            if capture is None and (out/'capture.request.json').exists():
                capture=json.loads((out/'capture.request.json').read_text());(out/'capture.request.json').unlink();view(capture.get('view','Overview'));capture['tick']=counter
                if rgb is None:
                    import omni.replicator.core as rep
                    render_product=rep.create.render_product('/World/Camera',(1440,900));rgb=rep.AnnotatorRegistry.get_annotator('rgb');rgb.attach([render_product])
            if capture is not None and counter>=capture['tick']+20:
                data=rgb.get_data()
                if data.size:
                    from PIL import Image
                    Image.fromarray(data).save(out/(capture['label']+'.png'));save(capture['label']+'.capture.json',{'sim_time_s':world.current_time,'view':capture.get('view','Overview'),'camera':'/World/Camera'});capture=None
                    rgb.detach([render_product]);render_product.destroy();rgb=None
            for phase in ('SUPPLY_APPROACH','LIFT','TRANSPORT','PRE_CONTACT','EMPTY_RETREAT'):
                active=json.loads((out/'active_step.json').read_text()) if (out/'active_step.json').exists() else {'step_id':'BOOT'}
                key=active['step_id']+'_'+phase
                path=out/active['step_id']/(phase+'.result.yaml')
                if key not in path_drawn and path.exists():
                    import yaml
                    planned=yaml.load(path.read_text(),Loader=getattr(yaml,'CSafeLoader',yaml.SafeLoader))
                    if planned and planned.get('plan_success'):
                        points=[row['tcp_matrix'] for row in planned['checked_states']]
                        points=[Gf.Vec3f(*[t[i][3] for i in range(3)]) for t in points[::5]]
                        if len(points)>1:
                            curve=UsdGeom.BasisCurves.Define(stage,'/World/MoveItPaths/'+key);curve.CreateTypeAttr('linear');curve.CreateCurveVertexCountsAttr([len(points)]);curve.CreatePointsAttr(points);curve.CreateWidthsAttr([.001]);curve.SetWidthsInterpolation('constant');curve.CreateDisplayColorAttr([Gf.Vec3f(.1,.95,.3)])
                        path_drawn.add(key)
            if (out/'display.json').exists() and not args.headless:
                label.text=json.loads((out/'display.json').read_text()).get('message','')
                help_label.text=json.loads((out/'hmi.pending.json').read_text()).get('message','No pending human request.') if (out/'hmi.pending.json').exists() else 'No pending human request.'
            time.sleep(.001 if args.headless else .002)
    finally:
        trace.close();collision_trace.close();Ros2ControlManager.teardown('/World/Robot');timeline.stop();node.destroy_node();rclpy.shutdown()

try:
    main()
except Exception:
    status['error']=traceback.format_exc();save('host_failure.json',status);traceback.print_exc();app.close();sys.exit(1)
app.close()
