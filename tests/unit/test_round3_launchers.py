"""Both checkout layouts invoke a fake Python; no Qt, ROS, device or API opens."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('delivered',[False,True])
@pytest.mark.parametrize('launcher',['round3_service.bash','round3_stack_five.bash','round3_b_three_step.bash'])
def test_preview_uses_original_venv_but_current_checkout_code(tmp_path,delivered,launcher):
    current=tmp_path/('delivery/runtime' if delivered else 'C-2-round4')
    original=tmp_path/'C-2-round3'
    (current/'scripts').mkdir(parents=True);(current/'robot_control_integration').mkdir()
    python=original/'.venv/bin/python3';python.parent.mkdir(parents=True)
    python.write_text(f'#!{sys.executable}\nimport os,sys,json\nwith open(os.environ["TRACE"],"a") as f: f.write(json.dumps(dict(args=sys.argv[1:],cwd=os.getcwd()))+"\\n")\n')
    python.chmod(0o755)
    shutil.copy2(ROOT/'scripts'/launcher,current/'scripts'/launcher)
    env=dict(os.environ,TRACE=str(tmp_path/'trace.jsonl'));env.pop('C2_ROUND3_BASE_ROOT',None);env.pop('C2_B3_PYTHON',None)
    result=subprocess.run(['bash',str(current/'scripts'/launcher),'preview'],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    calls=[json.loads(s) for s in (tmp_path/'trace.jsonl').read_text().splitlines()]
    assert calls[0]['cwd']==str(current)
    assert all(str(current) in c['cwd'] for c in calls)
    assert len(calls)==(2 if launcher=='round3_b_three_step.bash' else 1)


def test_service_hmi_accepts_explicit_private_env_without_real_python(tmp_path):
    current=tmp_path/'C-2-round4';original=tmp_path/'private-base'
    (current/'scripts').mkdir(parents=True)
    python=original/'.venv/bin/python3';python.parent.mkdir(parents=True)
    python.write_text(f'#!{sys.executable}\nimport os,json\nprint(json.dumps(dict(root=os.environ["C2_PROJECT_ROOT"],model=os.environ["OPENAI_MODEL"],cwd=os.getcwd())))\n')
    python.chmod(0o755)
    (original/'.env.round3-local.bash').write_text('cd /\n')
    (original/'.env.sixpart-local.bash').write_text('export OPENAI_LLM_API_KEY=TEST_FIXTURE_ONLY\n')
    private=tmp_path/'private-service.bash';private.write_text('export OPENAI_MODEL=fixture-model\n')
    shutil.copy2(ROOT/'scripts/round3_service.bash',current/'scripts/round3_service.bash')
    env=dict(os.environ,C2_ROUND3_BASE_ROOT=str(original),C2_SERVICE_LOCAL_ENV=str(private))
    env.pop('C2_ROUND3_ENV',None);env.pop('C2_SERVICE_ENV',None)
    result=subprocess.run(['bash',str(current/'scripts/round3_service.bash'),'hmi'],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)==dict(root=str(current),model='fixture-model',cwd=str(current))
