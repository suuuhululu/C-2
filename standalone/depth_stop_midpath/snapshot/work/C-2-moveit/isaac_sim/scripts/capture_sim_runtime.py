"""Native SIM contact grasp, lift, pause and paired observation export.

Explicit sim_transport optionally continues through D's chosen calculation
engine. Historical setup postures initialize a new nominal SIM only.
"""
from collections import deque
from pathlib import Path
import json
import os
import time
import traceback

import numpy as np

from capture_sim_scene import prepare_capture_setup, command_counts, contact_state, verified_stop, verified_hold, read_scene_geometry, capture_post_grasp
from sim_utils import save, matrix_pose

ROOT = Path(__file__).resolve().parents[1]


def checkpoint_transport_route(args, isolated_domain):
    """Explicit restore route only; grants no plan/start/dispatch approval."""
    if isolated_domain != 194 or not args.sim_transport:
        raise ValueError('FIXED_CHECKPOINT_ISOLATED_PREPARED_TRANSPORT_REQUIRED')
    prepared = getattr(args, 'prepared_transport', None)
    if getattr(args, 'fresh_moveit_baseline', False):
        calculator = getattr(args, 'transport_calculator', None)
        if (getattr(args, 'fresh_moveit_baseline') is not True or prepared is not None or
                getattr(args, 'transport_engine', None) != 'moveit' or
                getattr(args, 'depth_owner_test', None) is not True or
                not callable(getattr(args, 'checkpoint_restore_hook', None)) or
                calculator is None or not Path(calculator).is_file() or
                not os.access(calculator, os.X_OK)):
            raise ValueError('FIXED_CHECKPOINT_FRESH_MOVEIT_RESTORE_CONTRACT_REQUIRED')
        return 'ISOLATED_FRESH_MOVEIT_ACTUAL_GRASP_THEN_NEW_PLAN'
    if not prepared:
        raise ValueError('FIXED_CHECKPOINT_ISOLATED_PREPARED_TRANSPORT_REQUIRED')
    return 'EXISTING_ISOLATED_PREPARED_TRANSPORT'


def initialize_native(app, stage, setup, cfg):
    """Same native control bootstrap/compatibility as the existing SIM host."""
    import omni.kit.app, omni.graph.core as og, omni.timeline
    from pxr import Usd, UsdGeom, UsdPhysics, UsdShade, PhysxSchema, Gf
    from scipy.spatial.transform import Rotation
    from isaacsim.core.api import World
    from isaacsim.core.prims import SingleArticulation
    from isaacsim.core.utils.types import ArticulationAction
    manager = omni.kit.app.get_app().get_extension_manager()
    for name in ('isaacsim.ros2.core', 'isaacsim.ros2.bridge', 'isaacsim.ros2.control'):
        manager.set_extension_enabled_immediate(name, True); app.update()
    from isaacsim.ros2.control import Ros2ControlManager, ros2_control_manager
    from isaacsim.ros2.control.bindings import _isaacsim_ros2_control as backend
    from native_compat import apply, physics_mimic_control_xml
    apply()
    prim = stage.GetPrimAtPath('/World/Robot')
    material = UsdShade.Material.Get(stage,'/World/NominalContactMaterial')
    for part in Usd.PrimRange(prim,Usd.TraverseInstanceProxies()):
        if part.IsA(UsdGeom.Mesh) and part.HasAPI(UsdPhysics.CollisionAPI) and not part.IsInstanceProxy():
            UsdShade.MaterialBindingAPI.Apply(part).Bind(material,materialPurpose='physics')
    rigid = {p.GetName():p for p in Usd.PrimRange(prim) if p.HasAPI(UsdPhysics.RigidBodyAPI)}
    mount = UsdPhysics.Joint(stage.GetPrimAtPath('/World/Robot/Physics/joint0'))
    parent = stage.GetPrimAtPath(mount.GetBody0Rel().GetTargets()[0])
    if not parent.HasAPI(UsdPhysics.RigidBodyAPI):
        def wm(p): return np.asarray(UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T
        anchor = np.eye(4); anchor[:3,3] = np.asarray(mount.GetLocalPos0Attr().Get())
        q = mount.GetLocalRot0Attr().Get(); anchor[:3,:3] = Rotation.from_quat([*q.GetImaginary(),q.GetReal()]).as_matrix()
        corrected = np.linalg.inv(wm(rigid['link_6'])) @ wm(parent) @ anchor
        q = Rotation.from_matrix(corrected[:3,:3]).as_quat()
        mount.GetBody0Rel().SetTargets([rigid['link_6'].GetPath()])
        mount.GetLocalPos0Attr().Set(Gf.Vec3f(*corrected[:3,3]))
        mount.GetLocalRot0Attr().Set(Gf.Quatf(float(q[3]),Gf.Vec3f(*q[:3])))
    roots = [p for p in Usd.PrimRange(prim) if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
    if cfg.get('sim_fixed_base_root',False):
        if len(roots)!=1:raise ValueError('Fixed-base trial requires one articulation root')
        fixed=UsdPhysics.FixedJoint(stage.GetPrimAtPath('/World/Robot/Physics/preview_world_base'))
        if not fixed or fixed.GetBody1Rel().GetTargets()!=[roots[0].GetPath()]:
            raise ValueError('Fixed-base joint does not bind the original root link')
        # Fixed root API must be on the joint to world, not the base rigid body.
        # Session-layer edits preserve the source asset and all link geometry.
        fixed.GetBody0Rel().SetTargets([])
        from isaacsim.asset.importer.utils import fix_articulation_root_for_fixed_base
        if fix_articulation_root_for_fixed_base(stage)!=1:
            raise ValueError('Exactly one fixed-base root relocation required')
        roots=[p for p in Usd.PrimRange(prim) if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if len(roots)!=1 or roots[0]!=fixed.GetPrim():
            raise ValueError('Fixed-base relocation left multiple or incorrect roots')
    physics = PhysxSchema.PhysxArticulationAPI.Apply(roots[0])
    iterations=setup.get('solver_iterations',dict(position=64,velocity=4))
    physics.CreateSolverPositionIterationCountAttr(iterations['position'])
    physics.CreateSolverVelocityIterationCountAttr(iterations['velocity'])
    if cfg.get('sim_tgs_forces_every_iteration',False):
        scenes=[p for p in stage.Traverse() if p.IsA(UsdPhysics.Scene)]
        if len(scenes)!=1:raise ValueError('TGS trial requires one explicit physics scene')
        PhysxSchema.PhysxSceneAPI.Apply(scenes[0]).CreateEnableExternalForcesEveryIterationAttr(True)
    world = World(stage_units_in_meters=1, physics_dt=cfg['physics_dt_s'], rendering_dt=cfg['physics_dt_s'])
    if cfg.get('sim_solver_type')=='PGS':world.get_physics_context().set_solver_type('PGS')
    robot = SingleArticulation(prim_path=str(roots[0].GetPath()), name='stage3_native_capture')
    world.scene.add(robot); world.reset(); robot.initialize()
    names = robot.dof_names; positions = np.zeros(len(names))
    for i,value in enumerate(setup['initial_q_rad'],1): positions[names.index('joint_'+str(i))] = value
    for name in names:
        if name.startswith('rg2_'):
            positions[names.index(name)] = cfg['gripper'].get('initial_q_rad',cfg['gripper']['open_q_rad'])*(1 if name=='rg2_finger_joint' or 'inner_finger' in name else -1)
    # Initialization precedes native controller ownership, as in sim_host.
    robot.set_joint_positions(positions); robot.set_joint_velocities(np.zeros(len(names)))
    robot.apply_action(ArticulationAction(joint_positions=positions))
    for _ in range(60): world.step(render=True)
    import rclpy
    from controller_manager_msgs.srv import LoadController, ConfigureController, SwitchController
    rclpy.init(); node = rclpy.create_node('stage3_sim_capture')
    keys = og.Controller.Keys
    render_every = int(cfg.get('render_every_physics_steps', 1))
    if render_every < 1: raise ValueError('Positive render interval required')
    trigger = 'isaacsim.core.nodes.OnPhysicsStep' if render_every > 1 else 'omni.graph.action.OnPlaybackTick'
    pulse = 'step' if render_every > 1 else 'tick'
    clock_graph = {'graph_path':'/Stage3Clock','evaluator_name':'execution'}
    if render_every > 1: clock_graph['pipeline_stage'] = og.GraphPipelineStage.GRAPH_PIPELINE_STAGE_ONDEMAND
    og.Controller.edit(clock_graph, {
        keys.CREATE_NODES:[('Tick',trigger),('Time','isaacsim.core.nodes.IsaacReadSimulationTime'),('Clock','isaacsim.ros2.bridge.ROS2PublishClock')],
        keys.CONNECT:[('Tick.outputs:'+pulse,'Clock.inputs:execIn'),('Time.outputs:simulationTime','Clock.inputs:timeStamp')]})
    timeline = omni.timeline.get_timeline_interface(); timeline.pause(); app.update()
    if not backend.is_ready(): raise RuntimeError('Native SIM backend not ready')
    xml = physics_mimic_control_xml(ros2_control_manager.build_full_urdf(stage,'/World/Robot'))
    ros2_control_manager.build_full_urdf = lambda *args,**kwargs: xml
    if Ros2ControlManager.setup('/World/Robot', cfg.get('controller_config_path',str(ROOT/'config/controllers.yaml')), namespace='sim/m0609',
                               publish_robot_description=False,use_sim_time=True) != 0:
        raise RuntimeError('Native SIM controller setup failed')
    timeline.play()
    steps = 0
    def tick():
        nonlocal steps
        rclpy.spin_once(node,timeout_sec=0)
        source_hooks=cfg.get('source_render_hooks_provider',lambda:None)()
        if render_every==1 and source_hooks is not None:
            world.step(render=False,update_fabric=True)
            source_hooks.before_render()
            world.render()
            source_hooks.after_render()
        elif render_every == 1: world.step(render=True)
        else:
            # Render without advancing physics a second time. The ROS clock
            # remains driven by every physics step, independently of the UI.
            world.step(render=False,update_fabric=True)
            steps += 1
            if steps % render_every == 0:
                if source_hooks is not None: source_hooks.before_render()
                world.render()
                if source_hooks is not None: source_hooks.after_render()
    for service,cls,controllers in (
            ('load_controller',LoadController,['joint_state_broadcaster','arm_controller','gripper_controller']),
            ('configure_controller',ConfigureController,['joint_state_broadcaster','arm_controller','gripper_controller'])):
        client = node.create_client(cls,'/sim/m0609/controller_manager/'+service)
        for name in controllers:
            end = time.monotonic()+30
            while not client.service_is_ready() and time.monotonic()<end: tick()
            if not client.service_is_ready(): raise RuntimeError('Native service unavailable: '+service)
            future = client.call_async(cls.Request(name=name))
            while not future.done() and time.monotonic()<end: tick()
            if not future.done() or not future.result().ok: raise RuntimeError('Native controller load/configure failed')
    client = node.create_client(SwitchController,'/sim/m0609/controller_manager/switch_controller')
    end = time.monotonic()+30
    while not client.service_is_ready() and time.monotonic()<end: tick()
    if not client.service_is_ready(): raise RuntimeError('Native switch service unavailable')
    request = SwitchController.Request(activate_controllers=['joint_state_broadcaster','arm_controller','gripper_controller'],strictness=2)
    request.timeout.sec = 15; future = client.call_async(request)
    while not future.done() and time.monotonic()<end: tick()
    if not future.done() or not future.result().ok: raise RuntimeError('Native controller activation failed')
    return world,robot,node,tick


def run_capture(app, args, out, isolated_domain=93):
    if (isolated_domain not in (93,194) or os.environ.get('ROS_DOMAIN_ID') != str(isolated_domain)
            or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'):
        raise ValueError('Capture requires its explicit isolated SIM domain/LOCALHOST')
    if args.model_bundle is None or bool(args.archive_postures)==bool(args.capture_setup) or args.auto_start:
        raise ValueError('Explicit model/posture references required; legacy auto-start is unavailable')
    folder = args.capture_scene.resolve()
    seed = json.loads((folder/'scene.seed.json').read_text())
    motion = json.loads((folder.parent/'prepared_input/motion.request.json').read_text())
    if args.capture_setup:
        from prepare_taught_sim import prepare_taught_capture_setup
        setup = prepare_taught_capture_setup(seed,motion,args.model_bundle,args.capture_setup)
    else:
        setup = prepare_capture_setup(seed,motion,args.model_bundle,args.archive_postures)
    cfg = json.loads((ROOT/'config/contact.sim.json').read_text())
    if getattr(args,'source_depth_baseline',False):
        if isolated_domain!=194 or not getattr(args,'fresh_moveit_baseline',False):raise ValueError('SOURCE_BASELINE_FRESH_SIM194_ONLY')
        cfg['source_render_hooks_provider']=lambda:getattr(args,'source_render_hooks',None)
    wrist_reference=getattr(args,'wrist_runtime_reference',None)
    if wrist_reference:
        if isolated_domain!=194 or (args.sim_transport and not getattr(args,'depth_owner_test',False)) or not getattr(args,'wrist_depth_hook',None):
            raise ValueError('Wrist reference is isolated capture-only SIM')
        cfg['controller_config_path']=str(wrist_reference['controller_config_path'])
        cfg['render_every_physics_steps']=1
    if getattr(args,'source_depth_baseline',False):
        cadence=getattr(args,'source_render_every_physics_steps',1)
        if type(cadence) is not int or cadence not in (1,4):
            raise ValueError('SOURCE_RENDER_CADENCE_MUST_BE_1_OR_4')
        cfg['render_every_physics_steps']=cadence
    if getattr(args,'sim_solver_type','TGS')=='PGS':
        if isolated_domain!=194 or not getattr(args,'tracking_audit',False) or not getattr(args,'sim_fixed_base_root',False):
            raise ValueError('PGS trial requires audited isolated fixed-base SIM')
        cfg['sim_solver_type']='PGS'
    if getattr(args,'sim_fixed_base_root',False):
        if isolated_domain!=194 or not getattr(args,'tracking_audit',False) or not args.sim_transport:
            raise ValueError('Fixed-base correction is audited isolated SIM only')
        cfg['sim_fixed_base_root']=True
    position_iterations=getattr(args,'sim_tgs_position_iterations',None)
    velocity_iterations=getattr(args,'sim_tgs_velocity_iterations',None)
    if position_iterations is not None or velocity_iterations is not None:
        if isolated_domain!=194 or not getattr(args,'tracking_audit',False) or getattr(args,'sim_arm_servo','position')!='velocity-pi':
            raise ValueError('Solver trial requires explicit audited isolated velocity PI')
        if position_iterations not in (None,1,4,8,16,128) or velocity_iterations not in (None,1,16):
            raise ValueError('Unsupported solver iteration trial')
        setup['solver_iterations']=dict(setup['solver_iterations'])
        if position_iterations is not None:setup['solver_iterations']['position']=position_iterations
        if velocity_iterations is not None:setup['solver_iterations']['velocity']=velocity_iterations
    if args.capture_setup:
        cfg['physics_dt_s']=setup['physics_dt_s']
        if any(setup['sim_gripper'][key]!=cfg['gripper'][key] for key in ('open_q_rad','close_q_rad')):
            raise ValueError('Declared SIM gripper preset differs from configured model')
    if getattr(args,'tracking_audit',False):
        import yaml
        rate=args.sim_controller_rate
        if isolated_domain!=194 or not args.sim_transport or rate not in (60,120):
            raise ValueError('Controller trial is isolated cuMotion SIM only')
        controllers=yaml.safe_load((ROOT/'config/controllers.yaml').read_text())
        from sim_tracking import controller_trial
        controllers=controller_trial(controllers,rate,getattr(args,'sim_arm_servo','position'))
        path=out/'tracking.controllers.yaml';path.write_text(yaml.safe_dump(controllers,sort_keys=False))
        cfg['controller_config_path']=str(path)
    if getattr(args,'sim_tgs_forces_every_iteration',False):
        if isolated_domain!=194 or not args.sim_transport or not getattr(args,'tracking_audit',False):
            raise ValueError('TGS trial is isolated audited cuMotion SIM only')
        cfg['sim_tgs_forces_every_iteration']=True
    checkpoint=getattr(args,'fixed_checkpoint',None)
    if checkpoint:
        route=checkpoint_transport_route(args,isolated_domain)
        save(out/'checkpoint_restore_route.json',dict(route=route,scope='SIM_INITIALIZATION_ONLY_NOT_PLANNING_OR_EXECUTION_APPROVAL'))
        setup['initial_q_rad']=list(checkpoint['q_rad'])
        cfg['gripper']['initial_q_rad']=float(checkpoint['grip_rad'])
    save(out/'capture_setup.json',setup)
    import omni.usd, omni.timeline
    from pxr import Usd, UsdGeom, UsdPhysics, PhysxSchema, PhysicsSchemaTools
    from omni.physx import get_physx_simulation_interface
    context = omni.usd.get_context(); context.open_stage(str(folder/'scene.usda'))
    stage = context.get_stage(); stage.SetEditTarget(stage.GetSessionLayer())
    if wrist_reference:
        joint=stage.GetPrimAtPath(wrist_reference['gripper_drive']['path'])
        drive=UsdPhysics.DriveAPI.Get(joint,'angular')
        if not drive:raise ValueError('Reference native gripper drive missing')
        drive.GetMaxForceAttr().Set(wrist_reference['gripper_drive']['nominal_test_max_force'])
        drive.GetDampingAttr().Set(wrist_reference['gripper_drive']['nominal_test_damping'])
    read_scene_geometry(stage,seed)  # Reject changed inventory/geometry before any initialization or goal.
    selected = next(o for o in seed['world_objects'] if o['id']==setup['source_slot_id'])
    transport_active=False
    from prepare_cpu_model import read_model_bundle
    import xml.etree.ElementTree as ET
    model_bundle=read_model_bundle(args.model_bundle)
    allowed_self={frozenset((item.get('link1'),item.get('link2')))
                  for item in ET.fromstring(model_bundle['robot_description_semantic']).findall('disable_collisions')}
    block = stage.GetPrimAtPath(selected['prim_path']); fingers = set(); finger_shapes = {}; guard_hits = []
    interactive = args.capture_interactive
    if interactive:
        import omni.ui as ui
        from omni.kit.viewport.utility import get_active_viewport
        from pxr import Gf
        camera=UsdGeom.Camera.Define(stage,'/World/CaptureCamera')
        transform=camera.AddTransformOp(); camera.CreateFocalLengthAttr(28)
        camera.CreateClippingRangeAttr(Gf.Vec2f(.001,100))
        get_active_viewport().set_active_camera(str(camera.GetPath()))
        centre=np.asarray(UsdGeom.Xformable(block).ComputeLocalToWorldTransform(Usd.TimeCode.Default()))[3,:3]
        def view(close=False):
            target=centre+np.array([0,0,.065]) if close else np.array([0,0,.23])
            eye=target+np.array([.18,-.38,.25]) if close else np.array([.25,-1.2,.90])
            transform.Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse())
        view()
        started=False
        def start():
            nonlocal started
            started=True; start_button.enabled=False
            save(out/'capture_ui_status.json',dict(visible=True,waiting_for_start=False,paused=False,source_slot_id=setup['source_slot_id']))
        window=ui.Window(getattr(args,'capture_window_title','Seeun / Stage 5 transport' if args.sim_transport else 'Seeun / SIM grasp capture'),width=480,height=315)
        with window.frame:
            with ui.VStack(spacing=8):
                ui.Label('Latest D pickup pose / supply slots 1-5 / nominal SIM',height=30)
                ui.Label('Capture case: '+setup.get('fresh_capture_case','D taught pickup').replace('_',' '),height=24)
                phase_label=ui.Label('Loading native SIM controller...',height=60,word_wrap=True)
                start_button=ui.Button('Start grasp test',clicked_fn=start,height=38,enabled=False)
                with ui.HStack():
                    ui.Button('Overview',clicked_fn=lambda:view(False))
                    ui.Button('Gripper close-up',clicked_fn=lambda:view(True))
                if args.sim_transport:
                    ui.Button('STOP transport (no open / no automatic resume)',clicked_fn=lambda:(out/'stop.request').touch(),height=35)
                ui.Label('Fresh grasp -> MoveIt -> full native transport -> hold at D waiting pose.\nNo insertion or opening.' if args.sim_transport else
                         'Grasp -> 30 mm lift -> return. Result stays paused.\nAssembly transport is the next development stage.',height=45,word_wrap=True)
        def keep_paused(message,success):
            omni.timeline.get_timeline_interface().pause(); phase_label.text=message
            save(out/'capture_ui_status.json',dict(visible=True,waiting_for_start=False,paused=True,result_success=success,
                                                  source_slot_id=setup['source_slot_id']))
            while app.is_running() and not (out/'shutdown.request').exists():
                if omni.timeline.get_timeline_interface().is_playing(): omni.timeline.get_timeline_interface().pause()
                app.update(); time.sleep(1/60)
    contact_trace = (out/'contact_reports.jsonl').open('w')
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI): PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr(0)
    def contact(headers,data):
        for header in headers:
            paths = [str(PhysicsSchemaTools.intToSdfPath(header.actor0)),str(PhysicsSchemaTools.intToSdfPath(header.actor1))]
            contacts = [data[i] for i in range(header.contact_data_offset,header.contact_data_offset+header.num_contact_data)]
            row = dict(actors=paths,contact_count=len(contacts),
                       minimum_separation_m=min((float(c.separation) for c in contacts),default=None),
                       maximum_impulse_ns=max((float(np.linalg.norm(np.asarray(c.impulse))) for c in contacts),default=0))
            contact_trace.write(json.dumps(row)+'\n'); contact_trace.flush()
            near,force_bearing = contact_state(row)
            blocked=near
            if transport_active:
                from d_sim_transport import physical_contact
                blocked=physical_contact(row)
            robots = [p for p in paths if p.startswith('/World/Robot/')]
            env = [p for p in paths if p.startswith('/World/Environment/') or p in getattr(args,'fixed_obstacle_prim_paths',[])]
            if selected['prim_path'] in paths:
                other = paths[1] if paths[0]==selected['prim_path'] else paths[0]
                name = other.rsplit('/',1)[-1]
                if name in ('rg2_left_inner_finger','rg2_right_inner_finger'):
                    # One body/stud candidate must not erase another loaded collider.
                    key = (header.collider0,header.collider1)
                    finger_shapes[key] = (name,force_bearing)
                    fingers.clear(); fingers.update(n for n,loaded in finger_shapes.values() if loaded)
                else:
                    support=getattr(args,'source_support_contact',None)
                    intended_support=(support(row) if transport_active and support is not None and isolated_domain==194 and (getattr(args,'prepared_transport',None) or getattr(args,'fresh_moveit_baseline',False)) else False)
                    if blocked and not intended_support and (transport_active or not other.startswith('/World/Environment/SupplyBoard')):guard_hits.append(row)
            elif robots and env and blocked: guard_hits.append(row)
            elif transport_active and len(robots)==2 and blocked:
                links=[p.rsplit('/',1)[-1] for p in robots]
                if links[0]!=links[1] and frozenset(links) not in allowed_self: guard_hits.append(row)
    subscription = get_physx_simulation_interface().subscribe_contact_report_events(contact)
    world,robot,node,raw_tick = initialize_native(app,stage,setup,cfg)
    import rclpy
    from rclpy.action import ActionClient
    from action_msgs.msg import GoalStatusArray
    from control_msgs.action import FollowJointTrajectory
    from trajectory_msgs.msg import JointTrajectoryPoint
    from isaacsim.ros2.control import Ros2ControlManager
    from prepare_gpu_scene import tcp_fk
    from prepare_cpu_model import read_model_bundle
    bundle = read_model_bundle(args.model_bundle)
    names = robot.dof_names; arm = [names.index('joint_'+str(i)) for i in range(1,7)]; grip = names.index('rg2_finger_joint')
    tracking_snapshot=None;tracking_close=None
    if getattr(args,'tracking_audit',False) or getattr(args,'depth_owner_test',False):
        from sim_tracking import install_tracking
        view=robot._articulation_view._physics_view
        meta=view.get_metatype(0)
        if getattr(args,'sim_fixed_base_root',False) and not meta.fixed_base:
            raise ValueError('Fixed-base correction is not active in native physics')
        save(out/'articulation_snapshot.json',dict(fixed_base=bool(meta.fixed_base),
            link_names=list(meta.link_names),joint_names=list(meta.joint_names),
            root_pose_xyz_xyzw=np.asarray(view.get_root_transforms(),dtype=float)[0].tolist(),
            scope='READ_ONLY_NATIVE_ARTICULATION_METADATA'))
        scenes=[p for p in stage.Traverse() if p.IsA(UsdPhysics.Scene)]
        save(out/'physics_scene_snapshot.json',dict(scenes=[dict(path=str(p.GetPath()),
            solver_type=PhysxSchema.PhysxSceneAPI(p).GetSolverTypeAttr().Get(),
            external_forces_every_iteration=PhysxSchema.PhysxSceneAPI(p).GetEnableExternalForcesEveryIterationAttr().Get()) for p in scenes],
            scope='READ_ONLY_SIM_NUMERICAL_SETTINGS',hardware_execution_allowed=False))
        tracking_snapshot,tracking_close=install_tracking(world,robot,node,out,arm)
    gains=robot.get_articulation_controller().get_gains()
    save(out/'native_drive_snapshot.json',dict(dof_names=names,kps=np.asarray(gains[0]).tolist(),
        kds=np.asarray(gains[1]).tolist(),solver_iterations=setup.get('solver_iterations',dict(position=64,velocity=4)),
        scope='READ_ONLY_NATIVE_PHYSICS_GAINS_BEFORE_TEST'))
    statuses = {'arm_controller':None,'gripper_controller':None}; active_goals = []; phase='INITIALIZED'
    capture_event=getattr(args,'capture_event_hook',None)
    def emit(kind,payload):
        if capture_event:capture_event(kind,payload,float(world.current_time))
    def status_callback(msg,key):
        statuses[key]=[int(s.status) for s in msg.status_list]
        header=getattr(msg,'header',None)
        emit('COMMAND_COUNTS',dict(controller=key,header_ns=header.stamp.sec*10**9+header.stamp.nanosec if header is not None else None,
            statuses=[dict(goal_id=bytes(s.goal_info.goal_id.uuid).hex(),status=int(s.status),
                goal_stamp_ns=s.goal_info.stamp.sec*10**9+s.goal_info.stamp.nanosec) for s in msg.status_list]))
    for name in statuses:
        node.create_subscription(GoalStatusArray,'/sim/m0609/'+name+'/follow_joint_trajectory/_action/status',
            lambda msg,key=name:status_callback(msg,key),10)
    def matrix(prim): return np.asarray(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T
    tcp_prim = stage.GetPrimAtPath(seed['robot_tcp_prim'])
    def sample():
        all_q=robot.get_joint_positions(); tcp=matrix(tcp_prim); body=matrix(block)
        base=matrix(stage.GetPrimAtPath(seed['robot_base_prim']))
        row=dict(time_s=world.current_time,q_rad=all_q[arm].tolist(),grip_rad=float(all_q[grip]),
            tcp_pose=matrix_pose(np.linalg.inv(base)@tcp),
            velocity_rad_s=robot.get_joint_velocities()[[*arm,grip]].tolist(),body_z_m=float(body[2,3]),
            attachment=(np.linalg.inv(tcp)@body).tolist(),contact_fingers=sorted(fingers))
        if tracking_snapshot:row['tracking']=tracking_snapshot()
        if getattr(args,'depth_owner_test',False):row['step_readout']=getattr(args,'last_step_readout',None)
        return row
    if getattr(args,'depth_owner_test',False):
        original_raw_tick=raw_tick
        def raw_tick():
            before_q=robot.get_joint_positions();before_v=robot.get_joint_velocities();before_time=float(world.current_time)
            original_raw_tick()
            if getattr(args,'live_transport',None):
                for _ in range(64):rclpy.spin_once(node,timeout_sec=0)
            args.last_step_readout=dict(before_stamp_s=before_time,after_stamp_s=float(world.current_time),
                dof_names=names,arm_dof_indices=arm,units='RAD_AND_RAD_PER_SECOND',
                pre_q_rad=before_q[arm].tolist(),pre_native_v_rad_s=before_v[arm].tolist(),
                post_q_rad=robot.get_joint_positions()[arm].tolist(),post_native_v_rad_s=robot.get_joint_velocities()[arm].tolist(),
                method='SAME_DOF_SINGLE_ARTICULATION_PRE_POST_WORLD_STEP',
                direct_physics_q_rad=np.asarray(robot._articulation_view._physics_view.get_dof_positions())[0,arm].tolist(),
                direct_physics_v_rad_s=np.asarray(robot._articulation_view._physics_view.get_dof_velocities())[0,arm].tolist())
    trace=(out/'capture_observations.jsonl').open('w')
    def tick():
        wall_start=time.monotonic()
        raw_tick(); row=sample(); trace.write(json.dumps(dict(row,phase=phase))+'\n')
        if interactive:
            phase_label.text=phase.replace('_',' ')+'\nNative controller running; observing contacts and stop.'
            time.sleep(max(0,cfg['physics_dt_s']-(time.monotonic()-wall_start)))
        if guard_hits: raise RuntimeError('Unexpected SIM contact: '+str(guard_hits[-1]))
        if (out/'shutdown.request').exists(): raise RuntimeError('Stage3 capture shutdown requested')
    def goal(controller,joints,start,target,duration,*,operation_wall_timeout_s=60.):
        nonlocal phase
        phase = controller+'_GOAL'
        client=ActionClient(node,FollowJointTrajectory,'/sim/m0609/'+controller+'/follow_joint_trajectory')
        if operation_wall_timeout_s!=60. and not (operation_wall_timeout_s==120. and controller=='gripper_controller' and duration==8. and os.environ.get('ROS_DOMAIN_ID')=='194' and os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')=='LOCALHOST'):
            raise ValueError('SIM194_BOOTSTRAP_GRIPPER_OPERATION_BUDGET_ONLY')
        operation_start=time.monotonic();start_observation=sample();end=operation_start+operation_wall_timeout_s
        while not client.server_is_ready() and time.monotonic()<end: tick()
        if not client.server_is_ready(): raise RuntimeError('Native trajectory action unavailable')
        request=FollowJointTrajectory.Goal(); request.trajectory.joint_names=joints
        for t in np.linspace(0,duration,61):
            u=float(t/duration); s=10*u**3-15*u**4+6*u**5
            v=(30*u**2-60*u**3+30*u**4)/duration; a=(60*u-180*u**2+120*u**3)/duration**2
            delta=np.asarray(target)-start; positions=(np.asarray(start)+s*delta).tolist()
            q=positions if len(joints)==6 else sample()['q_rad']; g=positions[0] if len(joints)==1 else sample()['grip_rad']
            tcp_fk(bundle,q,g)
            point=JointTrajectoryPoint(positions=positions,velocities=(v*delta).tolist(),accelerations=(a*delta).tolist())
            point.time_from_start.sec=int(t); point.time_from_start.nanosec=round((float(t)-int(t))*1e9)
            request.trajectory.points.append(point)
        goal_uuid=None
        if capture_event:
            import uuid
            from unique_identifier_msgs.msg import UUID
            goal_uuid=UUID(uuid=list(uuid.uuid4().bytes))
        emit('SUBMISSION_INTENT',dict(controller=controller,joints=joints,duration_s=duration,source_q=sample()['q_rad'],
            goal_id=bytes(goal_uuid.uuid).hex() if goal_uuid else None))
        future=client.send_goal_async(request,**({'goal_uuid':goal_uuid} if goal_uuid else {}))
        emit('GOAL_SUBMITTED',dict(controller=controller,request_issued=True,goal_id=bytes(goal_uuid.uuid).hex() if goal_uuid else None))
        while not future.done() and time.monotonic()<end: tick()
        if not future.done() or not future.result().accepted: raise RuntimeError('Native trajectory rejected/timed out')
        handle=future.result(); active_goals.append(handle); result=handle.get_result_async()
        emit('GOAL_ACCEPTED',dict(controller=controller,accepted=bool(handle.accepted),goal_id=bytes(handle.goal_id.uuid).hex()))
        while not result.done() and time.monotonic()<end: tick()
        done=result.done();response=result.result() if done else None;finished=time.monotonic()
        save(out/('bootstrap_'+controller+'_'+str(int(operation_start*1e9))+'.operation.json'),dict(
            scope='SIM_CLIENT_OPERATION_WAIT_NOT_CONTROLLER_LIMIT_OR_SDK_CRITERION',controller=controller,
            operation_wall_budget_s=operation_wall_timeout_s,operation_start_wall_monotonic_s=operation_start,
            observation_wall_monotonic_s=finished,elapsed_wall_s=finished-operation_start,
            command_duration_SIM_s=duration,result_pending=not done,
            actual_status=None if response is None else int(response.status),
            actual_error_code=None if response is None else int(response.result.error_code),
            actual_error_string=None if response is None else response.result.error_string,
            actual_goal_id=bytes(handle.goal_id.uuid).hex(),source_start_observation=start_observation,
            source_final_observation=sample(),success=done and response.status==4 and response.result.error_code==0))
        if not done or response.status!=4 or response.result.error_code!=0:
            raise RuntimeError('Native trajectory did not complete successfully')
        emit('GOAL_RESULT',dict(controller=controller,goal_id=bytes(handle.goal_id.uuid).hex(),
            status=int(result.result().status),error_code=int(result.result().result.error_code)))
        active_goals.remove(handle); phase=controller+'_SUCCEEDED'
    try:
        if interactive:
            omni.timeline.get_timeline_interface().pause(); start_button.enabled=True
            phase_label.text='Ready. Press Start grasp test to watch the test at real time.'
            save(out/'capture_ui_status.json',dict(visible=True,waiting_for_start=True,source_slot_id=setup['source_slot_id']))
            deadline=time.monotonic()+args.capture_delay_s if args.capture_delay_s is not None else None
            while app.is_running() and not started and not (out/'shutdown.request').exists():
                if omni.timeline.get_timeline_interface().is_playing(): omni.timeline.get_timeline_interface().pause()
                if deadline is not None:
                    phase_label.text=f'Ready. Test starts in {max(0,deadline-time.monotonic()):.1f}s.\n'+('Fresh grasp, then MoveIt transport to D waiting pose.' if args.sim_transport else 'Grasp -> 30 mm lift -> return; no assembly transport.')
                    if time.monotonic()>=deadline:start()
                app.update(); time.sleep(1/60)
            if not started or not app.is_running(): raise RuntimeError('Interactive test closed before Start')
            omni.timeline.get_timeline_interface().play()
        restore_hook=getattr(args,'checkpoint_restore_hook',None)
        if restore_hook:
            samples,holding_proof=restore_hook(world,robot,node,sample,tick,goal,statuses)
        else:
            initial=sample(); initial_z=initial['body_z_m']
            goal('arm_controller',['joint_'+str(i) for i in range(1,7)],initial['q_rad'],initial['q_rad'],1)
            goal('gripper_controller',['rg2_finger_joint'],[sample()['grip_rad']],[cfg['gripper']['close_q_rad']],8)
            end_sim=world.current_time+cfg['gripper']['minimum_close_settle_s']
            while world.current_time<end_sim: tick()
            goal('arm_controller',['joint_'+str(i) for i in range(1,7)],sample()['q_rad'],setup['lift_q_rad'],3)
            phase='POST_LIFT_OBSERVATION'; samples=deque(); end_sim=world.current_time+3
            while world.current_time<end_sim:
                tick(); samples.append(sample())
                while samples[-1]['time_s']-samples[0]['time_s']>1: samples.popleft()
            counts=command_counts(statuses)
            if active_goals or any(counts.values()): raise RuntimeError('Native SIM commands still active/pending')
            verified_hold(list(samples),initial_z,cfg['contact_demo'])
            holding_proof = dict(body_lift_m=samples[-1]['body_z_m']-initial_z,
                evidence_ref=str((out/'capture_observations.jsonl').resolve()),sample=samples[-1])
            if setup.get('return_to_pickup_before_capture'):
                attachment=np.array(samples[-1]['attachment'])
                goal('arm_controller',['joint_'+str(i) for i in range(1,7)],sample()['q_rad'],setup['initial_q_rad'],3)
                phase='PICKUP_RETURN_OBSERVATION'; samples=deque(); end_sim=world.current_time+3
                while world.current_time<end_sim:
                    tick(); samples.append(sample())
                    while samples[-1]['time_s']-samples[0]['time_s']>1: samples.popleft()
                from sim_utils import error
                for row in samples:
                    drift=error(attachment,np.array(row['attachment']))
                    if (row['contact_fingers']!=['rg2_left_inner_finger','rg2_right_inner_finger'] or
                            drift[0]>cfg['contact_demo']['position_drift_tolerance_m'] or
                            drift[1]>cfg['contact_demo']['orientation_drift_tolerance_rad']):
                        raise ValueError('Grasp not retained after returning to taught pickup')
                counts=command_counts(statuses)
                if active_goals or any(counts.values()): raise RuntimeError('Return commands still active/pending')
                verified_stop(list(samples))
        counts=command_counts(statuses)
        controls=dict(source_kind='ISAAC_SIM_SAVED_STATE',evidence_ref=str((out/'capture_observations.jsonl').resolve()),
            a_context=seed['a_context'],reservation_binding=seed['reservation_binding'],current_revision=seed['current']['current_revision'],
            timeline_paused=True,holding_confirmed=True,stopped_verified=True,virtual_attachment_used=False,
            grasp_kind='DYNAMIC_CONTACT_GRASP',stop_observation_duration_s=samples[-1]['time_s']-samples[0]['time_s'],
            position_observations=list(samples),stop_metrics=verified_stop(list(samples)),
            native_action_statuses=statuses,ros_domain_id=isolated_domain,holding_proof=holding_proof,
            capture_boundary='TAUGHT_PICKUP_AFTER_GRASP_PROOF' if args.capture_setup else 'POST_LIFT',
            d_gripper_reference=seed.get('d_gripper_reference'),physics_dt_s=cfg['physics_dt_s'],
            render_every_physics_steps=cfg.get('render_every_physics_steps',1),
            clock_trigger='OnPhysicsStep' if cfg.get('render_every_physics_steps',1)>1 else 'OnPlaybackTick',
            solver_iterations=setup.get('solver_iterations',dict(position=64,velocity=4)),**counts)
        omni.timeline.get_timeline_interface().pause(); app.update(); trace.flush()
        if omni.timeline.get_timeline_interface().is_playing(): raise RuntimeError('SIM did not pause')
        save(out/'control_observation.json',controls)
        checks=capture_post_grasp(stage,robot,seed,motion,args.model_bundle,controls,out/'capture')
        save(out/'capture_status.json',dict(success=True,scope='STAGE3_NEW_SIM_CONTACT_CAPTURE',checks=checks,
            old_observation_reused_as_current=False,MoveIt_solver_run=False,assembly_transport_executed=False,hardware_execution_allowed=False))
        wrist_hook=getattr(args,'wrist_depth_hook',None)
        if wrist_hook:
            wrist_hook(app,stage,world,robot,raw_tick,seed,motion,controls,sample,statuses,out,args.model_bundle)
        if args.sim_transport and not getattr(args,'tracking_capture_only',False):
            from d_sim_transport import run_transport
            def set_phase(value):
                nonlocal phase
                phase=value
                if interactive:phase_label.text=value.replace('_',' ')+'\nHolding block; no opening or contact insertion.'
            transport_active=True
            transport_stop_samples=getattr(getattr(args,'live_transport',None),'bootstrap_rows',list(samples))
            result=run_transport(app,args,out,motion,sample,raw_tick,world,node,statuses,guard_hits,transport_stop_samples,set_phase,
                                 lambda:read_scene_geometry(stage,seed)[0])
            after_transport=getattr(args,'after_transport_hook',None)
            if after_transport:after_transport(app,stage,world,robot,raw_tick,seed,motion,controls,sample,statuses,out,args.model_bundle,result)
            flush=getattr(args,'source_depth_flush_hook',None)
            if flush:flush(app,sample,statuses)
            if interactive:
                keep_paused('Transport result saved. Grasp/stop evidence recorded; no automatic contact.',
                            result.get('success',False) or result.get('expected_stop_test_verified',False) or result.get('conservative_stop_verified',False))
        elif interactive:
            keep_paused('PASS: grasp, lift, return and stop verified.\nSaved fresh SIM state. Use the view buttons to inspect.',True)
    except Exception:
        save(out/('transport_failure.json' if args.sim_transport else 'capture_failure.json'),dict(success=False,error=traceback.format_exc()))
        if interactive and app.is_running():
            keep_paused('FAIL: test paused.\nFailure evidence saved; no contact handoff or automatic resume.',False)
        raise
    finally:
        if tracking_close:tracking_close()
        for handle in active_goals: handle.cancel_goal_async()
        trace.close(); contact_trace.close(); subscription=None
        Ros2ControlManager.teardown('/World/Robot'); omni.timeline.get_timeline_interface().stop()
        node.destroy_node(); rclpy.shutdown()
