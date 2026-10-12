"""Colab-only trial on approved, unreviewed real labels; not deployment validation."""
import sys
import subprocess
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'ultralytics==8.4.173'])
from pathlib import Path
import json
import zipfile
import shutil
import torch
from google.colab import files
from ultralytics import YOLO

uploaded = files.upload()
if list(uploaded) != ['hand_train_trial.zip']:
    raise ValueError('Upload hand_train_trial.zip only')
root = Path('/content/c2_hand_trial')
if root.exists():
    raise FileExistsError('Trial directory exists; preserve earlier results')
with zipfile.ZipFile('hand_train_trial.zip') as archive:
    for name in archive.namelist():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Unsafe archive path')
    archive.extractall(root)
assert len(list((root/'images/train').glob('*.png'))) == 16
assert len(list((root/'labels/train').glob('*.txt'))) == 16
print('TRIAL ONLY: 16 AI-draft frames; no independent validation; 4 held frames excluded.')
device = 0 if torch.cuda.is_available() else 'cpu'
print('Training device:', device)
model = YOLO('yolo11n.pt')
model.train(data=str(root/'data_trial.yaml'), epochs=60, imgsz=640, batch=8,
            device=device, workers=2, project='/content/c2_hand_runs', name='trial',
            exist_ok=False, val=False, patience=0, seed=42, plots=True, save=True)
run = Path(model.trainer.save_dir)
best = run/'weights/best.pt'
assert best.is_file()
trained = YOLO(str(best))
assert trained.task == 'detect' and trained.names == {0:'hand'}
trained.predict(source=str(root/'images/train'), device=device, conf=0.25,
                save=True, project='/content/c2_hand_runs', name='in_sample_preview',
                exist_ok=False, verbose=False)
summary = {'scope':'TRIAL_UNREVIEWED_IN_SAMPLE_ONLY', 'source_model':'yolo11n.pt',
           'class_names':{'0':'hand'}, 'training_frames':16, 'epochs':60,
           'independent_validation':False, 'human_label_review':False,
           'held_frames_used':False, 'device':str(device),
           'warning':'Any reported final validation metrics use training images and are NOT generalization evidence.'}
(run/'TRIAL_SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n')
package = Path('/content/c2_hand_trial_result')
package.mkdir()
shutil.copy2(best,package/'hand_yolo11n_trial_best.pt')
shutil.copy2(run/'weights/last.pt',package/'hand_yolo11n_trial_last.pt')
for name in ('TRIAL_SUMMARY.json','args.yaml','results.csv','results.png'):
    if (run/name).is_file():
        shutil.copy2(run/name,package/name)
shutil.copytree('/content/c2_hand_runs/in_sample_preview',package/'in_sample_preview')
archive_path=shutil.make_archive('/content/c2_hand_trial_result','zip',package)
print('TRAINING_COMPLETED:',best)
print('RESULT_ARCHIVE:',archive_path)
files.download(archive_path)
