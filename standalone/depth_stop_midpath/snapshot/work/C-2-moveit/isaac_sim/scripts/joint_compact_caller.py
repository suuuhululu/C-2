"""One read-only joint contact: current MI providers -> reviewed R caller.

No planner, SDK, FCL, trajectory sender, clock retag, sensor/geometry policy or
retry is added. Result remains input-only WAIT. Historical initial source and
new stopped owner are distinct; the selected initial result is an explicit D
retimer input ref, never guessed from a file name or substituted from old runs.
"""
from copy import deepcopy
from pathlib import Path
import threading
import time

from current_stop_providers import pin, pinned
from compact_stop_handoff import CPU, RUNTIME, exclusive, callback_diagnostics
from conservative_stop_packet import build_conservative_stop_packet, PROFILE
from initial_moveit_source import verify_initial_moveit_source
from live_current_cumotion_inputs import (
    prepare_live_current_inputs, current_clock, review_clock_progress,
    review_source_ages, LIVE,
)
from online_cumotion_validity import IDENTITY


class JointCompactCaller:
    def __init__(self, runtime, output, initial_source_provider, *, scope=RUNTIME,
                 CPU_historical_review=None):
        if scope not in (RUNTIME, CPU):
            raise ValueError('EXPLICIT_JOINT_INPUT_SCOPE_REQUIRED')
        if CPU_historical_review is not None and scope != CPU:
            raise ValueError('CPU_HISTORICAL_REVIEW_CANNOT_OVERRIDE_RUNTIME_SOURCE')
        self.runtime = runtime
        self.output = Path(output)
        self.initial_source_provider = initial_source_provider
        self.scope = scope
        self.CPU_historical_review = deepcopy(CPU_historical_review)
        self.attempted = None
        self.result_ref = None

    def poll(self):
        if threading.get_ident() != threading.main_thread().ident:
            raise ValueError('JOINT_CALLER_MAIN_THREAD_ONLY')
        if self.attempted is not None:
            return None  # At most one selected input contact; no retry/admission.
        runtime = self.runtime
        selected = None;capture_ref = None;capture = None;publication = None
        before = None;after = None;caller_invoked = False;initial_ref = None;config_ref = None
        output_attempted = False;output_ready = False
        try:
            source_clock_provider = getattr(runtime, 'current_stop_source_clock_provider', None)
            capture_provider = getattr(runtime, 'current_stop_capture_provider', None)
            compact_point_provider = getattr(runtime, 'current_compact_stop_input_provider', None)
            if not all(callable(p) for p in (source_clock_provider,capture_provider,compact_point_provider)):
                return dict(status='WAIT_MI_CURRENT_PROVIDER_BINDING',SDK_READY=False,execution_allowed=False)
            selected = compact_point_provider()
            if selected is None:
                return dict(status='WAIT_CURRENT_COMPLETE_COMPACT_POINT_PRODUCT',SDK_READY=False,execution_allowed=False,
                    original_provider_diagnostic=callback_diagnostics(compact_point_provider))
            capture_ref = capture_provider()
            if capture_ref is None:
                return dict(status='WAIT_CURRENT_COMPLETE_STOPPED_CAPTURE',SDK_READY=False,execution_allowed=False,
                    original_provider_diagnostic=callback_diagnostics(capture_provider))
            if capture_ref != selected['complete_capture_ref']:
                raise ValueError('CURRENT_CAPTURE_AND_COMPACT_SELECTION_CHANGED')
            capture = pinned(capture_ref)
            publication = pinned(capture['owner_publication'])
            owner = pinned(publication['owner_ref'])
            frame = pinned(capture['frame_input'])
            if selected['scope'] != self.scope:
                raise ValueError('JOINT_SELECTED_SCOPE_CHANGED')
            # Tuple originates in original current-frame/D identity, not a caller
            # counter. A failed attempt remains failed and is never sent again.
            self.attempted = dict(frame=capture['frame_input'],owner=publication['owner_ref'],
                                  identity={k:deepcopy(owner[k]) for k in IDENTITY},scope=self.scope)
            output_attempted = True
            self.output.mkdir(parents=True,exist_ok=False);output_ready = True
            before = current_clock(source_clock_provider)
            selected_initial = self.initial_source_provider()
            if selected_initial is None:
                raise ValueError('WAIT_EXPLICIT_SELECTED_INITIAL_MOVEIT_RESULT_SOURCE')
            if selected_initial['scope'] != 'ORIGINAL_MOVEIT_SELECTED_SOURCE_REFS_NOT_CURRENT_OWNER':
                raise ValueError('EXPLICIT_SELECTED_INITIAL_SOURCE_ROLE_REQUIRED')
            proof = pinned(owner['stop_verification'])
            accepted_ref = proof['evidence']['accepted']
            accepted = pinned(accepted_ref)
            initial_request_ref = selected_initial['request']
            initial_result_ref = selected_initial['result']
            if initial_request_ref != accepted['original_request']:
                raise ValueError('CURRENT_OWNER_INITIAL_REQUEST_SELECTION_CHANGED')
            for ref in (initial_request_ref,initial_result_ref,selected_initial['packet']):
                if pin(ref['path']) != ref:
                    raise ValueError('SELECTED_INITIAL_MOVEIT_PARENT_CHANGED')
            review = self.CPU_historical_review
            if review is None:
                review = verify_initial_moveit_source(initial_request_ref,initial_result_ref)
            if review['request_ref'] != initial_request_ref or review['result_ref'] != initial_result_ref:
                raise ValueError('HISTORICAL_INITIAL_REVIEW_NOT_SELECTED_ACTUAL_RESULT')
            initial_ref = exclusive(self.output/'initial_source_review.NOT_CURRENT.json',review)
            source_refs = dict(owner=publication['owner_ref'],state=proof['evidence']['current_state'],
                proof=owner['stop_verification'],accepted=accepted_ref,policy=publication['owner_limits_ref'],
                original_request=accepted['original_request'],accepted_wire=accepted['accepted_wire'])
            mapping = build_conservative_stop_packet(source_refs)
            mapping_ref = exclusive(self.output/'conservative_source_mapping.json',mapping)
            selected['packet'].verify()
            compact = selected['packet'].read(selected['compact_ref'])
            config = dict(scope=LIVE,owner_packet_profile=PROFILE,conservative_stop_packet_ref=mapping_ref,
                expected_identity={k:deepcopy(owner[k]) for k in IDENTITY},
                expected_depth_frame_seq=frame['frame_seq'],expected_known_map_digest=compact['projected_metadata']['map_digest'],
                refs=dict(anchor_request=initial_request_ref,initial_result=initial_result_ref,
                    owner=publication['owner_ref'],owner_limits=publication['owner_limits_ref'],
                    accepted=accepted_ref,accepted_wire=accepted['accepted_wire'],depth_frame=capture['frame_input'],
                    known_map=compact['map_ref']))
            config_ref = exclusive(self.output/'caller_config.INPUT_ONLY.json',config)
            caller_invoked = True
            result = prepare_live_current_inputs(config,initial_source_review=review,
                capture_provider=runtime.current_stop_capture_provider,
                source_clock_provider=runtime.current_stop_source_clock_provider,
                compact_point_provider=runtime.current_compact_stop_input_provider,
                compact_reader_scope=self.scope,output=self.output/'NO_REQUEST_OR_JOB')
            if any(result.get(k) is True for k in ('SDK_READY','READY','apply_allowed','execution_allowed','hardware_execution_allowed')):
                raise ValueError('INPUT_ONLY_CALLER_CANNOT_GRANT_ADMISSION')
            selected['packet'].verify()
            latest = compact_point_provider()
            if (capture_provider() != capture_ref or latest is None or latest['packet'] is not selected['packet']
                    or any(latest[k] != selected[k] for k in ('compact_ref','compact_completion_ref','complete_capture_ref','scope'))):
                raise ValueError('JOINT_CURRENT_SELECTION_CHANGED_AFTER_CALLER')
            after = current_clock(source_clock_provider)
            review_clock_progress(before,after)
            review_source_ages(owner,frame,after['source_s'])
        except Exception as exc:
            # Input selection failures are terminal for this one-shot contact.
            # Unverified original identities remain null, never reconstructed.
            if self.attempted is None:
                self.attempted = dict(
                    frame=capture.get('frame_input') if isinstance(capture,dict) else None,
                    owner=publication.get('owner_ref') if isinstance(publication,dict) else None,
                    identity=None,scope=self.scope)
            result = dict(status='HOLD_JOINT_CURRENT_INPUT_CONTACT',reason=str(exc),error_type=type(exc).__name__,
                request_draft=None,selected_job=None,SDK_READY=False,execution_allowed=False,automatic_resume=False)
        record = dict(schema='mi-joint-current-input-contact/1',scope=self.scope,
            attempted=self.attempted,caller_invoked=caller_invoked,initial_historical_review=initial_ref,
            config=config_ref,original_complete_capture_ref=capture_ref,
            compact_completion_ref=selected.get('compact_completion_ref') if isinstance(selected,dict) else None,clock_before=before,clock_after=after,
            result=result,typed_reader_reached=isinstance(result.get('compact_input_review'),dict),
            SDK_READY=False,execution_allowed=False,hardware_execution_allowed=False,
            automatic_resume=False,retry=False,current_clock_or_source_retagged=False)
        try:
            if not output_attempted:
                output_attempted = True
                self.output.mkdir(parents=True,exist_ok=False);output_ready = True
            if not output_ready:
                raise OSError('JOINT_OUTPUT_DIRECTORY_UNAVAILABLE')
            self.result_ref = exclusive(self.output/'joint_contact.json',record)
        except Exception as exc:
            # Logging cannot escape into the existing sensor loop or reopen
            # this attempt. Preserve the original input error in the return.
            return dict(status='HOLD_JOINT_CURRENT_INPUT_RECORD_UNAVAILABLE',
                reason=str(exc),error_type=type(exc).__name__,input_result=result,
                joint_contact_ref=None,SDK_READY=False,execution_allowed=False,
                automatic_resume=False,retry=False)
        return dict(status=result['status'],joint_contact_ref=self.result_ref,
                    SDK_READY=False,execution_allowed=False,automatic_resume=False)
