import sys
import math
import requests # Нужно для загрузки данных из интернета
import random
import os
from PyQt6 import QtGui
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, 
    QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QGridLayout, QLineEdit, QScrollArea, 
)
from PyQt6.QtCore import Qt, QTimer, QSize, QRect, QPoint, QDateTime, QPointF, pyqtSignal
from PyQt6 import QtCore, QtSvg
from PyQt6.QtGui import (
    QColor, QPixmap, QPainter, QFont, QGuiApplication, 
    QPainterPath, QRegion, QRadialGradient, QLinearGradient, QBrush, QPen, QIcon # Добавили QPen
)
from PyQt6.QtSvg import QSvgRenderer
import keyboard  # Добавь к остальным импортам
from PyQt6 import QtCore
import threading # Добавь это

try:
    import ctypes
    import ctypes.wintypes
    _user32 = ctypes.windll.user32
    _WINDOWS = True
except (AttributeError, OSError):
    _WINDOWS = False

# ── Station zone polygons (mirrored from map JS) ──────────────────────────────
STATION_ZONES = {
    "Arad":       [(46.19227,21.32248),(46.19301,21.32439),(46.18923,21.32760),(46.18848,21.32565)],
    "Glogovat":   [(46.17633,21.41287),(46.17588,21.41276),(46.17728,21.39760),(46.17787,21.39776)],
    "Ghioroc":    [(46.14953,21.58396),(46.14952,21.58338),(46.14762,21.58352),(46.14763,21.58419)],
    "Paulis hc.": [(46.12058,21.58582),(46.12059,21.58637),(46.12240,21.58619),(46.12239,21.58575)],
    "Paulis":     [(46.10721,21.61172),(46.10676,21.61175),(46.10662,21.60836),(46.10703,21.60840)],
    "Radna":      [(46.09431,21.69036),(46.09342,21.69146),(46.09616,21.69554),(46.09705,21.69427)],
}

STATION_CENTERS = {
    name: [sum(p[0] for p in poly)/len(poly), sum(p[1] for p in poly)/len(poly)]
    for name, poly in STATION_ZONES.items()
}

ROUTE_ORDER = {
    "Radna_Arad": ["Radna","Paulis","Paulis hc.","Ghioroc","Glogovat","Arad"],
    "Arad_Radna": ["Arad","Glogovat","Ghioroc","Paulis hc.","Paulis","Radna"],
}

def _haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def _point_in_polygon(lat, lon, polygon):
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        lat1, lon1 = polygon[i]
        lat2, lon2 = polygon[j]
        if ((lat1 > lat) != (lat2 > lat)) and (lon < (lon2-lon1)*(lat-lat1)/(lat2-lat1)+lon1):
            inside = not inside
        j = i
    return inside

def _dist_to_polygon(lat, lon, polygon):
    min_d = float('inf')
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        lat1, lon1 = polygon[i]
        lat2, lon2 = polygon[j]
        dx, dy = lat2-lat1, lon2-lon1
        len2 = dx*dx + dy*dy
        t = max(0, min(1, ((lat-lat1)*dx+(lon-lon1)*dy)/len2)) if len2 > 0 else 0
        d = _haversine(lat, lon, lat1+t*dx, lon1+t*dy)
        if d < min_d:
            min_d = d
    return min_d


class StationTimeline(QWidget):
    """Paints dots + connecting line segments for the station list."""

    STATE_COLORS = {
        'passed':  QColor(80, 80, 80),
        'current': QColor(0xf1, 0xc4, 0x0f),   # yellow
        'next':    QColor(0x00, 0xff, 0x44),    # green
        'future':  QColor(255, 255, 255, 180),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.states = []
        self.setFixedWidth(16)

    def set_states(self, states):
        self.states = states
        self.update()

    def paintEvent(self, event):
        if not self.states:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        n = len(self.states)
        h = max(self.height(), 1)
        row_h = h / n
        cx = self.width() // 2

        for i, state in enumerate(self.states):
            cy = int(i * row_h + row_h / 2)

            # Line to next station
            if i < n - 1:
                cy_next = int((i+1) * row_h + row_h / 2)
                nxt = self.states[i+1]
                if state == 'passed' and nxt in ('next', 'current'):
                    pen = QPen(QColor(0x00, 0xff, 0x44), 2)
                    pen.setStyle(Qt.PenStyle.DashLine)
                    pen.setDashPattern([4.0, 4.0])
                elif state == 'passed':
                    pen = QPen(QColor(80, 80, 80, 160), 2)
                elif state in ('current', 'next'):
                    pen = QPen(QColor(255, 255, 255, 50), 2)
                else:
                    pen = QPen(QColor(255, 255, 255, 50), 2)
                painter.setPen(pen)
                painter.drawLine(cx, cy + 5, cx, cy_next - 5)

            # Dot
            color = self.STATE_COLORS.get(state, QColor(255, 255, 255, 180))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            r = 5 if state == 'current' else 4
            painter.drawEllipse(QPointF(cx, cy), r, r)

        painter.end()


class Overlay(QWidget):
    key_signal = pyqtSignal(str) # Сигнал для связи потоков

    def trigger_key_logic(self, key_name):
        # Если виджет не активен — игнорим
        if not self.task_widget.isVisible() and self.task_state != 2:
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

        import keyboard
        # Передаем нажатие в основной поток через сигнал
        # Вместо on_press_key
        # Очищаем всё старое
        keyboard.unhook_all()

        # Создаем функцию-слушателя
        def global_listener():
            while True:
                # wait() блокирует поток до нажатия, это потребляет 0% процессора
                event = keyboard.read_event()
                if event.event_type == keyboard.KEY_DOWN:
                    if event.name == "left":
                        self.key_signal.emit("left")
                    elif event.name == "right":
                        self.key_signal.emit("right")

        # Запускаем слушателя в отдельном потоке, чтобы он не зависел от отрисовки HUD
        listener_thread = threading.Thread(target=global_listener, daemon=True)
        listener_thread.start()

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
            border: 2px solid #070e2e; 
            border-radius: 4px; 
            background-color: #070e2e;
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
        # --- ВОТ СЮДА ВСТАВЛЯЙ ---
        # Регистрируем глобальные нажатия (будут работать везде)
        import keyboard

        # Focus detection: show overlay only when RailWorks is in foreground
        self._game_focused = True
        self._focus_timer = QTimer(self)
        self._focus_timer.timeout.connect(self._check_game_focus)
        self._focus_timer.start(500)


    def show_task_widget(self):
        self.task_state = 0
        self.task_widget.show()
        self.task_widget.adjustSize() # ПЕРЕСЧИТАЛИ
        self.update_positions()       # ПЕРЕДВИНУЛИ
        self.blink_task_timer.start(150)

    def hide_task_widget(self):
        self.blink_task_timer.stop()
        self.task_widget.hide()


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
        self.chat_widget.setStyleSheet("background-color: #000000; border: 1px solid #1a1a1a; border-radius: 0px;")

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
            ("<span style='color: #00d4ff; font-weight: 800;'>Player1:</span> Ready", "14:53"),
            ("<span style='color: #00ff88; font-weight: 800;'>Arad IDM:</span> Proceed to P2", "14:55"),
            ("<span style='color: #ff3333; font-weight: 900;'>ATENTION!</span> Signal Overrun", "14:58")
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

        # Номер поезда (тип — красный, номер — синий)
        train_info_lay = QHBoxLayout()
        train_icon = get_svg_label("train.svg", 16)
        self.train_type_label = QLabel("")
        self.train_type_label.setStyleSheet("color: #cc1111; font-family: 'Segoe UI'; font-size: 12px; font-weight: 800; border: none;")
        self.train_number_label = QLabel("---")
        self.train_number_label.setStyleSheet("color: #3458e1; font-family: 'Segoe UI'; font-size: 12px; font-weight: 800; border: none;")
        train_info_lay.addWidget(train_icon)
        train_info_lay.addSpacing(4)
        train_info_lay.addWidget(self.train_type_label)
        train_info_lay.addSpacing(3)
        train_info_lay.addWidget(self.train_number_label)
        train_info_lay.addStretch()
        self.panel_layout.addLayout(train_info_lay)

        # Маршрут (Динамический)
        route_info_lay = QHBoxLayout()
        route_icon = get_svg_label("route.svg", 16)
        self.route_text_label = QLabel("Loading...")
        self.route_text_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-family: 'Segoe UI'; font-size: 11px; font-weight: 500; border: none;")
        route_info_lay.addWidget(route_icon)
        route_info_lay.addWidget(self.route_text_label)
        route_info_lay.addStretch()
        self.dst_label = QLabel("DST —")
        self.dst_label.setStyleSheet("color: #ffffff; font-family: 'Segoe UI'; font-size: 11px; font-weight: 800; font-style: italic; border: none;")
        route_info_lay.addWidget(self.dst_label)
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

        # ── Train number (type red + number blue) ────────────────────────────
        train_type = data.get("train_type", "")
        train_number = data.get("train_number", "")
        if not train_type and not train_number:
            parts = data.get("train_num", "---").split(" ", 1)
            train_type   = parts[0] if parts else ""
            train_number = parts[1] if len(parts) > 1 else ""
        self.train_type_label.setText(train_type)
        self.train_number_label.setText(train_number)
        self.route_text_label.setText(data.get("route", "---"))

        # ── GPS state ────────────────────────────────────────────────────────
        lat        = data.get("lat", 0) or 0
        lon        = data.get("lon", 0) or 0
        route_from = data.get("route_from", "")
        route_to   = data.get("route_to", "")
        gps = self._get_station_state(lat, lon, route_from, route_to)

        # ── DST / ON STATION label ───────────────────────────────────────────
        if gps:
            if gps["on_station"]:
                self.dst_label.setText(f"ON ST.")
                self.dst_label.setStyleSheet(
                    "color: #f1c40f; font-family: 'Segoe UI'; font-size: 11px; font-weight: 800; font-style: italic; border: none;")
            else:
                self.dst_label.setText(f"DST {self._fmt_dist(gps['remaining'])}")
                self.dst_label.setStyleSheet(
                    "color: #ffffff; font-family: 'Segoe UI'; font-size: 11px; font-weight: 800; font-style: italic; border: none;")
        else:
            self.dst_label.setText("DST —")
            self.dst_label.setStyleSheet(
                "color: #ffffff; font-family: 'Segoe UI'; font-size: 11px; font-weight: 800; font-style: italic; border: none;")

        # ── Clear grid ───────────────────────────────────────────────────────
        while self.tt_grid.count():
            item = self.tt_grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        stations = data.get("stations", [])
        if not stations:
            return

        n = len(stations)
        station_names = [s[0] for s in stations]
        states = self._compute_station_states(station_names, gps)

        # ── Timeline widget (column 1, spans all rows) ───────────────────────
        timeline = StationTimeline()
        timeline.set_states(states)
        self.tt_grid.addWidget(timeline, 0, 1, n, 1, QtCore.Qt.AlignmentFlag.AlignHCenter)

        t_style = "font-family: 'Segoe UI'; font-size: 10px; font-weight: 800;"

        for i, (name, arr, dep) in enumerate(stations):
            state = states[i]

            # Colors per state
            if state == 'passed':
                name_css = "color: rgba(255,255,255,0.30);"
                time_css = f"color: rgba(255,255,255,0.25); {t_style}"
                dep_css  = f"color: rgba(255,255,255,0.15); {t_style}"
            elif state == 'current':
                name_css = "color: #f1c40f;"
                time_css = f"color: #f1c40f; {t_style}"
                dep_css  = f"color: rgba(241,196,15,0.6); {t_style}"
            elif state == 'next':
                name_css = "color: #00ff44;"
                time_css = f"color: white; {t_style}"
                dep_css  = f"color: rgba(255,255,255,0.4); {t_style}"
            else:
                name_css = "color: white;"
                time_css = f"color: white; {t_style}"
                dep_css  = f"color: rgba(255,255,255,0.4); {t_style}"

            # Time container
            time_container = QWidget()
            time_v = QVBoxLayout(time_container)
            time_v.setContentsMargins(0, 0, 0, 0)
            time_v.setSpacing(0)

            a_l = QLabel(arr)
            a_l.setStyleSheet(time_css)
            a_l.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

            d_l = QLabel(dep if dep not in ("--:--", "") else " ")
            d_l.setStyleSheet(dep_css)
            d_l.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

            time_v.addWidget(a_l)
            time_v.addWidget(d_l)

            # Station name (strikethrough if passed)
            st_l = QLabel(name)
            decoration = "text-decoration: line-through;" if state == 'passed' else ""
            st_l.setStyleSheet(
                f"font-family: 'Segoe UI'; font-size: 12px; font-weight: 800; border: none; {name_css} {decoration}")

            self.tt_grid.addWidget(time_container, i, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.tt_grid.addWidget(st_l,           i, 2, QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.tt_grid.setColumnStretch(0, 0)
        self.tt_grid.setColumnStretch(1, 0)
        self.tt_grid.setColumnStretch(2, 1)

    # ── Station GPS helpers ───────────────────────────────────────────────────

    def _get_current_zone(self, lat, lon):
        for name, poly in STATION_ZONES.items():
            if _point_in_polygon(lat, lon, poly):
                return name
        for name, poly in STATION_ZONES.items():
            if _dist_to_polygon(lat, lon, poly) < 200:
                return name
        return None

    def _get_station_state(self, lat, lon, route_from, route_to):
        if not lat or not lon or not route_from or not route_to:
            return None
        key = f"{route_from}_{route_to}"
        order = ROUTE_ORDER.get(key)
        if not order:
            return None

        zone = self._get_current_zone(lat, lon)
        if zone and zone in order:
            idx = order.index(zone)
            next_st = order[idx + 1] if idx < len(order) - 1 else order[-1]
            remaining = _dist_to_polygon(lat, lon, STATION_ZONES[next_st]) if next_st in STATION_ZONES else 0
            return {
                "on_station":      True,
                "current_station": zone,
                "next_station":    next_st,
                "remaining":       remaining,
                "passed_stations": order[:idx],
            }

        # Between stations: project onto route
        best_seg, min_d = 0, float('inf')
        for i in range(len(order) - 1):
            if order[i] not in STATION_CENTERS or order[i+1] not in STATION_CENTERS:
                continue
            p1 = STATION_CENTERS[order[i]]
            p2 = STATION_CENTERS[order[i+1]]
            dx, dy = p2[0]-p1[0], p2[1]-p1[1]
            len2 = dx*dx + dy*dy
            t = max(0, min(1, ((lat-p1[0])*dx+(lon-p1[1])*dy)/len2)) if len2 > 0 else 0
            d = _haversine(lat, lon, p1[0]+t*dx, p1[1]+t*dy)
            if d < min_d:
                min_d = d
                best_seg = i

        next_st = order[best_seg + 1]
        remaining = _dist_to_polygon(lat, lon, STATION_ZONES[next_st]) if next_st in STATION_ZONES else 0
        return {
            "on_station":      False,
            "current_station": None,
            "next_station":    next_st,
            "remaining":       remaining,
            "passed_stations": order[:best_seg + 1],
        }

    def _compute_station_states(self, station_names, gps):
        states = ['future'] * len(station_names)
        if not gps:
            return states
        passed  = set(gps.get("passed_stations", []))
        current = gps.get("current_station")
        nxt     = gps.get("next_station")
        on_st   = gps.get("on_station", False)
        for i, name in enumerate(station_names):
            if name in passed:
                states[i] = 'passed'
            elif on_st and name == current:
                states[i] = 'current'
            elif not on_st and name == nxt:
                states[i] = 'next'
        return states

    @staticmethod
    def _fmt_dist(meters):
        if meters >= 1000:
            return f"{meters/1000:.1f} km"
        return f"{round(meters)} m"

    # ── Focus detection ───────────────────────────────────────────────────────

    def _check_game_focus(self):
        if not _WINDOWS:
            return
        try:
            hwnd = _user32.GetForegroundWindow()
            length = _user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            focused = "RailWorks" in title or "Train Simulator" in title
            if focused != self._game_focused:
                self._game_focused = focused
                if focused:
                    self.show()
                    self.raise_()
                else:
                    self.hide()
        except Exception:
            pass



    def update_time(self):
        now = QDateTime.currentDateTime()
        # Часы в один лейбл
        self.time_label.setText(now.toString("HH"))
        # Минуты в другой
        self.minutes_label.setText(now.toString("mm"))
        # Дата отдельно
        self.date_label.setText(now.toString("dd/MM/yyyy"))

if __name__ == '__main__':
    # Silent exit if not launched by the launcher
    if not any(a.startswith('--key=') for a in sys.argv[1:]):
        sys.exit(0)

    # ИСПРАВЛЕНИЕ: Вызываем политику ДО создания QApplication
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    
    ex = Overlay()
    # Удаляем вызов политики из __init__ класса Overlay!
    
    sys.exit(app.exec())