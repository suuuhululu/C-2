"""Two-stage offline test: color contour -> stud candidates -> complete lattice."""
import itertools
import cv2
import numpy as np


def candidates(image, row, method="baseline"):
    x,y,w,h = row['bbox_xywh']
    # Upscale for numerical stability, not to create additional detail.
    scale = 4
    crop = cv2.resize(image[y:y+h,x:x+w],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    if method == 'clahe_v':
        value = cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)[:,:,2]
        gray = cv2.createCLAHE(clipLimit=2.,tileGridSize=(4,4)).apply(value)
    elif method not in ('baseline','blackhat'):
        raise ValueError('Unknown method: '+method)
    outline = np.zeros(image.shape[:2],np.uint8)
    cv2.fillPoly(outline,[np.array(row['contour_uv'],np.int32)],255)
    inside = cv2.resize(outline[y:y+h,x:x+w],(w*scale,h*scale),interpolation=cv2.INTER_NEAREST)
    inside = cv2.erode(inside,np.ones((9,9),np.uint8))
    # Stud rims are locally darker than their colored surroundings.
    smooth = cv2.GaussianBlur(gray,(0,0),2.5*scale)
    dark = cv2.subtract(smooth,gray)
    if method == 'blackhat':
        dark = cv2.morphologyEx(gray,cv2.MORPH_BLACKHAT,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9*scale+1,9*scale+1)))
    binary = np.uint8(dark >= 5)*255
    binary &= inside
    binary = cv2.morphologyEx(binary,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_ = cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    found=[]
    for contour in contours:
        area=cv2.contourArea(contour)/scale**2
        if len(contour)<5 or not 5 <= area <= 85:continue
        (u,v),(a,b),angle=cv2.fitEllipse(contour)
        small,large=sorted((a/scale,b/scale))
        if not 2.5<=small<=10 or not large<=12 or large/small>2:continue
        fill=area/(np.pi*a*b/4/scale**2)
        if not .45<=fill<=1.35:continue
        point=[x+u/scale,y+v/scale]
        if any(np.linalg.norm(np.array(point)-f['center_uv'])<3 for f in found):continue
        found.append(dict(center_uv=point,diameter_px=(small+large)/2,contrast=float(dark[int(round(v)),int(round(u))])))
    return found,binary


def fit_array(found, kind):
    cols,rows=map(int,kind.split('x')[:2])
    expected=cols*rows
    if len(found)<expected:return None,'INCOMPLETE_STUD_ARRAY'
    if len(found)>14:return None,'TOO_MANY_CANDIDATES'
    points=np.array([f['center_uv'] for f in found])
    # Enumerate nearby axis vectors. Each candidate must match a unique lattice cell.
    accepted={}
    for origin_index,origin in enumerate(points):
        for j,k in itertools.permutations(range(len(points)),2):
            if j==origin_index or k==origin_index:continue
            a,b=points[j]-origin,points[k]-origin
            la,lb=np.linalg.norm(a),np.linalg.norm(b)
            if not 6<=la<=22 or not 6<=lb<=22:continue
            if abs(np.dot(a,b)/(la*lb))>.35 or not .65<=la/lb<=1.55:continue
            if cols==1:continue
            grid=np.array([origin+i*a+t*b for t in range(rows) for i in range(cols)])
            distances=np.linalg.norm(grid[:,None,:]-points[None,:,:],axis=2)
            ids=distances.argmin(axis=1)
            error=distances[np.arange(expected),ids]
            if len(set(ids))!=expected or error.max()>min(la,lb)*.18:continue
            diam=np.array([found[i]['diameter_px'] for i in ids])
            if diam.max()/diam.min()>1.65:continue
            key=tuple(sorted(ids.tolist()))
            score=float(np.mean(error**2))
            if key not in accepted or score<accepted[key]['score']:
                design=np.array([[1,i,t] for t in range(rows) for i in range(cols)])
                coefficients=np.linalg.lstsq(design,points[ids],rcond=None)[0]
                center=np.array([1,(cols-1)/2,(rows-1)/2])@coefficients
                axes=coefficients[1:]
                lines=[[ (center-axis*extent/2).tolist(),(center+axis*extent/2).tolist()]
                       for axis,extent in zip(axes,(cols,rows))]
                accepted[key]=dict(center_uv=center.tolist(),lines_uv=lines,selected_indices=ids.tolist(),score=score)
    # 1x2 has only two studs: no second axis can be verified.
    if cols==1:
        for j,k in itertools.combinations(range(len(points)),2):
            a=points[k]-points[j];length=np.linalg.norm(a)
            if not 6<=length<=22:continue
            if max(found[j]['diameter_px'],found[k]['diameter_px'])/min(found[j]['diameter_px'],found[k]['diameter_px'])>1.65:continue
            center=(points[j]+points[k])/2
            b=np.array([-a[1],a[0]])/2
            accepted[(j,k)]=dict(center_uv=center.tolist(),lines_uv=[[(center-a).tolist(),(center+a).tolist()],[(center-b).tolist(),(center+b).tolist()]],selected_indices=[j,k],score=0)
    if not accepted:return None,'STUD_GEOMETRY_REJECTED'
    if len(accepted)>1:return None,'AMBIGUOUS_STUD_ARRAY'
    return next(iter(accepted.values())),'COMPLETE_ARRAY_CANDIDATE'
