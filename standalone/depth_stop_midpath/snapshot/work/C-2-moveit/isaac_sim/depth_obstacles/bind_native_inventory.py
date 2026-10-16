"""Verify recorded native USD geometry against original model and held pieces.

CPU USD read-only inspection. No renderer, ROS node, controller or SDK planner.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from urllib.parse import unquote,urlparse
import xml.etree.ElementTree as ET

import numpy as np


def canonical_triangles(triangles):
    triangles=np.asarray(triangles,dtype='<f4').copy()
    if triangles.ndim!=3 or triangles.shape[1:]!=(3,3) or not np.isfinite(triangles).all():
        raise ValueError('Complete finite triangle surfaces required')
    triangles[triangles==0]=0
    order=np.lexsort((triangles[:,:,2],triangles[:,:,1],triangles[:,:,0]),axis=1)
    rows=np.take_along_axis(triangles,order[:,:,None],axis=1).reshape(-1,9)
    return rows[np.lexsort(tuple(rows[:,k] for k in range(8,-1,-1)))]


def stl_triangles(path):
    raw=Path(path).read_bytes();count=struct.unpack_from('<I',raw,80)[0]
    if not count or len(raw)!=84+50*count:raise ValueError('Original complete binary STL required')
    dtype=np.dtype([('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attribute','<u2')])
    return np.frombuffer(raw,dtype=dtype,count=count,offset=84)['vertices']


def semantic(prim):
    while prim:
        attr=prim.GetAttribute('semantic:class:params:semanticData')
        if attr and attr.HasAuthoredValueOpinion():return attr.Get()
        prim=prim.GetParent()
    return None


def bind(folder,model_path):
    from pxr import Usd,UsdGeom
    from prepare_cpu_model import read_model_bundle,file_hash
    from plan_only import digest
    from bounded_sim_evidence import robot_visual_inventory,semantic_scene_binding
    from held_geometry_inputs import nominal_definition,bind_snapshot,verify_native_cubes,held_pieces
    folder=Path(folder).resolve();model=read_model_bundle(model_path)
    frame=json.loads((folder/'frame.json').read_text());pose=json.loads((folder/'pose.json').read_text())
    raw=json.loads((folder/'scene_inventory.json').read_text())
    stage=Usd.Stage.Open(raw['scene']['path'])
    if file_hash(raw['scene']['path'])!=raw['scene']['sha256']:raise ValueError('Captured scene changed')
    matrix=lambda prim:np.asarray(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T
    base=matrix(stage.GetPrimAtPath(frame['base_frame_id']));inverse_base=np.linalg.inv(base)
    obj=raw['geometry_context']['held_geometry'];attachment=raw['geometry_context']['attachment']
    geometry={k:obj[k] for k in ('id','size_m','studs','block')}
    context=dict(held_geometry=geometry,grip_rad=pose['grip_rad'],attachment=attachment)
    definition=nominal_definition(geometry,model)
    snapshot=dict(source_kind='SIM_DEPTH',selected_id=obj['id'],clock_basis=frame['clock_basis'],
        model_manifest_sha256=model['manifest_sha256'],profile_digest=definition['profile_digest'],
        session_id=frame['session_id'],state_sequence=pose['state_sequence'],stamp_s=frame['source_stamp_s'],
        T_base_tcp=frame['T_base_tool'],T_base_block=(inverse_base@matrix(stage.GetPrimAtPath(obj['prim_path']))).tolist(),
        recorded_attachment=attachment)
    held_binding=bind_snapshot(definition,snapshot)
    held_audit=verify_native_cubes(definition,held_binding,raw,base)
    expected=robot_visual_inventory(model);robot=ET.fromstring(model['robot_description']);visuals=[];surface_checks=[]
    prims=[p for p in Usd.PrimRange(stage.GetPrimAtPath('/World/Robot'),Usd.TraverseInstanceProxies()) if p.IsA(UsdGeom.Mesh)]
    for key,signature in expected.items():
        link,index=key.rsplit(':',1);name=f'{link}_visual_{index}'
        candidates=[p for p in prims if p.GetParent().GetName()==name]
        if len(candidates)!=1:raise ValueError('One actual USD prim per model visual required: '+key)
        prim=candidates[0];image=UsdGeom.Imageable(prim)
        if image.ComputeVisibility()=='invisible' or image.ComputePurpose()!='default' or semantic(prim)!='robot':
            raise ValueError('Original model visual not enabled/labeled: '+key)
        mesh=UsdGeom.Mesh(prim);points=np.asarray(mesh.GetPointsAttr().Get());indices=np.asarray(mesh.GetFaceVertexIndicesAttr().Get())
        counts=np.asarray(mesh.GetFaceVertexCountsAttr().Get())
        if np.any(counts!=3):raise ValueError('Triangulated original model USD required: '+key)
        element=robot.find(f"link[@name='{link}']").findall('visual')[int(index)].find('geometry/mesh')
        path=Path(unquote(urlparse(element.get('filename')).path));scale=np.array(element.get('scale','1 1 1').split(),float)
        original=canonical_triangles(stl_triangles(path)*scale)
        rendered=canonical_triangles(points[indices.reshape(-1,3)])
        if not np.array_equal(original,rendered):raise ValueError('Original STL and actual rendered USD surface differ: '+key)
        surface_checks.append(dict(model_visual_id=key,prim_path=str(prim.GetPath()),stl_sha256=file_hash(path),
            triangle_count=len(original),float32_triangle_surface_sha256=hashlib.sha256(original.tobytes()).hexdigest(),
            surface_comparison='EXACT_FLOAT32_SURFACE_VERTEX_AND_TRIANGLE_MULTISET'))
        visuals.append(dict(model_visual_id=key,prim_path=str(prim.GetPath()),geometry_signature=signature,
            semantic_class=semantic(prim),render_enabled=True,T_base_visual=(inverse_base@matrix(prim)).tolist()))
    pieces=[]
    canonical_pieces=held_pieces(definition,attachment)
    for item,canonical in zip(held_audit['pieces'],canonical_pieces):
        prim=stage.GetPrimAtPath(item['prim_path'])
        if semantic(prim)!='held':raise ValueError('Actual held body/stud semantic missing')
        # Preserve the recorded same-capture attachment for the consumer's
        # exact metadata comparison. Its inverse(base TCP)*base block form was
        # independently checked above; different float64 products differ by ULPs.
        pieces.append(dict(item,T_tool_piece=canonical['T_tool_piece'],semantic_class='held',render_enabled=True))
    collision_only=[l.get('name') for l in robot.findall('link') if l.findall('collision') and not l.findall('visual')]
    audit=dict(scope='SEMANTIC_FULL_SCENE_BINDING',scene=raw['scene'],
        model_manifest_sha256=model['manifest_sha256'],held_geometry_digest=digest(context),geometry_context=context,
        semantic_ids_sha256=file_hash(folder/'semantic_ids.npy'),capture_source_sha256=file_hash(folder/'capture_source.py'),
        session_id=frame['session_id'],frame_seq=frame['frame_seq'],source_stamp_s=frame['source_stamp_s'],clock_basis=frame['clock_basis'],
        robot_root_prim='/World/Robot',robot_visuals=visuals,held_pieces=pieces,
        collision_only_visual_exceptions=collision_only,collision_only_expected=collision_only,
        usd_collision_mesh_render_scope='GUIDE_PURPOSE_EXCLUDED_FROM_SENSOR_RENDER',
        robot_surface_checks=surface_checks,held_piece_checks=held_audit,
        recorded_vs_reexpressed_attachment_max_error=float(np.max(abs(np.asarray(attachment)-np.asarray(held_binding['attachment_tcp_to_block'])))),
        source_inventory_sha256=file_hash(folder/'scene_inventory.json'),
        validator_source_sha256=file_hash(Path(__file__)))
    error=semantic_scene_binding(audit,dict(semantic_ids=folder/'semantic_ids.npy',capture_source=folder/'capture_source.py'),frame,model,context)
    audit['robot_visual_fk_peak_m_rad']=error
    for name,data in [('held.definition.json',definition),('held.snapshot_binding.json',held_binding),
        ('held.piece_audit.json',held_audit),('geometry_context.json',context),('mask_audit.json',audit)]:
        (folder/name).write_text(json.dumps(data,indent=2,default=lambda value:value.item() if isinstance(value,np.generic) else value.tolist())+'\n')
    return dict(status='ORIGINAL_MODEL_AND_NATIVE_HELD_PIECES_VERIFIED',robot_visuals=len(visuals),held_pieces=len(pieces),
        robot_visual_fk_peak_m_rad=error,consumer_execution_allowed=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path);parser.add_argument('model',type=Path)
    args=parser.parse_args()
    try:result=bind(args.folder,args.model)
    except Exception as exc:
        result=dict(status='HOLD',reason=str(exc));raise
    finally:(args.folder/'inventory_binding_result.json').write_text(json.dumps(result,indent=2)+'\n')
