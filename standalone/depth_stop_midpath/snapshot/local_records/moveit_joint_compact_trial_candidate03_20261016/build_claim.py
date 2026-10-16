"""Bind a frozen claim template; no file mutation, process start or lease grant."""
from copy import deepcopy
from pathlib import Path
import json

TEMPLATE=Path(__file__).with_name('CLAIM_TEMPLATE.json')

def build_claim(*,allocation_ref,final_pins_ref,run,at_utc,resource_observation_ref):
    value=json.loads(TEMPLATE.read_text())
    assert value['maximum_starts']==value['starts_used']==1
    assert value['remaining_after_attempt']==value['starts_remaining']==0
    for name in ('allocation','final_pins','run','at_utc','resource_observation'):
        assert value[name] is None
    value.update(allocation=deepcopy(allocation_ref),final_pins=deepcopy(final_pins_ref),
        run=str(Path(run).resolve()),at_utc=at_utc,
        resource_observation=deepcopy(resource_observation_ref))
    return value
