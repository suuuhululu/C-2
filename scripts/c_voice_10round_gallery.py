"""c_voice_10round_e2e.py 결과(HMI 캡처 PNG) gallery. production 코드 미사용.

  python3 scripts/c_voice_10round_gallery.py [--mode paired|v1|v2] [--out ~/c_voice_e2e_10runs] [--rounds 5]
키: Space / → 다음, ← 이전, Esc / X 종료. 제목에 Round·버전·설계 이름·selected family·blocks·red·1x2x1·max layer·validator,
v2는 Current preserved·judge verdict·v2 total latency까지 표시한다(metadata.json 키 기준).
"""
import argparse
import json
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow


def collect(out, rounds, mode):
    items = []
    for k in range(1, rounds + 1):
        rdir = os.path.join(out, f"round{k:02d}")
        meta = json.load(open(os.path.join(rdir, "metadata.json"))) if os.path.exists(os.path.join(rdir, "metadata.json")) else {}
        for ver in (("v1", "v2") if mode == "paired" else (mode,)):
            png = os.path.join(rdir, f"{ver}_hmi.png")
            if not os.path.exists(png):
                continue
            m = meta.get(ver) or {}; j = m.get("judge") or {}; sc = meta.get("scenario") or {}; sh = m.get("shape") or {}
            family = m.get("selected_family") if ver == "v1" else (j.get("design_family") or m.get("design_family"))
            title = f"Round {k} · {ver} · {m.get('design_name')} [{family}]"
            title += (f" · blocks {sh.get('blocks')} · red {sh.get('red')} · 1x2x1 {sh.get('1x2x1')} · max layer {sh.get('max_layer')}"
                      f" · validator {'PASS' if m.get('validator') == [] else 'FAIL'}")
            if ver == "v2":
                title += (f" · {sc.get('id')} · preserved {m.get('preserved')} · {j.get('verdict')} · regen {m.get('regenerations')}"
                          f" · {m.get('total_latency_s', m.get('seconds'))} s")
            items.append((title, png))
    return items


class Gallery(QMainWindow):
    def __init__(self, items):
        super().__init__()
        self.items, self.i = items, 0
        self.label = QLabel(); self.label.setAlignment(Qt.AlignCenter); self.setCentralWidget(self.label)
        self.resize(1000, 1000); self.show_item()

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
    ap.add_argument("--mode", choices=("paired", "v1", "v2"), default="paired")
    ap.add_argument("--out", default=os.path.expanduser("~/c_voice_e2e_10runs")); ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()
    items = collect(args.out, args.rounds, args.mode)
    if not items:
        sys.exit(f"no captures under {args.out}")
    app = QApplication.instance() or QApplication([])
    g = Gallery(items); g.show()
    app.exec_()


if __name__ == "__main__":
    main_cli()
