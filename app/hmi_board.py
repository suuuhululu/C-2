"""채택 Design/현재 목표의 표시용 투영. 완료·기하 검증을 수행하지 않는다."""

from copy import deepcopy
from math import sqrt

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QWidget


# LDraw 기준: 가로 20, 몸체 높이 24, 돌기 지름 12·높이 4 LDU.
# 표시용 치수이며 조립 계약/Robot의 물리 좌표로 사용하지 않는다.
ISO_X = sqrt(3)/2
ISO_Y = .5
STUD_RADIUS = 12/20/2
STUD_HEIGHT = 4/20


def dimensions(block):
    return (2, 2) if block["brick_type"] == "2x2x1" else (
        (3, 2) if block["orientation_deg"] == 90 else (2, 3))


class BoardView(QWidget):
    def __init__(self, *, isometric=False, brick_height_per_stud=24/20):
        super().__init__()
        self.isometric = isometric
        self.brick_height_per_stud = brick_height_per_stud
        self.blocks = []
        self.transfer_target = None
        self.reported_placement = None
        self.setMinimumHeight(155)
        self.setAccessibleName("전체 목표 투영과 확대" if isometric else "현재 목표 위에서 보기와 확대")

    def set_blocks(self, blocks):
        self.blocks = deepcopy(blocks)
        self.update()

    def set_transfer_target(self, target):
        self.transfer_target = deepcopy(target)
        self.update()

    def set_reported_placement(self, block):
        self.reported_placement = deepcopy(block)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#526170"))
        if self.transfer_target is not None:
            self._transfer(painter)
            return
        if not self.blocks:
            painter.drawText(self.rect(), Qt.AlignCenter, "아직 채택된 목표 없음" if self.isometric else "현재 목표 없음")
            return
        if self.isometric:
            self._isometric(painter)
        else:
            self._overhead(painter)

    def _transfer(self, painter):
        # 종류 그림만 그린다. 조립 좌표·층·자세를 만들어 Board 배치로 사용하지 않는다.
        target = self.transfer_target
        w, d = (2, 2) if target["brick_type"] == "2x2x1" else (2, 3)
        scale = min((self.width()-40)/w, (self.height()-70)/d, 48)
        left, top = (self.width()-w*scale)/2, 30
        painter.drawText(QRectF(0, 0, self.width(), 25), Qt.AlignCenter, f"전달할 블록 · 공급 슬롯 {target['slot']}번")
        painter.setBrush(QColor("#efc94b" if target["color"] == "yellow" else "#699bde"))
        painter.setPen(QColor("#344453"))
        painter.drawRect(QRectF(left, top, w*scale, d*scale))
        for x in range(w):
            for y in range(d):
                painter.drawEllipse(QPointF(left+(x+.5)*scale, top+(y+.5)*scale), scale*STUD_RADIUS, scale*STUD_RADIUS)

    def _project(self, x, y, z):
        return QPointF((x-y)*ISO_X, (x+y)*ISO_Y-z*self.brick_height_per_stud)
        painter.drawText(QRectF(0, top+d*scale+10, self.width(), 25), Qt.AlignCenter, "공급판 → 고정 전달판")

    def _brick(self, painter, block, project, scale):
        x, y, z = block["x"], block["y"], block["layer"]
        w, d = dimensions(block)
        color = QColor("#efc94b" if block["color"] == "yellow" else "#699bde")
        painter.setPen(QPen(QColor("#344453"), 0.8))
        for points, shade in (
            ([(x, y+d, z), (x+w, y+d, z), (x+w, y+d, z-1), (x, y+d, z-1)], 113),
            ([(x+w, y, z), (x+w, y+d, z), (x+w, y+d, z-1), (x+w, y, z-1)], 130),
            ([(x, y, z), (x+w, y, z), (x+w, y+d, z), (x, y+d, z)], 100),
        ):
            painter.setBrush(color.darker(shade))
            painter.drawPolygon(QPolygonF([project(*point) for point in points]))
        rx, ry = scale*STUD_RADIUS*sqrt(2)*ISO_X, scale*STUD_RADIUS*sqrt(2)*ISO_Y
        for dx in range(w):
            for dy in range(d):
                base = project(x+dx+.5, y+dy+.5, z)
                top = project(x+dx+.5, y+dy+.5, z+STUD_HEIGHT/self.brick_height_per_stud)
                painter.setBrush(color.darker(113))
                painter.drawEllipse(base, rx, ry)
                painter.drawPolygon(QPolygonF([base+QPointF(-rx,0), base+QPointF(rx,0),
                                               top+QPointF(rx,0), top+QPointF(-rx,0)]))
                painter.setBrush(color)
                painter.drawEllipse(top, rx, ry)

    def _isometric(self, painter):
        area, height = self.width()*.6, self.height()
        blocks = sorted(self.blocks, key=lambda block: (block["layer"], block["x"]+block["y"]))
        # 바닥의 먼 모서리와 최상층 돌기까지 포함해 높아진 블록의 잘림을 방지한다.
        raw = [self._project(x,y,z) for block in blocks
               for x in (block["x"], block["x"]+dimensions(block)[0])
               for y in (block["y"], block["y"]+dimensions(block)[1])
               for z in (block["layer"]-1, block["layer"]+STUD_HEIGHT/self.brick_height_per_stud)]
        min_y = min(0, min(point.y() for point in raw))
        max_y = max(24, max(point.y() for point in raw))
        scale = min((area-24)/(48*ISO_X), (height-50)/(max_y-min_y))
        project = lambda x, y, z: QPointF(area/2,27-min_y*scale)+self._project(x,y,z)*scale
        painter.drawText(QRectF(0, 0, area, 22), Qt.AlignCenter, "24×24점 전체판 · 투영")
        painter.setBrush(QColor("#f0f2f4"))
        painter.setPen(QColor("#bdc7d1"))
        painter.drawPolygon(QPolygonF([project(x, y, 0) for x, y in ((0,0), (24,0), (24,24), (0,24))]))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#85919e"))
        for x in range(24):
            for y in range(24):
                painter.drawEllipse(project(x+.5, y+.5, 0), scale*.2, scale*.1)
        for block in blocks:
            self._brick(painter, block, project, scale)
        painter.setPen(QColor("#526170"))
        painter.drawText(project(0,0,0)+QPointF(-16,-5), "(0,0)")
        painter.drawText(project(24,0,0)+QPointF(-25,13), "X →")
        painter.drawText(project(0,24,0)+QPointF(0,13), "← Y")
        # 확대는 같은 채택 blocks의 화면 좌표만 계산한다. 후보 Design은 입력받지 않는다.
        min_x, max_x = min(p.x() for p in raw), max(p.x() for p in raw)
        min_y, max_y = min(p.y() for p in raw), max(p.y() for p in raw)
        zoom = min((self.width()-area-18)/max(max_x-min_x,1), (height-55)/max(max_y-min_y,1), 23)
        cx, cy = (min_x+max_x)/2, (min_y+max_y)/2
        project_zoom = lambda x,y,z: QPointF(area+(self.width()-area)/2,(height+30)/2) + (
            self._project(x,y,z)-QPointF(cx,cy))*zoom
        painter.drawText(QRectF(area,0,self.width()-area,22), Qt.AlignCenter, "완성 목표 확대")
        for block in blocks:
            self._brick(painter, block, project_zoom, zoom)

    def _overhead(self, painter):
        block = self.blocks[0]
        size, left, top = min(self.height()-43, self.width()*.49), 22, 18
        scale = size/24
        painter.setPen(QPen(QColor("#ccd3dc"), .5))
        for i in range(25):
            painter.drawLine(QPointF(left+i*scale,top), QPointF(left+i*scale,top+size))
            painter.drawLine(QPointF(left,top+i*scale), QPointF(left+size,top+i*scale))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#84919e"))
        for x in range(24):
            for y in range(24):
                painter.drawEllipse(QPointF(left+(x+.5)*scale, top+(23.5-y)*scale), .6, .6)
        painter.setPen(QColor("#526170"))
        for i in (0,6,12,18,23):
            painter.drawText(QPointF(left+(i+.5)*scale-4,top+size+16), str(i))
            painter.drawText(QPointF(left-17,top+(23.5-i)*scale+4), str(i))
        w, d = dimensions(block)
        color = QColor("#efc94b" if block["color"] == "yellow" else "#699bde")
        painter.setBrush(color)
        painter.setPen(QColor("#344453"))
        painter.drawRect(QRectF(left+block["x"]*scale, top+(24-block["y"]-d)*scale, w*scale,d*scale))
        if self.reported_placement:
            actual = self.reported_placement
            aw, ad = dimensions(actual)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#c0392b"), 2))
            painter.drawRect(QRectF(left+actual["x"]*scale, top+(24-actual["y"]-ad)*scale, aw*scale, ad*scale))
            painter.setBrush(color)
            painter.setPen(QColor("#344453"))
        zx, zoom = left+size+23, min((self.width()-left-size-32)/4,24)
        painter.drawText(QRectF(zx,0,self.width()-zx,22), Qt.AlignCenter, "목표 확대")
        painter.drawText(QRectF(zx,24,self.width()-zx,22), Qt.AlignCenter,
                         f"({block['x']}, {block['y']}) · {block['layer']}층")
        painter.drawRect(QRectF(zx,57,w*zoom,d*zoom))
        for x in range(w):
            for y in range(d):
                painter.drawEllipse(QPointF(zx+(x+.5)*zoom,57+(y+.5)*zoom), zoom*STUD_RADIUS,zoom*STUD_RADIUS)
