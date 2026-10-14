"""Additional real-image trial; no independent validation or deployment claim."""
import sys
import subprocess
subprocess.check_call([sys.executable,'-m','pip','install','-q','ultralytics==8.4.173'])
from pathlib import Path
import zipfile
import json
import shutil
import torch
from ultralytics import YOLO
from IPython.display import HTML, display
import base64

root=Path('/content/hand_added_20261012')
if root.exists():
    raise FileExistsError(root)
with zipfile.ZipFile('/content/hand_added_20261012.zip') as archive:
    assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in archive.namelist())
    archive.extractall(root)
assert len(list((root/'images/train').glob('*.png')))==29
config=root/'data.yaml'
config.write_text('path: /content/hand_added_20261012\ntrain: images/train\nval: images/train\nnames:\n  0: hand\n')
assert torch.cuda.is_available(), 'Free GPU required; no paid upgrade'
model=YOLO('/content/hand_yolo11n_trial_best.pt')
assert model.names=={0:'hand'} and model.task=='detect'
model.train(data=str(config),epochs=60,imgsz=640,batch=8,device=0,workers=2,
            project='/content/hand_added_runs',name='trial_20261012',exist_ok=False,
            val=False,patience=0,seed=42,plots=True,save=True)
run=Path(model.trainer.save_dir)
trained=YOLO(str(run/'weights/best.pt'))
trained.predict(source=str(root/'images/train'),device=0,save=True,conf=0.25,
                project=str(run),name='in_sample_preview',verbose=False)
(run/'TRIAL_SUMMARY.json').write_text(json.dumps(dict(training_images=29,training_hands=53,
    epochs=60,initialization='20261010 trial best.pt',human_label_review=False,
    independent_validation=False,held_frames_used=False,device='Colab T4',
    warning='Evaluation uses training images; NOT generalization evidence.'),indent=2))
output=shutil.make_archive('/content/hand_added_result_20261012','zip',run)
print('TRAINING_COMPLETED:',run/'weights/best.pt',flush=True)
payload=base64.b64encode(Path(output).read_bytes()).decode()
display(HTML('<a download="hand_added_result_20261012.zip" href="data:application/zip;base64,'+payload+'">Download added hand results</a>'))
