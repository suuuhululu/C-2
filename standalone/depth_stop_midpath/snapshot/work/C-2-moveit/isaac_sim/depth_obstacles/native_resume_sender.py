"""Same-owner submission adapter. Creates no client, executor, thread or lock."""
from copy import deepcopy
from uuid import UUID,uuid4
from plan_only import digest


class SameDResumeSender:
    def __init__(self,*,ipc,client,owner_lock,current_observation_provider,goal_builder,
                 uuid_message,encoded_proof_provider,encoding_source_pins,on_submitted,on_failure,prepare_adoption):
        if not callable(getattr(owner_lock,'_is_owned',None)):
            raise ValueError('EXISTING_D_REENTRANT_APPLY_LOCK_REQUIRED')
        for callback in (current_observation_provider,goal_builder,uuid_message,encoded_proof_provider,on_submitted,on_failure,prepare_adoption):
            if not callable(callback):raise ValueError('EXISTING_OWNER_CALLBACK_REQUIRED')
        self.ipc=ipc;self.client=client;self.lock=owner_lock;self.observe=current_observation_provider
        self.goal_builder=goal_builder;self.uuid_message=uuid_message;self.encoded=encoded_proof_provider
        self.source_pins=deepcopy(encoding_source_pins);self.on_submitted=on_submitted;self.on_failure=on_failure;self.prepare_adoption=prepare_adoption
        self.used=False;self.reservation=None

    def reserve(self,intent):
        if not self.lock._is_owned() or self.reservation is not None:
            raise ValueError('D_RESERVATION_ONCE_INSIDE_EXISTING_LOCK')
        new_id=uuid4().hex
        if new_id==UUID(intent['identity']['goal_id']).hex:raise ValueError('NEW_D_UUID_REQUIRED')
        self.reservation=dict(scope='D_SERIALIZED_NATIVE_RESERVATION_NOT_SEND',single_writer='D',native_send_called=False,
                              **deepcopy(intent),new_goal_id=new_id)
        return deepcopy(self.reservation)

    @staticmethod
    def guard(source):
        if source is None:raise ValueError('CURRENT_D_SOURCE_REQUIRED')
        owner=source['owner']
        if any(owner.get(k) is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):
            raise ValueError('D_STOP_FAILURE_UNKNOWN_NO_RESUME')
        if owner.get('mode')!='OBSTACLE_HOLD' or owner.get('holding_confirmed') is not True:
            raise ValueError('CURRENT_D_VERIFIED_HOLD_REQUIRED')

    def try_submit(self):
        # These are necessary prerequisites only. The canonical final helper
        # validates every actual job/proof/STOP/clock/Depth/target and source pin.
        if self.used:return dict(status='HOLD_NO_AUTOMATIC_RESEND',native_send_called=False)
        if (self.ipc.job_ref is None or self.ipc.geometry_handoff_ref is None or
                self.ipc.current_geometry is None or not self.source_pins):
            return dict(status='HOLD_FRESH_JOB_AND_CURRENT_ENCODED_PROOF_REQUIRED',native_send_called=False)
        submitted=False;future=None;goal=None;audit=None
        try:
            with self.lock:
                before=deepcopy(self.observe());self.guard(before)
                self.used=True  # A final review/reservation attempt is never retried automatically.
                goal,audit=self.ipc.final_current_geometry_goal(
                    current_observation_provider=self.observe,owner_lock=self.lock,reserve_new_goal=self.reserve,
                    goal_builder=self.goal_builder,encoded_proof_provider=self.encoded,encoding_source_pins=self.source_pins)
                if self.reservation is None or UUID(audit['new_goal_id']).hex!=self.reservation['new_goal_id']:
                    raise ValueError('AUDIT_UUID_NOT_D_RESERVATION')
                if UUID(audit['new_goal_id']).hex==UUID(before['owner']['goal_id']).hex:
                    raise ValueError('OLD_GOAL_UUID_CANNOT_RESUME')
                frozen_goal=deepcopy(goal);goal_identity=id(goal)
                adoption=self.prepare_adoption(goal,audit)
                message=self.uuid_message(UUID(audit['new_goal_id']).bytes)
                after=deepcopy(self.observe());self.guard(after)
                if digest(before)!=digest(after):raise ValueError('D_CURRENT_SOURCE_CHANGED_BEFORE_EXISTING_SEND')
                if id(goal)!=goal_identity or goal!=frozen_goal:raise ValueError('SAME_TYPED_GOAL_CHANGED_BEFORE_EXISTING_SEND')
                # Synchronous submission decision under the SAME outer owner lock;
                # acceptance/result monitoring belongs to the existing D loop.
                submitted=True
                future=self.client.send_goal_async(goal,goal_uuid=message)
            self.on_submitted(goal,future,audit,adoption)
            return dict(status='D_EXISTING_CLIENT_SUBMISSION_PENDING_ACCEPTANCE',new_goal_id=audit['new_goal_id'],
                        native_send_called=True,accepted_verified=False,goal_succeeded=False)
        except Exception as exc:
            self.used=True
            self.on_failure(dict(reason=str(exc),submission_attempted=submitted,reservation=deepcopy(self.reservation),
                                 future=future,goal=goal,audit=audit))
            return dict(status='HOLD_D_OWNER_CLEANUP_REQUIRED_NO_AUTOMATIC_RETRY',reason=str(exc),
                        native_send_called=submitted,accepted_verified=False,goal_succeeded=False)


def encoded_selection_provider(output_root):
    """Invoke CU's existing exact encoding derivation, never a new FCL/SDK run."""
    from pathlib import Path
    from isaac_sim.depth_obstacles.live_sensor_bundle import pin
    def produce(wire_ref,delivery_ref,selection):
        from current_geometry_fcl import produce_encoded_geometry_proof
        provider=selection['snapshot_provider']
        if not callable(provider):raise ValueError('INDEPENDENT_CURRENT_GEOMETRY_PROVIDER_REQUIRED')
        folder=Path(output_root)/uuid4().hex
        proof=produce_encoded_geometry_proof(selection['proof_ref'],selection['files'],wire_ref,delivery_ref,provider,folder)
        return dict(proof_ref=pin(folder/'current_geometry_FCL.json'),files=proof['calculation_files'],snapshot_provider=provider)
    return produce
