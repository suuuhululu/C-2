"""Local pixel edge/grid direction diagnostics. No metric or robot authority."""
import math
import numpy as np


def track_visible_edge(previous_gray,current_gray,edge):
    """Track the operator-labelled top edge; reject lost or inconsistent corners."""
    import cv2
    points=np.asarray(edge,np.float32)
    if points.shape!=(2,2) or not np.isfinite(points).all():return None
    options=dict(winSize=(21,21),maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
    tracked,ok,_=cv2.calcOpticalFlowPyrLK(previous_gray,current_gray,points.reshape(-1,1,2),None,**options)
    if tracked is None or not ok.all() or not np.isfinite(tracked).all():return None
    back,back_ok,_=cv2.calcOpticalFlowPyrLK(current_gray,previous_gray,tracked,None,**options)
    if back is None or not back_ok.all() or not np.isfinite(back).all():return None
    result=tracked.reshape(2,2)
    h,w=current_gray.shape
    if (np.linalg.norm(back.reshape(2,2)-points,axis=1).max()>1.5
            or np.linalg.norm(result[1]-result[0])<8
            or np.any(result<0) or np.any(result[:,0]>=w) or np.any(result[:,1]>=h)):
        return None
    return result.tolist()


def angle_delta(target, source):
    return (target-source+90.)%180.-90.


def fit_grid_axes(points, merge_px=3., angle_tolerance_deg=6.):
    result=dict(status='UNKNOWN', reason=None, axes_deg=[], physical_commands=0, execution_allowed=False)
    data=np.asarray(points,dtype=float)
    if data.ndim!=2 or data.shape[1]!=2 or not np.isfinite(data).all():
        result['reason']='INVALID_CENTERS';return result
    # Retain one centroid per local circular-feature cluster.
    groups=[]
    for point in data:
        group=next((g for g in groups if np.linalg.norm(point-np.mean(g,axis=0))<=merge_px),None)
        if group is None:groups.append([point])
        else:group.append(point)
    centers=np.asarray([np.mean(g,axis=0) for g in groups])
    result['unique_centers_uv']=centers.tolist()
    if len(centers)<6:
        result['reason']='AT_LEAST_SIX_DISTINCT_CENTERS_REQUIRED';return result
    distances=np.linalg.norm(centers[:,None]-centers[None,:],axis=2)
    np.fill_diagonal(distances,np.inf)
    pitch=float(np.median(distances.min(axis=1)))
    if pitch<=2*merge_px:
        result['reason']='UNRESOLVED_FEATURE_SPACING';return result
    pairs=[]
    for i in range(len(centers)):
        for j in np.argsort(distances[i])[:4]:
            if j>i and .65*pitch<=distances[i,j]<=1.35*pitch:
                vector=centers[j]-centers[i]
                pairs.append((i,int(j),math.degrees(math.atan2(vector[1],vector[0]))%180))
    if len(pairs)<6:
        result['reason']='NEIGHBOR_CONNECTIONS_INSUFFICIENT';return result
    angles=np.array([p[2] for p in pairs])
    clusters=[]
    for seed in angles:
        selected=np.abs((angles-seed+90)%180-90)<=angle_tolerance_deg
        support=int(selected.sum())
        values=np.radians(angles[selected]*2)
        axis=math.degrees(math.atan2(np.sin(values).mean(),np.cos(values).mean()))/2%180
        residual=float(np.max(np.abs((angles[selected]-axis+90)%180-90)))
        clusters.append((support,axis,residual,selected))
    clusters.sort(key=lambda item:item[0],reverse=True)
    first=clusters[0]
    second=next((c for c in clusters if 50<=abs(angle_delta(c[1],first[1]))<=90),None)
    if first[0]<3 or second is None or second[0]<3:
        result['reason']='TWO_GRID_AXIS_CONSENSUSES_REQUIRED';return result
    result.update(status='PIXEL_GRID_AXES_CANDIDATE', axes_deg=[first[1],second[1]],
        support_pairs=[first[0],second[0]], maximum_angle_residual_deg=[first[2],second[2]],
        nearest_spacing_px=pitch, origin_uv=np.median(centers,axis=0).tolist(),
        neighbor_pairs=[dict(points_uv=[centers[i].tolist(),centers[j].tolist()],angle_deg=a) for i,j,a in pairs],
        grid_cell_identity_verified=False)
    return result


def compare_edge_grid(edges, points, axis_index=None):
    result=dict(status='UNKNOWN', reason=None, grid=fit_grid_axes(points),
                robot_correction=None, execution_allowed=False, physical_commands=0)
    if result['grid']['status']=='UNKNOWN':
        result['reason']=result['grid']['reason'];return result
    segments=[]
    for edge in edges:
        p=np.asarray(edge,dtype=float)
        if p.shape!=(2,2) or not np.isfinite(p).all():continue
        vector=p[1]-p[0];length=float(np.linalg.norm(vector))
        if length>=8:segments.append((length,p,math.degrees(math.atan2(vector[1],vector[0]))%180))
    if not segments:
        result['reason']='VISIBLE_EDGE_INSUFFICIENT';return result
    length,edge,angle=max(segments,key=lambda item:item[0])
    axes=result['grid']['axes_deg']
    selected=min(range(2),key=lambda i:abs(angle_delta(axes[i],angle))) if axis_index is None else axis_index
    if selected not in (0,1):raise ValueError('GRID_AXIS_0_OR_1_REQUIRED')
    result.update(status='EDGE_GRID_RELATIVE_ANGLE_CANDIDATE',block_edge_uv=edge.tolist(),
        block_edge_angle_deg=angle,selected_grid_axis=selected,grid_axis_angle_deg=axes[selected],
        relative_angle_deg=angle_delta(axes[selected],angle),edge_length_px=length,
        axis_selection='NEAREST_IMAGE_AXIS' if axis_index is None else 'OPERATOR_SELECTED_AXIS',
        body_edge_identity_verified=False,metric_alignment_verified=False)
    return result
