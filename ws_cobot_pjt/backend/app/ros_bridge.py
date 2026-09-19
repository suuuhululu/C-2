"""Jazzy monitor_gateway_node. 팀 c2_interfaces 설치본만 사용하며 자체 메시지를 만들지 않는다.

실제 장치 연결은 이 초안 범위가 아니다. source_mode=SIMULATION만 허용한다.
파일 ID 해석 계약 확정 후 artifact_loader를 주입해 생성 결과 수신을 연결한다.
"""
import asyncio
import math
import threading


def json_values(value):
    """비유한 측정값은 JSON null. 신호별 quality 매핑은 설치 메시지 계약에서 확정한다."""
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,dict):return {k:json_values(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_values(v) for v in value]
    if hasattr(value,'tolist'):return json_values(value.tolist())
    return value


async def await_ros(future, timeout):
    loop=asyncio.get_running_loop(); result=loop.create_future()
    def done(source):
        def settle():
            if result.done():return
            try:result.set_result(source.result())
            except Exception as exc:result.set_exception(exc)
        loop.call_soon_threadsafe(settle)
    future.add_done_callback(done)
    return await asyncio.wait_for(result,timeout)


def fill_message(message, values):
    """키 누락·자료형 차이는 숨기지 않고 설치 타입에서 거절한다."""
    fields=message.get_fields_and_field_types()
    missing=set(values)-set(fields)
    if missing:raise ValueError(f'c2_interfaces 필드 불일치: {sorted(missing)}')
    for key,value in values.items():setattr(message,key,value)
    return message


class RosBridge:
    transport='ROS2'

    def __init__(self,emit,artifact_loader=None):
        self.emit=emit;self.artifact_loader=artifact_loader;self.handles={};self.pending=set()

    async def start(self):
        try:
            import rclpy
            from rclpy.context import Context
            from rclpy.node import Node
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.callback_groups import ReentrantCallbackGroup
            from rclpy.action import ActionClient
            from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
            from rosidl_runtime_py.convert import message_to_ordereddict
            from c2_interfaces.action import GeneratePath, ExecuteProcess
            from c2_interfaces.srv import StopProcess
            from c2_interfaces.msg import ProcessState, ProcessEvent
        except ImportError as exc:
            raise RuntimeError('ROS 모드는 Jazzy와 팀 c2_interfaces 빌드·source가 필요합니다. 임의 메시지로 대체하지 않습니다.') from exc
        self.rclpy=rclpy;self.loop=asyncio.get_running_loop();self.convert=message_to_ordereddict
        self.types=(GeneratePath,ExecuteProcess,StopProcess)
        self.context=Context();rclpy.init(context=self.context)
        self.node=Node('monitor_gateway_node',context=self.context)
        self.group=ReentrantCallbackGroup()
        self.generate_client=ActionClient(self.node,GeneratePath,'/c2/generate_path',callback_group=self.group)
        self.execute_client=ActionClient(self.node,ExecuteProcess,'/c2/execute_process',callback_group=self.group)
        self.stop_client=self.node.create_client(StopProcess,'/c2/stop_process',callback_group=self.group)
        for msg,name,kind,depth in [(ProcessState,'/c2/process_state','state',1),(ProcessEvent,'/c2/process_events','event',100)]:
            qos=QoSProfile(depth=depth,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.VOLATILE)
            self.node.create_subscription(msg,name,lambda m,k=kind:self.deliver(k,self.convert(m)),qos,callback_group=self.group)
        self.executor=MultiThreadedExecutor(num_threads=2,context=self.context)
        self.executor.add_node(self.node)
        self.thread=threading.Thread(target=self.executor.spin,name='monitor-ros-executor',daemon=True)
        self.thread.start()

    def deliver(self,kind,value):
        # ROS 콜백은 DB/HTTP 처리를 기다리지 않는다.
        def enqueue():
            task=self.loop.create_task(self.emit(kind,json_values(dict(value))))
            self.pending.add(task);task.add_done_callback(self.pending.discard)
        self.loop.call_soon_threadsafe(enqueue)

    async def action(self,client,msg,values,feedback=None):
        if values.get('source_mode')!='SIMULATION':raise ValueError('이 게이트웨이 초안은 SIMULATION 전용입니다.')
        if not client.server_is_ready():raise ConnectionError('ROS Action 서버가 준비되지 않았습니다.')
        goal=fill_message(msg.Goal(),values)
        def on_feedback(packet):
            if feedback:
                self.loop.call_soon_threadsafe(lambda:self.track_feedback(feedback,dict(self.convert(packet.feedback))))
        accepting=client.send_goal_async(goal,feedback_callback=on_feedback)
        try:handle=await await_ros(accepting,3)
        except (asyncio.CancelledError,asyncio.TimeoutError):
            # 접수 응답이 뒤늦게 와도 취소를 요청한다. 실제 종료 결과는 UNKNOWN으로 유지한다.
            def cancel_late(f):
                try:
                    late=f.result()
                    if late and late.accepted:late.cancel_goal_async()
                except Exception:pass
            accepting.add_done_callback(cancel_late)
            raise
        if not handle.accepted:raise RuntimeError('ROS Goal이 거절되었습니다.')
        self.handles[values['request_id']]=handle
        try:
            result=await await_ros(handle.get_result_async(),120 if client is self.generate_client else 3600)
            return dict(self.convert(result.result))
        except (asyncio.CancelledError,asyncio.TimeoutError):
            handle.cancel_goal_async()  # 수락을 정지 확인으로 간주하지 않는다.
            raise
        finally:self.handles.pop(values['request_id'],None)

    def track_feedback(self,callback,value):
        task=self.loop.create_task(callback(value));self.pending.add(task);task.add_done_callback(self.pending.discard)

    async def generate_raw(self,goal,feedback):
        return await self.action(self.generate_client,self.types[0],goal,feedback)

    async def generate(self,goal,feedback):
        if self.artifact_loader is None:
            raise RuntimeError('좌표 노드의 ID→파일 계약과 preview 형식 확정 후 artifact_loader를 연결해야 합니다.')
        result=await self.generate_raw(goal,feedback)
        metadata=await self.artifact_loader(goal,result) if result['success'] else None
        return metadata,result

    def prepare(self,run):pass

    async def execute(self,goal):
        return await self.action(self.execute_client,self.types[1],goal)

    async def stop(self,body):
        if not self.stop_client.service_is_ready():raise ConnectionError('ROS 정지 Service 연결 불가')
        request=fill_message(self.types[2].Request(),body)
        response=await await_ros(self.stop_client.call_async(request),1)
        return dict(self.convert(response))

    async def close(self):
        for handle in self.handles.values():handle.cancel_goal_async()
        await asyncio.to_thread(self.executor.shutdown,timeout_sec=2)
        self.node.destroy_node();self.context.shutdown();self.thread.join(timeout=2)
        await asyncio.gather(*list(self.pending),return_exceptions=True)
