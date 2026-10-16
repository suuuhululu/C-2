"""Initial assembly with no Current; the full waiting supply remains present."""
from pathlib import Path
import sys,json
from copy import deepcopy
REPO=Path('/home/ms-02/Documents/ChatGPT/협동2_장애물회피/work/C-2-moveit')
sys.path.insert(0,str(REPO/'isaac_sim/scripts'))
from prepare_taught_sim import prepare_taught_inputs,align_nominal_model,source_file,prepare_taught_capture_setup
from prepare_sim_scene import scene_seed,write_usd_scene
from planning_trial.assembly_api_fixtures import brick
from plan_only import digest
from sim_utils import save
E=Path(__file__).resolve().parent;OLD=E.parent/'step3_1_taught_sim_20261013';base=OLD/'design_v2'
folder=E/'empty_current';folder.mkdir(exist_ok=False)
w=json.loads((base/'prepared_input/whole.request.json').read_text())
w['design']=dict(design_version=1,blocks=[brick(x=11,y=11)])
w['current']=dict(current_revision=0,blocks=[])
w['context'].update(request_id='sim-stage4-empty-current',world_state_revision=14,input_current_revision=0,
    design_version=1,workflow_generation=34,source_epoch='sim-nominal-collision-case-20261013')
prepared=prepare_taught_inputs(w,REPO/'robot_control_integration',1)
geometry=json.loads((base/'nominal_geometry.json').read_text());geometry['current_models']=[]
geometry['evidence_ref']=str(folder/'nominal_geometry.json')
save(folder/'nominal_geometry.json',geometry)
prepared['coordinate_provenance']['sources'].update(nominal_geometry=source_file(folder/'nominal_geometry.json'),case_builder=source_file(__file__))
template=json.loads((base/'prepared_input/model.json').read_text())
template['plan_base_current']=deepcopy(w['current']);template['selected_action']=deepcopy(prepared['reassessment_result']['action_proposal'])
model=align_nominal_model(template,prepared,geometry);seed=scene_seed(model,prepared['motion_request'])
(folder/'prepared_input').mkdir();(folder/'scene').mkdir()
for key in ('whole_request','whole_result','reassessment_request','reassessment_result','motion_request','motion_result'):
    save(folder/'prepared_input'/(key.replace('_','.')+'.json'),prepared[key])
save(folder/'prepared_input/model.json',model)
alignment=write_usd_scene(seed,folder/'scene/scene.usda',REPO/'isaac_sim/assets/aligned_robot.sim.usda')
save(folder/'scene/scene.seed.json',seed);save(folder/'scene/frame_alignment.seed.json',alignment)
setup=json.loads((base/'capture.solver128_16.setup.json').read_text())
setup.update(seed_digest=digest(seed),motion_input_digest=digest(prepared['motion_request']),d_gripper_reference=deepcopy(seed['d_gripper_reference']),
    fresh_capture_case='empty_current',setup_reference_only=True,old_observation_reused_as_current=False)
save(folder/'capture.setup.json',setup)
prepare_taught_capture_setup(seed,prepared['motion_request'],E.parent/'step3_gpu_model_20261013/model',folder/'capture.setup.json')
print('No Current; all25 supply bodies retained; scene objects',len(seed['world_objects']))
