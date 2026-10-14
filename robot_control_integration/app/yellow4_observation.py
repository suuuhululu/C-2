"""Challenge source binding and read-only image diagnostics; never moves devices."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
from app.edge_first_seating import pose_matrix, matrix_pose, preview
from app.contracts import validate_block
from app.assembly_motion import pose_error
from app.supply_stud.backend import observe as supply_observe
from scripts import supply_pick_release_trial as supply
from scripts.held_corner_stud_trial import target_layer_approach
from supply_vision.virtual_board_grid import VirtualBoardGrid, project_base


def source(path):
    path=Path(path)
    return dict(path=str(path.resolve()),sha256=sha256(path.read_bytes()).hexdigest())


def prepare(root,settings,measurements=None):
    root=Path(root)
    if settings.get('schema_version')!='yellow4-observation-settings/1':raise ValueError('OBSERVATION_SETTINGS_REQUIRED')
    paths={key:(Path(value) if Path(value).is_absolute() else root/value)
           for key,value in settings['sources'].items()}
    supply_config=supply.load_config(paths['supply_config'])
    held=supply.load_config(paths['held_config'])
    scenario=json.loads(paths['scenario'].read_text())
    if tuple(scenario['scope'][k] for k in ('color','brick_type','block_count'))!=('yellow','2x2x1',1):
        raise ValueError('SINGLE_YELLOW4_SCENARIO_REQUIRED')
    target=validate_block(dict(color='yellow',brick_type='2x2x1',**{k:scenario['proposed_target'][k]
        for k in ('x','y','layer','orientation_deg')}))
    row=deepcopy(next(r for r in supply_config['blocks'] if (r['color'],r['brick_type'],r['slot'])==('yellow','2x2x1',settings['slot'])))
    if target['orientation_deg']!=0:raise ValueError('CURRENT_LAYER_REFERENCE_IS_ZERO_DEG_ONLY')
    placed=target_layer_approach(held,target['layer'],target_x=target['x'],target_y=target['y'])['alignment_target']
    baseline=row['pickup_pose'];landing=placed['placement_tcp_reference']
    raised=json.loads(paths['raised_profile'].read_text())
    mode=settings.get('grasp_mode','STANDARD')
    if mode not in ('STANDARD','HUMAN_REPLACEMENT'):raise ValueError('STANDARD_OR_HUMAN_REPLACEMENT_GRASP_REQUIRED')
    policy=scenario['grasp_policy']
    height=policy['standard_pad_bottom_height_mm'] if mode=='STANDARD' else policy['human_replacement_pad_bottom_height_mm']
    delta=height-policy['standard_pad_bottom_height_mm']
    if mode=='HUMAN_REPLACEMENT':
        if tuple(raised['binding'][k] for k in ('color','brick_type','slot'))!=('yellow','2x2x1',row['slot']):
            raise ValueError('RAISED_PROFILE_GRASP_BINDING_MISMATCH')
        if raised['pad_bottom_from_block_bottom_mm']!=height or raised['requested_raise_mm']!=delta:
            raise ValueError('EXPECTED_HUMAN_REPLACEMENT_GRASP_POLICY')
    pick_trial=baseline.copy();pick_trial[2]+=delta
    land_trial=landing.copy();land_trial[2]+=delta
    grid=VirtualBoardGrid(held['virtual_grid'])
    refs={k:source(v) for k,v in paths.items()};refs.update(grid.sources)
    refs['supply_layout']=source(supply_config['vision']['layout'])
    bundle=dict(schema_version='yellow4-observation/1',status='PREPARED_FOR_FIELD_OBSERVATION',target=target,
        slot=row['slot'],connection=deepcopy(supply_config['connection']),sources=refs,
        supply_row=row,vision=deepcopy(supply_config['vision']),virtual_grid=deepcopy(held['virtual_grid']),
        supply_observation_pose=supply_config['observation_pose'],baseline_supply_tcp=baseline,
        baseline_seated_tcp=landing,layer_reference=placed,
        selected_pickup_tcp_candidate=pick_trial,selected_seated_tcp_candidate=land_trial,grasp_mode=mode,
        selected_grasp_basis='STANDARD5_EXISTING_TEACHING' if mode=='STANDARD' else 'USER_BASE_Z_PLUS10_HUMAN_REPLACEMENT_NOT_MEASURED_15MM',
        intended_pad_bottom_height_mm=height,
        raised_profile_has_measured_poses=all(raised[k] is not None for k in ('pickup_pose','landing_pose','measurement_ref')),
        dimensions=deepcopy(grid.geometry),board_transform_status=grid.board['status'],
        tcp_to_block_pose_mm_zyz_deg=None,geometry_config=None,
        missing_measurements=['tcp_to_block_relation','seated_block_pose','assembly_contact_axis','removal_contact_axis','board_fixation'],
        physical_commands=0,execution_allowed=False,field_verified=False)
    if measurements is not None:
        m=deepcopy(measurements)
        if m['target']!=target or m['slot']!=row['slot'] or m['tcp']!=bundle['connection']['tcp'] or m['tool']!=bundle['connection']['tool']:
            raise ValueError('MEASUREMENT_TARGET_SLOT_TCP_TOOL_MISMATCH')
        if m['source_kind']!='OPERATOR_FIELD_MEASUREMENT' or not m.get('evidence_ref'):
            raise ValueError('FIELD_MEASUREMENT_EVIDENCE_REQUIRED')
        if m['pad_bottom_from_block_bottom_mm']!=height or m.get('grasp_mode')!=mode or m['frame']!='BASE' or not m.get('grasp_id'):
            raise ValueError('MEASURED_SELECTED_HEIGHT_MODE_BASE_FRAME_GRASP_REQUIRED')
        tcp=pose_matrix(m['tcp_pose_mm_zyz_deg']);block=pose_matrix(m['block_pose_mm_zyz_deg'])
        grasp=matrix_pose(np.linalg.inv(tcp)@block)
        geometry=dict(schema_version='yellow4-pivot-preview/2',mode='PREVIEW_ONLY',operation='assembly',
            source_kind='OPERATOR_FIELD_MEASUREMENT_GEOMETRY_NOT_LOADED_PIVOT_VERIFICATION',
            coordinate_frame='BASE',output_frame='BASE',frame_pose_in_output_mm_zyz_deg=[0,0,0,0,0,0],
            block=target,seated_block_pose_mm_zyz_deg=m['block_pose_mm_zyz_deg'],tcp_to_block_pose_mm_zyz_deg=grasp,
            block_geometry=m['block_geometry'],target_studs=m['target_studs'],operations=m['operations'])
        known=[operation for operation in ('assembly','removal') if m['operations'].get(operation) is not None]
        missing=[operation+'_contact_axis' for operation in ('assembly','removal') if operation not in known]
        if m['block_geometry'] is None:missing.append('block_geometry')
        if m['target_studs'] is None:missing.append('target_studs')
        if not m.get('board_fixation_confirmed'):missing.append('board_fixation')
        if known and m['block_geometry'] is not None and m['target_studs'] is not None:
            geometry['operation']=known[0]
            for operation in known:preview(geometry,operation)
        else:geometry=None
        bundle.update(tcp_to_block_pose_mm_zyz_deg=grasp,geometry_config=geometry,measurement= m,
            missing_measurements=missing)
    return bundle


def camera_info(value):
    if value is None:return None
    return SimpleNamespace(width=value['width'],height=value['height'],k=value['k'],d=value['d'],
        distortion_model=value['distortion_model'],header=SimpleNamespace(frame_id=value['frame_id']))


def analyze(frame,bundle,view,*,sample=None,info=None,edge=(),axis=(),roi=None,stamp_ns=0,grid=None):
    canvas=frame.copy();report=dict(view=view,physical_commands=0,execution_allowed=False,
        roll_pitch_observed=False,roll_pitch_deg=None,source_kind='IMAGE_DIAGNOSTIC_NOT_FIELD_REGISTRATION')
    if view=='supply':
        layout=json.loads(Path(bundle['vision']['layout']).read_text())
        entry=next(s for s in layout['slots'] if (s['color'],s['brick_type'],s['slot'])==('yellow','2x2x1',bundle['slot']))
        if roi is not None:
            x0,y0,x1,y1=roi;size=min(x1-x0,y1-y0)
            entry.update(roi_xyxy=list(roi),short_side_px=[size*.25,size*.95],long_side_px=[size*.25,size*.95],min_area_px=size*size*.03)
            layout['image_size']=[frame.shape[1],frame.shape[0]]
            report['roi_override']=list(roi);report['roi_source']='OPERATOR_CURRENT_FRAME_NOT_SAVED_LAYOUT'
        if layout['image_size']!=[frame.shape[1],frame.shape[0]]:
            decision=dict(slot_id=f"yellow_2x2x1_{bundle['slot']:02d}",vision_attempted=True,recognized=False,
                center_available=False,reason='LAYOUT_IMAGE_SIZE_MISMATCH_SELECT_B_ROI')
        else:decision=supply_observe(frame,layout,bundle['supply_row'],stamp_ns)
        row=deepcopy(bundle['supply_row'])
        mapping=row.get('center_mapping')
        view_confirmed=(sample is not None and 'posx' in sample and sample.get('motion_status')==0
            and all(sample.get(k)==bundle['connection'][k] for k in ('tcp','tool'))
            and max(pose_error(sample['posx'],bundle['supply_observation_pose']))<=.5)
        if mapping and mapping.get('independently_verified') is True and not view_confirmed:
            row.pop('center_mapping')
        candidate=supply.center_target(row,decision)
        if mapping and mapping.get('independently_verified') is True and not view_confirmed:
            decision['fallback_reason']='MAPPING_OBSERVATION_POSE_NOT_CONFIRMED'
        report.update(supply_decision=decision,coordinate_fallback_tcp=candidate,pickup_tcp_candidate=[*candidate[:2],bundle['selected_pickup_tcp_candidate'][2],*candidate[3:]])
        cv2.rectangle(canvas,tuple(entry['roi_xyxy'][:2]),tuple(entry['roi_xyxy'][2:]),(255,180,0),1)
        for line in decision.get('center_lines_uv',[]):cv2.line(canvas,tuple(np.array(line[0],int)),tuple(np.array(line[1],int)),(0,255,255),2)
        if decision.get('center_uv') is not None:cv2.drawMarker(canvas,tuple(np.array(decision['center_uv'],int)),(0,0,255),cv2.MARKER_CROSS,14,2)
    elif view=='assembly':
        if sample is None or info is None:
            report.update(reason='CURRENT_TCP_AND_CAMERA_INFO_REQUIRED',relative_angle_deg=None)
        elif any(sample.get(k)!=bundle['connection'][k] for k in ('tcp','tool')):
            report.update(reason='CURRENT_TCP_TOOL_MISMATCH_OR_UNKNOWN',relative_angle_deg=None)
        else:
            grid=grid or VirtualBoardGrid(bundle['virtual_grid'])
            canvas,reference=grid.overlay(canvas,sample,camera_info(info),layer=bundle['target']['layer'],
                target_xy=(bundle['target']['x'],bundle['target']['y']),edges=[edge] if len(edge)==2 else [])
            report.update(grid_reference=reference,relative_angle_deg=reference.get('relative_angle_deg'),reason=reference.get('reason'))
            if bundle['geometry_config'] is not None and 'T_base_from_camera_mm' in reference:
                path=preview(bundle['geometry_config'])
                points=[p['tcp_mm_zyz_deg'][:3] for p in path['waypoints']]
                uv,ok=project_base(points,np.array(reference['T_base_from_camera_mm']),info['k'],info['d'])
                if ok.all():cv2.polylines(canvas,[uv.astype(np.int32)],False,(255,0,255),2)
                axis_uv,valid=project_base(path['contact_line_points_mm'],np.array(reference['T_base_from_camera_mm']),info['k'],info['d'])
                if valid.all():cv2.line(canvas,tuple(axis_uv[0].astype(int)),tuple(axis_uv[1].astype(int)),(0,140,255),3)
                report['projected_path_source']='FIELD_INPUT_GEOMETRY_NOT_LOADED_CONTACT_VERIFIED'
    else:raise ValueError('SUPPLY_OR_ASSEMBLY_VIEW_REQUIRED')
    for segment,color in ((edge,(0,0,255)),(axis,(0,140,255))):
        if len(segment)==2:cv2.line(canvas,tuple(np.array(segment[0],int)),tuple(np.array(segment[1],int)),color,2)
    report.update(top_edge_pixels=list(edge),contact_axis_pixels=list(axis),pixel_axis_is_measured_3d_axis=False)
    return canvas,report


def save_capture(directory,frame,canvas,bundle,report,*,sample=None,info=None,notes='',role='OBSERVATION',timing=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    for name,value in (('rgb.png',frame),('overlay.png',canvas)):
        if not cv2.imwrite(str(directory/name),value):raise OSError('IMAGE_SAVE_FAILED')
    record=dict(schema_version='yellow4-read-only-capture/1',role=role,notes=notes,sample=sample,camera_info=info,
        timing=timing,observation=report,sources=bundle['sources'],target=bundle['target'],
        grasp_mode=bundle['grasp_mode'],intended_pad_bottom_height_mm=bundle['intended_pad_bottom_height_mm'],
        robot_stopped_at_capture=None if not sample or 'velx' not in sample else
            sample.get('motion_status')==0 and max(map(abs,sample['velx']))==0,
        pose_image_registration_verified=False,actual_pad_bottom_height_verified=False,
        block_pose_measured=False,physical_commands=0,execution_allowed=False)
    (directory/'capture.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (directory/'prepared.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return directory
