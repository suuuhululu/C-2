"""Request-bound CLAHE-first stud observation; taught coordinates are retained on failure."""
import cv2
import numpy as np
from .outline import detect
from .studs import candidates, fit_array


def observe(frame, layout, row, stamp):
    entries=[s for s in layout['slots'] if (s['color'],s['brick_type'],s['slot'])==(row['color'],row['brick_type'],row['slot'])]
    if len(entries)!=1:raise ValueError('EXACT_TARGET_SLOT_REQUIRED')
    entry=dict(entries[0]);kind=row['brick_type'];red=row['color']=='red'
    short,long=(20,39) if red else (38,38 if kind=='2x2x1' else 58)
    entry.update(id='requested',instance=1)
    defaults=dict(min_area_px=150,short_side_px=[short*.65,short*1.3],long_side_px=[long*.65,long*1.3],
        aspect_range=[1,1.3] if kind=='2x2x1' else ([1.25,1.9] if kind=='2x3x1' else [1.5,2.8]))
    for key,value in defaults.items():entry.setdefault(key,value)
    config=dict(image_size=layout['image_size'],hsv_ranges=layout['surface']['hsv_ranges'],slots=[entry])
    outlines,_=detect(frame,config);outline=outlines[0]
    result=dict(slot_id=f"{row['color']}_{kind}_{row['slot']:02d}",vision_attempted=True,inference_completed=True,recognized=False,center_available=False,center_uv=None,center_basis='STUD_ARRAY',reason=outline['reason'],frame_stamp_ns=stamp,attempts=[],execution_allowed=False)
    if not outline['success']:return result
    scale=.75;small=cv2.resize(frame,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    contour=np.rint(np.array(outline['contour_uv'])*scale).astype(np.int32)
    contour[:,0]=np.clip(contour[:,0],0,small.shape[1]-1);contour[:,1]=np.clip(contour[:,1],0,small.shape[0]-1)
    normalized=dict(contour_uv=contour.tolist(),bbox_xywh=list(cv2.boundingRect(contour)))
    for method in ('clahe_v','baseline'):
        found,_=candidates(small,normalized,method);fit,reason=fit_array(found,kind)
        result['attempts'].append(dict(method=method,candidate_count=len(found),reason=reason))
        result['reason']=reason
        if fit:
            result.update(recognized=True,center_available=True,center_uv=(np.array(fit['center_uv'])/scale).tolist(),selected_method=method,center_lines_uv=(np.array(fit['lines_uv'])/scale).tolist(),stud_centers_uv=[(np.array(found[i]['center_uv'])/scale).tolist() for i in fit['selected_indices']])
            break
    result['contour_uv']=outline['contour_uv']
    return result
