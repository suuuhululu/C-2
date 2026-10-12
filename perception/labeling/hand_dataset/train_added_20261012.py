"""CPU trial retraining on real RGB and AI draft labels; no independent evaluation."""
from pathlib import Path
import csv
import json
import torch
from ultralytics import YOLO

root = Path(__file__).resolve().parent
output = root.parents[1] / 'models' / 'hand_yolo11n_trial_20261012_cpu'
if output.exists():
    raise FileExistsError('Preserve existing training result')
torch.set_num_threads(2)
config = root / 'data_added_20261012.yaml'
assert len(list((root/'images/train').glob('*.png'))) == 29
model = YOLO(str(root.parents[1]/'models/hand_yolo11n_trial_20261010/hand_yolo11n_trial_best.pt'))
model.add_callback('on_train_start', lambda trainer: torch.set_num_threads(2))
model.train(data=str(config), epochs=60, imgsz=640, batch=2, device='cpu',
            workers=0, project=str(output.parent), name=output.name,
            exist_ok=False, val=False, patience=0, seed=42, plots=True, save=True)
run = Path(model.trainer.save_dir)
trained = YOLO(str(run/'weights/best.pt'))
assert trained.task == 'detect' and trained.names == {0:'hand'}
rows = list(csv.DictReader((run/'results.csv').open()))
assert len(rows) == 60
trained.predict(source=str(root/'images/train'),device='cpu',save=True,
                project=str(run),name='in_sample_preview',conf=0.25,verbose=False)
(run/'TRIAL_SUMMARY.json').write_text(json.dumps(dict(
    training_images=29,training_hands=53,epochs=60,device='cpu',
    initialization='20261010 trial best.pt',human_label_review=False,
    independent_validation=False,held_frames_used=False,
    warning='Evaluation uses training images; not deployment or generalization evidence.'),indent=2))
print('TRAINING_COMPLETED',run/'weights/best.pt',flush=True)
