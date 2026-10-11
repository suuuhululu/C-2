"""C 단독 시험용 HMI 스타일 렌더러(표시 전용). A planner·Backend·contracts를 호출하지 않고 blocks만으로 그린다.

app/hmi_board.py의 BoardView(등받이 뒤쪽 시점 "24×24점 전체판·투영" + "완성 목표 확대")를 그대로 재사용하고,
층별 평면(L1~L5)과 metadata 줄을 PIL로 붙인다. Stage 2 어휘(red·1x2x1)는 이 프로세스 안에서만 hmi_board의 표시 함수를
바꿔 그린다(D 파일 수정 없음, Robot/조립 좌표 아님). 사람이 옮긴 블록(actual)은 표시 전용 색 "moved"(주황)로 강조한다.

  c_voice_e2e_c_only.py가 Round 중 v1·v2 직후 호출한다(즉시 표시).
  사후 재렌더: python3 scripts/c_design_hmi_render.py --out ~/c_voice_e2e_c_only
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.c_design import validator  # noqa: E402

COLOR_HEX = {"yellow": "#efc94b", "blue": "#699bde", "red": "#d9534f", "moved": "#ff8c1a"}
BRICK_DIMS = {"1x2x1": (1, 2), "2x2x1": (2, 2), "2x3x1": (2, 3)}
FIELDS = validator.BLOCK_FIELDS
_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
_FONT_R = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
_PATCHED = {"done": False}


def _font(bold, size):
    try:
        return ImageFont.truetype(_FONT if bold else _FONT_R, size, index=1)
    except OSError:
        return ImageFont.load_default()


def _patch_hmi_board():
    """표시 전용: hmi_board의 brick 크기·색 표를 Stage 2 어휘로 바꾼다(이 프로세스 안에서만)."""
    if _PATCHED["done"]:
        return
    from app import hmi_board
    from PyQt5.QtGui import QColor

    def dimensions(block):
        w, d = BRICK_DIMS[block["brick_type"]]
        return (d, w) if block["orientation_deg"] == 90 else (w, d)
    hmi_board.dimensions = dimensions
    original_brick = hmi_board.BoardView._brick

    def _brick(self, painter, block, project, scale):
        # 원래 함수는 yellow/blue 두 색만 안다. 색을 미리 계산해 QColor 생성 지점만 바꾼다.
        hex_color = COLOR_HEX.get(block["color"], "#999999")
        shown = dict(block, color="yellow" if hex_color == COLOR_HEX["yellow"] else "blue")
        saved = hmi_board.QColor
        hmi_board.QColor = lambda spec=None, *a, **k: QColor(hex_color) if spec in ("#efc94b", "#699bde") else QColor(spec, *a, **k)
        try:
            original_brick(self, painter, shown, project, scale)
        finally:
            hmi_board.QColor = saved
    hmi_board.BoardView._brick = _brick
    _PATCHED["done"] = True


def board_image(blocks, size=(1500, 600), current=None, expected=None):
    """BoardView 캡처 → PIL 이미지. current가 있으면 Current 실선 + expected 점선(assembly 모드)."""
    _patch_hmi_board()
    from PyQt5.QtCore import QBuffer, QIODevice
    from PyQt5.QtWidgets import QApplication
    from app.hmi_board import BoardView
    app = QApplication.instance() or QApplication([])
    view = BoardView(isometric=True)
    view.resize(*size)
    view.show()
    app.processEvents()
    if current is None:
        view.set_blocks(blocks)
    else:
        view.set_assembly({"current_revision": 1, "blocks": current}, expected)
    app.processEvents()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    view.grab().save(buf, "PNG")
    view.hide()
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGB")


def mini_layers(blocks, cell=7):
    """L1~MAX_LAYER 위에서 본 평면(+X 오른쪽 / +Y 위, 계약 좌표 그대로)."""
    pad, n_layers = 6, validator.MAX_LAYER
    size = len(validator.BOARD_RANGE) * cell
    img = Image.new("RGB", ((size + pad) * n_layers + pad, size + 40), "white")
    dr = ImageDraw.Draw(img)
    for layer in range(1, n_layers + 1):
        x0, y0 = pad + (layer - 1) * (size + pad), 32
        dr.rectangle([x0, y0, x0 + size, y0 + size], fill="#f4f6f8", outline="#bdc7d1")
        for b in blocks:
            if b["layer"] != layer:
                continue
            for px, py in validator.footprint(b):
                top = y0 + (validator.BOARD_RANGE[-1] - py) * cell
                dr.rectangle([x0 + px * cell, top, x0 + (px + 1) * cell - 1, top + cell - 1], fill=COLOR_HEX.get(b["color"], "#999999"))
        dr.text((x0, 4), f"L{layer} · {sum(1 for b in blocks if b['layer'] == layer)}", fill="black", font=_font(False, 19))
    return img


def _text_block(dr, x, y, lines, font, step):
    for i, line in enumerate(lines):
        dr.text((x, y + i * step), line, fill="black", font=font)
    return y + len(lines) * step


def compose_v1(title, blocks, lines, png_path):
    """v1 화면: 투영 + 완성 확대(위), 층별 평면(가운데), metadata 줄(아래)."""
    iso = board_image(blocks)
    mini = mini_layers(blocks)
    font_m = _font(False, 24)
    width = max(iso.width, mini.width + 20) + 40
    height = 60 + iso.height + 30 + mini.height + 30 + 32 * len(lines) + 30
    img = Image.new("RGB", (width, height), "white")
    dr = ImageDraw.Draw(img)
    dr.text((20, 12), title, fill="black", font=_font(True, 30))
    img.paste(iso, (20, 60))
    y = 60 + iso.height + 10
    dr.text((20, y), "층별 평면(L1~L5, +X 오른쪽 / +Y 위)", fill="#333333", font=_font(False, 19))
    img.paste(mini, (20, y + 24))
    _text_block(dr, 20, y + 24 + mini.height + 10, lines, font_m, 32)
    img.save(png_path)
    return img


def compose_v2(title, v1_blocks, current, expected, actual, v2_blocks, captions, lines, png_path):
    """v2 화면: [v1 | Current+Difference | v2] 같은 투영+확대 스타일, 아래에 v2 층별 평면과 metadata 줄."""
    size = (1150, 480)
    shown_current = [dict(b, color="moved") if all(b[f] == actual[f] for f in FIELDS) else b for b in current]
    panels = [board_image(v1_blocks, size), board_image(None, size, current=shown_current, expected=expected),
              board_image(v2_blocks, size) if v2_blocks else None]
    mini = mini_layers(v2_blocks) if v2_blocks else None
    font_cap, font_small, font_m = _font(False, 24), _font(False, 19), _font(False, 24)
    width = size[0] * 3 + 80
    height = 60 + size[1] + 110 + (mini.height + 40 if mini else 0) + 32 * len(lines) + 30
    img = Image.new("RGB", (width, height), "white")
    dr = ImageDraw.Draw(img)
    dr.text((20, 12), title, fill="black", font=_font(True, 30))
    for i, (panel, cap) in enumerate(zip(panels, captions)):
        x = 20 + i * (size[0] + 20)
        if panel is not None:
            img.paste(panel, (x, 60))
        else:
            dr.rectangle([x, 60, x + size[0], 60 + size[1]], outline="#bdc7d1")
            dr.text((x + 20, 80), "v2 없음", fill="gray", font=font_cap)
        for li, text in enumerate(cap):
            dr.text((x, 60 + size[1] + 8 + li * 28), text, fill="black", font=font_cap if li == 0 else font_small)
    y = 60 + size[1] + 110
    if mini:
        dr.text((20, y), "v2 층별 평면(L1~L5)", fill="#333333", font=font_small)
        img.paste(mini, (20, y + 24))
        y += mini.height + 40
    _text_block(dr, 20, y, lines, font_m, 32)
    img.save(png_path)
    return img


def counts_line(blocks):
    return (f"blocks {len(blocks)} · red {sum(b['color'] == 'red' for b in blocks)} · 1x2x1 {sum(b['brick_type'] == '1x2x1' for b in blocks)}"
            f" · max layer {max((b['layer'] for b in blocks), default=0)}")


def rerender_saved(out):
    """저장된 roundNN(v1.json·metadata.json·transcript.json·v2.json)을 다시 그린다(LLM 호출 없음)."""
    made = []
    for name in sorted(os.listdir(out)):
        rdir = os.path.join(out, name)
        if not (name.startswith("round") and os.path.exists(os.path.join(rdir, "v1.json"))):
            continue
        env1 = json.load(open(os.path.join(rdir, "v1.json")))
        meta = json.load(open(os.path.join(rdir, "metadata.json")))
        if not env1.get("design"):
            continue
        d1 = env1["design"]; m1 = env1.get("design_metadata") or {}
        lines = meta.get("screen_lines")
        if lines is None:  # Wave 4b 이전 저장분: runner의 같은 함수로 줄을 다시 만든다
            from c_voice_e2e_c_only import screen_lines
            lines = screen_lines(meta)
        made.append(compose_v1(f"Round {meta['round']} · v1 · {m1.get('design_name')}", d1["blocks"], lines, os.path.join(rdir, "v1.png")))
        v2_path = os.path.join(rdir, "v2.json")
        if os.path.exists(v2_path) and meta.get("scenario"):
            v2doc = json.load(open(v2_path)); env2 = v2doc["envelope"]; sc = meta["scenario"]; d2 = env2.get("design")
            m2 = env2.get("design_metadata") or {}
            caps = [[f"v1 · {m1.get('design_name')}", counts_line(d1["blocks"])],
                    ["Current + Difference", "실선: Current · 주황: 옮긴 블록(actual) · 점선: 원래 Design 위치(expected)"],
                    [f"v2 · {m2.get('design_name')}" if d2 else "v2 없음", counts_line(d2["blocks"]) if d2 else ""]]
            made.append(compose_v2(f"Round {meta['round']} · v1 | Current+Difference | v2", d1["blocks"], sc["current"], sc["expected"], sc["actual"],
                                   d2["blocks"] if d2 else None, caps, lines, os.path.join(rdir, "screen.png")))
        print("rendered", rdir, flush=True)
    return made


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/c_voice_e2e_c_only"))
    args = ap.parse_args()
    print("done", len(rerender_saved(os.path.expanduser(args.out))))
