import { useEffect, useRef, useState } from "react";
import { Download, Upload } from "lucide-react";
import { request, SCHEMA_VERSION } from "./api";
import type { Asset, PathResult, Placement } from "./api";
import { CylinderPreview, UnwrappedPreview } from "./Previews";
import { matchesPreview } from "./preview";

type RegisteredProfile = {
  id: string;
  sha256: string;
  payload: Record<string, unknown>;
};
type Profiles = { items: RegisteredProfile[]; selected_id: string | null };
type StoredPath = Pick<
  PathResult,
  "path_id" | "path_version" | "path_sha256" | "profile_snapshot"
>;

export default function FileIntegration({
  asset,
  placement,
  locked,
  onUpload,
  onChange,
}: {
  asset: Asset | null;
  placement: Placement;
  locked: boolean;
  onUpload: (file?: File) => Promise<void>;
  onChange: (placement: Placement) => void;
}) {
  const [profiles, setProfiles] = useState<Profiles>({
    items: [],
    selected_id: null,
  });
  const [paths, setPaths] = useState<StoredPath[]>([]);
  const [preview, setPreview] = useState<PathResult | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [download, setDownload] = useState<string | null>(null);
  const exportRequest = useRef<{ key: string; body: unknown } | null>(null);
  const selected = profiles.items.find((p) => p.id === profiles.selected_id);
  const disabled = locked || pending;

  async function refresh() {
    const [p, items] = await Promise.all([
      request<Profiles>("/integration/profiles"),
      request<StoredPath[]>("/integration/paths"),
    ]);
    setProfiles(p);
    setPaths(items);
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    setDownload(null);
  }, [asset?.asset_id, placement, profiles.selected_id]);

  async function perform(action: () => Promise<void>) {
    if (disabled) return;
    setPending(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }
  async function register(file?: File) {
    if (!file) return;
    await perform(async () => {
      const data = new FormData();
      data.append("file", file);
      await request("/integration/profiles", data);
      await refresh();
      setMessage(
        "스냅샷을 등록하고 선택했습니다. 공정 설정 검증은 별도로 필요합니다.",
      );
    });
  }
  async function select(id: string) {
    if (!id) return;
    await perform(async () => {
      await request(`/integration/profiles/${id}/select`, {});
      await refresh();
      setMessage("파일 교환에 사용할 스냅샷을 선택했습니다.");
    });
  }
  async function exportInput() {
    if (!asset || !selected) return;
    await perform(async () => {
      const key = JSON.stringify([asset.asset_id, selected.id, placement]);
      if (exportRequest.current?.key !== key) {
        exportRequest.current = {
          key,
          body: {
            schema_version: SCHEMA_VERSION,
            request_id: crypto.randomUUID(),
            source_mode: "SIMULATION",
            asset_id: asset.asset_id,
            asset_sha256: asset.asset_sha256,
            ...placement,
            conversion_preset: "raster_centerline_bezier",
            tool_id: "engraving_drill",
            profile_snapshot_id: selected.id,
            profile_sha256: selected.sha256,
          },
        };
      }
      const value = await request<{ download_url: string }>(
        "/integration/inputs",
        exportRequest.current.body,
      );
      setDownload(value.download_url);
      setMessage(
        "입력 묶음이 준비됐습니다. ZIP을 내려받아 경로 생성 담당자에게 전달하세요.",
      );
    });
  }
  async function showPath(path: StoredPath) {
    setPreview(null);
    const value = await request<PathResult>(
      `/paths/${path.path_id}/versions/${path.path_version}`,
    );
    if (!matchesPreview(value, "c2-path-preview/1") || !value.profile_snapshot)
      throw new Error("가져온 경로와 미리보기의 계약이 일치하지 않습니다.");
    setPreview(value);
  }
  async function importResult(file?: File) {
    if (!file) return;
    await perform(async () => {
      setPreview(null);
      const data = new FormData();
      data.append("file", file);
      const path = await request<StoredPath>(
        "/integration/results",
        data,
        30000,
      );
      await refresh();
      await showPath(path);
      setMessage(
        "파일·참조 검증을 통과해 미리보기를 등록했습니다. 공정 실행은 아직 확인되지 않았습니다.",
      );
    });
  }

  return (
    <div className="integration-page">
      <p className="info-box">
        등록된 설정과 입력 이미지를 경로 생성 담당자에게 전달하고, 돌아온 결과를
        확인합니다. 파일 교환용 설정 선택은 기존 ROS·모의 생성 설정을 변경하지
        않습니다.
      </p>
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      {message && (
        <div className="info-box" role="status">
          {message}
        </div>
      )}
      <div className="integration-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>1. 공통 스냅샷 등록</h2>
            <span className="tag">SIMULATION</span>
          </div>
          <p className="field-help">
            JSON의 추가 필드는 그대로 보존합니다. 등록은 파일 보관 확인이며 공정
            계약의 승인·검증은 아닙니다.
          </p>
          <label
            className={`secondary integration-upload ${disabled ? "disabled" : ""}`}
          >
            <Upload size={16} /> 스냅샷 JSON 등록
            <input
              type="file"
              accept=".json,application/json"
              disabled={disabled}
              onChange={(e) => {
                register(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
          <label className="stacked-label">
            파일 교환에 사용할 스냅샷
            <select
              value={profiles.selected_id ?? ""}
              disabled={disabled}
              onChange={(e) => select(e.target.value)}
            >
              <option value="" disabled>
                스냅샷을 선택하세요
              </option>
              {profiles.items.map((p) => (
                <option key={p.id} value={p.id}>
                  {String(
                    p.payload.label ?? p.payload.contract ?? "등록 스냅샷",
                  )}{" "}
                  · {p.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {selected && (
            <>
              <dl className="integration-ids">
                <dt>스냅샷 ID</dt>
                <dd>{selected.id}</dd>
                <dt>SHA-256</dt>
                <dd>{selected.sha256}</dd>
              </dl>
              <a
                className="text-link"
                href={`/api/operator/assets/${selected.id}/content`}
                download="snapshot.json"
              >
                최종 저장 JSON 내려받기
              </a>
              <details>
                <summary>등록된 JSON 확인</summary>
                <pre>{JSON.stringify(selected.payload, null, 2)}</pre>
              </details>
            </>
          )}
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>2. 입력 묶음 전달</h2>
          </div>
          <p className="field-help">
            스냅샷·원본 이미지·생성 요청·파일 목록을 ZIP으로 내려받습니다.
          </p>
          <label
            className={`secondary integration-upload ${disabled ? "disabled" : ""}`}
          >
            <Upload size={16} />{" "}
            {asset ? "입력 이미지 변경" : "입력 이미지 첨부"}
            <input
              type="file"
              accept="image/png,image/jpeg"
              disabled={disabled}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                perform(() => onUpload(file));
              }}
            />
          </label>
          <p>
            {asset?.name ?? "작업 준비에서 첨부한 이미지도 사용할 수 있습니다."}
          </p>
          <div className="integration-placement">
            {(
              [
                ["width_mm", "도안 너비 (mm)"],
                ["height_mm", "도안 높이 (mm)"],
                ["offset_u_mm", "U 위치 (mm)"],
                ["offset_v_mm", "V 위치 (mm)"],
                ["rotation_deg", "회전 (°)"],
              ] as [keyof Placement, string][]
            ).map(([key, label]) => (
              <label className="stacked-label" key={key}>
                {label}
                <input
                  type="number"
                  step="0.1"
                  value={placement[key]}
                  disabled={disabled}
                  onChange={(e) => {
                    const value = e.target.valueAsNumber;
                    if (Number.isFinite(value))
                      onChange({ ...placement, [key]: value });
                  }}
                />
              </label>
            ))}
          </div>
          <button
            className="primary"
            disabled={disabled || !asset || !selected}
            onClick={exportInput}
          >
            입력 묶음 준비
          </button>
          {download && (
            <a className="secondary" href={download} download>
              <Download size={16} /> 입력 ZIP 내려받기
            </a>
          )}
        </section>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>3. 결과 묶음 확인</h2>
          <span className="tag">미리보기 전용</span>
        </div>
        <p className="field-help">
          입력 묶음에 경로·SVG·미리보기·검증 보고서·결과를 추가한 ZIP을
          선택하세요. HMI 파일 교환 형식 c2-hmi-bundle/1을 사용합니다.
        </p>
        <label
          className={`secondary integration-upload ${disabled ? "disabled" : ""}`}
        >
          <Upload size={16} /> 결과 ZIP 가져오기
          <input
            type="file"
            accept=".zip,application/zip"
            disabled={disabled}
            onChange={(e) => {
              importResult(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
        <label className="stacked-label">
          등록된 결과
          <select
            disabled={disabled}
            value={preview ? `${preview.path_id}:${preview.path_version}` : ""}
            onChange={(e) => {
              const path = paths.find(
                (p) => `${p.path_id}:${p.path_version}` === e.target.value,
              );
              if (path) perform(() => showPath(path));
            }}
          >
            <option value="" disabled>
              결과를 선택하세요
            </option>
            {paths.map((p) => (
              <option
                key={`${p.path_id}:${p.path_version}`}
                value={`${p.path_id}:${p.path_version}`}
              >
                {p.path_id} · v{p.path_version}
              </option>
            ))}
          </select>
        </label>
        {preview && (
          <>
            <dl className="integration-ids">
              <dt>결과에 사용된 스냅샷 ID</dt>
              <dd>{preview.profile_snapshot?.id}</dd>
              <dt>경로 SHA-256</dt>
              <dd>{preview.path_sha256}</dd>
            </dl>
            <p>
              파일·참조 검증 통과 · 공정 실행 미확인 · 미검사:{" "}
              {preview.validation_not_checked?.join(", ") || "보고서 확인"}
            </p>
            <a
              className="secondary"
              href={`/api/operator/integration/paths/${preview.path_id}/versions/${preview.path_version}/bundle`}
              download
            >
              <Download size={16} /> 공정팀 전달 ZIP 내려받기
            </a>
            <a
              className="text-link"
              href={preview.validation_url}
              target="_blank"
              rel="noreferrer"
            >
              검증 보고서 보기
            </a>
          </>
        )}
      </section>
      {preview && (
        <div className="integration-grid">
          <UnwrappedPreview
            profile={preview.profile_snapshot}
            draft={preview.input}
            result={preview}
            asset={null}
            stale={false}
            locked={true}
            onChange={() => {}}
          />
          <CylinderPreview
            profile={preview.profile_snapshot}
            result={preview}
            stale={false}
          />
        </div>
      )}
    </div>
  );
}
