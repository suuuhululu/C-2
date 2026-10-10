"""D-owned profile references and A-owned content fingerprints are independent."""
from copy import deepcopy
from hashlib import sha256
import json


IMPLEMENTED_MOTION_MODES = ("ROBOT_GRIP", "HUMAN_ASSEMBLY")


def content_digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode()).hexdigest()


def profile_content_digest(profile):
    content = deepcopy(profile)
    content.pop('profile_id', None)
    content.pop('profile_version', None)
    return content_digest(content)


def assessment_input_digest(profile, assembly_context):
    """A emits this fingerprint; D only relays the associated assessment record."""
    return content_digest({'profile_content_digest': profile_content_digest(profile),
                           'assembly_context': assembly_context})


def validate_profile_reference(context, profile):
    for key, ref in (('profile_id', 'frame_profile_id'),
                     ('profile_version', 'frame_profile_version')):
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise ValueError('Explicit D profile ID and version required')
        if context[ref] != profile[key]:
            raise ValueError('Context and profile references differ: '+key)


def validate_supported_modes(assembly_context):
    modes = assembly_context['supported_modes']
    if not modes or any(mode not in IMPLEMENTED_MOTION_MODES for mode in modes):
        raise ValueError('Only implemented motion modes may be enabled: ROBOT_GRIP, HUMAN_ASSEMBLY')
