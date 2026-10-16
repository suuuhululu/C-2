"""Check Bash-expanded transport arguments before boot metadata or a claim."""
from pathlib import Path
import hashlib
import json
import shlex
import sys


def pin(path):
    path = Path(path).resolve(strict=True)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def option(args, name):
    if args.count(name) != 1 or sum(arg == name or arg.startswith(name + '=') for arg in args) != 1:
        raise ValueError('EXACT_ONE_' + name)
    index = args.index(name)
    if index + 1 >= len(args):
        raise ValueError('MISSING_' + name)
    return args[index + 1]


def selection_record(args, proposal_path, launcher_path):
    proposal_path, launcher_path = Path(proposal_path), Path(launcher_path)
    proposal = json.loads(proposal_path.read_text())
    selected = pin(option(args, '--transport-calculator'))
    if selected != proposal['chosen_calculator']:
        raise ValueError('ACTUAL_EXPANDED_CALCULATOR_SELECTION_MISMATCH')
    expected_binary = proposal['chosen_MoveIt_binary']
    if pin(expected_binary['path']) != expected_binary:
        raise ValueError('REVIEWED_BINARY_SHA_MISMATCH')
    # The reviewed wrapper ends in one literal exec path followed by "$@".
    commands = [shlex.split(line) for line in Path(selected['path']).read_text().splitlines()
                if line.strip().startswith('exec ')]
    if commands != [['exec', expected_binary['path'], '$@']]:
        raise ValueError('WRAPPER_EXEC_BINARY_SELECTION_MISMATCH')
    if pin(launcher_path) != proposal['launcher']:
        raise ValueError('ACTUAL_LAUNCHER_PIN_MISMATCH')
    return dict(schema='bash-expanded-calculator-selection-proof/1',
                scope='SELECTION_ONLY_NOT_ALLOCATION_OR_START_GRANT',
                proposal=pin(proposal_path), launcher=pin(launcher_path),
                checker=pin(__file__), expanded_args=list(args),
                calculator=selected, reviewed_binary=expected_binary,
                allocation_path=str(Path(option(args, '--allocation')).resolve()),
                run_path=str(Path(option(args, '--out')).resolve()))


def validate_claim_selection(proof_path, proposal_path, launcher_path, allocation_ref, run):
    proof = json.loads(Path(proof_path).read_text())
    actual = selection_record(proof['expanded_args'], proposal_path, launcher_path)
    if proof != actual:
        raise ValueError('STALE_OR_CHANGED_SELECTION_PROOF')
    if actual['allocation_path'] != str(Path(allocation_ref['path']).resolve()):
        raise ValueError('SELECTION_PROOF_ALLOCATION_MISMATCH')
    if actual['run_path'] != str(Path(run).resolve()):
        raise ValueError('SELECTION_PROOF_RUN_MISMATCH')


def main():
    proposal, launcher, proof, separator, *args = sys.argv[1:]
    if separator != '--':
        raise ValueError('EXPANDED_ARGUMENT_ARRAY_REQUIRED')
    value = selection_record(args, proposal, launcher)
    target = Path(proof)
    if target.exists():
        if json.loads(target.read_text()) != value:
            raise ValueError('EXISTING_SELECTION_PROOF_DIFFERS')
    else:
        with target.open('x') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    print('ACTUAL_BASH_EXPANDED_CALCULATOR_PATH_SHA_AND_EXEC_BINARY_VERIFIED')


if __name__ == '__main__':
    main()
