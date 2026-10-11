"""채택 Design/현재 목표의 표시용 투영. 완료·기하 검증을 수행하지 않는다."""

from copy import deepcopy
from math import sqrt

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QWidget

from app.current import _key

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
        self.current = None
        self.target = None
        self.transfer_target = None
        self.reported_placement = None
        self.zoom_caption = "완성 목표 확대"
        self.overview = True
        self.setMinimumHeight(155)
        self.setAccessibleName("전체 목표 투영과 확대" if isometric else "현재 목표 위에서 보기와 확대")

    def set_blocks(self, blocks):
        self.current = None
        self.target = None
        self.blocks = deepcopy(blocks)
        self.update()

    def set_assembly(self, current, target):
        # 표시 사본만 조합한다. 관측 채택/동일 물리 블록의 대응은 추정하지 않는다.
        self.current, self.target = deepcopy(current), deepcopy(target)
        self.blocks = deepcopy(current["blocks"])
        if target is not None and not any(_key(block) == _key(target) for block in self.blocks):
            self.blocks.append(deepcopy(target))
        self.setAccessibleName("확인된 현재 구조와 이번 목표 · 입체 투영과 확대")
        self.update()

    def set_transfer_target(self, target):
        self.transfer_target = deepcopy(target)
        if target is not None:
            self.setAccessibleName("공급 슬롯의 전달 블록 · 조립 목표 미채택")
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
            text = ("조립 관측 기록 없음\n실제 보드 비움 여부 미확인" if self.current is not None else
                    "아직 채택된 목표 없음" if self.isometric else "현재 목표 없음")
            painter.drawText(self.rect(), Qt.AlignCenter, text)
            return
        if self.isometric:
            if self.overview:
                self._isometric(painter)
            else:
                self._compact_isometric(painter)
        else:
            self._overhead(painter)

    def _compact_isometric(self, painter):
        # 한 페이지의 작은 카드에서도 같은 좌표/비율로 구조를 크게 보여준다.
        blocks = sorted(self.blocks, key=lambda block: (block["layer"], block["x"]+block["y"]))
        if self.current is not None and self.target is not None:
            blocks = [block for block in blocks if _key(block) != _key(self.target)] + [self.target]
        points = [self._project(x, y, z) for block in blocks
                  for x in (block["x"], block["x"]+dimensions(block)[0])
                  for y in (block["y"], block["y"]+dimensions(block)[1])
                  for z in (block["layer"]-1, block["layer"]+STUD_HEIGHT/self.brick_height_per_stud)]
        left, right = min(p.x() for p in points), max(p.x() for p in points)
        top, bottom = min(p.y() for p in points), max(p.y() for p in points)
        scale = min((self.width()-18)/max(right-left, 1), (self.height()-18)/max(bottom-top, 1), 28)
        project = lambda x, y, z: QPointF(self.width()/2, self.height()/2) + (
            self._project(x,y,z)-QPointF((left+right)/2, (top+bottom)/2))*scale
        for block in blocks:
            self._brick(painter, block, project, scale)

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
        # +X/+Y 쪽(현재 의자의 등받이 뒤쪽)에서 본다. 공통 좌표는 유지하고 표시만 바꾼다.
        return QPointF((y-x)*ISO_X, (x+y)*ISO_Y-z*self.brick_height_per_stud)
        painter.drawText(QRectF(0, top+d*scale+10, self.width(), 25), Qt.AlignCenter, "공급판 → 고정 전달판")

    def _brick(self, painter, block, project, scale):
        x, y, z = block["x"], block["y"], block["layer"]
        w, d = dimensions(block)
        color = QColor("#efc94b" if block["color"] == "yellow" else "#699bde")
        target = self.target is not None and _key(block) == _key(self.target)
        ghost = target and not any(_key(block) == _key(self.target) for block in self.current["blocks"])
        if ghost:
            color.setAlpha(65)
        painter.setPen(QPen(QColor("#182f48") if target else QColor("#344453"),
                            2 if target else .8, Qt.DashLine if target else Qt.SolidLine))
        for points, shade in (
            ([(x, y+d, z), (x+w, y+d, z), (x+w, y+d, z-1), (x, y+d, z-1)], 113),
            ([(x+w, y, z), (x+w, y+d, z), (x+w, y+d, z-1), (x+w, y, z-1)], 130),
            ([(x, y, z), (x+w, y, z), (x+w, y+d, z), (x, y+d, z)], 100),
        ):
            # 같은 위치의 색상 차이는 실제 색을 덮지 않고 목표 윤곽만 겹친다.
            occupied = ghost and any(other["layer"] == z and other["x"] == x and other["y"] == y
                                     for other in self.current["blocks"])
            painter.setBrush(Qt.NoBrush if occupied else color.darker(shade))
            painter.drawPolygon(QPolygonF([project(*point) for point in points]))
        rx, ry = scale*STUD_RADIUS*sqrt(2)*ISO_X, scale*STUD_RADIUS*sqrt(2)*ISO_Y
        painter.setPen(QPen(QColor("#526170"), .6))
        for dx in range(w):
            for dy in range(d):
                base = project(x+dx+.5, y+dy+.5, z)
                top = project(x+dx+.5, y+dy+.5, z+STUD_HEIGHT/self.brick_height_per_stud)
                painter.setBrush(Qt.NoBrush if ghost else color.darker(113))
                painter.drawEllipse(base, rx, ry)
                painter.drawPolygon(QPolygonF([base+QPointF(-rx,0), base+QPointF(rx,0),
                                               top+QPointF(rx,0), top+QPointF(-rx,0)]))
                painter.setBrush(Qt.NoBrush if ghost else color)
                painter.drawEllipse(top, rx, ry)

    def _isometric(self, painter):
        assembly = self.current is not None
        area, height = self.width()*(.38 if assembly else .6), self.height()
        blocks = sorted(self.blocks, key=lambda block: (block["layer"], block["x"]+block["y"]))
        if assembly and self.target is not None:
            # 미확인 목표의 윤곽은 실제 구조에 가려지지 않게 마지막에 겹쳐 그린다.
            blocks = [block for block in blocks if _key(block) != _key(self.target)] + [self.target]
        # 바닥의 먼 모서리와 최상층 돌기까지 포함해 높아진 블록의 잘림을 방지한다.
        raw = [self._project(x,y,z) for block in blocks
               for x in (block["x"], block["x"]+dimensions(block)[0])
               for y in (block["y"], block["y"]+dimensions(block)[1])
               for z in (block["layer"]-1, block["layer"]+STUD_HEIGHT/self.brick_height_per_stud)]
        min_y = min(0, min(point.y() for point in raw))
        max_y = max(24, max(point.y() for point in raw))
        scale = min((area-24)/(48*ISO_X), (height-50)/(max_y-min_y))
        project = lambda x, y, z: QPointF(area/2,27-min_y*scale)+self._project(x,y,z)*scale
        painter.drawText(QRectF(0, 0, area, 22), Qt.AlignCenter, "24×24점 판" if assembly else "24×24점 전체판 · 투영")
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
        painter.drawText(project(0,0,0)+QPointF(-16,8), "(0,0)")
        painter.drawText(project(24,0,0)+QPointF(0,13), "X ↙")
        painter.drawText(project(0,24,0)+QPointF(-25,13), "Y ↘")
        # 전체판에는 모든 Current를, 확대에는 이번 목표 주변과 아래층을 표시한다.
        zoom_blocks = blocks
        if assembly and self.target is not None:
            tx, ty = self.target["x"], self.target["y"]
            tw, td = dimensions(self.target)
            margin = 4
            zoom_blocks = [block for block in blocks
                           if block["x"] < tx+tw+margin and block["x"]+dimensions(block)[0] > tx-margin
                           and block["y"] < ty+td+margin and block["y"]+dimensions(block)[1] > ty-margin]
            raw = [self._project(x,y,z) for block in zoom_blocks
                   for x in (block["x"], block["x"]+dimensions(block)[0])
                   for y in (block["y"], block["y"]+dimensions(block)[1])
                   for z in (block["layer"]-1, block["layer"]+STUD_HEIGHT/self.brick_height_per_stud)]
        min_x, max_x = min(p.x() for p in raw), max(p.x() for p in raw)
        min_y, max_y = min(p.y() for p in raw), max(p.y() for p in raw)
        zoom = min((self.width()-area-28)/max(max_x-min_x,1), (height-75 if assembly else height-55)/max(max_y-min_y,1), 30 if assembly else 23)
        cx, cy = (min_x+max_x)/2, (min_y+max_y)/2
        project_zoom = lambda x,y,z: QPointF(area+(self.width()-area)/2,(height+(45 if assembly else 30))/2) + (
            self._project(x,y,z)-QPointF(cx,cy))*zoom
        caption = self.zoom_caption
        if assembly:
            caption = (f"이번 목표 · ({self.target['x']},{self.target['y']})\n"
                       f"{self.target['layer']}층 · {self.target['orientation_deg']}° · 주변 확대" if self.target else "최종 Current / 현재 구조")
        painter.drawText(QRectF(area,0,self.width()-area,42 if assembly else 22), Qt.AlignCenter, caption)
        for block in zoom_blocks:
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
