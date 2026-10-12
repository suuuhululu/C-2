import json
from pathlib import Path
import cv2
import numpy as np
source=Path('/home/roh/C-2/perception/recordings/supply_board_roi/20261012T002844481743Z/rgb.png')
out=Path('/home/roh/C-2/perception/labeling/supply_top_review_20261012')
im=cv2.imread(str(source)); canvas=im.copy()
# Visually placed top-face corner drafts, not detector output or verified ground truth.
rows=[
('yellow_2x2',[[[293,95],[347,95],[348,150],[293,150]],[[413,95],[466,95],[468,151],[414,151]],[[513,96],[567,95],[567,151],[514,151]],[[631,95],[685,95],[685,150],[631,150]],[[739,99],[793,99],[792,151],[738,151]],[[850,95],[904,94],[902,148],[849,149]]]),
('yellow_2x3',[[[291,180],[345,181],[342,263],[289,261]],[[413,182],[464,183],[466,263],[412,263]],[[518,180],[572,180],[572,260],[518,260]],[[632,180],[685,179],[685,261],[632,262]],[[739,180],[790,180],[790,261],[738,261]],[[852,179],[905,178],[904,257],[851,258]]]),
('blue_2x2',[[[294,317],[348,316],[348,368],[294,368]],[[408,321],[462,319],[462,371],[408,372]],[[525,318],[578,318],[578,370],[525,370]],[[634,317],[687,317],[687,368],[634,369]],[[742,317],[795,318],[794,368],[741,368]],[[854,320],[906,320],[906,370],[854,370]]]),
('blue_2x3',[[[299,405],[353,405],[353,483],[299,483]],[[411,404],[464,405],[463,483],[410,482]],[[522,402],[572,402],[573,481],[521,481]],[[635,401],[682,397],[689,475],[642,480]],[[746,408],[796,409],[795,486],[745,486]],[[853,408],[904,409],[904,488],[853,487]]]),
('red_2x1',[[[299,545],[351,543],[352,569],[300,570]],[[415,549],[468,548],[467,573],[415,573]],[[519,544],[569,545],[568,569],[518,568]],[[634,541],[683,541],[683,566],[634,566]],[[743,537],[794,538],[794,562],[743,562]],[[856,545],[907,540],[909,565],[859,571]]]),
('red_2x1',[[[299,631],[350,628],[352,652],[299,658]],[[416,633],[467,632],[469,655],[416,660]],[[529,631],[580,628],[581,652],[530,658]],[[636,632],[683,632],[684,656],[636,657]],[[745,623],[791,626],[791,649],[745,646]],[[856,625],[903,625],[906,649],[859,652]]])]
records=[]
colors={'yellow':(255,80,255),'blue':(0,255,255),'red':(255,255,0)}
for name,polygons in rows:
 for p in polygons:
  n=len(records)+1
  records.append({'id':n,'class_name':name,'top_polygon_uv':p,'reviewed':False})
  cv2.polylines(canvas,[np.int32(p)],True,colors[name.split('_')[0]],2)
  cv2.putText(canvas,str(n),tuple(p[0]),0,.4,(255,255,255),1)
footer=np.zeros((48,1280,3),np.uint8)
cv2.putText(footer,'TOP-FACE LABEL DRAFT | 36 polygons | visually placed corners, NOT automatic extraction | REVIEW REQUIRED',(15,30),0,.65,(255,255,255),1)
assert cv2.imwrite(str(out/'top_faces_draft.png'),np.vstack([canvas,footer]))
assert cv2.imwrite(str(out/'top_faces_closeup.png'),canvas[80:675,240:925])
report={'source':str(source),'image_size':[1280,720],'purpose':'TOP_FACE_LABEL_REVIEW',
 'method':'visually_placed_polygon_draft_drawn_with_opencv','status':'UNREVIEWED_NOT_TRAINING_GT','annotations':records}
(out/'top_faces_draft.json').write_text(json.dumps(report,indent=2))
print('Saved 36 draft top polygons; original unchanged:',out)
