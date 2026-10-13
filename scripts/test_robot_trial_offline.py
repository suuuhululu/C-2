"""Run D unit tests with isolated locks and no network/device connection."""
import builtins
import io
import os
from pathlib import Path
import re
import socket
import sys
import tempfile

os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
root=Path(__file__).resolve().parents[1]/'robot_control_integration'
os.chdir(root)
sys.path.insert(0,str(root))
original_builtin,original_io=builtins.open,io.open

def blocked(*args,**kwargs):
    raise AssertionError('External connections are disabled in offline Robot tests')

socket.socket.connect=blocked
socket.socket.connect_ex=blocked
socket.create_connection=blocked
with tempfile.TemporaryDirectory(prefix='c2-robot-test-locks-') as folder:
    def redirect(file):
        if isinstance(file,(str,os.PathLike)) and re.fullmatch(r'/tmp/c2-assembly-[^/]+\.lock',os.fspath(file)):
            return Path(folder)/Path(file).name
        return file
    def builtin_open(file,*args,**kwargs):return original_builtin(redirect(file),*args,**kwargs)
    def io_open(file,*args,**kwargs):return original_io(redirect(file),*args,**kwargs)
    builtins.open,io.open=builtin_open,io_open
    import pytest
    raise SystemExit(pytest.main(['tests/unit','-q','--tb=short',*sys.argv[1:]]))
