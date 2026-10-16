"""Separate bounded compact inputs, never legacy point API or SDK admission.

Worker: original classification -> sealed points -> complete original capture.
Main: independently current D/native clock/identity/order/.12 -> new receipt.
No Kit imports, extra worker, tick, command, resubmission or source retagging.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from queue import Queue, Empty, Full
import json
import math
import threading
import time
import numpy as np

from compact_points_guarded import complete_owned_point_arrays, OwnedCompactPoints
from current_stop_providers import pin, pinned, verify_raw, verify_state_capture, CurrentStopProviders

RUNTIME = 'ISOLATED_SIM_COMPACT_STOP_INPUT'
CPU = 'CPU_SYNTHETIC_NOT_RUNTIME'
IDENTITY = ('session_id', 'clock_basis', 'clock_epoch')
SOURCE = IDENTITY + ('frame_seq', 'source_stamp_s')
DIGEST_KIND = 'OWNED_NUMPY_ARRAY_CONTENT_SHA256_V1'
STORAGE = 'OWNED_COMPACT_DEPTH_POINTS'


def exclusive(path, value):
    path = Path(path)
    with path.open('x') as f:
        f.write(json.dumps(value, sort_keys=True, allow_nan=False) + '\n')
    return pin(path)


def complete_capture(folder, owner_publication, frame_ref, persist):
    """Only after original required raw/state/proof writes have completed."""
    persist()
    folder = Path(folder)
    raw_ref = pin(folder / 'retained_raw_artifacts.json')
    raw = pinned(raw_ref)
    publication = pinned(owner_publication)
    proof = pinned(publication['stop_verification_ref'])
    owner = pinned(publication['owner_ref'])
    if owner['stop_verification'] != publication['stop_verification_ref']:
        raise ValueError('ORIGINAL_COMPLETE_OWNER_PROOF_CHANGED')
    for evidence_ref in proof['evidence'].values():
        if pin(evidence_ref['path']) != evidence_ref:
            raise ValueError('INCOMPLETE_ORIGINAL_OWNER_PROOF_PARENT')
    verify_state_capture(owner, pinned(proof['evidence']['current_state']), pinned(frame_ref), frame_ref)
    verify_raw(raw, frame_ref)
    if (raw['payload_retained'] is not True or raw['frame_input_ref'] != frame_ref
            or proof['evidence']['frame'] != frame_ref):
        raise ValueError('INCOMPLETE_OR_MIXED_EARLY_CAPTURE')
    value = dict(scope='SAME_ORIGINAL_CAPTURE_FOR_NONEXECUTABLE_STOP_OWNER',
                 owner_publication=owner_publication, selected_raw_bundle=raw_ref,
                 frame_input=frame_ref, recaptured=False)
    path = folder / 'stopped_owner_capture.json'
    if path.exists():
        ref = pin(path)
        if pinned(ref) != value:
            raise ValueError('EXISTING_COMPLETE_CAPTURE_CHANGED')
        return ref
    return exclusive(path, value)


def callback_diagnostics(callback):
    """Only reviewed pure diagnostic accessors; never call an input provider."""
    owner = getattr(callback, '__self__', None)
    if not isinstance(owner,(CurrentStopProviders,CompactStopHandoff)):return None
    try:return owner.diagnostic_status()
    except Exception as exc:
        return dict(scope='DIAGNOSTIC_UNAVAILABLE_NOT_ADMISSION',error_type=type(exc).__name__)


class CompactStopEntry:
    """Immutable small metadata + the reviewed owned/sealed D packet lease."""
    __slots__ = ('packet', '_metadata', '_seal')

    def __init__(self, product, metadata):
        if product['complete'] is not True or product['completion_receipt'] is not None:
            raise ValueError('SEALED_POINTS_WITHOUT_EARLY_RECEIPT_REQUIRED')
        self.packet = product['packet']
        if type(self.packet) is not OwnedCompactPoints:
            raise ValueError('PINNED_OWNED_COMPACT_PRODUCER_CLASS_REQUIRED')
        self._metadata = json.dumps(metadata, sort_keys=True, allow_nan=False).encode()
        self._seal = sha256(self._metadata).hexdigest()
        self.verify()

    def read(self):
        self.verify()
        return json.loads(self._metadata)

    def verify(self):
        if sha256(self._metadata).hexdigest() != self._seal:
            raise ValueError('COMPACT_CARRIER_METADATA_CHANGED')
        meta = json.loads(self._metadata)
        self.packet.verify()
        if self.packet.ref() != meta['compact_ref']:
            raise ValueError('COMPACT_CARRIER_DESCRIPTOR_CHANGED')
        pinned(meta['complete_capture_ref'])


class CompactStopHandoff:
    def __init__(self, source_clock_provider, capture_provider, *, scope, receipt_folder):
        if scope not in (RUNTIME, CPU):
            raise ValueError('EXPLICIT_COMPACT_STOP_INPUT_SCOPE_REQUIRED')
        self.clock = source_clock_provider
        self.capture = capture_provider
        self.scope = scope
        self.receipt_folder = Path(receipt_folder)
        self.queue = Queue(maxsize=1)
        self.latest = None
        self.last_source = None
        self.last_frame = None
        self.last_status = None
        self._diagnostics={key:dict(failure_count=0,first_failure=None) for key in ('poll','current')}
        self._diagnostic_phase='UNOBSERVED'


    def prepare_worker(self, *, folder, payload, frame, review, shadow,
                       owner_publication, map_ref, model_ref, persist):
        """Existing source worker only. No native clock/owner calls here."""
        if threading.get_ident() == threading.main_thread().ident:
            raise ValueError('EXISTING_SOURCE_WORKER_LEASE_REQUIRED')
        if review['guard'] or not owner_publication:
            raise ValueError('SELECTED_POSTSTOP_CLASSIFICATION_REQUIRED')
        frame_ref = pin(Path(folder) / 'frame_input.json')
        if pinned(frame_ref) != frame:
            raise ValueError('ORIGINAL_FRAME_CHANGED_BEFORE_COMPACT')
        classification = dict(status=review['status'], guard=review['guard'],
            counts=deepcopy(shadow['counts']), frame_input=frame_ref,
            source_identity={k:deepcopy(frame[k]) for k in SOURCE},
            completed_wall_monotonic_s=shadow['compute_finished_wall_monotonic_s'])
        qualification = review['detection']['qualification_ref']
        product = complete_owned_point_arrays(review['detection'], frame,
            source_frame_ref=frame_ref, map_ref=map_ref,
            error_model_ref=shadow['error_model_ref'], model_ref=model_ref,
            origin_refs=[qualification], saved_cpu=self.scope == CPU)
        point_completed = time.monotonic()
        capture_ref = complete_capture(folder, owner_publication, frame_ref, persist)
        metadata = dict(kind='SEALED_COMPACT_STOP_INPUT_V1', scope=self.scope,
            frame_input=frame_ref, complete_capture_ref=capture_ref,
            compact_ref=product['compact_ref'], classification=classification,
            point_completed_wall_monotonic_s=point_completed,
            carrier_published_wall_monotonic_s=time.monotonic())
        entry = CompactStopEntry(product, metadata)
        try:self.queue.put_nowait(entry)
        except Full:raise ValueError('COMPACT_CARRIER_CAPACITY1_HOLD_NO_OVERWRITE')
        return dict(status='EARLY_COMPLETE_CAPTURE_AND_COMPACT_QUEUED',
                    complete_capture_ref=capture_ref, point_count=entry.packet.read(product['compact_ref'])['point_count'])

    @staticmethod
    def _failure_context(context,frame,observation):
        # Already-read inputs only: no provider, wall-clock, D, camera or Kit call.
        data={}
        try:
            data=deepcopy(context or {})
            if frame is not None:
                data['frame']={k:deepcopy(frame.get(k)) for k in SOURCE+('robot_state_stamp_s',)}
                data['frame_state_step']=frame.get('source_association',{}).get('state_physics_step_index')
            if observation is not None:data['observation']=deepcopy(observation)
            if frame is not None and observation is not None:
                data['identity_comparisons']={k:dict(frame_type=type(frame[k]).__name__,
                    observation_type=type(observation[k]).__name__,
                    type_matches=type(frame[k]) is type(observation[k]),
                    value_matches=frame[k]==observation[k]) for k in IDENTITY}
                data['source_age_s']=observation['source_s']-frame['source_stamp_s']
                data['state_age_s']=observation['source_s']-frame['robot_state_stamp_s']
                data['freshness_predicates']=dict(
                    identity_type_and_value=all(x['type_matches'] and x['value_matches'] for x in data['identity_comparisons'].values()),
                    native_step_not_reversed=observation['native_stamp']['native_physics_step_index']>=data['frame_state_step'],
                    source_age_within_original_012=0<=data['source_age_s']<=.12,
                    state_age_within_original_012=0<=data['state_age_s']<=.12)
                data['first_failed_freshness_predicate']=(next((k for k,v in data['freshness_predicates'].items() if not v),None)
                    if data.get('stage','').endswith('_FRESHNESS') else None)
            json.dumps(data,allow_nan=False)
            return data
        except Exception as diagnostic_error:
            # A diagnostic failure must never alter the original rejection.
            return dict(lifecycle_phase=data.get('lifecycle_phase'),stage=data.get('stage'),
                diagnostic_error_type=type(diagnostic_error).__name__,diagnostic_complete=False)

    def _diagnostic_failure(self,boundary,exc,context=None,frame=None,observation=None):
        item=self._diagnostics[boundary];item['failure_count']+=1
        if item['first_failure'] is None:
            item['first_failure']=dict(reason=str(exc),exception_type=type(exc).__name__,
                context=self._failure_context(context,frame,observation))

    def diagnostic_status(self):
        return dict(schema='compact-stop-input-diagnostic/1',
            scope='FIRST_REJECTION_AND_COUNTERS_NOT_CURRENT_ADMISSION',
            boundaries=deepcopy(self._diagnostics),
            original_provider=callback_diagnostics(self.clock),SDK_READY=False,execution_allowed=False)

    def _clock(self):
        start = time.monotonic()
        value = self.clock()
        returned = time.monotonic()
        if (not isinstance(value, dict) or value.get('schema') != 'native-current-source-clock/1.0'
                or value.get('clock_basis') != 'SIM_TIME'):
            raise ValueError('WAIT_CURRENT_NATIVE_CLOCK')
        native = value['native_stamp']
        if (value['source_s'] != native['world_time_s']
                or not start <= native['wall_monotonic_s'] <= value['observed_wall_monotonic_s'] <= returned
                or any(type(v) not in (int,float) or not math.isfinite(v)
                       for v in (value['source_s'],native['world_time_s'],native['native_simulation_time_s']))):
            raise ValueError('CURRENT_CAUSAL_NATIVE_CLOCK_REQUIRED')
        return value

    @staticmethod
    def _fresh(frame, observation):
        if (any(type(observation[k]) is not type(frame[k]) or observation[k] != frame[k] for k in IDENTITY)
                or observation['native_stamp']['native_physics_step_index'] < frame['source_association']['state_physics_step_index']
                or not 0 <= observation['source_s'] - frame['source_stamp_s'] <= .12
                or not 0 <= observation['source_s'] - frame['robot_state_stamp_s'] <= .12):
            raise ValueError('WAIT_ORIGINAL_012_SOURCE_CLASSIFICATION_AND_POINT_FRESHNESS')

    def _validate_product(self, entry, meta, frame):
        compact = entry.packet.read(meta['compact_ref'])
        expected_scope = ('SAVED_CPU_REPLAY_NOT_RUNTIME' if self.scope == CPU
                          else 'SOURCE_WORKER_ARRAYS_COMPLETE_NOT_CURRENT_CLOCK_OBSERVED')
        if (meta['scope'] != self.scope or compact['scope'] != expected_scope
                or compact['schema'] != 'depth-compact-point-product/1.0'
                or compact['digest_kind'] != DIGEST_KIND
                or meta['compact_ref']['storage'] != STORAGE
                or compact['source_frame_ref'] != meta['frame_input']
                or compact['source_frame_digest'] != sha256(json.dumps(frame,sort_keys=True,allow_nan=False).encode()).hexdigest()
                or meta['classification']['guard'] is not False
                or meta['classification']['frame_input'] != meta['frame_input']
                or meta['classification']['source_identity'] != {k:frame[k] for k in SOURCE}):
            raise ValueError('SAME_ORIGINAL_COMPACT_CLASSIFICATION_FRAME_REQUIRED')
        # Full original grip/attachment/T_base_tool bind through source_frame_digest
        # and the independent current-provider v2 frame/state proof. The original
        # projected metadata intentionally contains only its existing fields.
        projected = compact['projected_metadata']
        if any(type(projected[k]) is not type(frame[k]) or projected[k] != frame[k]
               for k in SOURCE + ('robot_state_stamp_s','transform_stamp_s','q_rad')):
            raise ValueError('COMPACT_ORIGINAL_QTF_SOURCE_CHANGED')
        n = compact['point_count']
        expected = dict(points_base_m=(np.dtype('float64'),(n,3)),pixel_uv=(np.dtype('int64'),(n,2)),
            point_is_foreground=(np.dtype('bool'),(n,)),point_is_uncertain=(np.dtype('bool'),(n,)),
            point_uncertainty_m=(np.dtype('float64'),(n,)))
        for key,(dtype,shape) in expected.items():
            value = compact[key]
            if value.dtype != dtype or value.shape != shape or value.flags.writeable:
                raise ValueError('OWNED_COMPACT_POINT_ARRAY_CONTRACT_CHANGED')
        if (not np.all(compact['point_is_foreground'] ^ compact['point_is_uncertain'])
                or not np.isnan(compact['point_uncertainty_m']).all()
                or compact['foreground_points'] != meta['classification']['counts']['foreground']
                or compact['foreground_points'] != int(compact['point_is_foreground'].sum())
                or compact['uncertain_points'] != int(compact['point_is_uncertain'].sum())
                or compact['uncertain_points'] != meta['classification']['counts']['uncertain']
                or compact['foreground_points'] + compact['uncertain_points'] != n):
            raise ValueError('ORIGINAL_FOREGROUND_UNCERTAIN_POINTS_OR_NULL_ERROR_CHANGED')
        return compact

    def poll(self,*,lifecycle_phase='UNOBSERVED'):
        self._diagnostic_phase=lifecycle_phase
        if threading.get_ident() != threading.main_thread().ident:
            raise ValueError('MAIN_THREAD_COMPACT_COMPLETION_REQUIRED')
        try:entry = self.queue.get_nowait()
        except Empty:return None
        received_wall = time.monotonic()
        self.latest = None
        context=dict(lifecycle_phase=lifecycle_phase,stage='CLASSIFICATION_WALL_ORDER')
        frame=None;observation=None
        try:
            meta = entry.read()
            if not (meta['classification']['completed_wall_monotonic_s'] <= meta['point_completed_wall_monotonic_s']
                    <= meta['carrier_published_wall_monotonic_s'] <= received_wall):
                raise ValueError('CLASSIFICATION_POINT_DELIVERY_WALL_ORDER_CHANGED')
            frame = pinned(meta['frame_input'])
            try:
                context.update(frame_input_ref=deepcopy(meta['frame_input']),
                    classification_completed_wall_s=meta['classification']['completed_wall_monotonic_s'],
                    point_completed_wall_s=meta['point_completed_wall_monotonic_s'],
                    carrier_published_wall_s=meta['carrier_published_wall_monotonic_s'],main_received_wall_s=received_wall)
            except Exception as diagnostic_error:
                context['enrichment_error_type']=type(diagnostic_error).__name__
            context['stage']='CLASSIFICATION_CLOCK'
            classification_now = self._clock()
            observation=classification_now;context['stage']='CLASSIFICATION_FRESHNESS'
            self._fresh(frame, classification_now)
            context['stage']='ORIGINAL_SOURCE_ORDER'
            if (self.last_source is not None and (frame['source_stamp_s'] <= self.last_source
                    or frame['frame_seq'] <= self.last_frame)):
                raise ValueError('OLD_OR_REPEATED_COMPACT_FRAME_HOLD')
            context['stage']='CURRENT_CAPTURE'
            capture_ref = self.capture()
            if capture_ref is None or capture_ref != meta['complete_capture_ref']:
                raise ValueError('WAIT_CURRENT_COMPLETE_CAPTURE_OR_D_GENERATION')
            capture = pinned(capture_ref)
            if capture['frame_input'] != meta['frame_input'] or capture['recaptured'] is not False:
                raise ValueError('CAPTURE_FRAME_MISMATCH')
            publication = pinned(capture['owner_publication'])
            owner = pinned(publication['owner_ref'])
            compact = self._validate_product(entry, meta, frame)
            if compact['model_ref']['sha256'] != owner['model_manifest_sha256']:
                raise ValueError('COMPACT_CURRENT_MODEL_CHANGED')
            entry.verify()
            if self.capture() != capture_ref:
                raise ValueError('CURRENT_D_OR_CAPTURE_CHANGED_DURING_POINT_CONSUMPTION')
            context['stage']='POINT_CLOCK';observation=None
            point_now = self._clock()
            observation=point_now;context['stage']='POINT_FRESHNESS'
            self._fresh(frame, point_now)
            context['stage']='MAIN_COMPLETION_ORDER_AND_RECEIPT'
            if (point_now['source_s'] < classification_now['source_s']
                    or point_now['native_stamp']['native_physics_step_index'] < classification_now['native_stamp']['native_physics_step_index']):
                raise ValueError('MAIN_COMPLETION_NATIVE_CLOCK_REVERSED')
            receipt = dict(schema='depth-compact-point-completion/1.0', scope=self.scope,
                frame_input=meta['frame_input'],source_identity={k:deepcopy(frame[k]) for k in SOURCE},
                compact_ref=meta['compact_ref'],compact_digest_kind=DIGEST_KIND,
                compact_digest=meta['compact_ref']['sha256'],point_count=compact['point_count'],
                completion_observation=point_now,completion_source_age_s=point_now['source_s']-frame['source_stamp_s'],
                completion_fresh=True,identity_verified=True,source_order_verified=True,
                complete_capture_ref=capture_ref,
                owner_ref=publication['owner_ref'],
                owner_identity={k:deepcopy(owner[k]) for k in IDENTITY +
                    ('execution_id','execution_version','goal_id','goal_version','cancel_generation','replan_sequence',
                     'state_digest','state_sequence','snapshot_digest','snapshot_version')},
                classification_completion_observation=classification_now,
                classification_completion_source_age_s=classification_now['source_s']-frame['source_stamp_s'],
                classification_completion_fresh=True,
                classification_completed_wall_monotonic_s=meta['classification']['completed_wall_monotonic_s'],
                point_completed_wall_monotonic_s=meta['point_completed_wall_monotonic_s'],
                carrier_published_wall_monotonic_s=meta['carrier_published_wall_monotonic_s'],
                main_received_wall_monotonic_s=received_wall,
                SDK_READY=False,execution_allowed=False,hardware_execution_allowed=False,
                risk_qualified=False,world_clear_allowed=False)
            # Both products are new and immutable; do not touch legacy files/digests.
            folder = self.receipt_folder / ('frame_' + str(frame['frame_seq']))
            folder.mkdir(parents=True,exist_ok=False)
            class_receipt = dict(schema='depth-compact-classification-delivery/1.0',scope=self.scope,
                **meta['classification'],completion_observation=classification_now,
                completion_source_age_s=classification_now['source_s']-frame['source_stamp_s'],
                completion_fresh=True,identity_verified=True,source_order_verified=True,
                exact_worker_completion_source_s=None,SDK_READY=False,execution_allowed=False)
            class_ref = exclusive(folder/'compact_classification_completion.json', class_receipt)
            receipt['classification_completion_ref'] = class_ref
            point_ref = exclusive(folder/'compact_point_completion.json', receipt)
            self.latest = dict(entry=entry,receipt=receipt,receipt_ref=point_ref,capture_ref=capture_ref)
            self.last_source = frame['source_stamp_s'];self.last_frame = frame['frame_seq']
            self.last_status = dict(status='CURRENT_COMPACT_STOP_INPUT_READY_NOT_SDK',scope=self.scope,
                compact_completion_ref=point_ref,complete_capture_ref=capture_ref,
                SDK_READY=False,execution_allowed=False)
        except (ValueError,TypeError,KeyError,IndexError,OSError,RuntimeError) as exc:
            self._diagnostic_failure('poll',exc,context,frame,observation)
            self.last_status = dict(status='HOLD_COMPACT_STOP_INPUT',reason=str(exc),scope=self.scope,
                compact_completion_ref=None,SDK_READY=False,execution_allowed=False,
                original_provider_diagnostic=self.diagnostic_status())
        return deepcopy(self.last_status)

    def current(self):
        if threading.get_ident() != threading.main_thread().ident:
            return None
        selected = self.latest
        if selected is None:return None
        context=dict(lifecycle_phase=self._diagnostic_phase,stage='CURRENT_FRAME')
        frame=None;observation=None
        try:
            entry = selected['entry'];meta = entry.read();frame = pinned(meta['frame_input'])
            context.update(frame_input_ref=deepcopy(meta['frame_input']),stage='CURRENT_CLASSIFICATION_CLOCK')
            observation=self._clock();context['stage']='CURRENT_CLASSIFICATION_FRESHNESS'
            self._fresh(frame,observation)
            context['stage']='CURRENT_CAPTURE'
            if self.capture() != selected['capture_ref']:
                raise ValueError('CURRENT_COMPLETE_CAPTURE_OR_D_CHANGED')
            pinned(selected['receipt_ref'])
            entry.verify()
            context['stage']='CURRENT_POINT_CLOCK';observation=None
            observation=self._clock();context['stage']='CURRENT_POINT_FRESHNESS'
            self._fresh(frame,observation)
            return dict(packet=entry.packet,compact_ref=meta['compact_ref'],
                        compact_completion_ref=selected['receipt_ref'],complete_capture_ref=selected['capture_ref'],
                        scope=self.scope,SDK_READY=False,execution_allowed=False)
        except (ValueError,TypeError,KeyError,IndexError,OSError,RuntimeError) as exc:
            self._diagnostic_failure('current',exc,context,frame,observation)
            self.latest = None
            return None
