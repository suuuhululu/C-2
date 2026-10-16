"""Prepare/inspect a nominal cuMotion model from a bound saved SIM request.

This does not plan, execute, create readiness, or connect to ROS/Isaac/robots.
"""
import argparse
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import sys
import shutil
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from scipy.spatial.transform import Rotation
import yaml

from cumotion_geometry import (read_closed_stl, mesh_spheres, box_spheres, object_boxes,
                               voxel_envelope, cloud_node, split_cloud, sphere_contacts)
from cumotion_geometry import box_cells, cell_spheres, split_box_cell
from prepare_cpu_model import read_model_bundle, file_hash
from plan_only import JOINTS, BINDING, prepare_request, prepare_d_candidate, digest, checked_pose, SIM_KIND

TCP = "GripperDA_v4_tcp"
TOUCH = ["rg2_left_inner_finger", "rg2_right_inner_finger"]


@lru_cache(maxsize=16)
def _parsed_model_yaml(content_sha256, text):
    # Installed PyYAML/libyaml safe constructor; no new dependency or loader
    # fallback. Exact-content LRU and independent source validation stay intact.
    return yaml.load(text,Loader=yaml.CSafeLoader)


def load_model_yaml(text):
    """Reuse pure parsing only; callers still verify every external source.

    Both SHA and exact bytes identify the value. A new source or changed file
    is parsed again, and a caller cannot mutate the retained parsed document.
    No owner, clock, Depth, STOP or validation verdict is cached here.
    """
    return deepcopy(_parsed_model_yaml(sha256(text.encode()).hexdigest(), text))


def verify_request(path, *, allow_fixture_cpu=False,allow_geometry_cpu=False):
    """SDK callers keep the default; CPU consumer tests explicitly opt in."""
    return _verify_request(path,allow_fixture_cpu=allow_fixture_cpu,allow_geometry_cpu=allow_geometry_cpu)[0]


def _verify_request(path, *, allow_fixture_cpu=False,allow_geometry_cpu=False):
    """Return the receipt already verified in this invocation, never cache it."""
    request = load_model_yaml(path.read_text())
    if request["confirmation_kind"] != SIM_KIND:
        raise ValueError("This first model stage accepts archived nominal SIM only")
    state_ref=request['simulation_provenance']['files']['state']
    if file_hash(Path(state_ref['path']))!=state_ref['sha256']:raise ValueError('SAVED_STATE_SOURCE_CHANGED')
    source_state=json.loads(Path(state_ref['path']).read_text())
    static=(path.parent/'static_calculation.admission.json').exists()
    dynamic=(path.parent/'dynamic_input.envelope.json').exists()
    bounded=(path.parent/'bounded_sim_admission.json').exists()
    live_candidate=(dynamic and bounded and json.loads((path.parent/'dynamic_input.envelope.json').read_text()).get('initial_condition_mode')=='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE')
    if source_state.get('calculation_scope')=='GEOMETRY_ALIGNMENT_ONLY_PENDING_OPTIMIZER_REST' and not (allow_geometry_cpu or static or live_candidate):
        raise ValueError('GEOMETRY_ONLY_INPUT_PENDING_OPTIMIZER_REST')
    fixture=request["simulation_provenance"]["source_kind"]=='SIM_CONTRACT_FIXTURE'
    if request["simulation_provenance"]["source_kind"] != "ISAAC_SIM_SAVED_STATE" and not (
            fixture and (allow_fixture_cpu or (bounded and dynamic))):
        raise ValueError("An actual archived SIM capture is required, not a contract fixture")
    if request["model_bundle"] != read_model_bundle(request["model_bundle"]["bundle_path"]):
        raise ValueError("Bound source model differs from verified bundle")
    manifest = json.loads((Path(request["model_bundle"]["bundle_path"]) / "MODEL_MANIFEST.json").read_text())
    if "kinematic_alignment" in manifest:
        raise ValueError("Do not mix a REAL aligned model into nominal SIM")
    motion = json.loads((path.parent / "motion.request.json").read_text())
    result = json.loads((path.parent / "motion.result.json").read_text())
    if dynamic:
        from dynamic_cumotion_inputs import verify_prepared
        derived=verify_prepared(path,request)
    else:
        derived=prepare_request(motion,result,request["source_snapshot"],request["model_bundle"]["bundle_path"])
    if digest(request) != digest(derived):
        raise ValueError("Saved prepared request differs from the common A boundary")
    bounded_admission=None
    if bounded:
        from dynamic_cumotion_inputs import verify_bounded_sim_admission
        bounded_admission=verify_bounded_sim_admission(path)
    context = json.loads((path.parent / "scene_context.json").read_text())
    if any(request[k] != context[k] for k in BINDING):
        raise ValueError("STALE_CONTEXT")
    state = request["planning_snapshot"]
    objects = state["world_objects"]
    supply = [o for o in objects if o["role"] in ("SUPPLY_BLOCK", "HELD_BLOCK")]
    expected = {f"{colour}_{kind}_{slot:02d}" for colour, kind in
                [("yellow", "2x2x1"), ("yellow", "2x3x1"), ("blue", "2x2x1"),
                 ("blue", "2x3x1"), ("red", "1x2x1")] for slot in range(1, 6)}
    if len(supply) != 25 or {o["id"] for o in supply} != expected:
        raise ValueError("Preserve all 25 supply positions with slot6 empty")
    if static:
        from stationary_sim_calculation import verify_static_request
        verify_static_request(path,request)
    return request,bounded_admission


def urdf_transforms(robot, q, grip):
    """Independent URDF FK for every downstream arm/finger/TCP frame."""
    values = dict(zip(JOINTS, q)) | {"rg2_finger_joint": grip}
    joints = robot.findall("joint")
    for joint in joints:
        mimic = joint.find("mimic")
        if mimic is not None:
            values[joint.get("name")] = (values[mimic.get("joint")] *
                float(mimic.get("multiplier", "1")) + float(mimic.get("offset", "0")))
    frames = {"base_link": np.eye(4)}
    for _ in joints:
        for joint in joints:
            parent, child = joint.find("parent").get("link"), joint.find("child").get("link")
            if parent not in frames or child in frames:
                continue
            origin = joint.find("origin")
            local = np.eye(4)
            if origin is not None:
                local[:3, 3] = np.array(origin.get("xyz", "0 0 0").split(), float)
                local[:3, :3] = Rotation.from_euler("xyz", np.array(
                    origin.get("rpy", "0 0 0").split(), float)).as_matrix()
            motion = np.eye(4)
            if joint.get("type") == "revolute":
                axis = np.array(joint.find("axis").get("xyz").split(), float)
                motion[:3, :3] = Rotation.from_rotvec(axis * values[joint.get("name")]).as_matrix()
            elif joint.get("type") != "fixed":
                raise ValueError("Unsupported joint kind")
            frames[child] = frames[parent] @ local @ motion
    return frames


def make_world(request, cumotion):
    world = cumotion.create_world()
    mapping = []
    for obj in request["planning_snapshot"]["world_objects"]:
        if obj["id"] == request["planning_snapshot"]["selected_slot_id"]:
            continue
        padding = .002 if obj["role"] in ("SUPPLY_BLOCK", "CURRENT_BLOCK") else 0
        pieces = object_boxes(obj, checked_pose(obj["pose"]), padding)
        for size, transform in pieces:
            obstacle = cumotion.create_obstacle(cumotion.Obstacle.Type.CUBOID)
            obstacle.set_attribute(cumotion.Obstacle.Attribute.SIDE_LENGTHS, size)
            world.add_obstacle(obstacle, cumotion.Pose3(transform))
        mapping.append(dict(id=obj["id"], role=obj["role"], primitive_count=len(pieces), padding_m=padding))
    return world, mapping


def read_cumotion_model(folder, request_path):
    """Fail closed on model, attachment, binding or source changes."""
    manifest = json.loads((folder / "CUMOTION_MODEL_MANIFEST.json").read_text())
    request,admission=_verify_request(request_path)
    source=_bounded_source_from_receipt(request_path,admission) if admission is not None else None
    if manifest.get('bounded_sim_source')!=source:
        raise ValueError('cuMotion bounded SIM source/generation changed')
    if manifest.get('archived_static_source')!=static_model_source(request_path,request):
        raise ValueError('cuMotion static source/generation changed')
    if 'held_geometry_definition' in manifest:
        from held_geometry_inputs import nominal_definition
        held=next(o for o in request['planning_snapshot']['world_objects'] if o['id']==request['planning_snapshot']['selected_slot_id'])
        if manifest['held_geometry_definition']!=nominal_definition(held,request['model_bundle']):
            raise ValueError('cuMotion held geometry profile/source changed')
    if (manifest["execution_allowed"] is not False or manifest["hardware_execution_allowed"] is not False or
            manifest["source_request_sha256"] != file_hash(request_path) or
            manifest["source_model"] != request["model_bundle"] or
            manifest["binding"] != {k: request[k] for k in BINDING} or
            manifest["attachment"] != request["attachment"] or
            manifest["grip_rad"] != request["planning_snapshot"]["grip_rad"]):
        raise ValueError("cuMotion source/binding/attachment mismatch")
    for name, expected in manifest["files"].items():
        if file_hash(folder / name) != expected:
            raise ValueError("Derived cuMotion file changed: " + name)
    if 'held_body_refinement' in manifest:
        proof=manifest['held_body_refinement']['cell_proof']
        if file_hash(Path(proof['path']))!=proof['sha256']:raise ValueError('Held BODY cell proof changed')
    original = ET.fromstring(request["model_bundle"]["robot_description"])
    derived = ET.parse(folder / "robot.urdf").getroot()
    limits = load_model_yaml(request["model_bundle"]["joint_limits_yaml"])["joint_limits"]
    for name in JOINTS:
        original.find(f"joint[@name='{name}']/limit").set("velocity", str(limits[name]["max_velocity"]))
    for tree in (original, derived):
        for element in tree.iter():
            element.text = (element.text or "").strip() or None
            element.tail = None
    if ET.tostring(original) != ET.tostring(derived):
        raise ValueError("Derived URDF changed more than six arm velocity limits")
    return request, manifest


def static_model_source(request_path,request):
    if not (request_path.parent/'static_calculation.admission.json').exists():return None
    from stationary_sim_calculation import verify_static_request
    return verify_static_request(request_path,request)


def bounded_model_source(request_path):
    sidecar=request_path.parent/'bounded_sim_admission.json'
    if not sidecar.exists():return None
    from dynamic_cumotion_inputs import verify_bounded_sim_admission
    value=verify_bounded_sim_admission(request_path)
    return _bounded_source_from_receipt(request_path,value)


def _bounded_source_from_receipt(request_path,value):
    """Pure projection of this call's verified receipt; source SHA still reread."""
    return dict(sidecar_sha256=file_hash(request_path.parent/'bounded_sim_admission.json'),source_capture=value['source_capture'],
                prior_sha256=value['prior_sha256'],model_manifest_sha256=value['model_manifest_sha256'],
                audit_context=value['audit_context'],planner_context=value['planner_context'],valid_until_s=value['valid_until_s'])


def reuse_collision_geometry(old_model,old_request,new_request,output):
    """Copy proven full-volume geometry, never a path/result/world validation.

    The current model/held/grip/attachment must be identical. A new manifest and
    XRDF defaults bind the new request. GPU start/world/FK checks and whole-path
    FCL remain mandatory; conservative spheres may reject the changed world.
    """
    old,manifest=read_cumotion_model(old_model,old_request);fresh=verify_request(new_request)
    from held_geometry_inputs import nominal_definition
    def held(r):return next(o for o in r['planning_snapshot']['world_objects'] if o['id']==r['planning_snapshot']['selected_slot_id'])
    if (old['model_bundle']!=fresh['model_bundle'] or old['attachment']!=fresh['attachment'] or
            old['planning_snapshot']['grip_rad']!=fresh['planning_snapshot']['grip_rad'] or
            nominal_definition(held(old),old['model_bundle'])!=nominal_definition(held(fresh),fresh['model_bundle'])):
        raise ValueError('GEOMETRY_REUSE_REQUIRES_IDENTICAL_ROBOT_HELD_GRIP_ATTACHMENT')
    output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(old_model/'robot.urdf',output/'robot.urdf')
    xrdf=load_model_yaml((old_model/'robot.xrdf').read_text())
    xrdf['default_joint_positions'].update(dict(zip(JOINTS,fresh['planning_snapshot']['q_rad'])))
    (output/'robot.xrdf').write_text(yaml.safe_dump(xrdf,sort_keys=False))
    manifest=deepcopy(manifest)
    manifest.update(source_request=str(new_request.resolve()),source_request_sha256=file_hash(new_request),
        binding={k:fresh[k] for k in BINDING},source_model=fresh['model_bundle'],
        geometry_reuse=dict(original_model_manifest_sha256=file_hash(old_model/'CUMOTION_MODEL_MANIFEST.json'),
            scope='GEOMETRY_ONLY_NO_OLD_TRAJECTORY_OR_WORLD_APPROVAL',new_world_inspection_required=True),
        files={n:file_hash(output/n) for n in ('robot.urdf','robot.xrdf')})
    for key in ('bounded_sim_source','archived_static_source'):manifest.pop(key,None)
    for key,value in (('bounded_sim_source',bounded_model_source(new_request)),('archived_static_source',static_model_source(new_request,fresh))):
        if value is not None:manifest[key]=value
    (output/'CUMOTION_MODEL_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    read_cumotion_model(output,new_request)
    return dict(status='GEOMETRY_REUSED_NEW_WORLD_GPU_INSPECTION_AND_FCL_REQUIRED',execution_allowed=False,hardware_execution_allowed=False)


def reprepare_collision_geometry(old_model, old_request, new_request, output, jerk):
    """CPU-only new model files from invariant link-local solid sphere covers.

    Reload robot/inspector/optimizer explicitly afterward. This preserves a
    cover, not old self/world validity, a trajectory, or latest-owner approval.
    """
    from held_geometry_inputs import nominal_definition
    from sim_utils import rigid
    old_model, old_request, new_request, output = map(Path, (old_model, old_request, new_request, output))
    if output.exists():raise FileExistsError('New geometry model folder required')
    old, source = read_cumotion_model(old_model, old_request)
    fresh = verify_request(new_request)
    def held(r):return next(o for o in r['planning_snapshot']['world_objects'] if o['id']==r['planning_snapshot']['selected_slot_id'])
    definition = nominal_definition(held(fresh), fresh['model_bundle'])
    if (old['model_bundle'] != fresh['model_bundle'] or
            nominal_definition(held(old), old['model_bundle']) != definition):
        raise ValueError('PROTOTYPE_REQUIRES_IDENTICAL_ROBOT_MESH_AND_HELD_SOLID_DEFINITION')
    if list(jerk) != source['jerk_limits']:
        raise ValueError('PROTOTYPE_REQUIRES_UNCHANGED_JERK_PROFILE')
    xrdf = load_model_yaml((old_model/'robot.xrdf').read_text())
    if (set(xrdf['geometry']) != {'full_geometry'} or
            ET.fromstring(old['model_bundle']['robot_description']).find(f"link[@name='{TCP}']/collision") is not None):
        raise ValueError('PROTOTYPE_REQUIRES_SEPARATE_TCP_HELD_SPHERES')
    spheres = xrdf['geometry']['full_geometry']['spheres']
    if len(spheres[TCP]) != source['held_sphere_count']:
        raise ValueError('PROTOTYPE_HELD_SPHERE_COUNT_CHANGED')
    transform = rigid(fresh['attachment']) @ np.linalg.inv(rigid(old['attachment']))
    # Spectral norm bounds the image of each ball, including floating matrix
    # roundoff. No observation tolerance or hidden geometry snap is used.
    radius_scale = max(1., float(np.linalg.norm(transform[:3,:3], 2)))
    for sphere in spheres[TCP]:
        sphere['center'] = (transform[:3,:3] @ np.asarray(sphere['center']) + transform[:3,3]).tolist()
        sphere['radius'] = float(np.nextafter(sphere['radius'] * radius_scale, np.inf))
    xrdf['default_joint_positions'].update(dict(zip(JOINTS, fresh['planning_snapshot']['q_rad'])))
    xrdf['default_joint_positions']['rg2_finger_joint'] = fresh['planning_snapshot']['grip_rad']
    pins = {str(p.resolve()):file_hash(p) for p in
            [old_request, new_request, old_model/'CUMOTION_MODEL_MANIFEST.json',
             *[old_model/name for name in source['files']]]}
    manifest = deepcopy(source)
    prototype = dict(scope='INVARIANT_SOLID_COVER_ONLY_NOT_NEW_WORLD_OR_PATH_PROOF', source_pins=pins,
        prior_compact_refinement=manifest.pop('compact_refinement', None),
        original_held_cell_partition=source['held_cell_partition'])
    manifest.update(source_request=str(new_request.resolve()), source_request_sha256=file_hash(new_request),
        source_model=fresh['model_bundle'], binding={k:fresh[k] for k in BINDING},
        attachment=deepcopy(fresh['attachment']), grip_rad=fresh['planning_snapshot']['grip_rad'],
        held_geometry_definition=definition, prototype_provenance=prototype,
        held_cell_partition='TRANSFORMED_SOURCE_SOLID_SPHERE_COVER',
        geometry_repreparation=dict(scope='CPU_NEW_GEOMETRY_REQUIRES_EXPLICIT_SDK_RELOAD_AND_INSPECTION',
            held_sphere_transform=transform.tolist(), radius_scale_bound=radius_scale,
            link_local_robot_spheres_unchanged=True, SDK_inspected=False,
            full_original_model_FCL_required=True, latest_actual_geometry_review_required=True),
        preparation_source_sha256={'prepare_cumotion_model.py':file_hash(Path(__file__))})
    # geometry_reuse means identical geometry to the live consumer; do not set
    # it for a new transform or carry a previous world's validation forward.
    for key in ('geometry_reuse', 'bounded_sim_source', 'archived_static_source'):
        manifest.pop(key, None)
    for key,value in (('bounded_sim_source',bounded_model_source(new_request)),
                      ('archived_static_source',static_model_source(new_request,fresh))):
        if value is not None:manifest[key]=value
    if any(file_hash(Path(path))!=sha for path,sha in pins.items()):
        raise ValueError('PROTOTYPE_SOURCE_CHANGED_DURING_PREPARATION')
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(old_model/'robot.urdf', output/'robot.urdf')
    (output/'robot.xrdf').write_text(yaml.safe_dump(xrdf, sort_keys=False))
    manifest['files']={name:file_hash(output/name) for name in ('robot.urdf','robot.xrdf')}
    (output/'CUMOTION_MODEL_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    read_cumotion_model(output,new_request)
    return manifest['geometry_repreparation']


def refine_held_body_cover(model,request_path,output,*,body_counts=(11,11,1),stud_counts=(4,4,1)):
    """One binary subdivision of exact BODY cells, no SDK or solid shrinkage.

    Reconstruct and verify the source cover first. Compare three split axes
    on the identical archived world; keep robot and stud spheres unchanged.
    Each child ball covers every corner and hence its entire convex box.
    """
    import itertools
    from scipy.spatial import cKDTree
    model,request_path,output=map(Path,(model,request_path,output))
    if output.exists():raise FileExistsError('New revised prototype folder required')
    request,source=read_cumotion_model(model,request_path)
    xrdf=load_model_yaml((model/'robot.xrdf').read_text())
    state=request['planning_snapshot'];held=next(o for o in state['world_objects'] if o['id']==state['selected_slot_id'])
    original=xrdf['geometry']['full_geometry']['spheres'][TCP]
    def exact_cells(size,transform,counts):
        counts=np.asarray(counts,int)
        if counts.shape!=(3,) or np.any(counts<=0):raise ValueError('Three positive explicit cell counts required')
        cells=box_cells(size,transform,np.nextafter(np.asarray(size)/counts,np.inf))
        if len(cells)!=int(np.prod(counts)):raise ValueError('Exact source cell count mismatch')
        return cells
    pieces=object_boxes(held,np.asarray(request['attachment']))
    body=exact_cells(*pieces[0],body_counts)
    studs=[cell for size,t in pieces[1:] for cell in exact_cells(size,t,stud_counts)]
    cells=body+studs;tree=cKDTree(np.asarray([s['center'] for s in original]))
    _,indices=tree.query([c['transform'][:3,3] for c in cells])
    if len(cells)!=len(original) or len(set(map(int,indices)))!=len(original):
        raise ValueError('Source BODY/stud partition must cover each original sphere once')
    signs=np.asarray(list(itertools.product([-1.,1.],repeat=3)))
    def corners(cell):return (signs*(cell['size']/2))@cell['transform'][:3,:3].T+cell['transform'][:3,3]
    source_checks=[]
    for cell,index in zip(cells,indices):
        sphere=original[int(index)]
        worst=float(np.max(np.linalg.norm(corners(cell)-sphere['center'],axis=1)))
        if worst>sphere['radius']:raise ValueError('Original sphere does not contain full source cell')
        source_checks.append(dict(source_sphere_index=int(index),size_m=cell['size'].tolist(),
            T_tcp_cell=cell['transform'].tolist(),maximum_corner_distance_m=worst,radius_m=sphere['radius']))
    body_indices=set(map(int,indices[:len(body)]))
    kept_studs=[deepcopy(s) for i,s in enumerate(original) if i not in body_indices]
    robot_count=sum(len(v) for link,v in xrdf['geometry']['full_geometry']['spheres'].items() if link!=TCP)
    robot=ET.fromstring(request['model_bundle']['robot_description'])
    frames=urdf_transforms(robot,state['q_rad'],state['grip_rad']);world=[];mapping=[]
    for obj in state['world_objects']:
        if obj['id']==held['id']:continue
        pad=.002 if obj['role'] in ('SUPPLY_BLOCK','CURRENT_BLOCK') else 0.
        boxes=object_boxes(obj,checked_pose(obj['pose']),pad)
        mapping.append(dict(id=obj['id'],role=obj['role'],primitive_count=len(boxes),padding_m=pad))
        world.extend((obj['id'],size,t) for size,t in boxes)
    def gaps(geometry):
        centres=[];radii=[]
        for link,items in geometry.items():
            t=frames[link]
            for s in items:centres.append(t[:3,:3]@s['center']+t[:3,3]);radii.append(s['radius'])
        centres=np.asarray(centres);radii=np.asarray(radii);minimum=np.inf;negative=0
        for _,size,t in world:
            local=(centres-t[:3,3])@t[:3,:3];delta=np.abs(local)-size/2
            signed=np.linalg.norm(np.maximum(delta,0),axis=1)+np.minimum(np.max(delta,axis=1),0)-radii
            minimum=min(minimum,float(signed.min()));negative+=int(np.sum(signed<0))
        return dict(minimum_gap_m=minimum,negative_pair_count=negative)
    options=[]
    for axis in range(3):
        children=[child for cell in body for child in split_box_cell(cell,axis)]
        fresh=cell_spheres(children)+kept_studs;geometry=deepcopy(xrdf['geometry']['full_geometry']['spheres']);geometry[TCP]=fresh
        total=robot_count+len(fresh)
        options.append(dict(axis=axis,total_sphere_count=total,body_cell_count=len(children),**gaps(geometry)))
    eligible=[v for v in options if v['total_sphere_count']<=1024 and v['negative_pair_count']==0]
    if not eligible:raise ValueError('One exact BODY split cannot clear this archived world within1024: '+str(options))
    choice=max(eligible,key=lambda v:v['minimum_gap_m']);axis=choice['axis']
    children=[child for cell in body for child in split_box_cell(cell,axis)]
    new_body=cell_spheres(children);child_checks=[]
    for cell,sphere in zip(children,new_body):
        worst=float(np.max(np.linalg.norm(corners(cell)-sphere['center'],axis=1)))
        if worst>sphere['radius']:raise ValueError('New sphere fails full child-box convex cover')
        child_checks.append(dict(size_m=cell['size'].tolist(),T_tcp_cell=cell['transform'].tolist(),
            radius_m=sphere['radius'],maximum_corner_distance_m=worst,volume_m3=float(np.prod(cell['size']))))
    for parent,left,right in zip(body,children[::2],children[1::2]):
        if np.prod(left['size'])+np.prod(right['size'])!=np.prod(parent['size']):raise ValueError('Binary child volume sum changed')
    proof=dict(scope='SOURCE_SOLID_VOLUME_COVER_NOT_WORLD_OR_SDK_APPROVAL',
        source_model_manifest=dict(path=str((model/'CUMOTION_MODEL_MANIFEST.json').resolve()),sha256=file_hash(model/'CUMOTION_MODEL_MANIFEST.json')),
        source_request=dict(path=str(request_path.resolve()),sha256=file_hash(request_path)),
        held_geometry_definition=source['held_geometry_definition'],body_counts=list(body_counts),stud_counts=list(stud_counts),
        body_size_m=held['size_m'],source_body_cells=source_checks[:len(body)],unchanged_stud_cells=source_checks[len(body):],
        selected_axis=axis,axis_comparisons=options,child_cells=child_checks,
        partition_proof='Cartesian intervals partition each original box. Each BODY parent splits into two half-intervals on exactly one axis with identical other axes, disjoint interiors and equal total volume. All eight child corners inside convex circumsphere imply every convex box point inside. All original stud cells remain covered by original unchanged spheres.',
        body_volume_m3=float(np.prod(held['size_m'])),child_volume_sum_m3=float(sum(np.prod(c['size']) for c in children)),
        physical_body_and_four_studs_unchanged=True,robot_spheres_unchanged=True,stud_spheres_unchanged=True,
        no_pose_padding_or_mask_change=True,SDK_inspected=False,world_mapping=mapping)
    output.mkdir(parents=True,exist_ok=False)
    proof_path=output/'held_body_cell_proof.json';proof_path.write_text(json.dumps(proof,indent=2)+'\n')
    shutil.copyfile(model/'robot.urdf',output/'robot.urdf')
    xrdf['geometry']['full_geometry']['spheres'][TCP]=new_body+kept_studs
    (output/'robot.xrdf').write_text(yaml.safe_dump(xrdf,sort_keys=False))
    manifest=deepcopy(source);manifest.update(held_sphere_count=len(new_body)+len(kept_studs),
        held_cell_partition='EXACT_SOURCE_BODY_BINARY_SPLIT_UNCHANGED_STUDS',
        held_body_refinement=dict(cell_proof=dict(path=str(proof_path.resolve()),sha256=file_hash(proof_path)),
            scope='SOURCE_SOLID_COVER_ONLY_NOT_LATEST_WORLD_CLEARANCE',SDK_inspected=False),
        preparation_source_sha256={'prepare_cumotion_model.py':file_hash(Path(__file__))},
        files={n:file_hash(output/n) for n in ('robot.urdf','robot.xrdf')})
    manifest['geometry_repreparation']=dict(scope='CPU_REFINED_BODY_REQUIRES_EXPLICIT_SDK_INSPECTION',SDK_inspected=False,
        full_original_model_FCL_required=True,latest_actual_geometry_review_required=True)
    (output/'CUMOTION_MODEL_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    read_cumotion_model(output,request_path)
    return dict(status='CPU_BODY_VOLUME_COVER_PREPARED_SDK_NOT_RUN',choice=choice,axis_comparisons=options,
        READY=False,apply_allowed=False,SDK_inspected=False)


def inspect_model(folder, request, cumotion):
    description = cumotion.load_robot_from_file(folder / "robot.xrdf", folder / "robot.urdf")
    if [description.cspace_coord_name(i) for i in range(description.num_cspace_coords())] != JOINTS:
        raise ValueError("cuMotion arm joint order changed")
    kinematics = description.kinematics()
    robot = ET.fromstring(request["model_bundle"]["robot_description"])
    state = request["planning_snapshot"]
    rng = np.random.default_rng(20261014)
    bounds = [robot.find(f"joint[@name='{n}']/limit") for n in JOINTS]
    lower = np.array([float(b.get("lower")) for b in bounds])
    upper = np.array([float(b.get("upper")) for b in bounds])
    samples = [np.array(state["q_rad"])] + list(rng.uniform(lower, upper, (64, 6)))
    peak_p, peak_r = 0., 0.
    for q in samples:
        reference = urdf_transforms(robot, q, state["grip_rad"])
        for frame in kinematics.frame_names():
            actual = kinematics.pose(q, frame).matrix()
            expected = reference[frame]
            peak_p = max(peak_p, float(np.linalg.norm(actual[:3, 3] - expected[:3, 3])))
            peak_r = max(peak_r, float(Rotation.from_matrix(
                expected[:3, :3].T @ actual[:3, :3]).magnitude()))
    if peak_p > 1e-6 or peak_r > 3e-6:
        raise ValueError(f"cuMotion/URDF frame mismatch: {peak_p}m/{peak_r}rad")
    world, mapping = make_world(request, cumotion)
    view = world.add_world_view()
    inspector = cumotion.create_robot_world_inspector(description, view)
    q = np.array(state["q_rad"])
    limits = load_model_yaml(request["model_bundle"]["joint_limits_yaml"])["joint_limits"]
    xrdf = load_model_yaml((folder / "robot.xrdf").read_text())
    for i, name in enumerate(JOINTS):
        if (kinematics.cspace_coord_velocity_limit(i) != limits[name]["max_velocity"] or
                kinematics.cspace_coord_acceleration_limit(i) != limits[name]["max_acceleration"] or
                kinematics.cspace_coord_jerk_limit(i) != xrdf["cspace"]["jerk_limits"][i]):
            raise ValueError("cuMotion loaded different calculation limits")
    spheres = xrdf["geometry"]["full_geometry"]["spheres"]
    if inspector.num_world_collision_spheres() != sum(map(len, spheres.values())):
        raise ValueError("cuMotion dropped collision spheres")
    return dict(status="MODEL_INSPECTED_NO_TRAJECTORY", execution_allowed=False,
        m0609_trajectory_calculated=False, independent_fcl_verified=False,
        fk_samples=len(samples), fk_frame_count=len(kinematics.frame_names()),
        max_fk_position_error_m=peak_p, max_fk_rotation_error_rad=peak_r,
        arm_velocity_limits=[kinematics.cspace_coord_velocity_limit(i) for i in range(6)],
        arm_acceleration_limits=[kinematics.cspace_coord_acceleration_limit(i) for i in range(6)],
        arm_jerk_limits=[kinematics.cspace_coord_jerk_limit(i) for i in range(6)],
        self_collision_pairs=inspector.frames_in_self_collision(q),
        start_world_collision=inspector.in_collision_with_obstacle(q),
        world_collision_sphere_count=inspector.num_world_collision_spheres(),
        world_mapping=mapping, geometric_start_valid=not inspector.frames_in_self_collision(q) and
        not inspector.in_collision_with_obstacle(q), gpu_self_collision_sphere_limit=1024,
        gpu_self_collision_sphere_count=inspector.num_self_collision_spheres(),
        model_ready_for_calculation=False)


def compact_geometry(robot, request, reference_paths, path_samples):
    """Cover whole meshes; subdivide only overly large or colliding partitions.

    Bound start/goal references choose conservative geometry resolution. They
    are never waypoints, replacement Current, or robot execution permission.
    """
    refs, metadata = [], []
    for request_path, result_path in reference_paths:
        ref = verify_request(request_path)
        if ref["model_bundle"] != request["model_bundle"]:
            raise ValueError("Compact references must share the original nominal model")
        result = yaml.load(result_path.read_text(), Loader=yaml.CSafeLoader)
        prepare_d_candidate(result, ref, {k: ref[k] for k in BINDING})
        points = result["planned_trajectory"]["points"]
        indices = sorted(set(np.linspace(0, len(points)-1, path_samples, dtype=int).tolist()))
        reference_q = [points[i]["positions_rad"] for i in indices]
        refs.append((ref, reference_q))
        metadata.append(dict(request=str(request_path), request_sha256=file_hash(request_path),
            result=str(result_path), result_sha256=file_hash(result_path),
            goal_q_rad=points[-1]["positions_rad"], refinement_q_rad=reference_q,
            reference_point_indices=indices, mandatory_waypoint=False, execution_allowed=False))
    if not any(digest(ref) == digest(request) for ref, _ in refs):
        raise ValueError("Primary request needs its own bound FCL-validated goal reference")
    semantic = ET.fromstring(request["model_bundle"]["robot_description_semantic"])
    ignore = {frozenset((p.get("link1"), p.get("link2"))) for p in semantic.findall("disable_collisions")}
    ignore |= {frozenset((TCP, t)) for t in TOUCH}
    leaves, coverage = [], []
    for link in robot.findall("link"):
        name = link.get("name")
        for collision in link.findall("collision"):
            mesh = collision.find("geometry/mesh")
            if mesh is None or mesh.get("scale", "1 1 1") != "1 1 1":
                raise ValueError("Original unscaled closed collision STL required")
            path = Path(unquote(urlparse(mesh.get("filename")).path))
            vertices, triangles = read_closed_stl(path)
            pitch = .0005 if name.startswith("rg2_") and name != "rg2_base_link" else .002
            cells, cell_radius, shape = voxel_envelope(vertices, triangles, pitch)
            origin = collision.find("origin")
            rotation = Rotation.from_euler("xyz", np.array(origin.get("rpy", "0 0 0").split(), float)).as_matrix()
            cells = cells @ rotation.T + np.array(origin.get("xyz", "0 0 0").split(), float)
            index = len(coverage)
            coverage.append(dict(link=name, mesh=str(path), mesh_sha256=file_hash(path),
                pitch_m=pitch, grid_shape=shape, occupied_cells=len(cells),
                closed_mesh_verified=True, conservative_voxel_cover_verified=True))
            pending = [cloud_node(name, cells, cell_radius, index)]
            while pending:
                node = pending.pop()
                if node["radius"] > (.02 if name.startswith("rg2_") else .08):
                    pending.extend(split_cloud(node))
                else:
                    leaves.append(node)
        print("compact initial", name, "total", len(leaves), flush=True)
    probes, held_groups = [], []
    primary_held_index = None
    for ref, reference_q in refs:
        state = ref["planning_snapshot"]
        obj = next(o for o in state["world_objects"] if o["id"] == state["selected_slot_id"])
        primary_obj = next(o for o in request["planning_snapshot"]["world_objects"]
                           if o["id"] == request["planning_snapshot"]["selected_slot_id"])
        if obj["size_m"] != primary_obj["size_m"] or obj["studs"] != primary_obj["studs"]:
            raise ValueError("Compact references need the same held body/stud dimensions")
        held = [c for size, t in object_boxes(obj, np.array(ref["attachment"]))
                for c in box_cells(size, t, [.003, .003, size[2]])]
        if digest(ref) == digest(request):
            primary_held_index = len(held_groups)
        held_groups.append(held)
        world = [(o["id"], size, t) for o in state["world_objects"] if o["id"] != state["selected_slot_id"]
                 for size, t in object_boxes(o, checked_pose(o["pose"]),
                     .002 if o["role"] in ("SUPPLY_BLOCK", "CURRENT_BLOCK") else 0)]
        for index, q in enumerate(reference_q):
            kind = "START" if index == 0 else "GOAL" if index+1 == len(reference_q) else "MODEL_REFINEMENT_REFERENCE"
            probes.append((kind, urdf_transforms(robot, q, state["grip_rad"]), held, world))
    iterations = []
    for iteration in range(24):
        bad, held_bad, held_axes = set(), set(), {}
        for kind, frames, held, world in probes:
            held_spheres = cell_spheres(held)
            names = [n["link"] for n in leaves] + [TCP] * len(held_spheres)
            centres = np.array([frames[n["link"]][:3, :3] @ n["center"] + frames[n["link"]][:3, 3] for n in leaves] +
                [frames[TCP][:3, :3] @ np.array(s["center"]) + frames[TCP][:3, 3] for s in held_spheres])
            radii = np.array([n["radius"] for n in leaves] + [s["radius"] for s in held_spheres])
            indices, contacts = sphere_contacts(names, centres, radii, world, ignore)
            bad.update(i for i in indices if i < len(leaves))
            for i in indices:
                if i < len(leaves):
                    continue
                h = i - len(leaves); held_bad.add(h)
                axis, worst_depth = int(np.argmax(held[h]["size"])), 0.
                for _, size, transform in world:
                    local = transform[:3, :3].T @ (centres[i] - transform[:3, 3])
                    delta = local - np.clip(local, -np.asarray(size)/2, np.asarray(size)/2)
                    distance = np.linalg.norm(delta); depth = radii[i] - distance
                    if depth > worst_depth and distance > 1e-12:
                        normal = held[h]["transform"][:3, :3].T @ frames[TCP][:3, :3].T @ (transform[:3, :3] @ delta / distance)
                        axis = int(np.argmax(held[h]["size"] * np.sqrt(np.maximum(0, 1 - normal**2))))
                        worst_depth = float(depth)
                if h not in held_axes or worst_depth > held_axes[h][1]:
                    held_axes[h] = (axis, worst_depth)
        total = len(leaves) + max(len(p[2]) for p in probes)
        iterations.append(dict(iteration=iteration, sphere_count=total,
                               partitions_to_refine=len(bad), held_cells_to_refine=len(held_bad)))
        print("compact refinement", iterations[-1], flush=True)
        if not bad and not held_bad:
            break
        if total + len(bad) + len(held_bad) > 1024:
            raise ValueError("Conservative refinement would exceed the verified1024-sphere kernel limit")
        leaves = [child for i, n in enumerate(leaves) for child in (split_cloud(n) if i in bad else [n])]
        for group in held_groups:
            group[:] = [child for i, c in enumerate(group) for child in
                        (split_box_cell(c, held_axes[i][0]) if i in held_bad else [c])]
    else:
        raise ValueError("Conservative refinement did not finish within its explicit24-iteration budget")
    geometry = {}
    for index, check in enumerate(coverage):
        parts = [n for n in leaves if n["source"] == index]
        if sum(len(n["points"]) for n in parts) != check["occupied_cells"]:
            raise ValueError("A source cell was lost while partitioning")
        worst = max(float(np.max(np.linalg.norm(n["points"] - n["center"], axis=1)) +
                          n["cell_radius"] - n["radius"]) for n in parts)
        if worst > 1e-9:
            raise ValueError("Compact sphere fails its whole-cell witness")
        check.update(sphere_count=len(parts), full_cell_max_uncovered_m=worst)
    for node in leaves:
        geometry.setdefault(node["link"], []).append(dict(center=node["center"].tolist(), radius=node["radius"]))
    geometry[TCP] = cell_spheres(held_groups[primary_held_index])
    for item in metadata:
        if file_hash(Path(item["request"])) != item["request_sha256"] or file_hash(Path(item["result"])) != item["result_sha256"]:
            raise ValueError("Geometry reference changed during preparation")
        verify_request(Path(item["request"]))
    return geometry, coverage, dict(method="WHOLE_CELL_PARTITION_CONSERVATIVE_SPHERE_REFINEMENT",
        references=metadata, iterations=iterations, source_cells_removed=0, new_ignore_pairs=0,
        reference_states_are_mandatory_waypoints=False)


def prepare_model(request_path, folder, jerk, compact_references=None, compact_path_samples=2):
    if folder.exists():
        raise FileExistsError("Existing model/failed evidence cannot be overwritten")
    jerk = np.asarray(jerk, float)
    if jerk.shape != (6,) or not np.isfinite(jerk).all() or np.any(jerk <= 0):
        raise ValueError("Explicit positive finite six-axis calculation jerk limits required")
    if type(compact_path_samples) is not int or not 2 <= compact_path_samples <= 200:
        raise ValueError("Use2..200 explicit geometry-reference samples; these are not waypoints")
    request = verify_request(request_path)
    source_hashes = {n: file_hash(Path(__file__).parent / n) for n in
                     ["prepare_cumotion_model.py", "cumotion_geometry.py"]}
    import cumotion
    if cumotion.__version__ != "1.1.0":
        raise ValueError("Selected stable cuMotion1.1.0 required")
    state = request["planning_snapshot"]
    robot = ET.fromstring(request["model_bundle"]["robot_description"])
    limits = load_model_yaml(request["model_bundle"]["joint_limits_yaml"])["joint_limits"]
    acceleration = []
    for name in JOINTS:
        robot.find(f"joint[@name='{name}']/limit").set("velocity", str(limits[name]["max_velocity"]))
        acceleration.append(limits[name]["max_acceleration"])
    geometry, coverage = {}, []
    compact = None
    if compact_references is not None:
        geometry, coverage, compact = compact_geometry(robot, request, compact_references, compact_path_samples)
    # Compact mode already covers every original collision link above.
    for link in ([] if compact is not None else robot.findall("link")):
        spheres = []
        for collision in link.findall("collision"):
            mesh = collision.find("geometry/mesh")
            if mesh is None or mesh.get("scale", "1 1 1") != "1 1 1":
                raise ValueError("Expected original unscaled collision mesh")
            path = Path(unquote(urlparse(mesh.get("filename")).path))
            vertices, triangles = read_closed_stl(path)
            pitch = .0005 if link.get("name").startswith("rg2_") else .002
            if link.get("name") == "rg2_base_link":
                pitch = .002
            margin = pitch if link.get("name").startswith("rg2_") and link.get("name") != "rg2_base_link" else 4 * pitch
            generated, checks = mesh_spheres(vertices, triangles, pitch, cumotion, margin)
            origin = collision.find("origin")
            translation = np.array(origin.get("xyz", "0 0 0").split(), float)
            rotation = Rotation.from_euler("xyz", np.array(origin.get("rpy", "0 0 0").split(), float)).as_matrix()
            for sphere in generated:
                sphere["center"] = (rotation @ sphere["center"] + translation).tolist()
            spheres.extend(generated)
            coverage.append(dict(mesh=str(path), mesh_sha256=file_hash(path), link=link.get("name"), **checks))
        if spheres:
            geometry[link.get("name")] = spheres
            print("prepared", link.get("name"), "spheres", len(spheres), flush=True)
    held = next(o for o in state["world_objects"] if o["id"] == state["selected_slot_id"])
    if compact is None:
        geometry[TCP] = [s for size, transform in object_boxes(held, np.array(request["attachment"]))
                         for s in box_spheres(size, transform, pitch=[.002, .002, size[2]])]
    if sum(len(v) for v in geometry.values()) > 10000:
        raise ValueError("Sphere count exceeds this PC's initial model inspection budget")
    semantic = ET.fromstring(request["model_bundle"]["robot_description_semantic"])
    ignore = {}
    for pair in semantic.findall("disable_collisions"):
        ignore.setdefault(pair.get("link1"), []).append(pair.get("link2"))
    ignore[TCP] = TOUCH.copy()
    defaults = dict(zip(JOINTS, state["q_rad"])) | {"rg2_finger_joint": state["grip_rad"]}
    xrdf = dict(format="xrdf", format_version=2.0, modifiers=[dict(set_base_frame="base_link")],
        default_joint_positions=defaults,
        cspace=dict(joint_names=JOINTS, acceleration_limits=acceleration, jerk_limits=jerk.tolist()),
        tool_frames=[TCP], world_collision=dict(geometry="full_geometry"),
        self_collision=dict(geometry="full_geometry", ignore=ignore),
        geometry=dict(full_geometry=dict(spheres=geometry)))
    folder.mkdir(parents=True)
    ET.indent(robot)
    ET.ElementTree(robot).write(folder / "robot.urdf", encoding="utf-8", xml_declaration=True)
    (folder / "robot.xrdf").write_text(yaml.safe_dump(xrdf, sort_keys=False))
    manifest = dict(scope="ARCHIVED_NOMINAL_SIM_CUMOTION_MODEL_NOT_FOR_EXECUTION",
        execution_allowed=False, hardware_execution_allowed=False,
        source_request=str(request_path.resolve()), source_request_sha256=file_hash(request_path),
        source_model=deepcopy(request["model_bundle"]), binding={k: request[k] for k in BINDING},
        jerk_source="USER_SELECTED_CALCULATION_ONLY_TEMPORARY_NOT_PHYSICAL", jerk_limits=jerk.tolist(),
        grip_angle_source="ARCHIVED_SIM_JOINT_FEEDBACK_NOT_REAL_RG2_WIDTH",
        grip_rad=state["grip_rad"], attachment=deepcopy(request["attachment"]),
        held_id=held["id"], held_sphere_count=len(geometry[TCP]), touch_links=TOUCH,
        held_cell_partition="2MM_XY_FULL_HEIGHT_CIRCUMSPHERES_COVER_SOLID_BODY_AND_STUDS",
        coverage=coverage, nominal_source_files_unchanged=True,
        preparation_source_sha256=source_hashes,
        derived_urdf_changes="ONLY_SIX_ARM_VELOCITY_LIMITS_FROM_EXISTING_MOVEIT_LIMITS",
        files={n: file_hash(folder / n) for n in ["robot.urdf", "robot.xrdf"]})
    if compact is not None:
        manifest.update(compact_refinement=compact, held_cell_partition="ADAPTIVE_EXACT_BOX_CELLS_CIRCUMSPHERES_BODY_AND_STUDS")
    from held_geometry_inputs import nominal_definition
    manifest['held_geometry_definition']=nominal_definition(held,request['model_bundle'])
    if bounded_model_source(request_path) is not None:
        manifest['bounded_sim_source']=bounded_model_source(request_path)
    if static_model_source(request_path,request) is not None:
        manifest['archived_static_source']=static_model_source(request_path,request)
    (folder / "CUMOTION_MODEL_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    read_cumotion_model(folder, request_path)
    report = inspect_model(folder, request, cumotion)
    report["model_ready_for_calculation"] = report["geometric_start_valid"] and report["gpu_self_collision_sphere_count"] <= 1024
    (folder / "model_checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    verify_request(request_path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jerk", type=float, nargs=6, required=True)
    parser.add_argument("--prototype-model", type=Path, help="CPU-only invariant sphere-cover source model")
    parser.add_argument("--prototype-request", type=Path, help="Exact request of the prototype model")
    parser.add_argument("--compact-reference", type=Path, nargs=2, action="append",
                        metavar=("REQUEST", "FCL_RESULT"), help="Bound archived SIM start/goal geometry reference; no waypoint")
    parser.add_argument("--compact-path-samples", type=int, default=2,
                        help="Geometry resolution references only; no planner waypoints")
    args = parser.parse_args()
    if args.prototype_model is not None or args.prototype_request is not None:
        if args.prototype_model is None or args.prototype_request is None or args.compact_reference:
            parser.error('Both prototype paths required; compact references belong to SDK preparation')
        print(json.dumps(reprepare_collision_geometry(args.prototype_model, args.prototype_request,
            args.request, args.output, args.jerk)))
        return
    references = [[p.resolve() for p in pair] for pair in args.compact_reference] if args.compact_reference else None
    report = prepare_model(args.request.resolve(), args.output, args.jerk, references, args.compact_path_samples)
    print(json.dumps({k: v for k, v in report.items() if k != "world_mapping"}))


if __name__ == "__main__":
    main()
