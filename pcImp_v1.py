import sys
import ctypes as _ctypes

def _ensure_admin():
    try:
        if _ctypes.windll.shell32.IsUserAnAdmin():
            return  # уже администратор
    except Exception:
        return
    # Перезапускаемся с UAC-запросом повышения прав
    _ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(f'"{a}"' for a in sys.argv), None, 1
    )
    sys.exit(0)

_ensure_admin()

import math
import requests # Нужно для загрузки данных из интернета
import random
import os
from PyQt6 import QtGui
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, 
    QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QGridLayout, QLineEdit, QScrollArea, 
)
from PyQt6.QtCore import Qt, QTimer, QSize, QRect, QPoint, QDateTime, QPointF, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6 import QtCore, QtSvg
from PyQt6.QtGui import (
    QColor, QPixmap, QPainter, QFont, QGuiApplication, 
    QPainterPath, QRegion, QRadialGradient, QLinearGradient, QBrush, QPen, QIcon # Добавили QPen
)
from PyQt6.QtSvg import QSvgRenderer
import keyboard  # Добавь к остальным импортам
from PyQt6 import QtCore
import threading # Добавь это
import ctypes
from ctypes import wintypes

_TARGET_PROCS = {'railwork64.exe', 'railworks64.exe', 'railworks.exe', 'railwork.exe'}

# ── Низкоуровневый глобальный хук клавиатуры ──────────────────────────────
_WH_KEYBOARD_LL  = 13
_WM_KEYDOWN      = 0x0100
_WM_SYSKEYDOWN   = 0x0104

class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('vkCode',      wintypes.DWORD),
        ('scanCode',    wintypes.DWORD),
        ('flags',       wintypes.DWORD),
        ('time',        wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_ulong),
    ]
# Ключевые слова в заголовке окна — резервный способ определения игры
_TARGET_TITLES = ('railwork', 'train simulator', 'railworks')

# ── Station zones (polygons) — ported from map/index.html ────────────────────
_STATION_ZONES = {
    "Arad": [
        [46.19227332454205, 21.32248424738745],
        [46.19301401193828, 21.324388205110626],
        [46.18923422322436, 21.327598183420765],
        [46.18848259160333, 21.325647020134213],
    ],
    "Glogovat": [
        [46.17632503773067, 21.41286866594898],
        [46.17587872097718, 21.412763282715765],
        [46.177276663699466, 21.397598172331335],
        [46.17787005403529, 21.3977573902941],
    ],
    "Ghioroc": [
        [46.14953315155513, 21.583959284909326],
        [46.14952426668114, 21.58338643577958],
        [46.147622870659816, 21.583523235571754],
        [46.14763175584068, 21.58419013455863],
    ],
    "Paulis hc.": [
        [46.12057633697037, 21.585819245867384],
        [46.12059072849195, 21.58637464816498],
        [46.12239683463942, 21.586192974484167],
        [46.12238963911497, 21.585746576375815],
    ],
    "Paulis": [
        [46.10720670033165, 21.61171666885639],
        [46.106759001565614, 21.611751573576658],
        [46.10661864120381, 21.608358834766346],
        [46.107025201270154, 21.60840072043067],
    ],
    "Radna": [
        [46.094307701095126, 21.690358858136978],
        [46.09341778906679, 21.69145879292082],
        [46.096164185499006, 21.695539362678925],
        [46.09705137901734, 21.6942656080852],
    ],
}

_STATION_CENTERS = {
    name: [
        sum(p[0] for p in poly) / len(poly),
        sum(p[1] for p in poly) / len(poly),
    ]
    for name, poly in _STATION_ZONES.items()
}

_ROUTE_ORDER = {
    "Radna_Arad": ["Radna", "Paulis", "Paulis hc.", "Ghioroc", "Glogovat", "Arad"],
    "Arad_Radna": ["Arad", "Glogovat", "Ghioroc", "Paulis hc.", "Paulis", "Radna"],
}


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_in_polygon(lat, lon, polygon):
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]
        if (lat_i > lat) != (lat_j > lat) and lon < (
            (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i) + lon_i
        ):
            inside = not inside
        j = i
    return inside


def _dist_to_polygon(lat, lon, polygon):
    min_dist = float('inf')
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        lat1, lon1 = polygon[i]
        lat2, lon2 = polygon[j]
        dx, dy = lat2 - lat1, lon2 - lon1
        len2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((lat - lat1) * dx + (lon - lon1) * dy) / len2)) if len2 > 0 else 0.0
        d = _haversine(lat, lon, lat1 + t * dx, lon1 + t * dy)
        if d < min_dist:
            min_dist = d
    return min_dist


def _get_current_zone(lat, lon):
    for name, poly in _STATION_ZONES.items():
        if _point_in_polygon(lat, lon, poly):
            return name
    for name, poly in _STATION_ZONES.items():
        if _dist_to_polygon(lat, lon, poly) < 200:
            return name
    return None


def _get_gps_progress(lat, lon, route_from, route_to):
    order = _ROUTE_ORDER.get(f"{route_from}_{route_to}")
    if not order:
        return None
    current_zone = _get_current_zone(lat, lon)
    if current_zone and current_zone in order:
        idx = order.index(current_zone)
        next_idx = idx + 1 if idx < len(order) - 1 else len(order) - 1
        next_st = order[next_idx]
        return {
            'current_station': current_zone,
            'next_station': next_st,
            'on_station': True,
            'remaining': _dist_to_polygon(lat, lon, _STATION_ZONES[next_st]),
            'passed_idx': idx,
            'order': order,
        }
    centers = [_STATION_CENTERS[s] for s in order]
    best_seg, min_d = 0, float('inf')
    for i in range(len(centers) - 1):
        p1, p2 = centers[i], centers[i + 1]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        len2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((lat - p1[0]) * dx + (lon - p1[1]) * dy) / len2)) if len2 > 0 else 0.0
        d = _haversine(lat, lon, p1[0] + t * dx, p1[1] + t * dy)
        if d < min_d:
            min_d, best_seg = d, i
    next_st = order[best_seg + 1]
    return {
        'current_station': None,
        'next_station': next_st,
        'on_station': False,
        'remaining': _dist_to_polygon(lat, lon, _STATION_ZONES[next_st]),
        'passed_idx': best_seg,
        'order': order,
    }


class _ShimmerBadge(QWidget):
    """Animated shimmer rectangle shown next to the current station name."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(30, 7)
        self._phase = 0.0
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def _tick(self):
        try:
            self._phase = (self._phase + 0.05) % 1.0
            self.update()
        except RuntimeError:
            self._timer.stop()

    def stop(self):
        self._timer.stop()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(255, 255, 255, 20))
        x_center = self._phase * self.width() * 2 - self.width() * 0.5
        grad = QLinearGradient(x_center - 18, 0, x_center + 18, 0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.5, QColor(255, 255, 255, 210))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(self.rect(), grad)
        p.end()


class _TrackCell(QWidget):
    """One grid row in the timetable: draws the vertical line segment + station dot."""
    _SEG_NONE   = 'none'
    _SEG_DIM    = 'dim'
    _SEG_SOLID  = 'solid'
    _SEG_DASHED = 'dashed'

    def __init__(self, dot_color: QColor, seg_above: str, seg_below: str, parent=None):
        super().__init__(parent)
        self.setFixedWidth(12)
        self._dot_color = dot_color
        self._seg_above = seg_above
        self._seg_below = seg_below

    def set_dot_blink(self, bright: bool):
        if bright:
            self._dot_color = QColor("#f1c40f")
        else:
            self._dot_color = QColor(241, 196, 15, 35)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() // 2
        cy = self.height() // 2
        r = 4

        def draw_seg(y0, y1, style):
            if style == _TrackCell._SEG_NONE or y0 >= y1:
                return
            if style == _TrackCell._SEG_DIM:
                pen = QPen(QColor(255, 255, 255, 50), 2)
                pen.setStyle(Qt.PenStyle.SolidLine)
            elif style == _TrackCell._SEG_DASHED:
                pen = QPen(QColor(255, 255, 255, 185), 2)
                pen.setStyle(Qt.PenStyle.CustomDashLine)
                pen.setDashPattern([3.0, 3.5])
            else:
                pen = QPen(QColor(255, 255, 255, 90), 2)
                pen.setStyle(Qt.PenStyle.SolidLine)
            p.setPen(pen)
            p.drawLine(QPointF(cx, float(y0)), QPointF(cx, float(y1)))

        draw_seg(0, cy - r - 1, self._seg_above)
        draw_seg(cy + r + 1, self.height(), self._seg_below)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._dot_color))
        p.drawEllipse(QPointF(float(cx), float(cy)), float(r), float(r))
        p.end()


def _fg_proc_name():
    """Возвращает (имя_процесса_нижний_регистр | None, hwnd) активного окна."""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None, 0

        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None, hwnd

        # Пробуем открыть процесс с разными уровнями доступа
        h = None
        for access in (0x1000, 0x0400, 0x0410):
            h = ctypes.windll.kernel32.OpenProcess(access, False, pid.value)
            if h:
                break

        if h:
            buf = ctypes.create_unicode_buffer(260)
            sz = ctypes.c_ulong(260)
            name = None
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(sz)):
                name = os.path.basename(buf.value).lower()
            ctypes.windll.kernel32.CloseHandle(h)
            print(f"[HUD] Foreground: {name}")
            return name, hwnd

        # OpenProcess не удался (игра запущена от Администратора) — смотрим заголовок окна
        title_buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 256)
        title = title_buf.value.lower()
        print(f"[HUD] Can't open process — window title: '{title}'")
        if any(k in title for k in _TARGET_TITLES):
            return 'railworks64.exe', hwnd  # считаем, что это игра
        return None, hwnd

    except Exception as e:
        print(f"[HUD] Focus check error: {e}")
        return None, 0


class Overlay(QWidget):
    key_signal = pyqtSignal(str) # Сигнал для связи потоков

    def trigger_key_logic(self, key_name):
        if not getattr(self, 'task_shown', False) or self.task_state >= 2:
            return

        green = "color: #2ecc71; font-family: 'Segoe UI'; font-size: 16px; font-weight: 800; border: none;"

        if key_name == "left" and self.task_state == 0:
            self.step_left.setStyleSheet(green)
            self.task_state = 1
            print("DEBUG: Left caught!")
            
        elif key_name == "right" and self.task_state == 1:
            self.step_right.setStyleSheet(green)
            self.step_nice.setStyleSheet(green)
            self.step_nice.setText("STATUS: NICE!")
            self.task_state = 2
            print("DEBUG: Right caught!")
            
            # ИСПРАВЛЕНИЕ ТУТ: Проверяем, какой таймер у тебя в коде
            if hasattr(self, 'blink_task_timer'):
                self.blink_task_timer.stop()
            elif hasattr(self, 'blink_timer'):
                self.blink_timer.stop()
            
            self.task_widget.show() # Оставляем гореть зеленым
            QTimer.singleShot(5000, self.task_widget.hide)

    def __init__(self):
        super().__init__()
        # Флаги: без рамки, поверх всех, не попадает в Alt-Tab
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.initUI()
        # Создаем панели ОДИН РАЗ при старте
        self.setup_left_panel()
        
        # Показываем строго на весь экран, прижимая к самой верхней границе
        self.showFullScreen()
        # Указываем геометрию окна явно (на всякий случай)
        screen = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        # Сразу загружаем первый раз
        self.fetch_data()
        self.fetch_steam_profile()

        # Регистрация кнопок через emit (безопасно)
        

        # Таймер для мигания
        self.blink_task_timer = QTimer(self)
        self.blink_task_timer.timeout.connect(self.blink_task_text)
        # Связываем сигнал с функцией обработки
        # В самом конце __init__:
        self.key_signal.connect(self.trigger_key_logic) # Соединяем

        self._install_keyboard_hook()

        # Таймер мигания всего виджета (стробоскоп)
        self.blink_task_timer = QTimer(self)
        self.blink_task_timer.timeout.connect(lambda: self.task_widget.setVisible(not self.task_widget.isVisible()) if self.task_state < 2 else None)
        QTimer.singleShot(3000, self.show_task_widget)

    def create_circular_pixmap(self, path, size):
        pm = QPixmap(path)
        if pm.isNull():
            pm = QPixmap(size, size)
            pm.fill(QColor("#2a2a2a"))
        
        # Масштабируем картинку
        pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            
        target = QPixmap(size, size)
        target.fill(Qt.GlobalColor.transparent)
        
        p = QPainter(target)
        # ВКЛЮЧАЕМ МАКСИМАЛЬНОЕ СГЛАЖИВАНИЕ
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # 1. Сначала рисуем белую обводку (круг)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(0, 0, size, size)
        
        # 2. Рисуем картинку чуть-чуть меньше, чтобы она была внутри обводки
        # (отступ в 2 пикселя для толщины рамки)
        thickness = 2
        path_clip = QPainterPath()
        path_clip.addEllipse(thickness, thickness, size - thickness*2, size - thickness*2)
        p.setClipPath(path_clip)
        
        p.drawPixmap(0, 0, pm)
        p.end()
        return target

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ==========================================
        # .top-nav-line
        # ==========================================
        self.top_bar = QFrame()
        self.top_bar.setFixedHeight(70)
        self.top_bar.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 0, 0, 180); /* 180 — это плотность цвета от 0 до 255 */
                border: none;
            }
        """)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(20, 0, 20, 0) # padding: 0 20px
        top_layout.setSpacing(0)

        

        # --- 2. .app-icon ---
        # --- 2. .app-icon ---
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(45, 45)
        self.icon_label.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Теперь здесь только чистая картинка, где рамка уже врисована идеально гладко
        self.icon_label.setPixmap(self.create_circular_pixmap("icon.png", 45))
        
        # Убираем border из стилей, оставляем только прозрачный фон
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        
        top_layout.addWidget(self.icon_label)
        top_layout.addSpacing(25)

        # --- 3. .brand-name & .server-label & .status-dot ---
        brand_container = QWidget()
        brand_lay = QHBoxLayout(brand_container)
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(12) # gap: 12px

        self.brand_label = QLabel("PC | MP HUD")
        self.brand_label.setStyleSheet("""
            font-family: 'Segoe UI', Tahoma, sans-serif;
            font-size: 32px; font-weight: 900; color: #ffffff;
            letter-spacing: -1px; background: transparent;
        """)
        brand_lay.addWidget(self.brand_label)

        self.server_label = QLabel("RO.sv-1")
        self.server_label.setStyleSheet("""
            font-family: 'Segoe UI', Tahoma, sans-serif;
            font-size: 20px; font-weight: 400; color: #cccccc;
            background: transparent;
        """)
        brand_lay.addWidget(self.server_label)

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(40, 40)
        # Чистый стиль без margin и border (всё сделаем через код)
        self.status_dot.setStyleSheet("background-color: #2ecc71; border-radius: 7px;")
        
        # Настраиваем тень один раз
        self.dot_shadow = QGraphicsDropShadowEffect()
        self.dot_shadow.setBlurRadius(0)
        self.dot_shadow.setOffset(0)
        self.dot_shadow.setColor(QColor(46, 204, 113))
        self.status_dot.setGraphicsEffect(self.dot_shadow)
        
        brand_lay.addSpacing(5)
        brand_lay.addWidget(self.status_dot)

        top_layout.addWidget(brand_container)
        top_layout.addStretch() # margin-left: auto

        ###ANNCMENTS!!!
        # --- ВИДЖЕТ ЗАДАНИЙ (СЛЕВА ВНИЗУ) ---
        # --- АГРЕССИВНЫЙ ВИДЖЕТ ПРЕДУПРЕЖДЕНИЯ (COMPACT & BRIGHT) ---
        self.task_widget = QWidget(self) 
        self.task_widget.setFixedWidth(380) # Сделали компактнее по ширине
        
        # Главный вертикальный лейаут (с минимальными отступами)
        task_lay = QVBoxLayout(self.task_widget)
        task_lay.setContentsMargins(5, 5, 5, 5) # Почти нет полей
        task_lay.setSpacing(1) # Буквально 1 пиксель между строками

        # Ядовито-красный стиль
        bright_red = "#FF0000"
        
        # --- ЧАСТЬ 1: ЗАГОЛОВОК С ИКОНКОЙ (ATENTION!!!) ---
        attn_container = QWidget()
        attn_lay = QHBoxLayout(attn_container)
        attn_lay.setContentsMargins(0, 0, 0, 0)
        attn_lay.setSpacing(6) # Расстояние между SVG и текстом

        # Загрузка SVG иконки player.svg
        self.attn_icon = QLabel()
        icon_size = 30 # Размер иконки
        
        # Простая функция для рендера SVG в Pixmap (аналогично правой панели)
        import os
        if os.path.exists("player.svg"):
            renderer = QtSvg.QSvgRenderer("player.svg")
            pix = QPixmap(icon_size, icon_size)
            pix.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            renderer.render(painter)
            painter.end()
            self.attn_icon.setPixmap(pix)
        else:
            # Если файла нет, ставим placeholder
            self.attn_icon.setText("⚠")
            self.attn_icon.setStyleSheet(f"color: {bright_red}; font-size: 24px; border: none;")

        attn_lay.addWidget(self.attn_icon, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Текст ATENTION!!! (с твоим написанием)
        self.attn_text = QLabel("ATENTION!!!")
        self.attn_text.setStyleSheet(f"""
            color: {bright_red};
            font-family: 'Segoe UI', Arial;
            font-size: 26px; /* Крупно и жирно */
            font-weight: 900;
            background: transparent;
            border: none;
            letter-spacing: -1px; /* Сжатый текст */
        """)
        attn_lay.addWidget(self.attn_text, alignment=Qt.AlignmentFlag.AlignVCenter)
        attn_lay.addStretch() # Прижимаем всё влево

        task_lay.addWidget(attn_container) # Сначала добавляем заголовок

        # --- ЧАСТЬ 2: ЧЕК-ЛИСТ ДЕЙСТВИЙ ---
        # Стиль для пунктов (поменьше и покомпактнее заголовка)
        style_red_task = f"color: {bright_red}; font-family: 'Segoe UI'; font-size: 16px; font-weight: 800; background: transparent; border: none;"
        
        self.step_left = QLabel("RESET [<-LEFT]")
        self.step_right = QLabel("BACK [RIGHT->]")
        self.step_nice = QLabel("READY!")

        for lbl in [self.step_left, self.step_right, self.step_nice]:
            lbl.setStyleSheet(style_red_task)
            lbl.setFixedHeight(22) # Зажали высоту строки
            
            # Шрифт с небольшим сжатием для компактности
            font = lbl.font()
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.2)
            lbl.setFont(font)
            
            # Тень оставляем, чтобы читалось на любом фоне
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(3)
            shadow.setColor(QColor(0, 0, 0, 255))
            shadow.setOffset(1, 1) # Тень поменьше
            lbl.setGraphicsEffect(shadow)
            task_lay.addWidget(lbl)

        self.task_widget.adjustSize() 
        self.task_widget.hide()
        self.task_state = 0


        # --- СЕКЦИЯ ИГРОКА (АБСОЛЮТНАЯ ЦЕНТРОВКА) ---
        # Важно: указываем self как родителя, чтобы виджет летал поверх лейаутов
        self.player_center_widget = QWidget(self) 
        self.player_center_widget.setFixedHeight(70) # Высота как у top_bar
        
        player_lay = QHBoxLayout(self.player_center_widget)
        player_lay.setContentsMargins(0, 0, 0, 0)
        player_lay.setSpacing(12)

        # Твоя квадратная аватарка
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(44, 44)
        self.avatar_label.setStyleSheet("""
            border: 2px solid #000000;
            border-radius: 4px;
            background-color: #000000;
        """)
        self.avatar_label.setScaledContents(True)

        self.nickname_label = QLabel("STEAM PLAYER")
        self.nickname_label.setStyleSheet("font-family: 'Segoe UI'; font-size: 16px; font-weight: 900; color: white;")
        # --- ДОБАВЬ ЭТУ СТРОКУ ---
        self.nickname_label.setMinimumWidth(100) # Дай ему запас, чтобы не хавало буквы

        player_lay.addWidget(self.avatar_label)
        player_lay.addWidget(self.nickname_label)
        
        # Магия: подгоняем размер под контент (иконка + текст)
        self.player_center_widget.adjustSize()

        # --- 4. .info-right ---
        # --- 4. .info-right ---
        info_right = QWidget()
        info_lay = QHBoxLayout(info_right)
        info_lay.setContentsMargins(0, 0, 0, 0)
        info_lay.setSpacing(25) 

        time_container = QWidget()
        time_lay = QHBoxLayout(time_container)
        time_lay.setContentsMargins(0, 0, 0, 0)
        time_lay.setSpacing(0)

        self.time_label = QLabel()
        self.time_label.setStyleSheet("font-family: 'Courier New'; font-size: 22px; font-weight: bold; color: #f1c40f; background: transparent;")

        self.colon_label = QLabel(":")
        self.colon_label.setStyleSheet(self.time_label.styleSheet())
        
        # Чтобы объект не удалялся, привязываем его родителем к label
        self.colon_effect = QGraphicsOpacityEffect(self.colon_label) 
        self.colon_label.setGraphicsEffect(self.colon_effect)

        self.minutes_label = QLabel()
        self.minutes_label.setStyleSheet(self.time_label.styleSheet())

        time_lay.addWidget(self.time_label)
        time_lay.addWidget(self.colon_label)
        time_lay.addWidget(self.minutes_label)

        # !!! ВОТ ЭТА СТРОЧКА БЫЛА ПРОПУЩЕНА (Добавляем часы в правую панель) !!!
        info_lay.addWidget(time_container) 

        self.divider = QLabel()
        # Сделаем чуть шире (было 1, станет 2) и выше, чтобы градиент раскрылся
        self.divider.setFixedSize(2, 30) 
        
        # Обновляем градиент: 
        # Добавляем больше точек (stop), чтобы края были максимально мягкими (fade effect)
        self.divider.setStyleSheet("""
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1, 
                stop:0 transparent, 
                stop:0.2 rgba(255, 255, 255, 0.1), 
                stop:0.5 rgba(255, 255, 255, 0.4), 
                stop:0.8 rgba(255, 255, 255, 0.1), 
                stop:1 transparent
            );
            border: none;
        """)
        info_lay.addWidget(self.divider)

        self.date_label = QLabel()
        self.date_label.setStyleSheet("""
            font-family: 'Courier New', Courier, monospace;
            font-size: 22px; font-weight: bold; color: #95a5a6; background: transparent;
        """)
        info_lay.addWidget(self.date_label)
        top_layout.addWidget(info_right)

        # --- 5. .actions-right ---
        actions_right = QWidget()
        actions_lay = QHBoxLayout(actions_right)
        actions_lay.setContentsMargins(0, 0, 0, 0)
        actions_lay.setSpacing(10) # gap: 10px
        actions_lay.addSpacing(25) # margin-left: 25px

        self.search_btn = self._create_btn()
        self.search_btn.setText("🔍")
        self.theme_btn = self._create_btn()
        self.theme_btn.setText("☀")
        actions_lay.addWidget(self.search_btn)
        actions_lay.addWidget(self.theme_btn)
        #top_layout.addWidget(actions_right)

        main_layout.addWidget(self.top_bar)
        main_layout.addStretch()

        # ==========================================
        # АБСОЛЮТНЫЕ ЭЛЕМЕНТЫ
        # ==========================================
        # .dropdown-menu
        self.dropdown = QWidget(self)
        self.dropdown.setFixedSize(200, 210)
        self.dropdown.setStyleSheet("""
            background: rgba(20, 20, 20, 0.95);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
        """)
        self.dropdown.hide()

        drop_lay = QVBoxLayout(self.dropdown)
        drop_lay.setContentsMargins(8, 8, 8, 8) # padding: 8px
        drop_lay.setSpacing(6) # gap: 6px

        dm_items = ["Website", "Facebook Page", "Facebook Group", "YouTube"]
        for txt in dm_items:
            item = QLabel(f"  {txt}")
            item.setCursor(Qt.CursorShape.PointingHandCursor)
            item.setStyleSheet("""
                QLabel { padding: 8px 10px; border-radius: 6px; color: white;
                         font-size: 13px; font-family: 'Segoe UI'; background: rgba(255,255,255,0.05); }
                QLabel:hover { background: rgba(255,255,255,0.15); }
            """)
            drop_lay.addWidget(item)

        # .country-absolute
        # .country-absolute
        self.romania_container = QWidget(self)
        rom_lay = QHBoxLayout(self.romania_container)
        rom_lay.setSpacing(0)
        rom_lay.setContentsMargins(0, 0, 0, 0)
        # Прижимаем всё содержимое влево, чтобы не было дырок
        rom_lay.setAlignment(Qt.AlignmentFlag.AlignLeft) 

        ro_parts = [("Ro", "#002B7F"), ("ma", "#FCD116"), ("nia", "#CE1126")]
        self.rom_labels = []
        for txt, color in ro_parts:
            lbl = QLabel(txt)
            # Убрали letter-spacing для слитности
            lbl.setStyleSheet(f"""
                color: {color}; font-size: 13px; font-weight: 700;
                font-family: 'Segoe UI'; background: transparent;
                padding: 0px; margin: 0px;
            """)
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(10)
            shadow.setColor(QColor(color))
            shadow.setOffset(0)
            lbl.setGraphicsEffect(shadow)
            
            # Устанавливаем минимальный размер, чтобы QLabel не "раздувался"
            lbl.adjustSize() 
            
            rom_lay.addWidget(lbl)
            self.rom_labels.append(lbl)
        
        # Фишка: фиксируем размер контейнера по содержимому
        self.romania_container.adjustSize()

        # ==========================================
        # ТАЙМЕРЫ И АНИМАЦИИ
        # ==========================================
        self.timer_time = QTimer(self)
        self.timer_time.timeout.connect(self.update_time)
        self.timer_time.start(1000)
        self.update_time()

        self.timer_blink = QTimer(self)
        self.timer_blink.timeout.connect(self.blink_colon)
        self.timer_blink.start(500) # @keyframes blink 1s infinite

        self.timer_pulse = QTimer(self)
        self.timer_pulse.timeout.connect(self.pulse_dot)
        self.timer_pulse.start(16) # ~60 FPS для плавности
        self.pulse_t = 0.0

        # === ВСТАВЛЯТЬ СЮДА ===
        self.setup_right_panel() 
        # ======================
        # === ВСТАВИТЬ В __init__ ===
        self.setup_chat_panel()

        # Station blink timer (for current station orange blink)
        self._current_station_label = None
        self._station_blink_state = True
        self._station_blink_timer = QTimer(self)
        self._station_blink_timer.timeout.connect(self._blink_current_station)
        self._station_blink_timer.start(400)

        # СОЗДАЕМ ОТДЕЛЬНУЮ ЛИНИЮ-НАКЛАДКУ
        self.top_line = QFrame(self)
        self.top_line.setFixedHeight(2) # Толщина линии
        self.top_line.setStyleSheet("background-color: rgba(255, 255, 255, 0.4); border: none;")
        
        self.update_positions()
        # Теперь поднимаем именно ЭТУ линию в самый топ
        self.top_line.raise_()

        self.update_positions()

        # Таймер обновления данных (раз в 5 секунд)
        self.data_timer = QTimer(self)
        self.data_timer.timeout.connect(self.fetch_data)
        self.data_timer.start(2000)

        # Сразу загружаем первый раз
        self.fetch_data()
        self.fetch_steam_profile()

        # Таймер слежения за активным окном: показываем худ только поверх игры
        self._game_focused = False
        self.setWindowOpacity(0.0)  # скрыт до первой проверки

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(300)

        self._focus_timer = QTimer(self)
        self._focus_timer.timeout.connect(self._check_game_focus)
        self._focus_timer.start(300)

    

    def show_task_widget(self):
        self.task_shown = True
        self.task_state = 0
        self.task_widget.show()
        self.task_widget.adjustSize() # ПЕРЕСЧИТАЛИ
        self.update_positions()       # ПЕРЕДВИНУЛИ
        self.blink_task_timer.start(150)

    def hide_task_widget(self):
        self.blink_task_timer.stop()
        self.task_widget.hide()

    def _install_keyboard_hook(self):
        def _hook_thread():
            u32 = ctypes.windll.user32
            u32.SetWindowsHookExW.restype  = ctypes.c_void_p
            u32.SetWindowsHookExW.argtypes = [
                ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD
            ]
            u32.CallNextHookEx.restype  = ctypes.c_long
            u32.CallNextHookEx.argtypes = [
                ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
            ]

            _HOOKPROC = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
            )

            def _proc(nCode, wParam, lParam):
                if nCode >= 0 and wParam in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
                    kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                    if kb.vkCode == 0x25:
                        print("[HUD] KEY: LEFT")
                        self.key_signal.emit("left")
                    elif kb.vkCode == 0x27:
                        print("[HUD] KEY: RIGHT")
                        self.key_signal.emit("right")
                return u32.CallNextHookEx(None, nCode, wParam, lParam)

            # Ссылка на callback — обязательно хранить в этом потоке
            proc_ref = _HOOKPROC(_proc)
            hook = u32.SetWindowsHookExW(_WH_KEYBOARD_LL, proc_ref, None, 0)

            if hook:
                print(f"[HUD] Keyboard hook OK, id={hook}")
            else:
                err = ctypes.windll.kernel32.GetLastError()
                print(f"[HUD] Keyboard hook FAILED, WinError={err}")
                return

            # Message pump на ЭТОМ же потоке — без него callback никогда не вызовется
            msg = wintypes.MSG()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))

            u32.UnhookWindowsHookEx(hook)

        t = threading.Thread(target=_hook_thread, daemon=True)
        t.start()
        self._kb_thread = t

    def _check_game_focus(self):
        proc, fg_hwnd = _fg_proc_name()
        try:
            if fg_hwnd and fg_hwnd == int(self.winId()):
                return
        except Exception:
            pass
        active = proc in _TARGET_PROCS if proc else False
        if active == self._game_focused:
            return
        self._game_focused = active

        self._fade_anim.stop()
        self._fade_anim.setStartValue(self.windowOpacity())
        if active:
            # Появление: быстро, ускорение в начале
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.setDuration(300)
            self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        else:
            # Исчезновение: плавнее, замедление к концу
            self._fade_anim.setEndValue(0.0)
            self._fade_anim.setDuration(600)
            self._fade_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_anim.start()


    def blink_task_text(self):
        # Стробоскоп: мигаем всем виджетом сразу
        if self.task_widget.isVisible() or self.task_state < 2:
            self.task_widget.setVisible(not self.task_widget.isVisible())

    def fetch_steam_profile(self):
        try:
            steam_id = "76561199571446604"
            url = f"https://steamcommunity.com/profiles/{steam_id}/?xml=1"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                from xml.dom import minidom
                dom = minidom.parseString(res.text)
                name = dom.getElementsByTagName('steamID')[0].firstChild.data
                avatar_url = dom.getElementsByTagName('avatarMedium')[0].firstChild.data
                
                img_data = requests.get(avatar_url).content
                pixmap = QPixmap()
                pixmap.loadFromData(img_data)
                
                # Просто ставим картинку как есть, QLabel её "оквардатит" сам
                self.avatar_label.setPixmap(pixmap)
                self.nickname_label.setText(name.upper())
        except:
            self.nickname_label.setText("OFFLINE")


    def setup_chat_panel(self):
        self.chat_widget = QFrame(self)
        self.chat_widget.setFixedWidth(400) 
        self.chat_widget.setFixedHeight(200) 
        self.chat_widget.setStyleSheet("background-color: #000000; border: 1px solid #1a1a1a; border-top-left-radius: 0px; border-top-right-radius: 0px; border-bottom-left-radius: 10px; border-bottom-right-radius: 10px;")

        chat_layout = QVBoxLayout(self.chat_widget)
        # Устанавливаем отступы основного контейнера. 
        # 10px слева — это будет наша "базовая линия" выравнивания
        chat_layout.setContentsMargins(10, 10, 10, 10) 
        chat_layout.setSpacing(4)

        # 1. Заголовок (убираем лишние margin, чтобы не прыгал)
        chat_title = QLabel("PC | MP CHAT")
        chat_title.setStyleSheet("color: #FFFFFF; font-family: 'Segoe UI'; font-size: 11px; font-weight: 900; border: none; margin: 0px; padding: 0px;")
        chat_layout.addWidget(chat_title)

        # Область сообщений
        self.chat_area = QScrollArea()
        self.chat_area.setWidgetResizable(True)
        self.chat_area.setStyleSheet("background: transparent; border: none;")
        self.chat_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        msg_container = QWidget()
        msg_container.setStyleSheet("background: transparent;")
        self.msg_layout = QVBoxLayout(msg_container)
        # ВАЖНО: Тут ставим 0, так как отступ уже задан в chat_layout
        self.msg_layout.setContentsMargins(0, 0, 0, 0) 
        self.msg_layout.setSpacing(6)
        self.msg_layout.addStretch()

        samples = [
            ("<span style='color: #00eeff; font-weight: 900;'>Player1:</span><span style='color:#ffffff;'> Ready</span>", "14:53"),
            ("<span style='color: #00ff55; font-weight: 900;'>Arad IDM:</span><span style='color:#ffffff;'> Proceed to P2</span>", "14:55"),
            ("<span style='color: #ff1111; font-weight: 900;'>ATENTION!</span><span style='color:#ff9900;'> Signal Overrun</span>", "14:58")
        ]

        for content, time_str in samples:
            msg_block = QWidget()
            msg_block_layout = QVBoxLayout(msg_block)
            # 2. Убираем ВСЕ отступы у блока сообщения, чтобы текст лип к левому краю контейнера
            msg_block_layout.setContentsMargins(0, 0, 0, 0) 
            msg_block_layout.setSpacing(0)

            text_label = QLabel(content)
            # Добавляем padding: 0px, чтобы системные рамки QLabel не двигали текст
            text_label.setStyleSheet("color: #eeeeee; font-family: 'Segoe UI Semibold'; font-size: 12px; border: none; padding: 0px;")
            
            time_label = QLabel(time_str)
            # 3. Время: убираем 2px, которые его двигали вправо. Ставим 0!
            time_label.setStyleSheet("color: #444444; font-family: 'Segoe UI'; font-size: 9px; font-weight: 700; border: none; padding: 0px;")
            time_label.setContentsMargins(0, -2, 0, 0) 

            msg_block_layout.addWidget(text_label)
            msg_block_layout.addWidget(time_label)
            self.msg_layout.addWidget(msg_block)

        self.chat_area.setWidget(msg_container)
        chat_layout.addWidget(self.chat_area)

        # Блок ввода
        input_container = QHBoxLayout()
        input_container.setContentsMargins(0, 0, 0, 0) # Убираем отступы контейнера ввода
        input_container.setSpacing(5)

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Write here...")
        # 4. СИНХРОНИЗАЦИЯ: Чтобы текст внутри Write here... был на той же линии, 
        # что и сообщения выше, padding-left должен быть около 2-5px, 
        # так как QLineEdit сам по себе имеет рамку.
        self.chat_input.setStyleSheet("""
            QLineEdit {
                background: #050505;
                border: 1px solid #1a1a1a;
                border-radius: 0px;
                color: #FFFFFF;
                font-family: 'Segoe UI';
                font-size: 12px;
                font-weight: 600;
                padding: 6px 5px; /* 5px слева — будет идеально */
            }
            QLineEdit:focus { border: 1px solid #333333; }
        """)

        self.send_btn = QPushButton()
        self.send_btn.setFixedSize(32, 32)
        if os.path.exists("send.svg"):
            self.send_btn.setIcon(QIcon("send.svg"))
            self.send_btn.setIconSize(QSize(18, 18))
        self.send_btn.setStyleSheet("QPushButton { background: transparent; border: none; } QPushButton:hover { background: #111111; }")

        input_container.addWidget(self.chat_input)
        input_container.addWidget(self.send_btn)
        chat_layout.addLayout(input_container)


    def setup_left_panel(self):
        # --- НАСТРОЙКИ ---
        scale = 0.6          
        box_size = int(100 * scale) 
        radius = 15 * scale  
        
        # Основной виджет панели
        self.left_panel = QFrame(self) # Поменяли на QFrame, чтобы внутри были слои
        self.left_panel.setFixedSize(box_size, box_size + 20) # +20px снизу для текста
        self.left_panel.setStyleSheet("background: transparent; border: none;")

        # 1. РИСУЕМ ФОН (Квадрат с закруглением слева)
        canvas = QPixmap(box_size, box_size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.moveTo(box_size, 0) 
        path.lineTo(radius, 0)
        path.arcTo(0, 0, radius * 2, radius * 2, 90, 90)
        path.lineTo(0, box_size - radius)
        path.arcTo(0, box_size - radius * 2, radius * 2, radius * 2, 180, 90)
        path.lineTo(box_size, box_size)
        path.closeSubpath()

        painter.setBrush(QBrush(QColor("#010101")))
        painter.setPen(QPen(QColor("#151515"), 1))
        painter.drawPath(path)

        # Рисуем линзу
        center_y = box_size / 2
        center_x = box_size / 2 + (5 * scale)
        self.draw_real_signal(painter, center_x, center_y, "#00ff44", True, scale)
        painter.end()

        # Помещаем картинку в отдельный Label
        self.lp_bg = QLabel(self.left_panel)
        self.lp_bg.setPixmap(canvas)
        self.lp_bg.setGeometry(0, 0, box_size, box_size)

        # 2. ТЕКСТ С ДИСТАНЦИЕЙ (SIG)
        self.sig_dist_label = QLabel("567m", self.left_panel)
        # Сдвигаем текст: x=center_x - ширина/2, y=сразу под квадратом
        self.sig_dist_label.setFixedWidth(box_size)
        self.sig_dist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Стили: белый цвет, жирный, шрифт Segoe UI
        self.sig_dist_label.setStyleSheet("""
            color: #ffffff; 
            font-family: 'Segoe UI'; 
            font-size: 11px; 
            font-weight: 900; 
            background: transparent;
        """)
        
        # Позиционируем текст ровно под линзой
        # center_x - 5 (корректировка)
        self.sig_dist_label.move(int(center_x - box_size/2), box_size + 2)

        # Добавляем тень для текста, чтобы читался на фоне игры
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(4)
        shadow.setColor(QColor(0, 0, 0, 255))
        shadow.setOffset(1, 1)
        self.sig_dist_label.setGraphicsEffect(shadow)

        self.left_panel.show()

    # ОБЯЗАТЕЛЬНО ДОБАВЬ ЭТОТ МЕТОД НИЖЕ (проверь отступы!)
    def draw_real_signal(self, painter, x, y, color_hex, is_on, scale):
        color = QColor(color_hex)
        r_hood = 30 * scale
        r_lens = 22 * scale
        
        # Козырек
        h_grad = QLinearGradient(x-r_hood, y-r_hood, x+r_hood, y+r_hood)
        h_grad.setColorAt(0, QColor("#000000"))
        h_grad.setColorAt(0.5, QColor("#1c1c1c"))
        h_grad.setColorAt(1, QColor("#000000"))
        painter.setBrush(h_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(x, y), r_hood, r_hood)

        if is_on:
            # Свечение
            glow1 = QRadialGradient(x, y, 50 * scale)
            glow1.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 130))
            glow1.setColorAt(1, Qt.GlobalColor.transparent)
            painter.setBrush(glow1)
            painter.drawEllipse(QPointF(x, y), 50 * scale, 50 * scale)
            
            glow2 = QRadialGradient(x, y, 28 * scale)
            glow2.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 255))
            glow2.setColorAt(1, Qt.GlobalColor.transparent)
            painter.setBrush(glow2)
            painter.drawEllipse(QPointF(x, y), 28 * scale, 28 * scale)

            # Матрица диодов
            rings = [(0, 1), (5, 6), (10, 12), (15, 18), (20, 24)]
            for r_base, count in rings:
                r = r_base * scale
                for i in range(count):
                    angle = (360 / count * i) if count > 0 else 0
                    rad = math.radians(angle)
                    dx, dy = x + r * math.cos(rad), y + r * math.sin(rad)
                    
                    dot_grad = QRadialGradient(dx, dy, 2.8 * scale)
                    dot_grad.setColorAt(0, QColor("#ffffff"))
                    dot_grad.setColorAt(0.3, color)
                    dot_grad.setColorAt(1, QColor(0,0,0,200))
                    painter.setBrush(dot_grad)
                    painter.drawEllipse(QPointF(dx, dy), 2.5*scale, 2.5*scale)
        else:
            painter.setBrush(QColor("#020202"))
            painter.drawEllipse(QPointF(x, y), r_lens, r_lens)




    def setup_right_panel(self):
        from PyQt6 import QtWidgets, QtCore, QtSvg
        from PyQt6.QtGui import QPixmap, QPainter, QColor
        from PyQt6.QtWidgets import QScrollArea
        import os

        def get_svg_label(path, size):
            lbl = QLabel()
            lbl.setFixedSize(size, size)
            if os.path.exists(path):
                renderer = QtSvg.QSvgRenderer(path)
                pix = QPixmap(size, size)
                pix.fill(QtCore.Qt.GlobalColor.transparent)
                painter = QPainter(pix)
                renderer.render(painter)
                painter.end()
            else:
                pix = QPixmap(size, size)
                pix.fill(QtCore.Qt.GlobalColor.transparent)
                painter = QPainter(pix)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setBrush(QColor(255, 255, 255, 180))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                if "train" in path: painter.drawRoundedRect(2, 4, size-4, size-8, 2, 2)
                else: painter.drawEllipse(4, 4, size-8, size-8)
                painter.end()
            lbl.setPixmap(pix)
            return lbl

        self.right_panel = QFrame(self)
        self.right_panel.setFixedWidth(200)
        self.right_panel.setFixedHeight(280)
        self.right_panel.setStyleSheet("""
            QFrame {
                background-color: #050505; 
                border-left: 2px solid rgba(255, 255, 255, 0.3);
                border-bottom: 2px solid rgba(255, 255, 255, 0.3);
                border-bottom-left-radius: 12px;
                border: none;
            }
        """)

        self.panel_layout = QVBoxLayout(self.right_panel)
        self.panel_layout.setContentsMargins(12, 10, 12, 4)
        self.panel_layout.setSpacing(5)

        # Номер поезда (Динамический)
        train_info_lay = QHBoxLayout()
        train_icon = get_svg_label("train.svg", 16)
        self.train_num_label = QLabel("---")
        self.train_num_label.setStyleSheet("font-family: 'Segoe UI'; font-size: 12px; font-weight: 800; border: none; background: transparent;")
        train_info_lay.addWidget(train_icon)
        train_info_lay.addWidget(self.train_num_label)
        train_info_lay.addStretch()
        # ВСТАВЬ ЭТУ СТРОКУ НИЖЕ:
        #train_info_lay.addWidget(QLabel("SIG 567m", styleSheet="color: #2ecc71; font-family: 'Segoe UI'; font-size: 11px; font-weight: 800; font-style: italic; border: none;"))
        self.panel_layout.addLayout(train_info_lay)

        # Маршрут (Динамический)
        route_info_lay = QHBoxLayout()
        route_icon = get_svg_label("route.svg", 16)
        self.route_text_label = QLabel("Loading...")
        self.route_text_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-family: 'Segoe UI'; font-size: 11px; border: none;")
        route_info_lay.addWidget(route_icon)
        route_info_lay.addWidget(self.route_text_label)
        route_info_lay.addStretch()
        # ВСТАВЬ ЭТУ СТРОКУ НИЖЕ:
        dst_container = QWidget()
        dst_container.setStyleSheet("background: transparent;")
        dst_inner = QHBoxLayout(dst_container)
        dst_inner.setContentsMargins(0, 0, 0, 0)
        dst_inner.setSpacing(3)
        dst_icon = get_svg_label("metr.svg", 14)
        self.dst_label = QLabel("102m")
        self.dst_label.setStyleSheet("color: #ffffff; font-family: 'Segoe UI'; font-size: 11px; font-weight: 900; border: none; background: transparent;")
        dst_inner.addWidget(dst_icon)
        dst_inner.addWidget(self.dst_label)
        route_info_lay.addWidget(dst_container)
        self.panel_layout.addLayout(route_info_lay)

        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")
        self.panel_layout.addWidget(sep)

        # Скролл
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 6px; border: none; }
            QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.3); border-radius: 3px; min-height: 20px; }
        """)
        
        self.tt_frame = QFrame()
        self.tt_frame.setStyleSheet("background: transparent; border: none;")
        self.tt_grid = QGridLayout(self.tt_frame)
        self.tt_grid.setContentsMargins(8, 0, 8, 0)
        self.tt_grid.setHorizontalSpacing(10)
        self.tt_grid.setVerticalSpacing(12)

        self.scroll_area.setWidget(self.tt_frame)
        self.panel_layout.addWidget(self.scroll_area)
        self.right_panel.show()

    def update_right_panel_pos(self):
        if hasattr(self, 'right_panel'):
            self.right_panel.move(self.width() - self.right_panel.width(), 75)

    



    def _create_btn(self):
        btn = QPushButton()
        btn.setFixedSize(45, 45)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                border: 2px solid #ffffff;
                border-radius: 10px;
                background: transparent;
                color: white; font-size: 18px;
            }
            QPushButton:hover { background: rgba(255, 255, 255, 0.15); }
            QPushButton:pressed { background: rgba(255, 255, 255, 0.25); }
        """)
        return btn

    def toggle_dropdown(self):
        if self.dropdown.isVisible():
            self.dropdown.hide()
        else:
            self.dropdown.show()
            self.update_positions()

    def update_positions(self):
        # .dropdown-menu: top: 70px, left: 55px
        self.dropdown.move(55, 70)
        
        # .country-absolute: top: 46px, left: calc(100% - 215px), transform: translateX(-50%)
        x = int(self.width() - 233 - (self.romania_container.width() / 2))
        self.romania_container.move(x, 46)

        # ПОЗИЦИЯ НАКЛАДНОЙ ЛИНИИ (на 68-м пикселе, чтобы закрыть стык)
        if hasattr(self, 'top_line'):
            self.top_line.setGeometry(0, 68, self.width(), 2)

        # === ПАНЕЛЬ СВЕТОФОРА (ТЕПЕРЬ СПРАВА ПОД РАСПИСАНИЕМ) ===
        if hasattr(self, 'left_panel') and hasattr(self, 'right_panel'):
            # Вычисляем X: такой же, как у правой панели (чтобы прилегало к правому краю)
            # Если нужно, чтобы он был выровнен по правой стенке:
            x_pos = self.width() - self.left_panel.width()
            
            # Вычисляем Y: позиция правой панели + её высота + отступ (например, 10px)
            y_pos = self.right_panel.y() + self.right_panel.height() + 10
            
            self.left_panel.move(x_pos, y_pos)
            self.left_panel.raise_()

        if hasattr(self, 'player_center_widget'):
            # Заставляем пересчитать размер на основе внутреннего контента прямо сейчас
            self.player_center_widget.adjustSize() 
            
            # Добавляем небольшой запас (пикселей 10), чтобы не было впритык
            w = self.player_center_widget.width() + 10 
            
            x_center = (self.width() - w) // 2
            self.player_center_widget.move(x_center, 0)
            self.player_center_widget.raise_()

        # Позиция таск-виджета: снизу слева с отступом 20px
        # Позиция таск-виджета: снизу слева
        # Позиция таск-виджета: СЛЕВА, НО ЧУТЬ НИЖЕ ВЕРХА
        if hasattr(self, 'task_widget'):
            self.task_widget.adjustSize() 
            
            # X остается 30 (отступ слева)
            x_pos = 30
            
            # Y теперь больше (чем больше число, тем ниже упадет виджет)
            # Попробуй 150. Если надо еще ниже — ставь 200 или 300.
            y_pos = 150 
            
            self.task_widget.move(x_pos, y_pos)
        # Позиция чата: СЛЕВА ВНИЗУ
        if hasattr(self, 'chat_widget'):
            # 20px отступ от левого края и 20px от нижнего
            x_chat = 20 
            y_chat = self.height() - self.chat_widget.height() - 20
            self.chat_widget.move(x_chat, y_chat)

        # === ВСТАВЛЯТЬ СЮДА ===
        self.update_right_panel_pos()
        # ======================

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_positions()

    def blink_colon(self):
        # Проверяем, существует ли еще объект, чтобы не было RuntimeError
        try:
            if hasattr(self, 'colon_effect') and self.colon_effect:
                cur = self.colon_effect.opacity()
                self.colon_effect.setOpacity(0.0 if cur > 0.0 else 1.0)
        except RuntimeError:
            pass # Если объект всё же удален, просто игнорируем шаг анимации

    def pulse_dot(self):
        # 1. Управляем временем. 
        # Увеличиваем pulse_t. 0.02 — это будет очень плавно.
        self.pulse_t += 0.02
        
        # Используем остаток от деления для создания бесконечного цикла от 0 до 1
        # Это дает линейный рост, который мы сгладим для "сочности"
        progress = self.pulse_t % 1.0 
        
        # Чтобы анимация не была "линейной и топорной", 
        # делаем мягкий вход и выход (эмуляция ease-in-out)
        t = (math.sin(progress * math.pi - math.pi/2) + 1) / 2

        # 2. РАЗМЕР (Масштаб)
        # От 14px до 18px для заметности
        current_size = 14 + int(4 * t)
        
        # Центрируем (контейнер у нас 40x40, как мы договорились)
        margin = (40 - current_size) // 2
        
        # Обновляем стиль (добавил border для четкости)
        self.status_dot.setStyleSheet(f"""
            background-color: #2ecc71; 
            border-radius: {current_size / 2}px; 
            margin: {margin}px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        """)

        # 3. СВЕЧЕНИЕ (Glow)
        # Делаем его ЯРКИМ. В пике (t=1) оно будет очень насыщенным.
        blur = 5 + int(15 * t)  # Размытие от 5 до 20
        
        # Яркость: от 50 (почти нет) до 255 (максимальный неон)
        alpha = 50 + int(205 * t) 
        
        self.dot_shadow.setBlurRadius(blur)
        # Используем ярко-зеленый цвет для тени
        self.dot_shadow.setColor(QColor(0, 255, 100, alpha))



    def _blink_current_station(self):
        self._station_blink_state = not self._station_blink_state
        bright = self._station_blink_state

        # Blink track cell dot (yellow)
        cell = getattr(self, '_current_track_cell', None)
        if cell is not None:
            try:
                cell.set_dot_blink(bright)
            except RuntimeError:
                self._current_track_cell = None

    def fetch_data(self):
        try:
            # Твой рабочий IP и порт
            url = "http://116.203.229.254:3000/get_hud_data"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                # Используем .json(), он сам разберется с кодировкой
                data = response.json()
                self.refresh_timetable(data)
                
                # Делаем точку зеленой — связь стабильна
                self.status_dot.setStyleSheet("background-color: #2ecc71; border-radius: 7px;")
            else:
                print(f"Ошибка сервера: {response.status_code}")
                self.status_dot.setStyleSheet("background-color: #f39c12; border-radius: 7px;")
                
        except Exception as e:
            print(f"Ошибка подключения: {e}")
            # Красная точка — если сервер упадет
            self.status_dot.setStyleSheet("background-color: #e74c3c; border-radius: 7px;")

    def refresh_timetable(self, data):
        from PyQt6 import QtCore
        import re

        # ── Header labels ─────────────────────────────────────────────────────
        train_num = data.get("train_num", "R ----")
        m = re.match(r'^([A-Za-z]+)\s*(\S.*)$', train_num)
        if m:
            cls_part, num_part = m.group(1), m.group(2)
            self.train_num_label.setText(
                f"<span style='color:#ff2222;'>{cls_part}</span>"
                f"&nbsp;<span style='color:#00c8ff;'>{num_part}</span>"
            )
        else:
            self.train_num_label.setText(f"<span style='color:#ffffff;'>{train_num}</span>")

        route = data.get("route", "---")
        parts = route.split(" to ", 1)
        if len(parts) == 2:
            self.route_text_label.setText(
                f"<span style='font-weight:800; text-decoration:underline; color:#ffffff;'>{parts[0]}</span>"
                f"<span style='font-weight:400;'> to </span>"
                f"<span style='font-weight:800; text-decoration:underline; color:#ffffff;'>{parts[1]}</span>"
            )
        else:
            self.route_text_label.setText(route)

        # ── GPS progress ──────────────────────────────────────────────────────
        lat = float(data.get("lat") or 0)
        lon = float(data.get("lon") or 0)
        route_from = data.get("route_from", "")
        route_to = data.get("route_to", "")

        gps = None
        if lat and lon and route_from and route_to:
            try:
                gps = _get_gps_progress(lat, lon, route_from, route_to)
            except Exception as e:
                print(f"[HUD] GPS progress error: {e}")

        # ── Distance label ────────────────────────────────────────────────────
        if gps:
            if gps['on_station']:
                self.dst_label.setText("At(ST):")
                self.dst_label.setStyleSheet(
                    "color: #f1c40f; font-family: 'Segoe UI'; font-size: 11px;"
                    " font-weight: 900; border: none; background: transparent;"
                )
            else:
                rem = gps['remaining']
                dist_str = f"{rem / 1000:.1f}km" if rem >= 1000 else f"{int(rem)}m"
                self.dst_label.setText(dist_str)
                self.dst_label.setStyleSheet(
                    "color: #ffffff; font-family: 'Segoe UI'; font-size: 11px;"
                    " font-weight: 900; border: none; background: transparent;"
                )

        # ── Station status helper ─────────────────────────────────────────────
        def station_status(name):
            if not gps:
                return 'future'
            order = gps['order']
            if name not in order:
                return 'future'
            idx = order.index(name)
            if gps['on_station'] and name == gps['current_station']:
                return 'current'
            if idx <= gps['passed_idx']:
                return 'passed'
            if name == gps['next_station']:
                return 'next'
            return 'future'

        # ── Segment style between consecutive displayed stations ───────────────
        def seg_style(a_name, b_name):
            a = station_status(a_name)
            b = station_status(b_name)
            if not gps:
                return _TrackCell._SEG_SOLID
            if a == 'passed' and b == 'passed':
                return _TrackCell._SEG_DIM
            if a == 'passed' and b == 'current':
                return _TrackCell._SEG_DIM
            if a in ('passed', 'current') and b == 'next' and not gps['on_station']:
                return _TrackCell._SEG_DASHED
            return _TrackCell._SEG_SOLID

        # ── Stop old shimmer before clearing grid ─────────────────────────────
        old_badge = getattr(self, '_current_shimmer_badge', None)
        if old_badge is not None:
            try:
                old_badge.stop()
            except RuntimeError:
                pass
            self._current_shimmer_badge = None

        # ── Rebuild grid ──────────────────────────────────────────────────────
        while self.tt_grid.count():
            item = self.tt_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._current_station_label = None
        self._current_track_cell = None

        stations = data.get("stations", [])
        if not stations:
            return

        t_style = "font-family: 'Segoe UI'; font-size: 10px; font-weight: 800;"
        n = len(stations)

        for i, (name, arr, dep) in enumerate(stations):
            status = station_status(name)

            # ── TrackCell (line segment + dot) ────────────────────────────────
            seg_above = _TrackCell._SEG_NONE if i == 0 else seg_style(stations[i - 1][0], name)
            seg_below = _TrackCell._SEG_NONE if i == n - 1 else seg_style(name, stations[i + 1][0])

            if status == 'passed':
                dot_color = QColor(255, 255, 255, 60)
            elif status == 'current':
                dot_color = QColor("#f1c40f")
            elif status == 'next':
                dot_color = QColor("#2ecc71")
            else:
                dot_color = QColor(255, 255, 255, 200)

            cell = _TrackCell(dot_color, seg_above, seg_below)
            self.tt_grid.addWidget(cell, i, 1, QtCore.Qt.AlignmentFlag.AlignCenter)

            if status == 'current':
                self._current_track_cell = cell
                self._station_blink_state = True

            # ── Time column ───────────────────────────────────────────────────
            time_container = QWidget()
            time_v = QVBoxLayout(time_container)
            time_v.setContentsMargins(0, 0, 0, 0)
            time_v.setSpacing(0)

            if status == 'passed':
                arr_color = "rgba(255, 255, 255, 0.25)"
                dep_color = "rgba(255, 255, 255, 0.15)"
            else:
                arr_color = "white"
                dep_color = "rgba(255, 255, 255, 0.4)"

            a_l = QLabel(arr)
            a_l.setStyleSheet(f"color: {arr_color}; {t_style}")
            a_l.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

            d_l = QLabel(dep if dep != "--:--" else " ")
            d_l.setStyleSheet(f"color: {dep_color}; {t_style}")
            d_l.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

            time_v.addWidget(a_l)
            time_v.addWidget(d_l)

            # ── Station name (col 2) ──────────────────────────────────────────
            if status == 'passed':
                st_l = QLabel(name)
                font = st_l.font()
                font.setStrikeOut(True)
                st_l.setFont(font)
                st_l.setStyleSheet(
                    "color: rgba(255,255,255,0.25); font-family: 'Segoe UI';"
                    " font-size: 12px; font-weight: 800; border: none;"
                )
                name_widget = st_l

            elif status == 'current':
                # White label + shimmer badge
                name_container = QWidget()
                name_container.setStyleSheet("background: transparent;")
                name_lay = QHBoxLayout(name_container)
                name_lay.setContentsMargins(0, 0, 0, 0)
                name_lay.setSpacing(5)

                st_l = QLabel(name)
                st_l.setStyleSheet(
                    "color: white; font-family: 'Segoe UI';"
                    " font-size: 12px; font-weight: 800; border: none;"
                )
                badge = _ShimmerBadge(name_container)
                self._current_shimmer_badge = badge

                name_lay.addWidget(st_l)
                name_lay.addWidget(badge)
                name_lay.addStretch()

                name_widget = name_container
                self._current_station_label = st_l

            elif status == 'next':
                st_l = QLabel(name)
                st_l.setStyleSheet(
                    "color: #2ecc71; font-family: 'Segoe UI';"
                    " font-size: 12px; font-weight: 800; border: none;"
                )
                name_widget = st_l

            else:
                st_l = QLabel(name)
                st_l.setStyleSheet(
                    "color: white; font-family: 'Segoe UI';"
                    " font-size: 12px; font-weight: 800; border: none;"
                )
                name_widget = st_l

            self.tt_grid.addWidget(time_container, i, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.tt_grid.addWidget(name_widget, i, 2, QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.tt_grid.setColumnStretch(0, 0)
        self.tt_grid.setColumnStretch(1, 0)
        self.tt_grid.setColumnStretch(2, 1)



    def update_time(self):
        now = QDateTime.currentDateTime()
        # Часы в один лейбл
        self.time_label.setText(now.toString("HH"))
        # Минуты в другой
        self.minutes_label.setText(now.toString("mm"))
        # Дата отдельно
        self.date_label.setText(now.toString("dd/MM/yyyy"))

if __name__ == '__main__':
    # ИСПРАВЛЕНИЕ: Вызываем политику ДО создания QApplication
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    
    ex = Overlay()
    # Удаляем вызов политики из __init__ класса Overlay!
    
    sys.exit(app.exec())