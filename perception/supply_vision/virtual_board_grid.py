"""Project the existing provisional board calibration; display diagnostics only."""
import json
from pathlib import Path
import math
from hashlib import sha256
import cv2
import numpy as np
from scipy.spatial.transform import Rotation
import yaml


def pose_matrix(pose):
    p=np.asarray(pose,float)
    if p.shape!=(6,) or not np.isfinite(p).all():raise ValueError('FINITE_MM_ZYZ_POSE_REQUIRED')
    matrix=np.eye(4);matrix[:3,:3]=Rotation.from_euler('ZYZ',p[3:],degrees=True).as_matrix();matrix[:3,3]=p[:3]
    return matrix


def layer_reference(records,target):
    """Prefer the explicitly adopted measurement, retaining all historical rows."""
    matches=[r for r in records if r.get('target')==target and not r.get('model_excluded')
        and r.get('adopt_as_layer_z') is not False]
    adopted=[r for r in matches if r.get('adopt_as_layer_z') is True]
    selected=adopted or matches
    if len(selected)!=1:raise ValueError('UNIQUE_TARGET_LAYER_REFERENCE_REQUIRED')
    return selected[0]


def static_transform(path,parent,child):
    graph={}
    records=[row for document in yaml.safe_load_all(Path(path).read_text()) if document for row in document['transforms']]
    definitions={}
    for row in records:
        source=row['header']['frame_id'];target=row['child_frame_id'];value=row['transform']
        t=value['translation'];r=value['rotation'];matrix=np.eye(4)
        matrix[:3,:3]=Rotation.from_quat([r[k] for k in ('x','y','z','w')]).as_matrix()
        matrix[:3,3]=[t[k]*1000 for k in ('x','y','z')]
        if target in definitions:
            previous_source,previous_matrix=definitions[target]
            if previous_source!=source or not np.allclose(previous_matrix,matrix,atol=1e-8):
                raise ValueError('CONFLICTING_STATIC_TRANSFORM:'+target)
            continue
        definitions[target]=(source,matrix)
        graph.setdefault(source,[]).append((target,matrix))
        graph.setdefault(target,[]).append((source,np.linalg.inv(matrix)))
    queue=[(parent,np.eye(4))];seen={parent}
    for current,transform in queue:
        if current==child:return transform
        for neighbor,matrix in graph.get(current,[]):
            if neighbor not in seen:
                seen.add(neighbor);queue.append((neighbor,transform@matrix))
    raise ValueError('STATIC_CAMERA_TRANSFORM_PATH_MISSING')


def project_base(points,T_base_camera,k,d):
    points=np.asarray(points,float)
    K=np.asarray(k,float).reshape(3,3)
    if points.ndim!=2 or points.shape[1]!=3 or not np.isfinite(points).all() or not np.isfinite(K).all() or K[0,0]<=0 or K[1,1]<=0:
        raise ValueError('FINITE_POINTS_AND_CAMERA_INTRINSICS_REQUIRED')
    camera=(np.linalg.inv(T_base_camera)@np.column_stack((points,np.ones(len(points)))).T).T[:,:3]
    valid=camera[:,2]>1.
    pixels=np.full((len(points),2),np.nan)
    if valid.any():pixels[valid]=cv2.projectPoints(camera[valid],np.zeros(3),np.zeros(3),K,np.asarray(d,float))[0].reshape(-1,2)
    return pixels,valid


def parallel_axes_at_pixel(pixel,T_base_camera,T_base_board,k,d,plane_z_mm,pitch_mm):
    """Project parallel board directions through the edge, independent of stud centers.

    Parallel 3D lines share a direction, but perspective can change their local
    pixel slopes. Intersect the edge midpoint ray with the selected layer plane.
    This supplies orientation only; it does not identify a physical stud or XY.
    """
    K=np.asarray(k,float).reshape(3,3)
    ray=cv2.undistortPoints(np.asarray(pixel,float).reshape(1,1,2),K,np.asarray(d,float)).reshape(2)
    board_from_camera=np.linalg.inv(T_base_board)@T_base_camera
    origin=board_from_camera[:3,3]
    direction=board_from_camera[:3,:3]@np.array([*ray,1.])
    if abs(direction[2])<1e-9:return [],[]
    distance=(plane_z_mm-origin[2])/direction[2]
    if distance<=0:return [],[]
    center=origin+distance*direction
    axes=[];segments=[]
    for delta in ([pitch_mm,0.,0.],[0.,pitch_mm,0.]):
        local=np.array([center-np.asarray(delta),center+np.asarray(delta)])
        base=(T_base_board@np.column_stack((local,np.ones(2))).T).T[:,:3]
        uv,valid=project_base(base,T_base_camera,k,d)
        if not valid.all():return [],[]
        vector=uv[1]-uv[0]
        if np.linalg.norm(vector)<1e-6:return [],[]
        axes.append(math.degrees(math.atan2(vector[1],vector[0]))%180)
        segments.append(uv.tolist())
    return axes,segments


class VirtualBoardGrid:
    def __init__(self,config):
        root=Path(__file__).resolve().parents[2]
        config={k:str(Path(v) if Path(v).is_absolute() else root/v) for k,v in config.items()}
        self.config=config
        self.board=json.loads(Path(config['board_calibration']).read_text())
        self.T_base_board=np.asarray(self.board['rigid_16mm_fit']['T_robot_base_from_board_mm'],float)
        if self.T_base_board.shape!=(4,4):raise ValueError('BOARD_TRANSFORM_REQUIRED')
        self.T_tool_camera=static_transform(config['static_tf'],'link_6','camera_color_optical_frame')
        self.T_tool_tcp=pose_matrix(self.board['tcp']['configured_flange_from_tcp_pose'])
        self.geometry=json.loads(Path(config['block_geometry']).read_text())['reported_dimensions']
        self.layer_records=json.loads(Path(config['layer_records']).read_text())
        self.sources={key:dict(path=str(Path(path).resolve()),sha256=sha256(Path(path).read_bytes()).hexdigest()) for key,path in config.items()}

    def overlay(self,frame,sample,info,layer=1,clearance_mm=20.,edges=(),axis_index=None,target_xy=(11,11),*,target=None):
        """An explicit common block supplies the display footprint and target layer.

        Layer offsets still come from the existing yellow 2x2 teaching anchor.
        Omitting target preserves the legacy yellow 2x2 target_xy/layer view.
        """
        report=dict(status='VIRTUAL_GRID_PREVIEW',execution_allowed=False,physical_commands=0,
            calibration_status=self.board['status'],physical_tip_coincides_with_tcp=self.board['tcp']['physical_tip_coincides_with_tcp'],
            sources=self.sources,projection_independently_verified=False,native_flange_frame_assumption='link_6',robot_correction=None,relative_angle_deg=None)
        if info is None:
            report.update(status='UNKNOWN',reason='CAMERA_INFO_REQUIRED');return frame.copy(),report
        if (info.width,info.height)!=(frame.shape[1],frame.shape[0]) or info.header.frame_id!='camera_color_optical_frame':
            report.update(status='UNKNOWN',reason='CAMERA_INFO_SIZE_OR_FRAME_MISMATCH');return frame.copy(),report
        if info.distortion_model not in ('plumb_bob','rational_polynomial'):
            report.update(status='UNKNOWN',reason='UNSUPPORTED_DISTORTION_MODEL');return frame.copy(),report
        target=(dict(brick_type='2x2x1',color='yellow',x=target_xy[0],y=target_xy[1],layer=layer,orientation_deg=0)
            if target is None else dict(target))
        layer=target['layer']
        if not 1<=layer<=5 or clearance_mm<0:raise ValueError('TARGET_LAYER_AND_CLEARANCE_REQUIRED')
        layer_anchor=dict(brick_type='2x2x1',color='yellow',x=11,y=11,layer=layer,orientation_deg=0)
        def seated_z(n):
            return layer_reference(self.layer_records,dict(layer_anchor,layer=n))['sample']['posx'][2]
        support_height=seated_z(layer)-seated_z(1)
        body_height=self.geometry['body_height_without_studs_mm'];stud_height=self.geometry['height_with_studs_mm']-body_height
        top_height=support_height+body_height-stud_height
        T_base_camera=pose_matrix(sample['posx'])@np.linalg.inv(self.T_tool_tcp)@self.T_tool_camera
        pitch=self.board['stud_pitch_mm']
        def base(points):
            return (self.T_base_board@np.column_stack((np.asarray(points,float),np.ones(len(points)))).T).T[:,:3]
        def pixels(points):return project_base(base(points),T_base_camera,info.k,info.d)
        canvas=frame.copy();segments=[]
        for i in range(24):
            for local in ([[i*pitch,0,support_height],[i*pitch,23*pitch,support_height]],
                          [[0,i*pitch,support_height],[23*pitch,i*pitch,support_height]]):
                uv,valid=pixels(local)
                if valid.all():
                    a,b=np.clip(uv,-10000,10000).astype(int)
                    cv2.line(canvas,tuple(a),tuple(b),(255,180,0),1)
                    segments.append(uv.tolist())
        nx,ny=map(int,target['brick_type'].split('x')[:2])
        if target['orientation_deg']==90:nx,ny=ny,nx
        center=np.array([(target['x']+(nx-1)/2)*pitch,(target['y']+(ny-1)/2)*pitch])
        extent=np.array([self.geometry[f'span_{n}_outer_length_mm'] for n in (nx,ny)])
        outline_local=[[center[0]+dx*extent[0]/2,center[1]+dy*extent[1]/2,top_height+clearance_mm] for dx,dy in [(-1,-1),(1,-1),(1,1),(-1,1)]]
        outline,valid=pixels(outline_local)
        color={'yellow':(0,255,255),'blue':(255,100,0),'red':(0,0,255)}[target['color']]
        if valid.all():cv2.polylines(canvas,[np.clip(outline,-10000,10000).astype(np.int32)],True,color,2)
        seated,_=pixels([[p[0],p[1],top_height] for p in outline_local])
        if np.isfinite(seated).all():cv2.polylines(canvas,[np.clip(seated,-10000,10000).astype(np.int32)],True,(255,100,255),1)
        axes=[]
        for delta in ([pitch,0],[0,pitch]):
            uv,ok=pixels([[*center,top_height+clearance_mm],[center[0]+delta[0],center[1]+delta[1],top_height+clearance_mm]])
            if not ok.all():continue
            v=uv[1]-uv[0]
            if np.linalg.norm(v)<1e-6:continue
            axes.append(math.degrees(math.atan2(v[1],v[0]))%180)
        lengths=[]
        for edge in edges:
            points=np.asarray(edge,float)
            if points.shape==(2,2) and np.isfinite(points).all():
                length=float(np.linalg.norm(points[1]-points[0]))
                if length>=8:lengths.append((length,points))
        if lengths and len(axes)==2:
            length,edge=max(lengths,key=lambda item:item[0]);v=edge[1]-edge[0]
            axes,local_segments=parallel_axes_at_pixel(edge.mean(axis=0),T_base_camera,self.T_base_board,
                info.k,info.d,top_height+clearance_mm,pitch)
            if len(axes)!=2:
                report.update(reason='LOCAL_PARALLEL_DIRECTIONS_UNAVAILABLE');return canvas,report
            angle=math.degrees(math.atan2(v[1],v[0]))%180
            difference=lambda value:(value-angle+90)%180-90
            index=min(range(2),key=lambda i:abs(difference(axes[i]))) if axis_index is None else axis_index
            report.update(block_edge_uv=edge.tolist(),block_edge_angle_deg=angle,selected_grid_axis=index,
                grid_axis_angle_deg=axes[index],relative_angle_deg=difference(axes[index]),axes_deg=axes,
                comparison_scope='YAW_DIRECTION_ONLY',stud_center_coincidence_required=False,
                roll_pitch_observed=False,local_reference_segments_uv=local_segments)
            for segment in local_segments:
                cv2.line(canvas,tuple(np.asarray(segment[0],int)),tuple(np.asarray(segment[1],int)),(255,255,0),2)
            cv2.line(canvas,tuple(edge[0].astype(int)),tuple(edge[1].astype(int)),(0,0,255),2)
        report.update(target=target,support_plane_offset_mm=support_height,body_top_offset_mm=top_height,
            target_footprint_studs=[nx,ny],target_center_board_mm=center.tolist(),target_outer_extent_mm=extent.tolist(),
            layer_height_reference_target=layer_anchor,
            hover_body_top_offset_mm=top_height+clearance_mm,clearance_mm=clearance_mm,
            grid_segments_uv=segments,target_hover_outline_uv=[[float(value) if np.isfinite(value) else None for value in point] for point in outline],
            target_seated_outline_uv=[[float(value) if np.isfinite(value) else None for value in point] for point in seated],
            T_base_from_camera_mm=T_base_camera.tolist(),reason=None if report['relative_angle_deg'] is not None else 'VISIBLE_BODY_EDGE_REQUIRED',
            T_base_from_board_mm=self.T_base_board.tolist(),
            target_hover_outline_base_mm=base(outline_local).tolist(),
            datum_basis='EXISTING_BOARD_CONTACT_PROXY_AND_LAYER_TCP_HEIGHT_DIFFERENCES')
        return canvas,report
