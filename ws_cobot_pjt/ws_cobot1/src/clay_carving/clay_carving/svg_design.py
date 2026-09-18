# SVG 도안 → 송곳 획(폴리라인) 목록. 노드 4 가 지점토 크기에 맞춰 스케일해 긋는다.
# 지원: <path d="..."> 의 M/m L/l H/h V/v C/c S/s Q/q T/t Z/z, <line>, <polyline>, <polygon>, <circle>, <ellipse>.
# A(호) 명령은 지원하지 않는다 (도안은 3차 곡선으로 그린다). 획 하나 = path/도형 하나 = 내려서 긋고 올리는 단위.
import math
import re
import xml.etree.ElementTree as ET

BEZIER_STEPS = 16          # 곡선 하나를 나누는 직선 수
K = 0.5522847              # 원을 4개의 3차 곡선으로 그릴 때의 제어점 비율

_num = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_cmd = re.compile(r"[MmLlHhVvCcSsQqTtZzAa]")


def _tokens(d):
    """path d 문자열 → [(명령, [숫자...]), ...]"""
    out = []
    pos = 0
    for m in _cmd.finditer(d):
        if out:
            out[-1][1].extend(float(x) for x in _num.findall(d[pos:m.start()]))
        out.append((m.group(), []))
        pos = m.end()
    if out:
        out[-1][1].extend(float(x) for x in _num.findall(d[pos:]))
    return out


def _cubic(p0, p1, p2, p3, n=BEZIER_STEPS):
    pts = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        pts.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return pts


def _quad(p0, p1, p2, n=BEZIER_STEPS):
    pts = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        pts.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return pts


def path_to_polylines(d):
    """path d → 폴리라인 목록 (M 마다 새 획)."""
    polys = []
    cur = None
    start = None
    last_c2 = None
    last_q1 = None
    pos = (0.0, 0.0)

    def begin(p):
        nonlocal cur, start
        cur = [p]
        polys.append(cur)
        start = p

    for cmd, a in _tokens(d):
        rel = cmd.islower()
        c = cmd.upper()
        if c == "A":
            raise ValueError("SVG arc (A) is not supported; draw curves with C/Q instead")
        if c == "M":
            for i in range(0, len(a), 2):
                p = (pos[0] + a[i], pos[1] + a[i + 1]) if rel else (a[i], a[i + 1])
                if i == 0:
                    begin(p)
                else:
                    cur.append(p)
                pos = p
            last_c2 = last_q1 = None
        elif c == "L":
            for i in range(0, len(a), 2):
                p = (pos[0] + a[i], pos[1] + a[i + 1]) if rel else (a[i], a[i + 1])
                cur.append(p); pos = p
            last_c2 = last_q1 = None
        elif c == "H":
            for x in a:
                p = (pos[0] + x, pos[1]) if rel else (x, pos[1])
                cur.append(p); pos = p
            last_c2 = last_q1 = None
        elif c == "V":
            for y in a:
                p = (pos[0], pos[1] + y) if rel else (pos[0], y)
                cur.append(p); pos = p
            last_c2 = last_q1 = None
        elif c == "C":
            for i in range(0, len(a), 6):
                q = a[i:i + 6]
                if rel:
                    q = [q[j] + pos[j % 2] for j in range(6)]
                p1, p2, p3 = (q[0], q[1]), (q[2], q[3]), (q[4], q[5])
                cur.extend(_cubic(pos, p1, p2, p3)); pos = p3; last_c2 = p2
            last_q1 = None
        elif c == "S":
            for i in range(0, len(a), 4):
                q = a[i:i + 4]
                if rel:
                    q = [q[j] + pos[j % 2] for j in range(4)]
                p1 = (2 * pos[0] - last_c2[0], 2 * pos[1] - last_c2[1]) if last_c2 else pos
                p2, p3 = (q[0], q[1]), (q[2], q[3])
                cur.extend(_cubic(pos, p1, p2, p3)); pos = p3; last_c2 = p2
            last_q1 = None
        elif c == "Q":
            for i in range(0, len(a), 4):
                q = a[i:i + 4]
                if rel:
                    q = [q[j] + pos[j % 2] for j in range(4)]
                p1, p2 = (q[0], q[1]), (q[2], q[3])
                cur.extend(_quad(pos, p1, p2)); pos = p2; last_q1 = p1
            last_c2 = None
        elif c == "T":
            for i in range(0, len(a), 2):
                p2 = (pos[0] + a[i], pos[1] + a[i + 1]) if rel else (a[i], a[i + 1])
                p1 = (2 * pos[0] - last_q1[0], 2 * pos[1] - last_q1[1]) if last_q1 else pos
                cur.extend(_quad(pos, p1, p2)); pos = p2; last_q1 = p1
            last_c2 = None
        elif c == "Z":
            if cur and start and (abs(cur[-1][0] - start[0]) > 1e-6 or abs(cur[-1][1] - start[1]) > 1e-6):
                cur.append(start)
            pos = start
            last_c2 = last_q1 = None
    return [p for p in polys if len(p) >= 2]


def _ellipse(cx, cy, rx, ry):
    kx, ky = K * rx, K * ry
    d = (f"M {cx + rx} {cy} C {cx + rx} {cy + ky} {cx + kx} {cy + ry} {cx} {cy + ry} "
         f"C {cx - kx} {cy + ry} {cx - rx} {cy + ky} {cx - rx} {cy} "
         f"C {cx - rx} {cy - ky} {cx - kx} {cy - ry} {cx} {cy - ry} "
         f"C {cx + kx} {cy - ry} {cx + rx} {cy - ky} {cx + rx} {cy} Z")
    return path_to_polylines(d)


def load_svg(path):
    """SVG 파일 → (획 목록[[(x,y),...]], viewBox(w,h)). 좌표는 SVG 단위 그대로(y 아래 방향)."""
    root = ET.parse(path).getroot()
    vb = root.get("viewBox")
    if vb:
        _, _, w, h = (float(v) for v in vb.replace(",", " ").split())
    else:
        w, h = float(root.get("width", 100)), float(root.get("height", 100))
    strokes = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "path":
            strokes.extend(path_to_polylines(el.get("d", "")))
        elif tag == "line":
            strokes.append([(float(el.get("x1")), float(el.get("y1"))), (float(el.get("x2")), float(el.get("y2")))])
        elif tag in ("polyline", "polygon"):
            nums = [float(v) for v in _num.findall(el.get("points", ""))]
            pts = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
            if tag == "polygon" and pts:
                pts.append(pts[0])
            if len(pts) >= 2:
                strokes.append(pts)
        elif tag == "circle":
            r = float(el.get("r"))
            strokes.extend(_ellipse(float(el.get("cx", 0)), float(el.get("cy", 0)), r, r))
        elif tag == "ellipse":
            strokes.extend(_ellipse(float(el.get("cx", 0)), float(el.get("cy", 0)), float(el.get("rx")), float(el.get("ry"))))
    return strokes, (w, h)


def resample(poly, step):
    """폴리라인을 대략 step 간격의 점으로 다시 찍는다 (movesx 점 수 조절)."""
    out = [poly[0]]
    acc = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg == 0:
            continue
        t = 0.0
        while acc + (seg - t) >= step:
            adv = step - acc
            t += adv
            out.append((x0 + (x1 - x0) * t / seg, y0 + (y1 - y0) * t / seg))
            acc = 0.0
        acc += seg - t
    if out[-1] != poly[-1]:
        out.append(poly[-1])
    return out


def fit_strokes(strokes, width_mm, step_mm=2.0):
    """도안 전체의 경계상자를 width_mm(긴 쪽) 에 맞춰 스케일하고, 중심을 (0,0) 으로 옮긴 뒤 step_mm 간격으로 재샘플.
    반환: 획 목록 (mm, y 위 방향 = SVG y 반전), (폭, 높이) mm"""
    xs = [x for s in strokes for x, _ in s]
    ys = [y for s in strokes for _, y in s]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    span = max(x1 - x0, y1 - y0)
    k = width_mm / span
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    out = []
    for s in strokes:
        mm = [((x - cx) * k, -(y - cy) * k) for x, y in s]
        out.append(resample(mm, step_mm))
    return out, ((x1 - x0) * k, (y1 - y0) * k)


def fit_to_box(strokes, box_w, box_h, fill=1.0, step_mm=2.0):
    """도안을 비율 그대로(가로세로 같은 배율) 상자 box_w × box_h [mm] 안에 들어가게 맞춘다.
    배율 k = fill × min(box_w/도안폭, box_h/도안높이). 중심을 (0,0) 으로 옮기고 step_mm 간격으로 재샘플.
    반환: 획 목록 (mm, y 위 방향 = SVG y 반전), (도안 폭, 높이) mm, k"""
    xs = [x for s in strokes for x, _ in s]
    ys = [y for s in strokes for _, y in s]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    dw, dh = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    k = fill * min(box_w / dw, box_h / dh)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    out = []
    for s in strokes:
        mm = [((x - cx) * k, -(y - cy) * k) for x, y in s]
        out.append(resample(mm, step_mm))
    return out, (dw * k, dh * k), k


def stroke_length(poly):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(poly, poly[1:]))
