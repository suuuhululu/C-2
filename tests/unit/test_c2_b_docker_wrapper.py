"""Check DDS launch arguments with a fake Docker command; no containers or ROS."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


WRAPPER = Path(__file__).resolve().parents[2] / 'scripts/c2_b_docker.sh'


@pytest.fixture
def invoke(tmp_path):
    calls = tmp_path / 'docker-calls.jsonl'
    docker = tmp_path / 'docker'
    docker.write_text(f'#!{sys.executable}\n'
        'import json,os,sys\n'
        'with open(os.environ["C2_TEST_DOCKER_CALLS"],"a") as stream:\n'
        '    stream.write(json.dumps(sys.argv[1:])+"\\n")\n')
    docker.chmod(0o755)

    def run(uri=None):
        env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ['PATH'],
            C2_TEST_DOCKER_CALLS=str(calls))
        env.pop('CYCLONEDDS_URI', None)
        if uri is not None:
            env['CYCLONEDDS_URI'] = uri
        result = subprocess.run(['bash', str(WRAPPER), 'python', '-V'], env=env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
        commands = [json.loads(row) for row in calls.read_text().splitlines()]
        return result, commands

    return run


def test_file_config_is_mounted_readonly_and_forwarded(invoke, tmp_path):
    config = tmp_path / 'config with spaces.xml'
    config.write_text('<CycloneDDS/>')
    result, commands = invoke('file://' + str(config))
    assert result.returncode == 0, result.stderr
    args = commands[-1]
    assert args[0] == 'run'
    assert f'type=bind,src={config},dst=/tmp/c2-cyclonedds.xml,readonly' in args
    assert 'CYCLONEDDS_URI=file:///tmp/c2-cyclonedds.xml' in args
    assert args[args.index('--network') + 1] == 'host'
    assert args[-2:] == ['python', '-V']


def test_missing_file_never_starts_a_container(invoke, tmp_path):
    result, commands = invoke('file://' + str(tmp_path / 'missing.xml'))
    assert result.returncode == 2
    assert 'missing or unreadable' in result.stderr
    assert all(command[0] != 'run' for command in commands)


def test_no_host_override_keeps_image_default(invoke):
    result, commands = invoke()
    assert result.returncode == 0, result.stderr
    assert not any('CYCLONEDDS_URI' in arg or 'c2-cyclonedds.xml' in arg
        for arg in commands[-1])


def test_inline_config_is_forwarded(invoke):
    result, commands = invoke('<CycloneDDS><Domain id="any"/></CycloneDDS>')
    assert result.returncode == 0, result.stderr
    assert 'CYCLONEDDS_URI' in commands[-1]
    assert not any('c2-cyclonedds.xml' in arg for arg in commands[-1])
