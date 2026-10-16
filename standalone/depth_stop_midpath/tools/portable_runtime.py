"""Resolve this extracted bundle and the receiving PC's Isaac installation."""
from pathlib import Path
import argparse,hashlib,json,os,platform,re,subprocess,sys,xml.etree.ElementTree as ET

PKG=Path(__file__).resolve().parents[1]

def python_site():
    lock=hashlib.sha256((PKG/'requirements.lock').read_bytes()).hexdigest()
    return PKG/'.runtime'/('python-'+lock[:16]),lock

def resolve(isaac_root=None,require_python_site=True):
    if platform.system()!='Linux' or platform.machine()!='x86_64':
        raise ValueError('Ubuntu 24.04 x86_64 is required for the packaged native binaries.')
    spec=json.loads((PKG/'runtime_dependencies.json').read_text())
    local=PKG/'runtime.local.json'
    chosen=isaac_root or os.environ.get('ISAAC_SIM_ROOT')
    if not chosen and local.exists():chosen=json.loads(local.read_text()).get('isaac_root')
    if not chosen:
        candidates=[Path.home()/'isaacsim',Path('/opt/isaacsim')]
        candidates+=sorted((Path.home()/'.local/share/ov/pkg').glob('isaac-sim*'),reverse=True)
        chosen=next((str(p) for p in candidates if (p/'python.sh').is_file()),None)
    if not chosen:
        raise ValueError('Isaac Sim not found. Run ./setup.sh --isaac-root /absolute/path/to/isaacsim')
    isaac=Path(chosen).expanduser().resolve()
    kit=isaac/'kit/python/bin/python3'
    for f in [isaac/'python.sh',kit,Path(spec['ros_setup'])]:
        if not f.is_file():raise ValueError('Required installation file missing: '+str(f))
    app=isaac/'apps/isaacsim.exp.full.kit'
    if not app.is_file():raise ValueError('Isaac Sim full binary installation required: '+str(app))
    version=re.search(r'^version\s*=\s*"([^"]+)"',app.read_text(),re.M)
    if not version or version.group(1)!=spec['required_isaac_version']:
        raise ValueError('This bundle was validated with Isaac Sim '+spec['required_isaac_version']+'. Found: '+(version.group(1) if version else 'unknown'))
    py=subprocess.run([str(kit),'--version'],capture_output=True,text=True)
    if py.returncode or not py.stdout.startswith('Python 3.12.'):
        raise ValueError('Packaged Python extensions require Isaac Python 3.12: '+py.stdout+py.stderr)
    package=Path('/opt/ros/jazzy/share/moveit_core/package.xml')
    if not package.exists() or ET.parse(package).findtext('version')!=spec['required_moveit_version']:
        raise ValueError('MoveIt '+spec['required_moveit_version']+' (ROS Jazzy) required. See README.md and system_packages_original_pc.tsv.')
    for package_name in ['moveit_planners_ompl','moveit_kinematics','controller_manager_msgs','control_msgs']:
        if not Path('/opt/ros/jazzy/share',package_name,'package.xml').is_file():
            raise ValueError('Missing ROS package: '+package_name+'; see README.md')
    site,lock=python_site()
    marker=site/'installed-lock.sha256'
    if require_python_site and (not marker.is_file() or marker.read_text().strip()!=lock):
        raise ValueError('Isolated Python dependencies missing. Run ./setup.sh first.')
    return dict(isaac_root=str(isaac),kit_python=str(kit),python_site=str(site),numpy_site=str(site),ros_setup=spec['ros_setup'])

def main():
    parser=argparse.ArgumentParser(description='Configure paths for this PC; no simulator or package installation is started.')
    parser.add_argument('--isaac-root',help='Isaac Sim 6.1.0 full binary installation directory')
    args=parser.parse_args()
    c=resolve(args.isaac_root,require_python_site=False)
    target=PKG/'runtime.local.json'
    target.write_text(json.dumps(dict(isaac_root=c['isaac_root']),indent=2)+'\n')
    print(json.dumps(dict(status='LOCAL_PATHS_CONFIGURED',**c,GPU_SIM_started=False),indent=2,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(2)
