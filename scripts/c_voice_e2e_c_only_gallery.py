"""c_voice_e2e_c_only.py 결과(Round 화면 PNG) gallery. production 코드 미사용.

  python3 scripts/c_voice_e2e_c_only_gallery.py [--out ~/c_voice_e2e_c_only] [--rounds 5]
Round마다 roundNN/screen.png([v1 | Current+Difference | v2]), 없으면 v1.png를 보여 준다.
키: Space / → 다음, ← 이전, Esc / X / Q 종료. 제목에 §12 항목(Initial raw STT·mode·family/concept·v1 blocks/red/1x2x1/
max layer/validator·Intervention 결과·style_hint·Current preserved·v2 blocks/red/1x2x1/max layer/validator·judge verdict·
지연 시간)을 metadata.json에서 읽어 넣는다.
"""
import argparse
import json
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow


def _counts(sh):
    return f"{sh.get('blocks')}/{sh.get('red')}/{sh.get('1x2x1')}/L{sh.get('max_layer')}" if sh else "-"


def _valid(reasons):
    return "-" if reasons is None else "PASS" if reasons == [] else "FAIL"


def _short(texts, limit=30):
    text = " / ".join(str(t) for t in texts or [])
    return text if len(text) <= limit else text[:limit] + "…"


def collect(out, rounds):
    items = []
    for k in range(1, rounds + 1):
        rdir = os.path.join(out, f"round{k:02d}")
        png = next((os.path.join(rdir, name) for name in ("screen.png", "v1.png") if os.path.exists(os.path.join(rdir, name))), None)
        if png is None:
            continue
        meta = {}
        if os.path.exists(os.path.join(rdir, "metadata.json")):
            with open(os.path.join(rdir, "metadata.json"), encoding="utf-8") as f:
                meta = json.load(f)
        v1, v2 = meta.get("v1") or {}, meta.get("v2") or {}
        it = v1.get("interpretation") or {}
        title = (f"Round {k} · {meta.get('status')} · STT {_short(v1.get('stt'))!r} · mode {it.get('mode')} · "
                 f"{('concept ' + str(it.get('concept'))) if it.get('concept') else ('family ' + str(v1.get('selected_family')))} · "
                 f"v1 {_counts(v1.get('shape'))} {_valid(v1.get('validator'))} {v1.get('seconds')}s")
        if v2:
            title += (f" · 답 {_short(v2.get('stt'), 20)!r} → {v2.get('hri_result')} · style_hint {v2.get('style_hint')} · "
                      f"preserved {v2.get('preserved')} · v2 {_counts(v2.get('shape'))} {_valid(v2.get('validator'))} · "
                      f"{v2.get('verdict')} · {v2.get('seconds')}s")
        items.append((title, png))
    return items


class Gallery(QMainWindow):
    def __init__(self, items):
        super().__init__()
        self.items, self.i = items, 0
        self.label = QLabel(); self.label.setAlignment(Qt.AlignCenter); self.setCentralWidget(self.label)
        self.resize(1600, 1000); self.show_item()

    def show_item(self):
        title, png = self.items[self.i]
        self.setWindowTitle(f"[{self.i + 1}/{len(self.items)}] {title}")
        self.label.setPixmap(QPixmap(png).scaled(self.label.size() if self.label.width() > 100 else self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        print(f"[{self.i + 1}/{len(self.items)}] {title}", flush=True)

    def resizeEvent(self, event):
        super().resizeEvent(event); self.show_item()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Space, Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter):
            self.i = (self.i + 1) % len(self.items); self.show_item()
        elif key in (Qt.Key_Left, Qt.Key_Backspace):
            self.i = (self.i - 1) % len(self.items); self.show_item()
        elif key in (Qt.Key_Escape, Qt.Key_X, Qt.Key_Q):
            self.close()


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/c_voice_e2e_c_only")); ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()
    items = collect(args.out, args.rounds)
    if not items:
        sys.exit(f"no captures under {args.out}")
    app = QApplication.instance() or QApplication([])
    g = Gallery(items); g.show()
    app.exec_()


if __name__ == "__main__":
    main_cli()
