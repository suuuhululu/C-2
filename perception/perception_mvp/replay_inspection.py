"""Replay synthetic B inspection inputs; never starts Camera/Robot/LLM or DB."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from queue import Queue

from .team_connection import connect_inspection
from .rgbd_io import write_cycle_json


def make_sample_observer(sample, *, scenario_name):
    """Explicit fixture injection for D connection tests, never a Camera fallback.

    D must send the fixture check_ids in order and load its fixture Plan.
    Unknown IDs fail rather than fabricate successful observations.
    """
    if sample.get('source') != 'SYNTHETIC_NOT_CAMERA':
        raise ValueError('sample observer requires explicitly synthetic input')
    scenarios = [item for item in sample['scenarios'] if item['name'] == scenario_name]
    if len(scenarios) != 1:
        raise ValueError('one matching sample scenario required')
    inputs = {action['request']['check_id']: deepcopy(action['observation'])
              for action in scenarios[0]['actions'] if 'observation' in action}

    def observe(context, active):
        if not active():
            raise RuntimeError('sample inspection canceled')
        identity = context['check_id']
        if identity not in inputs:
            raise ValueError(f'no synthetic observation for check_id={identity}')
        value = deepcopy(inputs[identity])
        value.update(check_id=identity, observation_seq=context['observation_seq'])
        return value, {'source': 'SYNTHETIC_NOT_CAMERA'}

    return observe


def replay(sample):
    if sample['source'] != 'SYNTHETIC_NOT_CAMERA':
        raise ValueError('this replay requires explicitly synthetic input')
    outputs = []
    for scenario in sample['scenarios']:
        inbox, inputs = Queue(), {}
        def observe(context, active):
            if not active():
                raise RuntimeError('replay check canceled')
            value = deepcopy(inputs[context['check_id']])
            value.update(check_id=context['check_id'], observation_seq=context['observation_seq'])
            return value, {}
        connection = connect_inspection(inbox.put, observe=observe,
                                        geometry_reference=sample['geometry_reference'])
        try:
            for action in scenario['actions']:
                if 'load_plan' in action:
                    plan = action['load_plan']
                    connection.load_plan(plan['design'], plan['plan'], plan['base_current'],
                                         geometry_reference=sample['geometry_reference'])
                    continue
                identity = action['request']['check_id']
                if 'observation' in action:
                    inputs[identity] = action['observation']
                connection.request(action['request'])
                result = inbox.get(timeout=5)
                actual = dict(status=result['status'], comparison=result['comparison'],
                              current_revision=None if result['current'] is None else
                              result['current']['current_revision'])
                if result['check_id'] != identity or actual != action['expected']:
                    raise ValueError(f'replay mismatch: {identity}: {actual}')
                outputs.append(dict(scenario=scenario['name'], result=result))
        finally:
            connection.close()
    return dict(source='SYNTHETIC_NOT_CAMERA', checks=len(outputs), status='PASS', results=outputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = replay(json.loads(args.sample.read_text()))
    write_cycle_json(args.output, result)
    print(f"SYNTHETIC replay: {result['checks']} checks PASS; output={args.output}")


if __name__ == '__main__':
    main()
