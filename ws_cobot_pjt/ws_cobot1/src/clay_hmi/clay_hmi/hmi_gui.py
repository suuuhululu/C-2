# hmi_gui.py — HMI 화면 (수업 qt_hmi/hmi_gui.py 구조). clay_hmi.ui 를 uic.loadUi 로 읽는다.
# 화면: 전원/시작/긴급정지, 상태, 작업 설정(도형·크기·받침대·SVG), 측정 결과, 위에서 본 2D 미리보기(지점토·도안·손끝),
#       확인/취소, 노드 로그. 좌표계: 화면 위 = base +X (로봇 앞), 화면 왼쪽 = base +Y.
import math
import os

from ament_index_python.packages import get_package_share_directory
from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPen, QBrush, QColor, QPainterPath, QFont, QPainter
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QGraphicsScene

from clay_carving.svg_design import load_svg, fit_to_box, stroke_length
from clay_carving import clay_heart as CH

PX_PER_MM = 3.0
SHAPES = ["flat_rect", "rect_column", "cylinder"]          # combo_shape 순서와 같다
FACES = ["top", "side"]                                     # combo_face 순서와 같다: 윗면 / 옆면


class RobotGUI(QtWidgets.QMainWindow):
    def __init__(self, hmi_ros2):
        super().__init__()
        ui_file = os.path.join(get_package_share_directory("clay_hmi"), "clay_hmi.ui")
        uic.loadUi(ui_file, self)
        self.node = hmi_ros2

        self.scene = QGraphicsScene(self)
        self.view_preview.setScene(self.scene)
        self.view_preview.setRenderHint(QPainter.Antialiasing)
        self.tcp_item = None
        self.svg_strokes = None                             # 선택한 SVG 원본 획 (SVG 단위)
        self.svg_name = ""
        self.measured = None                                # /clay/data 의 clay
        self.awl = None
        self.final_preview = None                           # 4번 노드가 보낸 실측 도안
        self.power_on = False
        self.open_prompt = None

        self.btn_power.clicked.connect(self.on_power)
        self.btn_start.clicked.connect(self.on_start)
        self.btn_estop.clicked.connect(self.on_estop)
        self.btn_svg.clicked.connect(self.choose_svg)
        self.btn_confirm.clicked.connect(lambda: self.on_confirm(True))
        self.btn_cancel.clicked.connect(lambda: self.on_confirm(False))
        for w in (self.spin_w, self.spin_h, self.spin_t, self.spin_stand):
            w.valueChanged.connect(self.redraw)
        self.combo_shape.currentIndexChanged.connect(self.on_shape_changed)
        self.combo_face.currentIndexChanged.connect(self.on_face_changed)
        for w in (self.spin_excl_top, self.spin_excl_bot, self.spin_angle, self.spin_zoff, self.spin_fill):
            w.valueChanged.connect(self.redraw)
        # 메뉴
        self.act_open_svg.triggered.connect(self.choose_svg)
        self.act_open_state.triggered.connect(self.load_last_state)
        self.act_quit.triggered.connect(self.close)
        self.act_bringup.triggered.connect(lambda: QMessageBox.information(self, "브링업 명령", " ".join(self.node.bringup_cmd())))
        self.act_reset_state.triggered.connect(self.reset_state)
        self.act_flow.triggered.connect(self.show_flow)
        self.act_about.triggered.connect(lambda: QMessageBox.about(self, "정보", "지점토 조각 관리자 HMI\nC그룹 2조 · Doosan M0609 + OnRobot RG2\nPyQt5 + ROS 2 Jazzy"))
        self.on_shape_changed()
        self.on_face_changed()
        self.chk_auto.toggled.connect(self.redraw)
        self.write_log("HMI 시작")
        self.redraw()
        self.node.set_gui(self)                             # 화면 요소가 다 만들어진 뒤에 연결 (상태 파일 결과 표시)

    # ---------------- 버튼 ----------------
    def on_power(self):
        on = self.node.toggle_power()
        self.update_power(on)

    def update_power(self, on):
        self.power_on = on
        self.btn_power.setText("전원 끄기 (브링업 종료)" if on else "전원 (브링업)")

    def on_start(self):
        job = self.current_job()
        if self.node.start_job(job):
            self.final_preview = None
            self.btn_confirm.setEnabled(False); self.btn_cancel.setEnabled(False)
            self.update_stage("스캔 중")

    def on_estop(self):
        self.node.emergency_stop()

    def on_confirm(self, ok):
        self.node.confirm(ok)
        self.btn_confirm.setEnabled(False); self.btn_cancel.setEnabled(False)

    def on_shape_changed(self, *_):
        flat = self.combo_shape.currentIndex() == 0
        self.combo_face.setEnabled(not flat)                 # 납작한 지점토는 윗면만
        if flat:
            self.combo_face.setCurrentIndex(0)
        self.label_w.setText("지름 [mm]" if self.combo_shape.currentIndex() == 2 else "가로 [mm]")
        if not flat and self.spin_t.value() < 30.0:
            self.spin_t.setValue(100.0)                        # 기둥·원통 기본 높이
        elif flat and self.spin_t.value() >= 30.0:
            self.spin_t.setValue(14.0)
        self.label_h.setEnabled(self.combo_shape.currentIndex() != 2); self.spin_h.setEnabled(self.combo_shape.currentIndex() != 2)
        self.redraw()

    def on_face_changed(self, *_):
        self.group_side.setEnabled(self.combo_face.currentIndex() == 1)
        self.redraw()

    def load_last_state(self):
        from clay_carving.clay_common import _load_state
        st = _load_state()
        if st.get("data"):
            self.update_data(st["data"]); self.update_stage(st.get("stage", ""))
            self.write_log("마지막 측정 결과를 불러왔습니다")
        else:
            self.write_log("저장된 측정 결과가 없습니다")

    def reset_state(self):
        from clay_carving.clay_common import _save_state
        _save_state(stage="", data={})
        self.measured = self.awl = self.final_preview = None
        self.text_result.setPlainText("아직 측정 없음"); self.update_stage(""); self.redraw()
        self.write_log("측정 결과를 지웠습니다 (새 작업)")

    def show_flow(self):
        QMessageBox.information(self, "작업 순서", "1. 전원 (브링업) 또는 터미널 sodreal\n"
                                "2. 터미널에서 노드 실행: clay_scan2 · gripper_ui · force_probe · clay_draw <svg>\n"
                                "3. 도형·그릴 면·크기·받침대·도안을 정하고 [작업 시작]\n"
                                "4. 그리퍼 질문 팝업에 답 (송곳을 넣은 뒤 예)\n"
                                "5. 실측 도안 미리보기가 뜨면 [확인] 또는 [취소]")

    def current_job(self):
        return dict(shape=SHAPES[self.combo_shape.currentIndex()], face=FACES[self.combo_face.currentIndex()],
                    excl_top=self.spin_excl_top.value(), excl_bot=self.spin_excl_bot.value(),
                    angle_deg=self.spin_angle.value(), z_off=self.spin_zoff.value(), fill=self.spin_fill.value() / 100.0,
                    auto=self.chk_auto.isChecked(),
                    w=self.spin_w.value(), h=self.spin_h.value(), t=self.spin_t.value(),
                    stand=self.spin_stand.value(), svg=self.edit_svg.text() or None)

    def choose_svg(self):
        path, _ = QFileDialog.getOpenFileName(self, "도안 SVG 선택", os.path.expanduser("~/Downloads"), "SVG (*.svg)")
        if not path:
            return
        try:
            strokes, _ = load_svg(path)
        except Exception as e:
            QMessageBox.warning(self, "SVG 읽기 실패", str(e)); return
        if not strokes:
            QMessageBox.warning(self, "SVG", "그릴 선이 없습니다 (path/line/circle 없음)"); return
        self.svg_strokes, self.svg_name = strokes, os.path.basename(path)
        self.edit_svg.setText(path)
        self.write_log(f"도안 선택: {self.svg_name} ({len(strokes)} 획)")
        self.redraw()

    # ---------------- 질문 팝업 (노드 2) ----------------
    def show_prompt(self, qid, text):
        if not text:
            return
        if self.open_prompt == qid:
            return
        self.open_prompt = qid
        r = QMessageBox.question(self, "확인", text, QMessageBox.Yes | QMessageBox.No)
        self.open_prompt = None
        self.node.answer(qid, r == QMessageBox.Yes)

    # ---------------- 상태 갱신 (ROS → 화면) ----------------
    def update_connection(self, ok):
        self.lbl_conn.setText("연결됨" if ok else "브링업 없음")
        self.lbl_conn.setStyleSheet("color: green;" if ok else "color: gray;")

    def update_robot_state(self, name, code):
        self.lbl_robot.setText(name)
        self.lbl_robot.setStyleSheet("color: green;" if code in (1, 2) else "color: red;")

    def update_joint_position(self, joint_deg):
        pass                                                 # 관절값은 2D 화면에 안 쓴다 (TCP 로 표시)

    def update_tcp(self, tcp):
        self.lbl_tcp.setText(f"({tcp[0]:.1f}, {tcp[1]:.1f}, {tcp[2]:.1f})")
        if self.tcp_item is not None:
            self.tcp_item.setPos(self.to_scene(tcp[0], tcp[1]))

    def update_stage(self, stage):
        names = {"scan_done": "1 스캔 완료 → 2 그리퍼", "grip_done": "2 그리퍼 완료 → 3 송곳", "probe_done": "3 송곳 완료 → 4 도안",
                 "draw_done": "4 그리기 완료", "draw_cancelled": "4 그리기 취소됨", "": "대기"}
        self.lbl_stage.setText(names.get(stage, stage))

    def update_data(self, data):
        self.measured = data.get("clay")
        self.awl = data.get("awl")
        lines = []
        c = self.measured
        if c:
            lines += [f"[1번] 중심 ({c['cx']:.1f}, {c['cy']:.1f})  가로 {c['size_x']:.1f} × 세로 {c['size_y']:.1f} mm",
                      f"      윗면 z {c['z_top']:.1f}  높이 {c.get('height') if c.get('height') is not None else c.get('thickness', 0):.1f} mm"
                      + (f"  부피 {c['volume_cm3']:.0f} cm³" if c.get('volume_cm3') else "")]
            if c.get("stand_side"):
                lines.append(f"      받침대: {c['stand_side']} 변 바깥에서 z {c['stand_z']:.1f}")
            if c.get("side_tilt"):
                lines.append("      옆면 기울기: " + ", ".join(f"{k} {v['tilt_deg']:+.1f}°" for k, v in c["side_tilt"].items()))
        a = self.awl
        if a:
            lines += [f"[3번] 송곳 길이 {a['awl_len']:.1f} mm  접촉 TCP z {a['z_touch_tcp']:.1f}  힘 {a['force_n']:.2f} N"]
        self.text_result.setPlainText("\n".join(lines) if lines else "아직 측정 없음")
        self.redraw()

    def show_final_preview(self, d):
        self.final_preview = d
        self.btn_confirm.setEnabled(True); self.btn_cancel.setEnabled(True)
        self.redraw()
        QMessageBox.information(self, "최종 확인", f"실측 지점토에 맞춘 도안 '{d.get('name')}' 을 미리보기에 표시했습니다.\n"
                                "확인을 누르면 그리기를 시작하고, 취소를 누르면 작업을 취소합니다.")

    # ---------------- 2D 미리보기 ----------------
    def to_scene(self, x, y):
        """base (x, y) mm → 화면. 위 = +X, 왼쪽 = +Y."""
        return QPointF(-y * PX_PER_MM, -x * PX_PER_MM)

    def fit_design(self, size_x, size_y):
        """4번 노드와 같은 규칙으로 도안을 지점토 상자에 맞춘다. 반환: [[(u,v)...]] (mm, u→-Y, v→+X)"""
        if not self.svg_strokes:
            return [], 0.0, (0, 0)
        box_y, box_x = size_y - 2 * CH.DESIGN_MARGIN, size_x - 2 * CH.DESIGN_MARGIN
        cands = []
        for rdeg in [0.0, 90.0]:
            bw, bh = (box_y, box_x) if rdeg == 0.0 else (box_x, box_y)
            fitted, (dw, dh), k = fit_to_box(self.svg_strokes, bw, bh, CH.DESIGN_FILL, CH.DESIGN_STEP)
            cands.append((k, rdeg, fitted, dw, dh))
        k, rdeg, fitted, dw, dh = max(cands, key=lambda c: c[0])
        sx = 1.0 if CH.DESIGN_MIRROR else -1.0
        rot = math.radians(rdeg)
        out = []
        for st in fitted:
            pts = []
            for x, y in st:
                u, v = sx * x, y
                xx = v * math.cos(rot) - u * math.sin(rot)
                yy = v * math.sin(rot) + u * math.cos(rot)
                pts.append((xx, yy))
            out.append(pts)
        return out, sum(stroke_length(s) for s in fitted), (dw, dh)

    def draw_side_preview(self, job, shape, sx, sy, label, pen):
        """옆면 모드: 왼쪽에 물체 앞모습(원통은 도안이 감긴 모습, 기둥은 앞면), 오른쪽에 펼친 옆면."""
        s = self.scene
        mh = (self.measured.get("height") or self.measured.get("thickness")) if self.measured else None
        H = mh if (mh and mh >= 20.0) else job["t"]          # 실측이 납작하면 입력 높이
        W = math.pi * sx if shape == "cylinder" else sx       # 펼친 폭: 둘레 또는 앞면 폭
        R = sx / 2.0
        self.group_preview.setTitle("미리보기 (옆면)  왼쪽: 앞에서 본 모습 · 오른쪽: 펼친 옆면 (가로 = " + ("둘레" if shape == "cylinder" else "앞면 폭") + ", 세로 = 높이)")
        blue = QPen(QColor("#2F6DB5"), 1.6)
        hidden = QPen(QColor("#2F6DB5"), 1.0, Qt.DotLine)
        fill = QBrush(QColor(184, 116, 58, 30))
        P = PX_PER_MM

        # ---- 작업 구간(띠): 위·아래 제외를 뺀 높이 범위. v 좌표는 물체 중앙 기준 (위 +)
        et, eb = job["excl_top"], job["excl_bot"]
        band_top, band_bot = H / 2 - et, -H / 2 + eb                 # 띠의 위·아래 (v)
        band_h = band_top - band_bot
        band_c = (band_top + band_bot) / 2 + job["z_off"]             # 도안 중심 높이
        u_off = math.radians(job["angle_deg"]) * R if shape == "cylinder" else 0.0   # 둘레 위치 → 펼친 u 오프셋
        # ---- 도안을 띠 안에 맞춘다 (여백·비율 유지, 크기 비율은 대시보드 값) ----
        fitted, dw, dh = [], 0.0, 0.0
        box_w, box_h = W - 2 * CH.DESIGN_MARGIN, band_h - 2 * CH.DESIGN_MARGIN
        if self.svg_strokes and box_w > 5 and box_h > 5:
            f0, (dw, dh), _ = fit_to_box(self.svg_strokes, box_w, box_h, job["fill"], CH.DESIGN_STEP)
            fitted = [[(u + u_off, v + band_c) for u, v in st] for st in f0]

        # ---- 왼쪽: 앞모습 ----
        ox = -(sx * 0.5 + 40 + W * 0.5) * P                 # 앞모습 중심 x (펼친 면과 나란히)
        ey = R * 0.28 * P                                     # 원통 윗면 타원의 반높이 (약간 위에서 본 시점)
        top, bot = -H / 2 * P, H / 2 * P
        if shape == "cylinder":
            body = QPainterPath(QPointF(ox - R * P, top))
            body.lineTo(ox - R * P, bot); body.arcTo(QRectF(ox - R * P, bot - ey, 2 * R * P, 2 * ey), 180, 180)
            body.lineTo(ox + R * P, top); body.arcTo(QRectF(ox - R * P, top - ey, 2 * R * P, 2 * ey), 0, -180)
            s.addPath(body, pen, fill)
            s.addEllipse(QRectF(ox - R * P, top - ey, 2 * R * P, 2 * ey), pen, QBrush(QColor(184, 116, 58, 60)))
            grey = QBrush(QColor(120, 120, 120, 70))
            if et > 0:
                s.addRect(QRectF(ox - R * P, top, 2 * R * P, et * P), QPen(Qt.NoPen), grey)
            if eb > 0:
                s.addRect(QRectF(ox - R * P, bot - eb * P, 2 * R * P, eb * P), QPen(Qt.NoPen), grey)
            # 도안: 펼친 좌표 (u = 둘레 방향 mm, v = 높이 mm) → 각도 θ = u / R → 앞모습 x = R sinθ, 뒤쪽(cosθ<0)은 점선
            for st in fitted:
                path, back, prev_front = None, None, None
                for u, v in st:
                    th = u / R
                    x = ox + R * math.sin(th) * P
                    y = -v * P
                    front = math.cos(th) >= 0
                    if front:
                        if path is None or prev_front is False:
                            path = QPainterPath(QPointF(x, y)); s.addPath(path, blue); path = None
                            path = QPainterPath(QPointF(x, y))
                        else:
                            path.lineTo(x, y)
                    else:
                        if back is None or prev_front is True:
                            if path is not None:
                                s.addPath(path, blue); path = None
                            back = QPainterPath(QPointF(x, y))
                        else:
                            back.lineTo(x, y)
                    prev_front = front
                if path is not None:
                    s.addPath(path, blue)
                if back is not None:
                    s.addPath(back, hidden)
        else:
            d = sy * 0.35 * P                                 # 깊이(세로)를 비스듬히 표현
            s.addRect(QRectF(ox - sx / 2 * P, top, sx * P, H * P), pen, fill)                      # 앞면
            grey = QBrush(QColor(120, 120, 120, 70))
            if et > 0:
                s.addRect(QRectF(ox - sx / 2 * P, top, sx * P, et * P), QPen(Qt.NoPen), grey)
            if eb > 0:
                s.addRect(QRectF(ox - sx / 2 * P, bot - eb * P, sx * P, eb * P), QPen(Qt.NoPen), grey)
            topface = QPainterPath(QPointF(ox - sx / 2 * P, top)); topface.lineTo(ox - sx / 2 * P + d * 0.6, top - d * 0.5)
            topface.lineTo(ox + sx / 2 * P + d * 0.6, top - d * 0.5); topface.lineTo(ox + sx / 2 * P, top); topface.closeSubpath()
            s.addPath(topface, pen, QBrush(QColor(184, 116, 58, 60)))
            sidef = QPainterPath(QPointF(ox + sx / 2 * P, top)); sidef.lineTo(ox + sx / 2 * P + d * 0.6, top - d * 0.5)
            sidef.lineTo(ox + sx / 2 * P + d * 0.6, bot - d * 0.5); sidef.lineTo(ox + sx / 2 * P, bot); sidef.closeSubpath()
            s.addPath(sidef, pen, QBrush(QColor(184, 116, 58, 45)))
            for st in fitted:                                  # 앞면에 평면으로
                path = QPainterPath(QPointF(ox + st[0][0] * P, -st[0][1] * P))
                for u, v in st[1:]:
                    path.lineTo(ox + u * P, -v * P)
                s.addPath(path, blue)
        t = s.addText(f"{label}  높이 {H:.0f}" + (f"  지름 {sx:.0f}" if shape == "cylinder" else ""), QFont("Sans", 9))
        t.setPos(ox - sx / 2 * P, bot + 8)

        # ---- 오른쪽: 펼친 옆면 ----
        rx = W / 2 * P + 20                                   # 펼친 면 중심 x
        rect = QRectF(rx - W / 2 * P, top, W * P, H * P)
        s.addRect(rect, pen, fill)
        grey = QBrush(QColor(120, 120, 120, 70))
        if et > 0:
            s.addRect(QRectF(rect.left(), top, W * P, et * P), QPen(Qt.NoPen), grey)
            te = s.addText(f"제외 {et:.0f} mm (뚜껑·어깨)", QFont("Sans", 8)); te.setDefaultTextColor(Qt.darkGray); te.setPos(rect.left() + 4, top)
        if eb > 0:
            s.addRect(QRectF(rect.left(), bot - eb * P, W * P, eb * P), QPen(Qt.NoPen), grey)
            tb = s.addText(f"제외 {eb:.0f} mm", QFont("Sans", 8)); tb.setDefaultTextColor(Qt.darkGray); tb.setPos(rect.left() + 4, bot - eb * P)
        s.addRect(QRectF(rect.left(), -band_top * P, W * P, band_h * P), QPen(QColor("#2E7D5B"), 1, Qt.DashLine))
        if shape == "cylinder":                                # 앞쪽 중앙(θ=0)과 뒤쪽 경계(±90°) 표시
            for u, name in ((0.0, "앞 0°"), (R * math.pi / 2, "+90°"), (-R * math.pi / 2, "−90°")):
                x = rx + u * P
                s.addLine(x, top, x, bot, QPen(Qt.gray, 1, Qt.DashLine))
                tt = s.addText(name, QFont("Sans", 8)); tt.setDefaultTextColor(Qt.gray); tt.setPos(x - 12, bot + 2)
        for st in fitted:
            path = QPainterPath(QPointF(rx + st[0][0] * P, -st[0][1] * P))
            for u, v in st[1:]:
                path.lineTo(rx + u * P, -v * P)
            s.addPath(path, blue)
        if self.svg_strokes and not fitted:
            warn = s.addText(f"작업 구간 높이 {band_h:.0f} mm 가 너무 낮습니다 (여백 {CH.DESIGN_MARGIN:.0f} mm 씩 빼고 5 mm 이상 필요). 높이나 제외값을 조정하세요",
                             QFont("Sans", 9)); warn.setDefaultTextColor(QColor("#B23A3A")); warn.setPos(rect.left(), rect.top() - 24)
        elif fitted:
            t2 = s.addText(f"{self.svg_name}: {len(fitted)} 획, {dw:.0f}×{dh:.0f} mm, 총 {sum(stroke_length(x) for x in fitted):.0f} mm  "
                           f"(펼친 면 {W:.0f}×{H:.0f}, 작업 구간 높이 {band_h:.0f}, 둘레 위치 {job['angle_deg']:+.0f}°)", QFont("Sans", 9))
            t2.setDefaultTextColor(QColor("#2F6DB5")); t2.setPos(rect.left(), rect.top() - 24)
        t3 = s.addText("옆면 그리기(로봇 동작)는 다음 단계에서 구현", QFont("Sans", 8)); t3.setDefaultTextColor(Qt.gray)
        t3.setPos(rect.left(), bot + 22)
        s.setSceneRect(s.itemsBoundingRect().adjusted(-40, -40, 40, 40))
        self.view_preview.fitInView(s.sceneRect(), Qt.KeepAspectRatio)

    def redraw(self):
        s = self.scene
        s.clear()
        self.tcp_item = None
        job = self.current_job()
        # 지점토: 실측이 있으면 실측, 없으면 입력값을 홈 손끝 아래에 그린다
        if self.measured:
            c = self.measured
            cx, cy, sx, sy = c["cx"], c["cy"], c["size_x"], c["size_y"]
            label = f"실측 {sx:.0f}×{sy:.0f}"
            pen = QPen(QColor("#B8743A"), 2)
        else:
            cx, cy, sx, sy = 384.0, 7.6, job["w"], job["h"]
            label = f"입력 {sx:.0f}×{sy:.0f}" + ("" if not job["auto"] else " (자동 측정 예정)")
            pen = QPen(QColor("#B8743A"), 1, Qt.DashLine)
        shape, face = job["shape"], job["face"]
        if face == "side":
            self.draw_side_preview(job, shape, sx, sy, label, pen)
            return
        self.group_preview.setTitle("미리보기 (위에서 본 지점토 · 도안 · 손끝)")
        rect = QRectF(-sy / 2 * PX_PER_MM, -sx / 2 * PX_PER_MM, sy * PX_PER_MM, sx * PX_PER_MM)
        if shape == "cylinder":
            rect = QRectF(-sx / 2 * PX_PER_MM, -sx / 2 * PX_PER_MM, sx * PX_PER_MM, sx * PX_PER_MM)
        rect.translate(self.to_scene(cx, cy))
        if shape == "cylinder":
            s.addEllipse(rect, pen, QBrush(QColor(184, 116, 58, 30)))
        else:
            s.addRect(rect, pen, QBrush(QColor(184, 116, 58, 30)))
        t = s.addText(label, QFont("Sans", 9)); t.setPos(rect.left(), rect.bottom() + 4)
        # 도안: 4번 노드가 보낸 실측 도안이 있으면 그것(절대 좌표), 아니면 입력/실측 상자에 맞춘 미리보기
        blue = QPen(QColor("#2F6DB5"), 1.5)
        if self.final_preview:
            for st in self.final_preview.get("strokes", []):
                path = QPainterPath(self.to_scene(*st[0]))
                for x, y in st[1:]:
                    path.lineTo(self.to_scene(x, y))
                s.addPath(path, blue)
            t2 = s.addText(f"실측 도안 {self.final_preview.get('name')} — 확인 대기", QFont("Sans", 9)); t2.setDefaultTextColor(QColor("#2F6DB5"))
            t2.setPos(rect.left(), rect.top() - 22)
        elif self.svg_strokes:
            strokes, total, (dw, dh) = self.fit_design(sx, sy)
            for st in strokes:
                path = QPainterPath(self.to_scene(cx + st[0][0], cy + st[0][1]))
                for xx, yy in st[1:]:
                    path.lineTo(self.to_scene(cx + xx, cy + yy))
                s.addPath(path, blue)
            t2 = s.addText(f"{self.svg_name}: {len(strokes)} 획, {dw:.0f}×{dh:.0f} mm, 총 {total:.0f} mm", QFont("Sans", 9))
            t2.setDefaultTextColor(QColor("#2F6DB5")); t2.setPos(rect.left(), rect.top() - 22)
        # 홈 손끝 위치와 현재 TCP
        home = self.to_scene(384.1, 7.6)
        s.addLine(home.x() - 6, home.y(), home.x() + 6, home.y(), QPen(Qt.gray, 1))
        s.addLine(home.x(), home.y() - 6, home.x(), home.y() + 6, QPen(Qt.gray, 1))
        self.tcp_item = s.addEllipse(-5, -5, 10, 10, QPen(QColor("#B23A3A"), 1.5), QBrush(QColor("#B23A3A")))
        self.tcp_item.setPos(self.to_scene(*self.node.tcp[:2]) if self.node.tcp else home)
        if self.awl:
            t3 = s.addText(f"송곳 {self.awl['awl_len']:.1f} mm", QFont("Sans", 9)); t3.setDefaultTextColor(QColor("#B23A3A"))
            t3.setPos(self.tcp_item.pos().x() + 8, self.tcp_item.pos().y() - 8)
        s.setSceneRect(s.itemsBoundingRect().adjusted(-40, -40, 40, 40))
        self.view_preview.fitInView(s.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.scene.items():
            self.view_preview.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    # ---------------- 로그 ----------------
    def write_log(self, text):
        self.text_log.append(str(text))

    def write_node_log(self, text, level):
        color = {40: "#c0392b", 50: "#c0392b", 30: "#b9770e"}.get(level)
        self.text_log.append(f'<span style="color:{color}">{text}</span>' if color else text)

    def closeEvent(self, event):
        self.node.shutdown()
        event.accept()
