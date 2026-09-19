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

const navItems = [
  { id: "prepare", name: "작업 준비", icon: FileImage },
  { id: "process", name: "공정 관제", icon: Activity },
  { id: "history", name: "실행 이력", icon: History },
  { id: "alarms", name: "알람", icon: Bell },
  { id: "settings", name: "설정 정보", icon: Settings2 },
];
const scenarios: Record<string, string> = {
  normal: "정상 공정",
  generation_failure: "경로 검증 실패",
  grip_failure: "도구 확인 실패",
  cut_quality_failure: "모의 압력 확인 실패",
  stop_unknown: "정지 확인 불가",
  communication_loss: "상태 통신 단절",
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
  const [uploading, setUploading] = useState(false),
    [generation, setGeneration] = useState<Generation | null>(null),
    [generating, setGenerating] = useState(false);
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
  const run = snapshot?.active_run;
  const fresh = connected && snapshot?.connection === "CONNECTED";
  const busy = active(run),
    locked = busy || pending || startUncertain;
  const profile = snapshot?.profile;
  const currentResult =
    !!result && !stale && result.preview.profile_snapshot_id === profile?.id;
  const canStart =
    currentResult &&
    reviewed &&
    fixture &&
    fresh &&
    !busy &&
    !pending &&
    !generating &&
    !snapshot?.storage_error;

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
          if (packet.type === "snapshot" && packet.data.schema_version === 1) {
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
    if (!asset || !profile || generating) return;
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
            schema_version: 1,
            request_id: crypto.randomUUID(),
            source_mode: "SIMULATION",
            asset_id: asset.asset_id,
            asset_sha256: asset.asset_sha256,
            ...draft,
            conversion_preset: "simulation_centerline",
            tool_id: profile.payload.tool_id,
            profile_snapshot_id: profile.id,
            profile_sha256: profile.sha256,
          };
    generationRequest.current = { body, revision: rev };
    try {
      let g = await request<Generation>("/path-generations", body);
      const start = Date.now();
      while (live.current && !["SUCCEEDED", "FAILED"].includes(g.state)) {
        setGeneration(g);
        if (Date.now() - start > 125000)
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
        throw new Error(g.result?.message || "경로를 생성하지 못했습니다.");
      }
      const p = await request<PathResult>(
        `/paths/${g.result.path_id}/versions/${g.result.path_version}`,
      );
      if (
        p.preview.contract !== "mock-preview/1" ||
        p.preview.path_id !== p.path_id ||
        p.preview.path_sha256 !== p.path_sha256 ||
        p.preview.path_version !== p.path_version
      )
        throw new Error("미리보기와 경로의 계약·버전이 일치하지 않습니다.");
      if (revision.current !== rev) {
        setToast("이전 입력의 생성이 끝났습니다. 현재 배치로 다시 생성하세요.");
        return;
      }
      setResult(p);
      setStale(false);
      setToast("모의 경로를 준비했습니다. 두 미리보기를 확인해 주세요.");
      generationRequest.current = null;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  }
  async function startRun() {
    if (!result) return;
    setPending(true);
    setError("");
    if (!startBody.current)
      startBody.current = {
        schema_version: 1,
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
    if (!run) return;
    setStopPending(true);
    setError("");
    if (stopId.current?.run !== run.run_id)
      stopId.current = { run: run.run_id, id: crypto.randomUUID() };
    try {
      const response = await request<{ message: string }>(
        `/runs/${run.run_id}/stop`,
        {
          schema_version: 1,
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
            SIMULATION
          </span>
          <div className={`connection ${fresh ? "online" : "offline"}`}>
            {fresh ? <Wifi size={16} /> : <WifiOff size={16} />}
            <span>{fresh ? "모의 통신 연결" : "통신 미확인"}</span>
          </div>
          <span className="physical-state">실기 미연결</span>
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
                  : nav === "process"
                    ? "준비부터 반납까지, 공정의 흐름을 확인합니다."
                    : nav === "history"
                      ? "각 실행에 사용한 경로와 결과를 함께 보관합니다."
                      : nav === "alarms"
                        ? "발생한 문제와 확인할 내용을 기록합니다."
                        : "현재 사용하는 모의 프로파일과 연결 정보를 확인합니다."}
              </p>
            </div>
            {nav === "prepare" ? (
              <div className="stepper">
                {["이미지·설정", "경로 생성", "미리보기 확인", "실행 요청"].map(
                  (s, i) => {
                    const step = !asset
                      ? 0
                      : !currentResult
                        ? 1
                        : !reviewed
                          ? 2
                          : 3;
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
                  },
                )}
              </div>
            ) : (
              <span className="tag">
                SIMULATION · {snapshot?.transport || "연결 대기"}
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
              최신 공정 상태를 확인할 수 없습니다. 시작 요청이 차단됩니다.
              저장된 상태는 실제 정지 확인을 뜻하지 않습니다.
            </div>
          )}
          {snapshot?.storage_error && (
            <div className="error-banner" role="alert">
              {snapshot.storage_error}
            </div>
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
                  SVG 변환은 좌표 노드에서 처리합니다.
                </p>
                <div className="rule" />
                <h3>
                  작업 설정 <small className="muted">모의 프로파일</small>
                </h3>
                <dl className="work-settings">
                  <div>
                    <dt>작업대상</dt>
                    <dd>양초 · Ø68 × H150 mm</dd>
                  </div>
                  <div>
                    <dt>도구</dt>
                    <dd>조각칼 01</dd>
                  </div>
                  <div>
                    <dt>이미지 처리</dt>
                    <dd>모의 중심선 샘플</dd>
                  </div>
                </dl>
                <div className="subtext">
                  명목 규격 · 실제 이미지 변환 연결 전
                </div>
                <div className="rule" />
                <h3>도안 배치</h3>
                <div className="placement-fields">
                  {(
                    [
                      ["width_mm", "가로", "mm"],
                      ["height_mm", "세로", "mm"],
                      ["offset_u_mm", "중심 U", "mm"],
                      ["offset_v_mm", "중심 V", "mm"],
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
                  U=0은 앞면 중심입니다.
                  <br />
                  크기·위치 변경 후 경로를 다시 생성하세요.
                </p>
                <button
                  className="primary generate-button"
                  onClick={generate}
                  disabled={
                    !asset ||
                    !profile ||
                    uploading ||
                    generating ||
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
                            모의 범위 확인
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
                      <dd>조각칼 01</dd>
                    </div>
                    <div>
                      <dt>장착 도구</dt>
                      <dd>
                        {snapshot?.state?.mounted_tool_id
                          ? "조각칼 01 · 모의 확인"
                          : "미확인 · 집기 전"}
                      </dd>
                    </div>
                    <div>
                      <dt>공정 상태</dt>
                      <dd>
                        <i className="status-dot" />
                        {run ? statusNames[run.status] : "대기 IDLE"}
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
                      disabled={!currentResult || locked}
                      onChange={(e) => setFixture(e.target.checked)}
                    />
                    지정 위치의 공작물 고정을 확인했습니다.
                  </label>
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
                    확인 후 요청 가능 · 공정 제어에서 준비 조건 재검사
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
                  <span>조각 구간 진행률 · 반납/검사와 별도</span>
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
                  {Object.entries(phaseNames)
                    .filter(([key]) => key !== "CLEAN_TOOL")
                    .map(([key, name], i) => (
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
                      조각칼 01 /{" "}
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
                    <dd>파라핀 양초 · Ø68 × H150 mm</dd>
                  </div>
                  <div>
                    <dt>U 범위</dt>
                    <dd>−106.81 ~ +106.81 mm / 중심 0°</dd>
                  </div>
                  <div>
                    <dt>모의 유효 높이</dt>
                    <dd>10 ~ 140 mm · 실측값 아님</dd>
                  </div>
                  <div>
                    <dt>도구 / 제어기 TCP</dt>
                    <dd>engraving_knife / GripperDA_v1</dd>
                  </div>
                  <div>
                    <dt>TCP 기준점</dt>
                    <dd>그리퍼 끝점</dd>
                  </div>
                  <div>
                    <dt>경로 기준점</dt>
                    <dd>칼끝 · m / quaternion xyzw</dd>
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
                  {profile?.payload.note}
                  <br />
                  그리퍼 TCP와 칼끝의 변환은 robot_adapter 책임입니다.
                </div>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">SIMULATION LAB</span>
                    <h2>모의 시나리오</h2>
                  </div>
                  <Activity size={18} />
                </div>
                <p className="section-copy">
                  가짜 상대 응답을 바꾸어 HMI의 오류·정지 표시를 확인합니다.
                </p>
                <div className="scenario-options">
                  {Object.entries(scenarios).map(([value, label]) => (
                    <button
                      key={value}
                      className={snapshot?.scenario === value ? "selected" : ""}
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
                <div className="info-box">
                  현재 통신: {snapshot?.transport || "연결 대기"}
                  <br />
                  미리보기 계약: mock-preview/1 · 좌표 담당 PR 반영 대기
                  <br />
                  실제 로봇 명령은 발행하지 않습니다.
                </div>
                <button className="secondary" onClick={resetSimulation}>
                  <RotateCcw size={15} />
                  모의 상태 초기화
                </button>
                <p className="field-help">
                  작업 종료 후 사용 · 실행 이력과 파일은 보존됩니다.
                </p>
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
            <span className={fresh ? "live-dot" : "offline-dot"} />
            {fresh ? "LIVE" : "OFFLINE"}
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
