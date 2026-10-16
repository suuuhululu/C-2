"""Small same-D pre-SDK file IPC. No ROS/client/SDK creation."""
from copy import deepcopy
from pathlib import Path
from uuid import UUID,uuid4
import json,hashlib,time


def pin(p):
    p=Path(p);return dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest())


def read(ref):
    p=Path(ref['path'])
    if not p.is_absolute() or pin(p)!=ref:raise ValueError('ADMISSION_REQUEST_PIN_CHANGED_OR_NOT_ABSOLUTE')
    return json.loads(p.read_text())


class PreparedAdmissionIPC:
    def __init__(self,folder,executor,approve,identity,telemetry=None):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.request_pointer=self.folder/'request.pointer.json';self.response_pointer=self.folder/'response.pointer.json'
        self.telemetry=telemetry or (lambda *a,**kw:None)
        self.executor=executor;self.approve=approve;self.identity=identity;self.sequence=-1;self.future=None;self.active=None

    def respond(self,attempt,response):
        path=self.folder/'attempts'/attempt/'response.json'
        with path.open('x') as f:json.dump(response,f,allow_nan=False,indent=2)
        pointer=dict(schema='same-d-prepared-admission-response-pointer/0.1',response=pin(path))
        temp=self.folder/(uuid4().hex+'.tmp');temp.write_text(json.dumps(pointer));temp.replace(self.response_pointer)

    def poll(self):
        if self.future is not None:
            if not self.future.done():return
            attempt,request_ref,started=self.active
            try:
                selected=self.future.result()
                if pin(selected['path'])!=selected:raise ValueError('RETURNED_NATIVE_SELECTED_JOB_PIN_CHANGED')
                response=dict(status='NATIVE_SELECTED_INPUT_BEFORE_SDK_NOT_READY_OR_APPLY',selected_native_job=selected)
            except Exception as exc:response=dict(status='HOLD_ADMISSION_REJECTED',reason=str(exc),selected_native_job=None)
            self.respond(attempt,dict(response,schema='same-d-prepared-admission-response/0.1',attempt_id=attempt,
                request=request_ref,CPU_queue_total_wall_s=time.monotonic()-started,READY=False,apply_allowed=False,SDK_started=False,native_send_called=False))
            self.future=None;self.active=None
            return
        if not self.request_pointer.exists():return
        pointer=json.loads(self.request_pointer.read_text())
        if pointer['schema']!='same-d-prepared-admission-request-pointer/0.1':raise ValueError('ADMISSION_POINTER_SCHEMA')
        request_ref=pointer['request'];request=read(request_ref)
        attempt=UUID(request['attempt_id']).hex
        folder=self.folder/'attempts'/attempt
        if folder.exists():
            original=json.loads((folder/'request.observed.json').read_text())
            if original['request_ref']!=request_ref:raise ValueError('ADMISSION_ATTEMPT_ID_REUSED_WITH_CHANGED_INPUT')
            return  # exact replay never re-admits or starts anything
        folder.mkdir(parents=True,exist_ok=False)
        try:
            with (folder/'request.observed.json').open('x') as f:json.dump(dict(request_ref=request_ref,request=request),f,indent=2)
            if request['schema']!='same-d-prepared-admission-request/0.1':raise ValueError('ADMISSION_REQUEST_SCHEMA')
            seq=request['sequence']
            if type(seq) is not int or seq<=self.sequence:raise ValueError('ADMISSION_SEQUENCE_NOT_NEW')
            if request['identity']!=self.identity():raise ValueError('ADMISSION_OTHER_SESSION_OR_CANCEL_IDENTITY')
            for ref in (request['prepared_job'],request['before_SDK_phase']):
                if not Path(ref['path']).is_absolute():raise ValueError('ADMISSION_INPUT_REF_NOT_ABSOLUTE')
            self.sequence=seq
            self.active=(attempt,deepcopy(request_ref),time.monotonic())
            job_ref=deepcopy(request['prepared_job']);phase_ref=deepcopy(request['before_SDK_phase'])
            queued=time.monotonic()
            self.telemetry('ADMISSION_CPU_QUEUED',attempt_id=attempt,queued_wall_monotonic_s=queued)
            def work():
                started=time.monotonic()
                self.telemetry('ADMISSION_CPU_START',attempt_id=attempt,queue_wait_wall_s=started-queued)
                try:
                    read(job_ref);read(phase_ref)
                    return self.approve(job_ref,phase_ref,request_ref=deepcopy(request_ref))
                finally:self.telemetry('ADMISSION_CPU_END',attempt_id=attempt,CPU_wall_s=time.monotonic()-started)
            self.future=self.executor.submit(work)
        except Exception as exc:
            self.respond(attempt,dict(schema='same-d-prepared-admission-response/0.1',attempt_id=attempt,request=request_ref,
                status='HOLD_ADMISSION_REJECTED',reason=str(exc),selected_native_job=None,READY=False,apply_allowed=False,SDK_started=False,native_send_called=False))
