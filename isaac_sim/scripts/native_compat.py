"""Process-local workaround for Isaac 6.1 rc.26 URDF control-tree pruning.

The bundled pruning treats both arm and fixed-mounted gripper as roots. When
walking the arm tree it then drops the mount edge because the gripper root is
already visited, yielding two disconnected URDF roots. No installed file edit.
"""
from collections import defaultdict

def prune_connected_control_tree(root, control_joint_names):
    joints=list(root.findall('joint'))
    links={l.get('name') for l in root.findall('link')}
    children={j.find('child').get('link') for j in joints}
    edges=defaultdict(list)
    for j in joints:edges[j.find('parent').get('link')].append(j)
    matches=[]
    for candidate in sorted(links-children):
        seen={candidate}; names=set();queue=[candidate]
        for name in queue:
            for joint in edges[name]:
                names.add(joint.get('name'))
                child=joint.find('child').get('link')
                if child not in seen:seen.add(child);queue.append(child)
        if set(control_joint_names)<=names:matches.append((seen,names))
    if len(matches)!=1:
        raise ValueError('Live USD export lacks one connected tree containing every controlled joint')
    seen,names=matches[0]
    for joint in joints:
        if joint.get('name') not in names:root.remove(joint)
    for link in list(root.findall('link')):
        if link.get('name') not in seen:root.remove(link)

def apply():
    from isaacsim.ros2.control import urdf_synth
    urdf_synth._prune_to_control_tree=prune_connected_control_tree


def physics_mimic_control_xml(xml):
    """Physical USD gear constraints own followers; avoid duplicate software drives."""
    import xml.etree.ElementTree as ET
    root=ET.fromstring(xml)
    for joint in root.findall('joint'):
        if joint.get('name','').startswith('rg2_'):
            for mimic in list(joint.findall('mimic')):joint.remove(mimic)
    for block in root.findall('ros2_control'):
        for joint in block.findall('joint'):
            if joint.get('name','').startswith('rg2_'):
                for param in list(joint.findall('param')):
                    if param.get('name') in ('mimic','multiplier','offset'):joint.remove(param)
    return ET.tostring(root,encoding='unicode')
