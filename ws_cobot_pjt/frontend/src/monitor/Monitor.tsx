import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  Bell,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileImage,
  History,
  Leaf,
  LoaderCircle,
  Octagon,
  Radio,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Upload,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import {
  SCHEMA_VERSION,
  active,
  ApiError,
  initialPlacement,
  phaseNames,
  request,
  stageNames,
  statusNames,
} from "./api";
import type {
  Asset,
  Generation,
  PathResult,
  Placement,
  Run,
  Snapshot,
} from "./api";
import { CylinderPreview, UnwrappedPreview } from "./Previews";
import "./monitor.css";
import LivePathPreview from "./LivePathPreview";
import { matchesPreview } from "./preview";
import FileIntegration from "./FileIntegration";
import WorkAreaSummary from "./WorkAreaSummary";
import PreparationPanel from "./PreparationPanel";
import { executionConfirmationKey } from "./preparation";
import RobotObservations from "./RobotObservations";
import { mm, topToBottom } from "./workArea";

const navItems = [
  { id: "prepare", name: "작업 준비", icon: FileImage },
  { id: "integration", name: "파일 통합 시험", icon: Upload },
  { id: "process", name: "공정 관제", icon: Activity },
  { id: "history", name: "실행 이력", icon: History },
  { id: "alarms", name: "알람", icon: Bell },
  { id: "settings", name: "설정 정보", icon: Settings2 },
];
const scenarios: Record<string, string> = {
  normal: "정상 공정",
  generation_failure: "경로 검증 실패",
  grip_failure: "드릴 장착·닫힘 확인 실패",
  calibration_failure: "드릴 보정 확인 실패",
  cut_quality_failure: "모의 압력 확인 실패",
  stop_unknown: "정지 확인 불가",
  communication_loss: "상태 통신 단절",
  preparation_failure: "준비 상태 검사 실패",
  measurement_reference_only: "측정 후 절대 윗면 미확인",
  preparation_timeout: "준비 대기 시간 초과 시험",
};
const short = (id?: string) => (id ? id.slice(0, 8) : "—");
const timeLabel = (iso: string) =>
  new Date(iso).toLocaleTimeString("ko-KR", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

export default function Monitor() {
  const [nav, setNav] = useState("prepare"),
    [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [connected, setConnected] = useState(false);
  const [asset, setAsset] = useState<Asset | null>(null),
    [draft, setDraft] = useState<Placement>(initialPlacement),
    [ratio, setRatio] = useState(true);
  const [result, setResult] = useState<PathResult | null>(null),
    [stale, setStale] = useState(false),
    [reviewed, setReviewed] = useState(false),
    [fixture, setFixture] = useState(false);
  const [drillConfirmation, setDrillConfirmation] = useState<string | null>(
    null,
  );
  const [uploading, setUploading] = useState(false),
    [generation, setGeneration] = useState<Generation | null>(null),
    [generating, setGenerating] = useState(false);
  const [cancelPending, setCancelPending] = useState(false);
  const [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [pending, setPending] = useState(false),
    [startUncertain, setStartUncertain] = useState(false),
    [stopPending, setStopPending] = useState(false);
  const [runs, setRuns] = useState<Run[]>([]),
    [alarms, setAlarms] = useState<
      {
        event_id: string;
        code: string;
        message: string;
        occurred_at: string;
        active: boolean;
      }[]
    >([]),
    [detail, setDetail] = useState<Run | null>(null);
  const [verdict, setVerdict] = useState("PASS"),
    [reason, setReason] = useState("");
  const input = useRef<HTMLInputElement>(null),
    revision = useRef(0),
    lastPacket = useRef(0),
    live = useRef(true);
  const startBody = useRef<unknown>(null),
    stopId = useRef<{ run: string; id: string } | null>(null);
  const generationRequest = useRef<{ body: unknown; revision: number } | null>(
    null,
  );
  const [executionPath, setExecutionPath] = useState<PathResult | null>(null);
  const previousProfile = useRef<string | null>(null);
  const previousPreparation = useRef<string | null>(null);
  const run = snapshot?.active_run;
  const fresh = connected && snapshot?.connection === "CONNECTED";
  const isRos = snapshot?.transport === "ROS2";
  const capabilities = snapshot?.path_generation;
  const serverGeneration = snapshot?.generation;
  const serverGenerating =
    !!serverGeneration &&
    ["ACCEPTED", "RUNNING", "CANCELING", "UNKNOWN"].includes(
      serverGeneration.state,
    );
  const pathReady = connected && (isRos ? !!capabilities?.ready : fresh);
  const headerConnected = snapshot?.source_mode === "REAL" ? fresh : pathReady;
  const busy = active(run),
    locked =
      busy || pending || startUncertain || !!snapshot?.preparation.blocks_work;
  const preparationBlocked =
    !!snapshot?.preparation.blocks_work ||
    (!isRos && !snapshot?.preparation.ready);
  const profile = snapshot?.profile;
  const baseXOrigin =
    !!profile?.payload.surface.axis_origin_m &&
    (profile.payload.surface.u_origin_angle_deg || 0) === 0;
  const currentResult =
    !!result && !stale && result.preview.profile_snapshot_id === profile?.id;
  const drillKey = executionConfirmationKey(
    [
      result?.path_id,
      result?.path_version,
      result?.path_sha256,
      profile?.id,
      profile?.sha256,
      snapshot?.preparation.current?.request_id,
      snapshot?.preparation.current?.state,
      snapshot?.state?.source_epoch,
      run?.run_id,
      run?.status,
      nav,
    ],
    !!fresh &&
      currentResult &&
      !locked &&
      !uploading &&
      !generating &&
      !serverGenerating &&
      !preparationBlocked,
  );
  const drillOn = !!drillKey && drillConfirmation === drillKey;
  useEffect(() => {
    setDrillConfirmation(null);
  }, [drillKey]);
  const canStart =
    capabilities?.execution_enabled &&
    !result?.test_only &&
    currentResult &&
    reviewed &&
    fixture &&
    drillOn &&
    !preparationBlocked &&
    fresh &&
    !busy &&
    !pending &&
    !uploading &&
    !generating &&
    !serverGenerating &&
    !snapshot?.storage_error;

  useEffect(() => {
    const id = snapshot?.preparation.current?.request_id;
    if (!id || id === previousPreparation.current) return;
    previousPreparation.current = id;
    revision.current++;
    setReviewed(false);
    setFixture(false);
    setStale(true);
    generationRequest.current = null;
  }, [snapshot?.preparation.current?.request_id]);

  useEffect(() => {
    if (!profile || !capabilities || previousProfile.current === profile.id)
      return;
    previousProfile.current = profile.id;
    revision.current++;
    setDraft(capabilities.default_placement);
    setResult(null);
    setReviewed(false);
    setFixture(false);
    generationRequest.current = null;
  }, [profile?.id, capabilities]);

  useEffect(() => {
    live.current = true;
    let ws: WebSocket | null = null,
      retry = 0,
      retryTimer = 0,
      disposed = false;
    const accept = (s: Snapshot) => {
      if (disposed) return;
      lastPacket.current = Date.now();
      setSnapshot(s);
      setConnected(true);
    };
    function connect() {
      request<Snapshot>("/snapshot")
        .then(accept)
        .catch(() => {
          if (!disposed) setConnected(false);
        });
      ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/operator/stream`,
      );
      ws.onmessage = (e) => {
        try {
          const packet = JSON.parse(e.data);
          if (
            packet.type === "snapshot" &&
            packet.data.schema_version === SCHEMA_VERSION
          ) {
            accept(packet.data);
            retry = 0;
          }
        } catch {
          setConnected(false);
        }
      };
      ws.onclose = () => {
        if (!disposed) {
          setConnected(false);
          retryTimer = window.setTimeout(
            connect,
            Math.min(5000, 700 * ++retry),
          );
        }
      };
      ws.onerror = () => ws?.close();
    }
    connect();
    const watchdog = window.setInterval(() => {
      if (Date.now() - lastPacket.current > 2000) setConnected(false);
    }, 500);
    return () => {
      disposed = true;
      live.current = false;
      clearTimeout(retryTimer);
      clearInterval(watchdog);
      ws?.close();
    };
  }, []);

  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 4500);
      return () => clearTimeout(t);
    }
  }, [toast]);
  useEffect(() => {
    if (nav === "history")
      request<Run[]>("/runs")
        .then(setRuns)
        .catch((e) => setError(e.message));
    if (nav === "alarms")
      request<typeof alarms>("/alarms")
        .then(setAlarms)
        .catch((e) => setError(e.message));
  }, [nav, run?.status]);
  useEffect(() => {
    if (
      run &&
      ["SUCCEEDED", "FAILED", "STOPPED", "UNKNOWN"].includes(run.status)
    ) {
      setFixture(false);
      setStartUncertain(false);
      startBody.current = null;
    }
  }, [run?.status, run?.run_id]);

  useEffect(() => {
    if (!run) {
      setExecutionPath(null);
      return;
    }
    let cancelled = false;
    setExecutionPath(null);
    request<PathResult>(`/paths/${run.path_id}/versions/${run.path_version}`)
      .then((p) => {
        if (!cancelled && p.path_sha256 === run.path_sha256)
          setExecutionPath(p);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [run?.run_id, run?.path_id, run?.path_version]);

  function edit(next: Placement) {
    setDrillConfirmation(null);
    revision.current++;
    setDraft(next);
    setStale(!!result);
    setReviewed(false);
    setFixture(false);
    generationRequest.current = null;
  }
  function field(key: keyof Placement, value: number) {
    if (!Number.isFinite(value)) return;
    const next = { ...draft, [key]: value };
    if (ratio && key === "width_mm" && draft.width_mm > 0)
      next.height_mm = +((draft.height_mm * value) / draft.width_mm).toFixed(1);
    if (ratio && key === "height_mm" && draft.height_mm > 0)
      next.width_mm = +((draft.width_mm * value) / draft.height_mm).toFixed(1);
    edit(next);
  }
  async function upload(file?: File) {
    if (!file || locked) return;
    setDrillConfirmation(null);
    setError("");
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const a = await request<Asset>("/assets", form);
      setAsset(a);
      setResult(null);
      setStale(false);
      setReviewed(false);
      setFixture(false);
      revision.current++;
      generationRequest.current = null;
      setToast("이미지를 첨부했습니다. 크기와 위치를 정해 주세요.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }
  async function sample() {
    try {
      const r = await fetch("/samples/monitor_centerline.png");
      if (!r.ok) throw new Error("샘플 이미지를 불러올 수 없습니다.");
      await upload(
        new File([await r.blob()], "botanical-sample.png", {
          type: "image/png",
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function generate() {
    if (
      !asset ||
      !profile ||
      !capabilities ||
      !pathReady ||
      preparationBlocked ||
      generating ||
      serverGenerating
    )
      return;
    setError("");
    setGenerating(true);
    setReviewed(false);
    setFixture(false);
    setStale(!!result);
    const rev = revision.current;
    const body =
      generationRequest.current?.revision === rev
        ? generationRequest.current.body
        : {
            schema_version: SCHEMA_VERSION,
            request_id: crypto.randomUUID(),
            source_mode: "SIMULATION",
            asset_id: asset.asset_id,
            asset_sha256: asset.asset_sha256,
            ...draft,
            conversion_preset: capabilities.preset,
            tool_id: profile.payload.tool_id,
            profile_snapshot_id: profile.id,
            profile_sha256: profile.sha256,
          };
    generationRequest.current = { body, revision: rev };
    try {
      let g = await request<Generation>("/path-generations", body);
      const start = Date.now();
      while (
        live.current &&
        !["SUCCEEDED", "FAILED", "UNKNOWN"].includes(g.state)
      ) {
        setGeneration(g);
        if (Date.now() - start > 135000)
          throw new Error(
            "생성 제한 시간이 지났습니다. 같은 요청을 다시 조회하세요.",
          );
        await new Promise((resolve) => setTimeout(resolve, 350));
        g = await request<Generation>(
          `/path-generations/${(body as { request_id: string }).request_id}`,
        );
      }
      if (!live.current) return;
      setGeneration(g);
      if (!g.result?.success) {
        generationRequest.current = null;
        if (g.result?.error_code === "CANCELED") {
          setToast(
            "경로 생성을 취소했습니다. 새 이미지를 선택하거나 다시 생성하세요.",
          );
          return;
        }
        throw new Error(g.result?.message || "경로를 생성하지 못했습니다.");
      }
      const p = await request<PathResult>(
        `/paths/${g.result.path_id}/versions/${g.result.path_version}`,
      );
      if (
        !matchesPreview(p, capabilities.preview_contract) ||
        p.preview.profile_snapshot_id !== profile.id
      )
        throw new Error("미리보기와 경로의 계약·버전이 일치하지 않습니다.");
      if (revision.current !== rev) {
        setToast("이전 입력의 생성이 끝났습니다. 현재 배치로 다시 생성하세요.");
        return;
      }
      setResult(p);
      setStale(false);
      setToast(
        isRos
          ? "첨부 이미지의 경로가 생성됐습니다. 기하 검증 결과와 미리보기를 확인하세요."
          : "모의 경로를 준비했습니다. 두 미리보기를 확인해 주세요.",
      );
      generationRequest.current = null;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  }
  async function cancelGeneration() {
    setDrillConfirmation(null);
    const rid = serverGeneration?.request_id || generation?.request_id;
    if (!rid || cancelPending) return;
    setCancelPending(true);
    setError("");
    try {
      const g = await request<Generation>(
        `/path-generations/${rid}/cancel`,
        {},
      );
      setGeneration(g);
      setSnapshot((s) => (s ? { ...s, generation: g } : s));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCancelPending(false);
    }
  }

  async function startRun() {
    if (!result || pending || (!startUncertain && !canStart)) return;
    setDrillConfirmation(null); // 한 번의 확인은 한 번의 새 요청에만 사용한다.
    setPending(true);
    setError("");
    if (!startBody.current)
      startBody.current = {
        schema_version: SCHEMA_VERSION,
        request_id: crypto.randomUUID(),
        source_mode: "SIMULATION",
        path_id: result.path_id,
        path_version: result.path_version,
        path_sha256: result.path_sha256,
        operator_confirmed_fixture: true,
      };
    try {
      await request<Run>("/runs", startBody.current);
      setStartUncertain(false);
      setNav("process");
      setToast("실행 요청을 접수했습니다. 실제 단계는 공정 상태로 확인합니다.");
    } catch (e) {
      setError((e as Error).message);
      const uncertain = !(e instanceof ApiError && e.status < 500);
      setStartUncertain(uncertain);
      if (!uncertain) startBody.current = null;
    } finally {
      setPending(false);
    }
  }
  async function stopRun() {
    setDrillConfirmation(null);
    if (!run) return;
    setStopPending(true);
    setError("");
    if (stopId.current?.run !== run.run_id)
      stopId.current = { run: run.run_id, id: crypto.randomUUID() };
    try {
      const response = await request<{ message: string }>(
        `/runs/${run.run_id}/stop`,
        {
          schema_version: SCHEMA_VERSION,
          request_id: stopId.current.id,
          reason: "운영자 정지 요청",
        },
      );
      setToast(response.message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStopPending(false);
    }
  }
  async function changeScenario(value: string) {
    try {
      await request("/simulation/scenario", { scenario: value });
      setToast("모의 시나리오를 변경했습니다.");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function resetSimulation() {
    setDrillConfirmation(null);
    try {
      const s = await request<Snapshot>("/simulation/reset", {});
      setSnapshot(s);
      setStartUncertain(false);
      startBody.current = null;
      stopId.current = null;
      setToast("모의 상태를 초기화했습니다. 기록은 보존됩니다.");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function inspect() {
    if (!detail || !reason.trim()) return;
    try {
      await request("/inspections", { run_id: detail.run_id, verdict, reason });
      setDetail(await request<Run>(`/runs/${detail.run_id}`));
      setReason("");
      setToast("검사 기록을 저장했습니다.");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="monitor-app">
      <aside className="sidebar">
        <a className="brand" href="/operator">
          <div className="brand-word">
            새김
            <Leaf size={32} strokeWidth={1} />
          </div>
          <span>SAEGIM</span>
          <small>시스템 모니터</small>
        </a>
        <nav>
          {navItems.map(({ id, name, icon: Icon }) => (
            <button
              key={id}
              className={nav === id ? "active" : ""}
              onClick={() => setNav(id)}
            >
              <Icon size={20} strokeWidth={1.6} />
              <span>{name}</span>
              {nav === id && <ChevronRight size={14} />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="cell-mark">
            <span />
            M0609 · CELL 01
          </div>
          <span>한 줄의 마음을, 표면 위에.</span>
          <small>MONITOR / V1.0</small>
        </div>
      </aside>
      <main className="monitor-main">
        <header className="topbar">
          <div className="cell-title">
            <span className="eyebrow">WORKCELL</span>
            <strong>각인 셀 01</strong>
          </div>
          <span className="mode-badge">
            <span />
            {snapshot?.source_mode || "연결 대기"}
          </span>
          <div
            className={`connection ${headerConnected ? "online" : "offline"}`}
          >
            {headerConnected ? <Wifi size={16} /> : <WifiOff size={16} />}
            <span>
              {snapshot?.source_mode === "REAL"
                ? "REAL 준비·측정 전용"
                : isRos
                  ? pathReady
                    ? "ROS 경로 노드 연결"
                    : "ROS 경로 노드 미연결"
                  : pathReady
                    ? "모의 통신 연결"
                    : "통신 미확인"}
            </span>
          </div>
          {isRos && (
            <span className="tag">
              공정 상태 {fresh ? "수신 중" : "미수신"}
            </span>
          )}
          <span className="physical-state">
            {snapshot?.source_mode === "REAL"
              ? "준비 요청 시 실제 로봇 이동"
              : "실기 미연결"}
          </span>
          <div className="stop-zone">
            <div>
              <b>
                {run
                  ? `${statusNames[run.status] || run.status} · ${short(run.run_id)}`
                  : "활성 실행 없음"}
              </b>
              <small>
                {run?.stop_state && run.stop_state !== "NONE"
                  ? `정지 상태 ${run.stop_state}`
                  : "소프트웨어 정지 · 물리 비상정지와 별도"}
              </small>
            </div>
            <button
              className="stop-button"
              disabled={!busy || stopPending}
              onClick={stopRun}
            >
              {stopPending ? (
                <LoaderCircle className="spin" size={19} />
              ) : (
                <Octagon size={19} />
              )}
              정지 요청
            </button>
          </div>
        </header>
        <div className="page-body">
          <div className="page-heading">
            <div>
              <div className="eyebrow">SAEGIM / OPERATOR CONSOLE</div>
              <h1>{navItems.find((n) => n.id === nav)?.name}</h1>
              <p>
                {nav === "prepare"
                  ? "이미지를 불러오고, 원기둥 위에 도안의 자리를 정하세요."
                  : nav === "integration"
                    ? "같은 스냅샷과 경로 파일을 등록·전달하고 미리보기를 확인합니다."
                    : nav === "process"
                      ? "고정 드릴의 준비·보정 확인부터 조각 완료까지 확인합니다."
                      : nav === "history"
                        ? "각 실행에 사용한 경로와 결과를 함께 보관합니다."
                        : nav === "alarms"
                          ? "발생한 문제와 확인할 내용을 기록합니다."
                          : "현재 사용하는 설정 스냅샷과 연결 정보를 확인합니다."}
              </p>
            </div>
            {nav === "prepare" ? (
              <div className="stepper">
                {(isRos
                  ? ["이미지·설정", "경로 생성", "미리보기 확인", "실행 요청"]
                  : [
                      "준비·측정",
                      "이미지·설정",
                      "경로 생성",
                      "미리보기 확인",
                      "실행 요청",
                    ]
                ).map((s, i) => {
                  const imageStep = !asset
                    ? 0
                    : !currentResult
                      ? 1
                      : !reviewed
                        ? 2
                        : 3;
                  const step = isRos
                    ? imageStep
                    : !snapshot?.preparation.ready
                      ? 0
                      : imageStep + 1;
                  return (
                    <div
                      key={s}
                      className={
                        i < step ? "done" : i === step ? "current" : ""
                      }
                    >
                      <span>
                        {i < step ? (
                          <Check size={13} />
                        ) : (
                          String(i + 1).padStart(2, "0")
                        )}
                      </span>
                      {s}
                    </div>
                  );
                })}
              </div>
            ) : (
              <span className="tag">
                {snapshot?.source_mode || "연결 대기"} ·{" "}
                {snapshot?.transport || "연결 대기"}
              </span>
            )}
          </div>
          {error && (
            <div className="error-banner" role="alert">
              <CircleHelp size={18} />
              <span>{error}</span>
              <button aria-label="오류 안내 닫기" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {!fresh && snapshot && (
            <div className="warning-banner">
              {isRos
                ? "공정 상태는 아직 수신되지 않았습니다. 경로 노드가 연결되면 이미지 변환·미리보기를 시험할 수 있습니다. 공정 실행은 비활성 상태입니다."
                : "최신 공정 상태를 확인할 수 없습니다. 시작 요청이 차단됩니다. 저장된 상태는 실제 정지 확인을 뜻하지 않습니다."}
            </div>
          )}
          {snapshot?.storage_error && (
            <div className="error-banner" role="alert">
              {snapshot.storage_error}
            </div>
          )}
          {nav === "prepare" && snapshot?.preparation && (
            <PreparationPanel
              data={snapshot.preparation}
              connected={!!fresh}
              locked={
                !!busy ||
                pending ||
                startUncertain ||
                generating ||
                serverGenerating
              }
              onSnapshot={setSnapshot}
              onError={setError}
              onInvalidate={() => {
                setDrillConfirmation(null);
                setReviewed(false);
                setFixture(false);
                setStale(true);
              }}
            />
          )}
          {(nav === "prepare" || nav === "process") && (
            <RobotObservations snapshot={snapshot} connected={connected} />
          )}
          {nav === "integration" && (
            <FileIntegration
              asset={asset}
              placement={draft}
              locked={locked || generating || uploading}
              onUpload={upload}
              onChange={edit}
            />
          )}
          {nav === "prepare" &&
            generation?.state === "FAILED" &&
            generation.result?.validation_report_id && (
              <p className="warning-banner">
                <a
                  href={`/api/operator/assets/${generation.result.validation_report_id}/content`}
                  target="_blank"
                  rel="noreferrer"
                >
                  실패 검증 보고서 보기
                </a>
                {generation.result.svg_asset_id && (
                  <a
                    href={`/api/operator/assets/${generation.result.svg_asset_id}/content`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    추출 SVG 보기
                  </a>
                )}
              </p>
            )}
          {nav === "prepare" &&
            generation?.state === "FAILED" &&
            generation.result?.diagnostic_asset_id && (
              <details className="diagnostic">
                <summary>실행 불가 · 실패 진단 그림 보기</summary>
                <img
                  src={`/api/operator/assets/${generation.result.diagnostic_asset_id}/content`}
                  alt="실행 불가 진단 그림. 빨간 선은 모의 영역 밖 구간입니다."
                />
                <p>
                  진단 그림에는 실행 경로 ID가 없습니다. 배치를 조정한 뒤 다시
                  생성하세요.
                </p>
              </details>
            )}
          {nav === "prepare" && serverGeneration && (
            <div className="generation-status" role="status" aria-live="polite">
              <div>
                <strong>
                  {serverGeneration.state === "UNKNOWN"
                    ? "생성 중단 미확인"
                    : serverGeneration.state === "CANCELING"
                      ? "생성 취소 중 · 계산 종료 확인 대기"
                      : serverGenerating
                        ? `서버에서 경로 생성 중 · ${stageNames[serverGeneration.stage] || serverGeneration.stage}`
                        : serverGeneration.result?.error_code === "CANCELED"
                          ? "경로 생성 취소 완료"
                          : serverGeneration.state === "SUCCEEDED"
                            ? "최근 경로 생성 완료"
                            : "최근 경로 생성 실패"}
                </strong>
                <span>
                  요청 {serverGeneration.request_id.slice(0, 8)} ·{" "}
                  {Math.round(serverGeneration.progress * 100)}%
                  {serverGeneration.result
                    ? ` · ${serverGeneration.result.message}`
                    : " · 새로고침해도 계산은 계속됩니다."}
                </span>
              </div>
              {serverGenerating && serverGeneration.state !== "UNKNOWN" && (
                <button
                  type="button"
                  onClick={cancelGeneration}
                  disabled={
                    cancelPending || serverGeneration.state === "CANCELING"
                  }
                >
                  {cancelPending || serverGeneration.state === "CANCELING"
                    ? "취소 확인 중…"
                    : "경로 생성 취소"}
                </button>
              )}
            </div>
          )}
          {nav === "prepare" && (
            <div className="prepare-grid">
              <section className="panel input-panel">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">DESIGN INPUT</span>
                    <h2>이미지 첨부</h2>
                  </div>
                  <FileImage size={18} />
                </div>
                <input
                  ref={input}
                  type="file"
                  accept="image/png,image/jpeg"
                  hidden
                  onChange={(e) => {
                    upload(e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
                <div
                  className={`upload-area ${asset ? "has-image" : ""}`}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    upload(e.dataTransfer.files[0]);
                  }}
                >
                  {asset ? (
                    <>
                      <img src={asset.url} alt="첨부한 원본 이미지" />
                      <div>
                        <b>{asset.name}</b>
                        <small>
                          {asset.metadata.width} × {asset.metadata.height} px
                        </small>
                        <button
                          className="secondary compact"
                          disabled={locked || uploading}
                          onClick={() => input.current?.click()}
                        >
                          <Upload size={14} />
                          이미지 변경
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <button
                        className="upload-prompt"
                        disabled={locked || uploading}
                        onClick={() => input.current?.click()}
                      >
                        {uploading ? (
                          <LoaderCircle className="spin" size={27} />
                        ) : (
                          <Upload size={27} strokeWidth={1.3} />
                        )}
                        <b>이미지를 첨부하세요</b>
                        <span>PNG / JPG · 끌어다 놓기 · 최대 10 MiB</span>
                      </button>
                      <button
                        className="sample-button"
                        onClick={sample}
                        disabled={uploading}
                      >
                        샘플로 둘러보기 <ArrowRight size={14} />
                      </button>
                    </>
                  )}
                </div>
                <p className="field-help">
                  {isRos
                    ? "첨부 이미지를 ROS 경로 노드에서 중심선 SVG로 변환합니다."
                    : "현재 모의 모드는 첨부 이미지 대신 고정 샘플을 반환합니다."}
                </p>
                <div className="rule" />
                <h3>
                  작업 설정{" "}
                  <small className="muted">
                    {isRos ? "경로 시험 프로파일" : "모의 프로파일"}
                  </small>
                </h3>
                <dl className="work-settings">
                  <div>
                    <dt>작업대상</dt>
                    <dd>
                      양초 · Ø
                      {((profile?.payload.surface.radius_mm ?? 34) * 2).toFixed(
                        1,
                      )}{" "}
                      × H{profile?.payload.surface.height_mm ?? 150} mm
                    </dd>
                  </div>
                  <div>
                    <dt>도구</dt>
                    <dd>고정 드릴</dd>
                  </div>
                  <div>
                    <dt>이미지 처리</dt>
                    <dd>
                      {isRos ? "첨부 이미지 중심선 변환" : "모의 중심선 샘플"}
                    </dd>
                  </div>
                </dl>
                <div className="subtext">
                  {isRos
                    ? "시험 설정 · 실제 이미지 계산 · 로봇 구동 없음"
                    : "명목 규격 · 실제 이미지 변환 연결 전"}
                </div>
                <div className="rule" />
                <h3>도안 배치</h3>
                <div className="placement-fields">
                  {(
                    [
                      ["width_mm", "가로", "mm"],
                      ["height_mm", "세로", "mm"],
                      ["offset_u_mm", "중심 U", "mm"],
                      ["offset_v_mm", "중심 V (바닥 ↑)", "mm"],
                      ["rotation_deg", "회전", "°"],
                    ] as const
                  ).map(([key, label, unit]) => (
                    <label key={key}>
                      <span>{label}</span>
                      <div className="unit-input">
                        <input
                          aria-label={label}
                          type="number"
                          value={draft[key]}
                          disabled={locked}
                          step={key === "rotation_deg" ? 1 : 0.1}
                          min={
                            key === "width_mm" || key === "height_mm"
                              ? 1
                              : key === "rotation_deg"
                                ? -180
                                : -250
                          }
                          max={key === "rotation_deg" ? 180 : 500}
                          onChange={(e) => field(key, e.target.valueAsNumber)}
                        />
                        <span>{unit}</span>
                      </div>
                    </label>
                  ))}
                </div>
                <label className="check-row ratio-check">
                  <input
                    type="checkbox"
                    checked={ratio}
                    disabled={locked}
                    onChange={(e) => setRatio(e.target.checked)}
                  />
                  비율 유지
                </label>
                <p className="field-help">
                  {baseXOrigin
                    ? "U=0은 base +X 방향입니다."
                    : "U=0은 앞면 중심입니다."}
                  <br />
                  크기·위치 변경 후 경로를 다시 생성하세요.
                  {isRos && (
                    <>
                      <br />
                      가로·세로 안에 중심선 비율을 유지해 맞춥니다. 편집 중
                      표시는 참고용입니다.
                    </>
                  )}
                </p>
                <button
                  className="primary generate-button"
                  onClick={generate}
                  disabled={
                    !asset ||
                    !profile ||
                    !pathReady ||
                    uploading ||
                    generating ||
                    serverGenerating ||
                    preparationBlocked ||
                    locked ||
                    draft.width_mm <= 0 ||
                    draft.height_mm <= 0
                  }
                >
                  {generating ? (
                    <LoaderCircle size={17} className="spin" />
                  ) : (
                    <ArrowRight size={17} />
                  )}{" "}
                  {generating
                    ? stageNames[generation?.stage || "CONVERTING"]
                    : result
                      ? "경로 다시 생성"
                      : "경로 생성"}
                </button>
                {isRos && (
                  <p className="field-help">
                    영역 기준과 현재 경로 프로파일이 다르면 전개면 아래에
                    표시됩니다. 경로 생성은 현재 프로파일의 제한을 적용합니다.
                  </p>
                )}
                {profile && (
                  <p className="field-help">
                    윗면 기준 중심 v ↓ ={" "}
                    {mm(
                      topToBottom(
                        profile.payload.surface.height_mm,
                        draft.offset_v_mm,
                      ),
                    )}{" "}
                    mm. V = 높이 − v이며, 경로 요청에는 바닥 기준 V를
                    전달합니다.
                  </p>
                )}
                {generating && (
                  <div className="progress-track">
                    <div
                      style={{ width: `${(generation?.progress || 0) * 100}%` }}
                    />
                  </div>
                )}
              </section>
              <UnwrappedPreview
                profile={profile}
                workAreaPolicy={snapshot?.work_area_policy}
                draft={draft}
                result={result}
                asset={asset}
                stale={stale}
                locked={locked}
                onChange={edit}
              />
              <div className="right-stack">
                <CylinderPreview
                  result={result}
                  stale={stale}
                  profile={profile}
                />
                <section className="panel execution-panel">
                  <div className="panel-heading">
                    <h2>실행 준비</h2>
                    <span className="tag">
                      {busy
                        ? "공정 진행"
                        : currentResult
                          ? "확인 대기"
                          : "경로 대기"}
                    </span>
                  </div>
                  <dl className="readiness">
                    <div>
                      <dt>경로 검증</dt>
                      <dd className={currentResult ? "green-text" : ""}>
                        {currentResult ? (
                          <>
                            <CheckCircle2 size={14} />
                            {result?.test_only
                              ? "기하 검사 통과 · 실기 미검증"
                              : "모의 범위 확인"}
                          </>
                        ) : stale ? (
                          "재생성 필요"
                        ) : (
                          "미생성"
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>선택 도구</dt>
                      <dd>고정 드릴</dd>
                    </div>
                    <div>
                      <dt>장착 도구</dt>
                      <dd>
                        {fresh && snapshot?.state?.mounted_tool_id
                          ? `${snapshot.state.mounted_tool_id} · ${snapshot.state.tool_confirmation_source || "UNKNOWN"}`
                          : "장착 관측 미확인"}
                      </dd>
                    </div>
                    <div>
                      <dt>공정 상태</dt>
                      <dd>
                        <i className="status-dot" />
                        {run
                          ? statusNames[run.status]
                          : fresh
                            ? statusNames[snapshot?.state?.status || ""] ||
                              snapshot?.state?.status ||
                              "미확인"
                            : "미확인"}
                      </dd>
                    </div>
                  </dl>
                  <div className="rule" />
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={reviewed}
                      disabled={!currentResult || locked}
                      onChange={(e) => setReviewed(e.target.checked)}
                    />
                    도안 위치와 경로를 확인했습니다.
                  </label>
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={fixture}
                      disabled={
                        !currentResult ||
                        locked ||
                        !capabilities?.execution_enabled
                      }
                      onChange={(e) => setFixture(e.target.checked)}
                    />
                    지정 위치의 공작물 고정을 확인했습니다.
                  </label>
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={drillOn}
                      disabled={!drillKey || !capabilities?.execution_enabled}
                      onChange={(e) =>
                        setDrillConfirmation(e.target.checked ? drillKey : null)
                      }
                    />
                    드릴을 수동으로 켰습니다. (화면 확인 전용)
                  </label>
                  <p className="field-help">
                    이 체크는 드릴 전원 센서나 제어 명령이 아닙니다.
                    취소·오류·작업 종료 후에는 드릴을 수동으로 꺼주세요.
                  </p>
                  <button
                    className="primary start-button"
                    disabled={startUncertain ? pending : !canStart}
                    onClick={startRun}
                  >
                    {pending ? (
                      <LoaderCircle size={17} className="spin" />
                    ) : (
                      <ArrowRight size={17} />
                    )}{" "}
                    {startUncertain ? "같은 실행 요청 다시 확인" : "시작 요청"}
                  </button>
                  <p className="field-help">
                    {capabilities?.execution_block_reason ||
                      "확인 후 요청 가능 · 공정 제어에서 준비 조건 재검사"}
                    {!!result?.validation_not_checked?.length && (
                      <>
                        <br />
                        미검사: {result.validation_not_checked.join(", ")}
                      </>
                    )}
                  </p>
                </section>
              </div>
            </div>
          )}
          {nav === "process" && (
            <section className="process-layout">
              <section
                className={`panel process-overview ${run ? "has-live-path" : ""}`}
              >
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">CURRENT PROCESS</span>
                    <h2>현재 공정</h2>
                  </div>
                  <span className="tag">
                    {run ? short(run.run_id) : "활성 실행 없음"}
                  </span>
                </div>
                <div className="process-status">
                  <div className="process-orbit">
                    <Activity size={42} strokeWidth={1} />
                  </div>
                  <div>
                    <span>
                      {run?.phase
                        ? phaseNames[run.phase]
                        : "작업을 준비해 주세요"}
                    </span>
                    <h2>{run ? statusNames[run.status] : "공정 대기"}</h2>
                    <p>
                      {run?.message ||
                        "작업 준비에서 경로를 생성하고 확인한 뒤 실행을 요청합니다."}
                    </p>
                  </div>
                  <strong className="percent">
                    {Math.round((run?.engraving_progress || 0) * 100)}
                    <small>%</small>
                  </strong>
                </div>
                <div className="progress-track big">
                  <div
                    style={{
                      width: `${(run?.engraving_progress || 0) * 100}%`,
                    }}
                  />
                </div>
                <div className="process-meta">
                  <span>조각 구간 진행률 · 이탈/검사와 별도</span>
                  <span>{Math.floor(run?.elapsed_s || 0)}초 경과</span>
                </div>
                {run && (
                  <LivePathPreview
                    path={executionPath}
                    run={run}
                    profile={profile}
                    fresh={!!fresh}
                  />
                )}
                <div className="phase-grid">
                  {Object.entries(phaseNames).map(([key, name], i) => (
                    <div
                      key={key}
                      className={run?.phase === key ? "current" : ""}
                    >
                      <span>{String(i + 1).padStart(2, "0")}</span>
                      <b>{name}</b>
                      <small>{key}</small>
                    </div>
                  ))}
                </div>
                <div className="process-facts">
                  <div>
                    <span>선택 / 장착 도구</span>
                    <b>
                      고정 드릴 /{" "}
                      {snapshot?.state?.mounted_tool_id
                        ? "모의 확인"
                        : "미확인"}
                    </b>
                  </div>
                  <div>
                    <span>확인 출처</span>
                    <b>
                      {snapshot?.state?.tool_confirmation_source || "UNKNOWN"}
                    </b>
                  </div>
                  <div>
                    <span>정지 상태</span>
                    <b>{run?.stop_state || "NONE"}</b>
                  </div>
                  <div>
                    <span>경로 버전</span>
                    <b>
                      {short(run?.path_id)}{" "}
                      {run ? `· v${run.path_version}` : ""}
                    </b>
                  </div>
                </div>
                <div className="monitoring-note">
                  <ShieldCheck size={20} />
                  <div>
                    <b>실제 장비의 센서값은 연결되지 않았습니다.</b>
                    <p>
                      모의 단계와 이벤트로 화면을 검증합니다. TCP·관절·온도는
                      미지원 상태입니다.
                    </p>
                  </div>
                </div>
                {!busy && (
                  <button
                    className="secondary"
                    onClick={() => setNav(run ? "history" : "prepare")}
                  >
                    {run ? "실행 이력에서 검사 기록" : "작업 준비로 이동"}
                    <ArrowRight size={16} />
                  </button>
                )}
              </section>
              <section className="panel timeline-panel">
                <div className="panel-heading">
                  <h2>공정 이벤트</h2>
                  <Radio size={17} />
                </div>
                <EventList snapshot={snapshot} />
              </section>
            </section>
          )}
          {nav === "history" && (
            <section className="panel history-panel">
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">PROCESS ARCHIVE</span>
                  <h2>
                    실행 기록 <span className="muted">{runs.length}</span>
                  </h2>
                </div>
                <button
                  className="secondary compact"
                  onClick={() =>
                    request<Run[]>("/runs")
                      .then(setRuns)
                      .catch((e) => setError(e.message))
                  }
                >
                  <RotateCcw size={14} />
                  새로고침
                </button>
              </div>
              {!runs.length ? (
                <Empty
                  title="아직 실행 기록이 없습니다."
                  text="모의 공정을 시작하면 사용한 경로와 결과가 이곳에 남습니다."
                />
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>실행 / 시각</th>
                      <th>경로 버전</th>
                      <th>결과</th>
                      <th>단계</th>
                      <th>조각 진행</th>
                      <th>검사</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr key={r.run_id}>
                        <td>
                          <b>{short(r.run_id)}</b>
                          <small>
                            {new Date(r.created_at).toLocaleString("ko-KR")}
                          </small>
                        </td>
                        <td>
                          {short(r.path_id)} · v{r.path_version}
                        </td>
                        <td>
                          <span
                            className={`tag ${r.status === "FAILED" || r.status === "UNKNOWN" ? "amber" : ""}`}
                          >
                            {statusNames[r.status]}
                          </span>
                        </td>
                        <td>{phaseNames[r.phase] || r.phase}</td>
                        <td>
                          {Math.round((r.engraving_progress || 0) * 100)}%
                        </td>
                        <td>
                          <button
                            className="text-button"
                            onClick={() =>
                              request<Run>(`/runs/${r.run_id}`)
                                .then((d) => {
                                  setDetail(d);
                                  setReason("");
                                })
                                .catch((e) => setError(e.message))
                            }
                          >
                            상세·검사
                            <ChevronRight size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}
          {nav === "alarms" && (
            <section className="panel history-panel">
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">ALARMS & EVENTS</span>
                  <h2>알람 기록</h2>
                </div>
                <span className="tag">{alarms.length}건</span>
              </div>
              {!alarms.length ? (
                <Empty
                  title="기록된 알람이 없습니다."
                  text="모의 도구 확인 실패·정지 확인 불가 시나리오로 알람을 확인할 수 있습니다."
                />
              ) : (
                <div className="alarm-list">
                  {alarms.map((a) => (
                    <div key={a.event_id}>
                      <Bell size={20} />
                      <div>
                        <b>{a.code}</b>
                        <p>{a.message}</p>
                      </div>
                      <time>{timeLabel(a.occurred_at)}</time>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}
          {nav === "settings" && (
            <div className="settings-grid">
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">PROFILE SNAPSHOT</span>
                    <h2>등록 설정</h2>
                  </div>
                  <Settings2 size={18} />
                </div>
                <dl className="settings-list">
                  <div>
                    <dt>작업대상</dt>
                    <dd>
                      양초 · Ø
                      {((profile?.payload.surface.radius_mm ?? 34) * 2).toFixed(
                        1,
                      )}{" "}
                      × H{profile?.payload.surface.height_mm ?? 150} mm
                    </dd>
                  </div>
                  <div>
                    <dt>U 범위</dt>
                    <dd>
                      ±
                      {(
                        (profile?.payload.surface.radius_mm ?? 34) * Math.PI
                      ).toFixed(2)}{" "}
                      mm / {baseXOrigin ? "U=0은 base +X" : "중심 0°"}
                    </dd>
                  </div>
                  <div>
                    <dt>옆면 배치 범위</dt>
                    <dd>
                      360° · V=0 ~ {profile?.payload.surface.height_mm ?? 150}{" "}
                      mm
                    </dd>
                  </div>
                  <div>
                    <dt>작업 영역 기준과 적용 상태</dt>
                    <dd>
                      <WorkAreaSummary
                        profile={profile}
                        policy={snapshot?.work_area_policy}
                      />
                    </dd>
                  </div>
                  <div>
                    <dt>도구 / 제어기 TCP</dt>
                    <dd>engraving_drill / GripperDA_v1</dd>
                  </div>
                  <div>
                    <dt>장착 정책</dt>
                    <dd>철사 고정 · 그리퍼 열기 금지</dd>
                  </div>
                  <div>
                    <dt>TCP 기준점</dt>
                    <dd>그리퍼 끝점</dd>
                  </div>
                  <div>
                    <dt>경로 기준점</dt>
                    <dd>드릴 끝 · m / quaternion xyzw</dd>
                  </div>
                  <div>
                    <dt>스냅샷 ID</dt>
                    <dd className="mono">{profile?.id}</dd>
                  </div>
                  <div>
                    <dt>실측·현장 설정</dt>
                    <dd>팀 확인 대기</dd>
                  </div>
                </dl>
                <div className="info-box">
                  {snapshot?.source_mode === "REAL"
                    ? "아래 경로 시험 프로파일은 REAL 준비에 사용하지 않습니다. 실제 준비 설정은 준비 패널의 입력 설정 ID/원본을 확인하세요."
                    : profile?.payload.note ||
                      "c2_path가 제공하는 불변 시험 프로파일입니다. 기하 검증 합격은 실기 실행 승인이 아닙니다."}
                  <br />
                  그리퍼 TCP와 드릴 끝의 변환은 robot_adapter 책임입니다.
                </div>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">
                      {snapshot?.source_mode === "REAL"
                        ? "REAL PREPARATION"
                        : "SIMULATION LAB"}
                    </span>
                    <h2>
                      {snapshot?.source_mode === "REAL"
                        ? "REAL 준비 연결"
                        : isRos
                          ? "ROS 경로 연결"
                          : "모의 시나리오"}
                    </h2>
                  </div>
                  <Activity size={18} />
                </div>
                <p className="section-copy">
                  {snapshot?.source_mode === "REAL"
                    ? "실제 공정 노드의 상태와 측정 결과를 받습니다. 경로 생성·조각·모의 상태 변경은 차단합니다."
                    : isRos
                      ? "경로 노드의 실제 계산 결과를 표시합니다. 공정 실행과 모의 상태 변경은 사용하지 않습니다."
                      : "가짜 상대 응답을 바꾸어 HMI의 오류·정지 표시를 확인합니다."}
                </p>
                {!isRos && (
                  <div className="scenario-options">
                    {Object.entries(scenarios).map(([value, label]) => (
                      <button
                        key={value}
                        className={
                          snapshot?.scenario === value ? "selected" : ""
                        }
                        disabled={busy || generating}
                        onClick={() => changeScenario(value)}
                      >
                        <span>{label}</span>
                        {snapshot?.scenario === value ? (
                          <CheckCircle2 size={17} />
                        ) : (
                          <ChevronRight size={17} />
                        )}
                      </button>
                    ))}
                  </div>
                )}
                <div className="info-box">
                  현재 통신: {snapshot?.transport || "연결 대기"}
                  <br />
                  미리보기 계약: {capabilities?.preview_contract || "확인 중"}
                  <br />
                  변환 방식: {capabilities?.preset || "확인 중"}
                  <br />
                  실제 로봇 명령은 발행하지 않습니다.
                </div>
                {!isRos && (
                  <button className="secondary" onClick={resetSimulation}>
                    <RotateCcw size={15} />
                    모의 상태 초기화
                  </button>
                )}
                {!isRos && (
                  <p className="field-help">
                    작업 종료 후 사용 · 실행 이력과 파일은 보존됩니다.
                  </p>
                )}
              </section>
            </div>
          )}
        </div>
        <footer className="event-footer">
          <b>최근 이벤트</b>
          <div>
            {snapshot?.events.slice(0, 3).map((e) => (
              <span key={e.event_id}>
                <CheckCircle2 size={15} />
                <em>{e.message}</em>
                <time>{timeLabel(e.occurred_at)}</time>
              </span>
            )) || <span>서버 연결을 기다립니다.</span>}
          </div>
          <small>
            <span className={connected ? "live-dot" : "offline-dot"} />
            {connected ? "서버 연결" : "서버 미연결"}
          </small>
        </footer>
      </main>
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={18} />
          {toast}
        </div>
      )}
      {detail && (
        <div className="modal-backdrop" onClick={() => setDetail(null)}>
          <section
            className="inspection-modal panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="inspection-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="panel-heading">
              <h2 id="inspection-title">실행 상세·검사</h2>
              <button
                aria-label="상세 닫기"
                className="icon-button"
                onClick={() => setDetail(null)}
              >
                <X size={20} />
              </button>
            </div>
            <p className="mono">{detail.run_id}</p>
            <div className="info-box">
              {statusNames[detail.status]} · {detail.message}
              <br />
              경로 {short(detail.path_id)} · v{detail.path_version}
            </div>
            <h3>검사 기록</h3>
            {detail.inspections?.length ? (
              detail.inspections.map((i) => (
                <div className="inspection-record" key={i.id}>
                  <b>{i.verdict}</b>
                  <span>{i.reason}</span>
                  <small>{timeLabel(i.created_at)}</small>
                </div>
              ))
            ) : (
              <p className="muted">아직 검사 기록이 없습니다.</p>
            )}
            {["SUCCEEDED", "FAILED", "STOPPED"].includes(detail.status) && (
              <>
                <label className="stacked-label">
                  판정
                  <select
                    value={verdict}
                    onChange={(e) => setVerdict(e.target.value)}
                  >
                    <option value="PASS">PASS · 합격</option>
                    <option value="HOLD">HOLD · 보류</option>
                    <option value="REJECT">REJECT · 불합격</option>
                  </select>
                </label>
                <label className="stacked-label">
                  검사 근거
                  <textarea
                    value={reason}
                    maxLength={500}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="확인한 결과와 판단 근거를 남겨주세요."
                  />
                </label>
                <button
                  className="primary"
                  disabled={!reason.trim()}
                  onClick={inspect}
                >
                  검사 기록 저장
                </button>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function EventList({ snapshot }: { snapshot: Snapshot | null }) {
  return (
    <div className="timeline">
      {snapshot?.events.slice(0, 14).map((e) => (
        <div key={e.event_id}>
          <i className={e.severity === "ERROR" ? "danger" : ""} />
          <div>
            <time>{timeLabel(e.occurred_at)}</time>
            <b>{e.message}</b>
            <small>{e.phase ? phaseNames[e.phase] : e.event_type}</small>
          </div>
        </div>
      ))}
      {!snapshot?.events.length && (
        <p className="muted">아직 이벤트가 없습니다.</p>
      )}
    </div>
  );
}
function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <Clock3 size={40} strokeWidth={1} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
