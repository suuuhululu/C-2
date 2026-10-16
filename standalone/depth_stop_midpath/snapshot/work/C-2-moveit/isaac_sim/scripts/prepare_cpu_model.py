"""Prepare and verify a local model bundle without ROS, controller or SIM setup."""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def prepare_model_bundle(out, isaac_root=ROOT):
    out, source = Path(out), Path(isaac_root)
    if out.exists():
        raise ValueError('Model bundle destination must be new; existing data is preserved')
    model = source/'ros_ws/src/m0609_rg2_sim_model'
    urdf = model/'urdf/m0609_rg2_sim.urdf'
    semantic = model/'config/m0609_rg2_sim.srdf'
    limits = source/'config/joint_limits.sim.yaml'
    robot = ET.parse(urdf)
    tcp = robot.find("joint[@name='link_6_to_GripperDA_v4_tcp']")
    if (tcp is None or tcp.get('type') != 'fixed' or tcp.find('parent').get('link') != 'link_6' or
            tcp.find('child').get('link') != 'GripperDA_v4_tcp' or
            list(map(float, tcp.find('origin').get('xyz').split())) != [0., 0., .228] or
            list(map(float, tcp.find('origin').get('rpy').split())) != [0., 0., 0.]):
        raise ValueError('Source model must preserve the 228mm flange TCP setting')
    meshes = {}
    for mesh in robot.findall('.//mesh'):
        prefix = 'package://m0609_rg2_sim_model/'
        name = mesh.get('filename')
        if not name.startswith(prefix):
            raise ValueError('Unexpected mesh URI in source model')
        path = (model/name.removeprefix(prefix)).resolve(strict=True)
        if not path.is_relative_to(model.resolve()) or not path.is_file():
            raise ValueError('Mesh must resolve inside the source model')
        meshes[str(path)] = file_hash(path)
        mesh.set('filename', path.as_uri())
    source_hashes = {str(p.resolve()): file_hash(p) for p in (urdf, semantic, limits)}
    # Read every source before writing; this helper never regenerates limits or
    # controller configuration through the old SIM prepare_config entry point.
    semantic_xml, limits_text = semantic.read_text(), limits.read_text()
    ET.indent(robot)
    out.mkdir(parents=True)
    robot.write(out/'robot.urdf', encoding='utf-8', xml_declaration=True)
    (out/'semantic.srdf').write_text(semantic_xml)
    (out/'joint_limits.yaml').write_text(limits_text)
    manifest = dict(scope='LOCAL_CALCULATION_MODEL_NOT_PHYSICALLY_VERIFIED', execution_allowed=False,
        tcp_frame='GripperDA_v4_tcp', flange_to_tcp_m=.228, source_files=source_hashes,
        meshes=meshes, files={name: file_hash(out/name) for name in ('robot.urdf', 'semantic.srdf', 'joint_limits.yaml')})
    (out/'MODEL_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return read_model_bundle(out)


def read_model_bundle(folder):
    folder = Path(folder).resolve(strict=True)
    raw = (folder/'MODEL_MANIFEST.json').read_bytes()
    manifest = json.loads(raw)
    if (manifest['scope'] != 'LOCAL_CALCULATION_MODEL_NOT_PHYSICALLY_VERIFIED' or
            manifest['execution_allowed'] is not False or manifest['flange_to_tcp_m'] != .228 or
            set(manifest['files']) != {'robot.urdf', 'semantic.srdf', 'joint_limits.yaml'}):
        raise ValueError('Calculation-only model manifest required')
    for name, expected in manifest['files'].items():
        if file_hash(folder/name) != expected:
            raise ValueError('Model bundle file changed: '+name)
    for path, expected in manifest['meshes'].items():
        if file_hash(path) != expected:
            raise ValueError('Collision/visual mesh changed: '+path)
    robot_xml = (folder/'robot.urdf').read_text()
    if 'kinematic_alignment' in manifest:
        verify_alignment(folder,manifest,robot_xml)
    references = set()
    for mesh in ET.fromstring(robot_xml).findall('.//mesh'):
        uri = urlparse(mesh.get('filename'))
        if uri.scheme != 'file' or uri.netloc:
            raise ValueError('CPU-local file mesh URI required')
        references.add(str(Path(unquote(uri.path)).resolve(strict=True)))
    if references != set(manifest['meshes']):
        raise ValueError('URDF mesh references differ from manifest')
    return dict(bundle_path=str(folder), manifest_sha256=sha256(raw).hexdigest(),
        files=manifest['files'], scope=manifest['scope'], robot_description=robot_xml,
        robot_description_semantic=(folder/'semantic.srdf').read_text(),
        joint_limits_yaml=(folder/'joint_limits.yaml').read_text())


def verify_alignment(folder, manifest, robot_xml):
    """An aligned bundle preserves geometry and binds independent FK evidence."""
    link=manifest['kinematic_alignment']
    report_file=folder/'kinematic_alignment.json'
    if link['file']!='kinematic_alignment.json' or file_hash(report_file)!=link['sha256']:
        raise ValueError('Kinematic alignment report changed')
    report=json.loads(report_file.read_text())
    if (report['status']!='INDEPENDENT_CONTROLLER_FK_CHECKED_NOT_PHYSICAL_PATH' or
            report['scope']!='CONTROLLER_KINEMATIC_EQUIVALENCE_NOT_PHYSICAL_COLLISION_CALIBRATION' or
            report['physical_trajectory_verified'] is not False or report['physical_link_geometry_verified'] is not False):
        raise ValueError('Independent kinematic evidence required')
    if file_hash(link['dataset_file'])!=link['dataset_sha256'] or report['dataset_sha256']!=link['dataset_sha256']:
        raise ValueError('Controller FK dataset changed')
    original=Path(link['source_bundle'])
    source=json.loads((original/'MODEL_MANIFEST.json').read_text())
    if ('kinematic_alignment' in source or file_hash(original/'MODEL_MANIFEST.json')!=link['source_manifest_sha256'] or
            report['source_manifest_sha256']!=link['source_manifest_sha256']):
        raise ValueError('Original model evidence changed')
    read_model_bundle(original)
    for key in ('heldout','existing_teaching'):
        if key not in report:continue
        values=report[key]['after']
        for name,limit in [('max_position_m',.0001),('max_orientation_rad',.0005)]:
            value=values[name]
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=limit:
                raise ValueError('Independent kinematic check failed')
    if report['heldout']['after']['sample_count']<64:raise ValueError('Independent FK sample set missing')
    trees=[ET.fromstring((original/'robot.urdf').read_text()),ET.fromstring(robot_xml)]
    for tree in trees:
        for i in range(1,7):tree.find(f"joint[@name='joint_{i}']/origin").attrib.clear()
        for node in tree.iter():
            node.text=(node.text or '').strip() or None
            node.tail=(node.tail or '').strip() or None
    if ET.tostring(trees[0])!=ET.tostring(trees[1]):
        raise ValueError('Aligned model may change only six arm joint origins')
    if any(manifest['files'][k]!=source['files'][k] for k in ('semantic.srdf','joint_limits.yaml')):
        raise ValueError('Preserve original semantic model and limits')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    bundle = prepare_model_bundle(args.output_dir)
    print('MODEL_FILES_PREPARED_ONLY:', bundle['bundle_path'], bundle['manifest_sha256'])
