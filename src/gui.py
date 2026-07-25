"""GUI界面模块：PyQt6主窗口"""

import sys
import os
import asyncio
import threading
import yaml
from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QTabWidget,
    QStatusBar, QDialog, QFormLayout, QLineEdit,
    QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit as QTextEditField,
    QGroupBox, QMessageBox, QSplitter, QCheckBox,
    QProgressDialog, QMenu, QMenuBar, QFrame, QGraphicsDropShadowEffect,
    QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, pyqtSlot, QTimer, QPoint, QPropertyAnimation, pyqtProperty, QRect
from PyQt6.QtGui import QTextCursor, QIcon, QColor, QPixmap, QPainter

from src.core import LiveCompanionEngine
from src import APP_DIR, DATA_DIR, __version__


# ─── 极简样式表 ───
STYLESHEET = """
QMainWindow {
    background-color: #F9FAFB;
}
QWidget {
    color: #111827;
    font-family: "Microsoft YaHei", "SimHei", sans-serif;
    font-size: 13px;
}
QGroupBox {
    background-color: transparent;
    border: none;
    margin-top: 20px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 0px;
    padding: 0;
    color: #374151;
    font-size: 14px;
    font-weight: bold;
}
QPushButton {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    color: #374151;
    cursor: pointer;
}
QPushButton:hover {
    background-color: #f3f4f6;
    border-color: #d1d5db;
}
QPushButton:pressed {
    background-color: #e5e7eb;
}
QPushButton:disabled {
    background-color: transparent;
    color: #9ca3af;
    border: none;
}
QPushButton#startBtn {
    background-color: #111827;
    color: #ffffff;
    border: none;
}
QPushButton#startBtn:hover {
    background-color: #374151;
}
QPushButton#stopBtn {
    background-color: #f3f4f6;
    color: #111827;
    border: 1px solid #e5e7eb;
}
QPushButton#stopBtn:hover {
    background-color: #e5e7eb;
}
/* 顶部按钮极简风格 */
QPushButton#startBtn, QPushButton#stopBtn, QPushButton#settingsBtn, QPushButton#miniBtn, QPushButton#logBtn {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    color: #374151;
    font-size: 12px;
    font-weight: 500;
    padding: 0 10px;
}
QPushButton#startBtn:hover, QPushButton#stopBtn:hover, QPushButton#settingsBtn:hover, QPushButton#miniBtn:hover, QPushButton#logBtn:hover {
    background-color: #f9fafb;
    border-color: #d1d5db;
}
QPushButton#startBtn:disabled, QPushButton#stopBtn:disabled, QPushButton#settingsBtn:disabled, QPushButton#miniBtn:disabled, QPushButton#logBtn:disabled {
    background-color: #f3f4f6;
    color: #9ca3af;
    border-color: #f3f4f6;
}
QTextEdit {
    background-color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 16px;
    font-size: 14px;
    color: #111827;
}
QScrollBar:vertical {
    background-color: transparent;
    width: 6px;
    border: none;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background-color: #d1d5db;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background-color: #9ca3af;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QLabel {
    font-size: 13px;
    color: #4b5563;
}
QLineEdit {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 6px;
    font-size: 13px;
    color: #111827;
}
QSpinBox, QDoubleSpinBox {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding-left: 8px;
    padding-right: 20px;
    min-height: 28px;
    font-size: 13px;
    color: #111827;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #9ca3af;
}

/* 高级极简下拉框 */
QComboBox {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
    color: #374151;
}
QComboBox:hover {
    border-color: #d1d5db;
}
QComboBox:focus {
    border-color: #9ca3af;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: none;
}
QComboBox::down-arrow {
    image: url(src/arrow_down.svg);
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    selection-background-color: #f3f4f6;
    selection-color: #111827;
    padding: 4px;
    outline: none;
}

QStatusBar {
    background-color: transparent;
    color: #9ca3af;
    font-size: 12px;
}
"""


class ToggleSwitch(QCheckBox):
    """现代滑动开关"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._position = 1.0 if self.isChecked() else 0.0
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(200)
        self.stateChanged.connect(self._on_state_changed)
        self.setStyleSheet(
            "QCheckBox::indicator { width: 0px; height: 0px; border: none; background: transparent; }"
            "QCheckBox { padding-left: 38px; spacing: 8px; color: #4b5563; font-size: 13px; }"
        )

    @pyqtProperty(float)
    def position(self):
        return self._position

    @position.setter
    def position(self, pos):
        self._position = pos
        self.update()

    def _on_state_changed(self, state):
        self._animation.stop()
        self._animation.setEndValue(1.0 if self.isChecked() else 0.0)
        self._animation.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._position = 1.0 if self.isChecked() else 0.0

    def hitButton(self, pos):
        # 由于隐藏了原生 indicator，必须自定义点击区域为整个控件
        return self.contentsRect().contains(pos)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = 36, 20
        y = (self.height() - h) // 2
        track_rect = QRect(0, y, w, h)
        
        r = int(209 + (59 - 209) * self._position)
        g = int(213 + (130 - 213) * self._position)
        b = int(219 + (246 - 219) * self._position)
        bg_color = QColor(r, g, b)
        
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg_color)
        p.drawRoundedRect(track_rect, h // 2, h // 2)
        
        knob_r = h - 4
        x = 2 + (w - knob_r - 4) * self._position
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(int(x), int(y + 2), int(knob_r), int(knob_r))


class EngineWorker(QObject):
    """在独立线程中运行引擎的工作器"""
    status_changed = pyqtSignal(str)
    danmu_received = pyqtSignal(str, str)  # username, content
    transcription_received = pyqtSignal(str)
    comment_generated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    room_switched = pyqtSignal()  # 切换直播间时通知GUI清除记录
    stopped = pyqtSignal()

    def __init__(self, config_path: str):
        super().__init__()
        self.config_path = config_path
        self.engine = None
        self._loop = None

    @pyqtSlot()
    def run(self):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            self.engine = LiveCompanionEngine(self.config_path)
            self.engine.on_status = self._emit_status
            self.engine.on_danmu = self._emit_danmu
            self.engine.on_transcription = self._emit_transcription
            self.engine.on_comment = self._emit_comment
            self.engine.on_error = self._emit_error
            self.engine.on_room_switch = self._emit_room_switch

            self._loop.run_until_complete(self.engine.start())
        except Exception as e:
            self.error_occurred.emit(f"引擎异常退出: {e}")
        finally:
            self.stopped.emit()

    def _emit_status(self, msg):
        self.status_changed.emit(msg)

    def _emit_danmu(self, username, content):
        self.danmu_received.emit(username, content)

    def _emit_transcription(self, text):
        self.transcription_received.emit(text)

    def _emit_comment(self, text):
        self.comment_generated.emit(text)

    def _emit_error(self, msg):
        self.error_occurred.emit(msg)

    def _emit_room_switch(self):
        self.room_switched.emit()

    def stop_engine(self):
        if self.engine and self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self.engine.stop(), self._loop
            )
            try:
                future.result(timeout=10)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)


class PromptEditDialog(QDialog):
    def __init__(self, initial_text, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(480, 360)
        self._init_ui(initial_text)
        self.start_pos = None

    def _init_ui(self, initial_text):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        
        main_frame = QFrame()
        main_frame.setStyleSheet("QFrame { background-color: #ffffff; border-radius: 12px; border: 1px solid #e5e7eb; }")
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        main_frame.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(main_frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        header = QHBoxLayout()
        title = QLabel("编辑系统提示词")
        title.setStyleSheet("color: #111827; font-size: 14px; font-weight: bold; border: none;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        self.text_edit = QTextEditField()
        self.text_edit.setPlainText(initial_text)
        self.text_edit.setStyleSheet("background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px; color: #374151; font-size: 13px;")
        layout.addWidget(self.text_edit)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(64, 32)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet("QPushButton { background-color: transparent; border: 1px solid #d1d5db; border-radius: 6px; color: #4b5563; font-size: 13px; padding: 0;} QPushButton:hover { background-color: #f3f4f6; }")
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = QPushButton("保存")
        save_btn.setFixedSize(64, 32)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet("QPushButton { background-color: #111827; color: white; border-radius: 6px; border: none; font-size: 13px; padding: 0;} QPushButton:hover { background-color: #374151; }")
        save_btn.clicked.connect(self.accept)
        
        btn_box.addWidget(cancel_btn)
        btn_box.addWidget(save_btn)
        
        layout.addLayout(btn_box)
        outer.addWidget(main_frame)

    def get_text(self):
        return self.text_edit.toPlainText()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.start_pos is not None:
            delta = event.globalPosition().toPoint() - self.start_pos
            self.window().move(self.window().pos() + delta)
            self.start_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.start_pos = None


class CustomMessageBox(QDialog):
    """自定义的高级极简消息弹窗"""
    def __init__(self, title, text, buttons=("确定",), parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(360)
        self.clicked_button = None
        self.start_pos = None
        self._init_ui(title, text, buttons)

    def _init_ui(self, title_text, msg_text, buttons):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        
        main_frame = QFrame()
        main_frame.setStyleSheet("QFrame { background-color: #ffffff; border-radius: 12px; border: 1px solid #e5e7eb; }")
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        main_frame.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(main_frame)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)
        
        header = QHBoxLayout()
        title = QLabel(title_text)
        title.setStyleSheet("color: #111827; font-size: 15px; font-weight: bold; border: none;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        msg_label = QLabel(msg_text)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("color: #4b5563; font-size: 13px; border: none; line-height: 1.5;")
        if "<" in msg_text:
            msg_label.setTextFormat(Qt.TextFormat.RichText)
            msg_label.setOpenExternalLinks(True)
        layout.addWidget(msg_label)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        for btn_name in buttons:
            btn = QPushButton(btn_name)
            btn.setFixedSize(64, 32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if btn_name in ("取消", "No"):
                btn.setStyleSheet("QPushButton { background-color: transparent; border: 1px solid #d1d5db; border-radius: 6px; color: #4b5563; font-size: 13px; padding: 0;} QPushButton:hover { background-color: #f3f4f6; }")
            else:
                btn.setStyleSheet("QPushButton { background-color: #111827; color: white; border-radius: 6px; border: none; font-size: 13px; padding: 0;} QPushButton:hover { background-color: #374151; }")
            
            btn.clicked.connect(lambda checked, name=btn_name: self._on_btn_clicked(name))
            btn_box.addWidget(btn)
            
        layout.addLayout(btn_box)
        outer.addWidget(main_frame)

    def _on_btn_clicked(self, name):
        self.clicked_button = name
        self.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.start_pos is not None:
            delta = event.globalPosition().toPoint() - self.start_pos
            self.window().move(self.window().pos() + delta)
            self.start_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.start_pos = None

    @classmethod
    def information(cls, parent, title, text):
        dialog = cls(title, text, ("确定",), parent)
        dialog.exec()
        
    @classmethod
    def warning(cls, parent, title, text):
        dialog = cls(title, text, ("确定",), parent)
        dialog.exec()

    @classmethod
    def question(cls, parent, title, text, *args, **kwargs):
        dialog = cls(title, text, ("取消", "确定"), parent)
        dialog.exec()
        return QMessageBox.StandardButton.Yes if dialog.clicked_button == "确定" else QMessageBox.StandardButton.No
    
    @classmethod
    def about(cls, parent, title, text):
        dialog = cls(title, text, ("确定",), parent)
        dialog.exec()


class WelcomeGuide(QDialog):
    """首次启动的新手引导"""
    STEPS = [
        {
            "title": "欢迎使用旁白",
            "desc": "旁白是一款快手直播间 AI 互动助手。\n它可以实时采集弹幕和主播语音，通过 AI 自动生成评论并发送到直播间。\n\n接下来用三步完成初始配置。"
        },
        {
            "title": "① 配置大模型 API",
            "desc": "API 就像是 AI 大脑的“钥匙”。有了它，旁白才能思考并帮您说话。<br><br>"
                    "点击顶部「设置」按钮填入密钥。<br>"
                    "推荐使用 <a href='https://bailian.console.aliyun.com/' style='color: #3b82f6; text-decoration: none;'>阿里云百炼</a> 或 <a href='https://open.bigmodel.cn/' style='color: #3b82f6; text-decoration: none;'>智谱AI</a>（提供免费的视觉模型），注册就能免费领额度！"
        },
        {
            "title": "② 点击启动",
            "desc": "配置完成后，点击「启动」按钮。\n\n程序会自动打开浏览器，您只需手动进入想要互动的直播间。\n首次使用需要扫码登录快手，之后会自动记住登录状态。"
        },
        {
            "title": "③ 享受 AI 互动",
            "desc": "启动后，主窗口会自动收缩为桌面悬浮舱。\n\nAI 会根据直播间的弹幕和主播语音，智能生成评论并自动发送。\n您可以随时点击悬浮舱的展开按钮，切回大面板查看详情。\n\n祝您使用愉快！"
        },
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(440, 340)
        self.current_step = 0
        self.start_pos = None
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)

        self.main_frame = QFrame()
        self.main_frame.setStyleSheet("QFrame { background-color: #ffffff; border-radius: 12px; border: 1px solid #e5e7eb; }")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        self.main_frame.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.main_frame)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(16)

        self.step_indicator = QLabel()
        self.step_indicator.setStyleSheet("color: #9ca3af; font-size: 11px; border: none;")
        layout.addWidget(self.step_indicator)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("color: #111827; font-size: 16px; font-weight: bold; border: none;")
        layout.addWidget(self.title_label)

        self.desc_label = QLabel()
        self.desc_label.setWordWrap(True)
        self.desc_label.setOpenExternalLinks(True)
        self.desc_label.setStyleSheet("color: #4b5563; font-size: 13px; border: none; line-height: 1.6;")
        layout.addWidget(self.desc_label)
        layout.addStretch()

        btn_box = QHBoxLayout()
        self.back_btn = QPushButton("上一步")
        self.back_btn.setFixedSize(72, 32)
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setStyleSheet("QPushButton { background-color: transparent; border: 1px solid #d1d5db; border-radius: 6px; color: #4b5563; font-size: 13px; padding: 0;} QPushButton:hover { background-color: #f3f4f6; }")
        self.back_btn.clicked.connect(self._prev_step)

        self.next_btn = QPushButton("下一步")
        self.next_btn.setFixedSize(72, 32)
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setStyleSheet("QPushButton { background-color: #111827; color: white; border-radius: 6px; border: none; font-size: 13px; padding: 0;} QPushButton:hover { background-color: #374151; }")
        self.next_btn.clicked.connect(self._next_step)

        btn_box.addStretch()
        btn_box.addWidget(self.back_btn)
        btn_box.addWidget(self.next_btn)
        layout.addLayout(btn_box)

        outer.addWidget(self.main_frame)
        self._update_step()

    def _update_step(self):
        step = self.STEPS[self.current_step]
        self.step_indicator.setText(f"步骤 {self.current_step + 1} / {len(self.STEPS)}")
        self.title_label.setText(step["title"])
        self.desc_label.setText(step["desc"])
        self.back_btn.setVisible(self.current_step > 0)
        self.next_btn.setText("开始使用" if self.current_step == len(self.STEPS) - 1 else "下一步")

    def _next_step(self):
        if self.current_step < len(self.STEPS) - 1:
            self.current_step += 1
            self._update_step()
        else:
            self.accept()

    def _prev_step(self):
        if self.current_step > 0:
            self.current_step -= 1
            self._update_step()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.start_pos is not None:
            delta = event.globalPosition().toPoint() - self.start_pos
            self.window().move(self.window().pos() + delta)
            self.start_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.start_pos = None


class LogViewerDialog(QDialog):
    """运行日志查看器"""
    def __init__(self, log_entries, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(520, 400)
        self.start_pos = None
        self._init_ui(log_entries)

    def _init_ui(self, log_entries):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)

        main_frame = QFrame()
        main_frame.setStyleSheet("QFrame { background-color: #ffffff; border-radius: 12px; border: 1px solid #e5e7eb; }")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        main_frame.setGraphicsEffect(shadow)

        layout = QVBoxLayout(main_frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("运行日志")
        title.setStyleSheet("color: #111827; font-size: 15px; font-weight: bold; border: none;")
        header.addWidget(title)
        
        header.addStretch()
        
        self.top_btn = QPushButton("📌")
        self.top_btn.setToolTip("置顶窗口")
        self.top_btn.setCheckable(True)
        self.top_btn.setFixedSize(30, 30)
        self.top_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.top_btn.setStyleSheet("""
            QPushButton { background-color: transparent; border: none; font-size: 16px; padding: 0; margin: 0; }
            QPushButton:hover { background-color: #f3f4f6; border-radius: 4px; }
            QPushButton:checked { background-color: #dbeafe; border-radius: 4px; border: 1px solid #bfdbfe; }
        """)
        self.top_btn.toggled.connect(self._toggle_top)
        header.addWidget(self.top_btn)
        
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("QPushButton { background-color: transparent; border: none; color: #374151; font-size: 18px; font-weight: bold; padding: 0; margin: 0; } QPushButton:hover { color: #ef4444; background-color: #fee2e2; border-radius: 4px; }")
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        layout.addLayout(header)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px; color: #374151; font-size: 12px; font-family: Consolas, monospace;")
        if log_entries:
            for ts, text, color in log_entries:
                self.add_log(ts, text, color)
        else:
            self.log_view.setPlaceholderText("暂无日志记录")
        layout.addWidget(self.log_view)

        outer.addWidget(main_frame)

    def add_log(self, ts, text, color):
        scrollbar = self.log_view.verticalScrollBar()
        # 智能滚动：如果当前滚动条在底部（允许少许误差），则随新内容滚动，否则保持原位
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 5
        
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f'<span style="color:#9ca3af;">[{ts}]</span> <span style="color:{color};">{text}</span><br>')
        
        if is_at_bottom:
            self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def _toggle_top(self, checked):
        if checked:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.start_pos is not None:
            delta = event.globalPosition().toPoint() - self.start_pos
            self.window().move(self.window().pos() + delta)
            self.start_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.start_pos = None


class SettingsDialog(QDialog):
    """设置对话框"""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(700)
        self.setMinimumHeight(480)
        self._init_ui()
        self._load_values()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── 上半部分：左右两栏 ──
        top_layout = QHBoxLayout()

        # ── 左栏：LLM + 视觉识别 ──
        left_col = QVBoxLayout()

        llm_group = QGroupBox("LLM 配置")
        llm_layout = QFormLayout()
        llm_layout.setSpacing(6)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["阿里云百炼(DashScope)", "自定义接口"])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        llm_layout.addRow("服务商:", self.provider_combo)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("输入你的API Key")
        llm_layout.addRow("API密钥:", self.api_key_input)

        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("如 qwen-turbo, qwen-plus")
        llm_layout.addRow("模型:", self.model_input)

        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("仅自定义接口需要")
        llm_layout.addRow("接口地址:", self.base_url_input)

        prompt_row = QHBoxLayout()
        self.system_prompt_input = QTextEditField()
        self.system_prompt_input.setMaximumHeight(60)
        prompt_row.addWidget(self.system_prompt_input)
        
        self.edit_prompt_btn = QPushButton("⛶")
        self.edit_prompt_btn.setFixedSize(28, 28)
        self.edit_prompt_btn.setToolTip("弹出独立窗口编辑")
        self.edit_prompt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_prompt_btn.setStyleSheet("QPushButton { background-color: transparent; border: 1px solid #e5e7eb; border-radius: 4px; color: #6b7280; font-size: 14px; padding: 0; } QPushButton:hover { background-color: #f3f4f6; color: #111827; }")
        self.edit_prompt_btn.clicked.connect(self._open_prompt_editor)
        
        prompt_vbox = QVBoxLayout()
        prompt_vbox.addWidget(self.edit_prompt_btn)
        prompt_vbox.addStretch()
        prompt_row.addLayout(prompt_vbox)
        
        llm_layout.addRow("系统提示词:", prompt_row)

        # 随机度和字数放一行
        param_row = QHBoxLayout()
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setFixedWidth(120)
        param_row.addWidget(QLabel("随机度:"))
        param_row.addWidget(self.temperature_spin)
        param_row.addSpacing(12)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(10, 500)
        self.max_tokens_spin.setFixedWidth(120)
        param_row.addWidget(QLabel("字数:"))
        param_row.addWidget(self.max_tokens_spin)
        param_row.addStretch()
        llm_layout.addRow(param_row)

        llm_group.setLayout(llm_layout)
        left_col.addWidget(llm_group)

        vision_group = QGroupBox("视觉识别")
        vision_layout = QFormLayout()
        vision_layout.setSpacing(6)

        self.vision_check = ToggleSwitch("启用截图识别直播类型")
        self.vision_check.setToolTip("进入直播间时截图，用视觉模型识别直播内容")
        vision_layout.addRow("", self.vision_check)

        self.vision_provider_combo = QComboBox()
        self.vision_provider_combo.addItems(["阿里云百炼(DashScope)", "智谱AI(BigModel)", "自定义接口"])
        self.vision_provider_combo.currentIndexChanged.connect(self._on_vision_provider_changed)
        vision_layout.addRow("服务商:", self.vision_provider_combo)

        self.vision_api_key_input = QLineEdit()
        self.vision_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.vision_api_key_input.setPlaceholderText("留空复用LLM密钥")
        vision_layout.addRow("API密钥:", self.vision_api_key_input)

        self.vision_model_input = QTextEditField()
        self.vision_model_input.setMinimumHeight(120)
        self.vision_model_input.setPlaceholderText("【多模型版】每行一个模型名，按优先级从上到下\n如:\nglm-4.6v-flash\nglm-4.1v-thinking-flash\nglm-4v-flash")
        self.vision_model_input.setToolTip("每行一个模型名，按优先级从上到下。前一个调用失败(限流/错误)时自动切换到下一个")
        vision_layout.addRow("视觉模型(多行):", self.vision_model_input)

        self.vision_base_url_input = QLineEdit()
        self.vision_base_url_input.setPlaceholderText("仅自定义接口需要")
        vision_layout.addRow("接口地址:", self.vision_base_url_input)

        vision_group.setLayout(vision_layout)
        left_col.addWidget(vision_group)

        left_col.addStretch()
        top_layout.addLayout(left_col)

        # ── 右栏：评论发送 + 语音识别 ──
        right_col = QVBoxLayout()

        sender_group = QGroupBox("评论发送")
        sender_layout = QFormLayout()
        sender_layout.setSpacing(6)

        self.min_interval_spin = QSpinBox()
        self.min_interval_spin.setRange(5, 300)
        self.min_interval_spin.setSuffix(" 秒")
        sender_layout.addRow("最小间隔:", self.min_interval_spin)

        self.max_interval_spin = QSpinBox()
        self.max_interval_spin.setRange(5, 600)
        self.max_interval_spin.setSuffix(" 秒")
        sender_layout.addRow("最大间隔:", self.max_interval_spin)

        self.max_length_spin = QSpinBox()
        self.max_length_spin.setRange(5, 100)
        self.max_length_spin.setSuffix(" 字")
        sender_layout.addRow("最大字数:", self.max_length_spin)

        sender_group.setLayout(sender_layout)
        right_col.addWidget(sender_group)

        audio_group = QGroupBox("语音识别")
        audio_layout = QFormLayout()
        audio_layout.setSpacing(6)

        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(["tiny(最快)", "base(均衡)", "small(较准)", "medium(很准)", "large(最准)"])
        audio_layout.addRow("识别模型:", self.whisper_combo)

        self.segment_spin = QSpinBox()
        self.segment_spin.setRange(5, 30)
        self.segment_spin.setSuffix(" 秒")
        audio_layout.addRow("片段长度:", self.segment_spin)

        self.danmu_check = ToggleSwitch("启用弹幕采集")
        audio_layout.addRow("", self.danmu_check)

        audio_group.setLayout(audio_layout)
        right_col.addWidget(audio_group)

        # 快手提示（精简）
        ks_hint = QLabel("启动后自动打开浏览器，手动进入直播间即可。\n首次需扫码登录，之后自动记住。")
        ks_hint.setWordWrap(True)
        ks_hint.setStyleSheet("color: #27ae60; font-size: 11px; padding: 4px;")
        right_col.addWidget(ks_hint)

        right_col.addStretch()
        top_layout.addLayout(right_col)

        layout.addLayout(top_layout)

        # ── 底部按钮 ──
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_provider_changed(self, index):
        is_custom = index == 1  # 索引1为"自定义接口"
        self.base_url_input.setEnabled(is_custom)

    def _on_vision_provider_changed(self, index):
        is_custom = index == 2  # 索引2为"自定义接口"
        self.vision_base_url_input.setEnabled(is_custom)

    def _load_values(self):
        llm = self.config.get("llm", {})
        provider = llm.get("provider", "dashscope")
        self.provider_combo.setCurrentIndex(1 if provider == "custom" else 0)
        self.api_key_input.setText(llm.get("api_key", ""))
        self.model_input.setText(llm.get("model", "qwen-turbo"))
        self.base_url_input.setText(llm.get("base_url", ""))
        self.system_prompt_input.setPlainText(llm.get("system_prompt", ""))
        self.temperature_spin.setValue(llm.get("temperature", 0.9))
        self.max_tokens_spin.setValue(llm.get("max_tokens", 50))

        sender = self.config.get("sender", {})
        self.min_interval_spin.setValue(sender.get("min_interval", 20))
        self.max_interval_spin.setValue(sender.get("max_interval", 50))
        self.max_length_spin.setValue(sender.get("max_length", 20))

        audio = self.config.get("audio", {})
        model_map = {"tiny": 0, "base": 1, "small": 2, "medium": 3, "large": 4}
        model_name = audio.get("whisper_model", "base")
        self.whisper_combo.setCurrentIndex(model_map.get(model_name, 1))
        self.segment_spin.setValue(audio.get("segment_length", 10))

        danmu = self.config.get("danmu", {})
        self.danmu_check.setChecked(danmu.get("enabled", True))

        vision = self.config.get("vision", {})
        self.vision_check.setChecked(vision.get("enabled", True))
        vision_provider = vision.get("provider", "dashscope")
        vision_provider_map = {"dashscope": 0, "zhipu": 1, "custom": 2}
        self.vision_provider_combo.setCurrentIndex(vision_provider_map.get(vision_provider, 0))
        self.vision_api_key_input.setText(vision.get("api_key", ""))
        # 兼容: 优先读 models 列表，回退到 model 单字段，都没有就用默认三个模型
        DEFAULT_MODELS = ["glm-4.6v-flash", "glm-4.1v-thinking-flash", "glm-4v-flash"]
        models_list = vision.get("models")
        if models_list and isinstance(models_list, list):
            self.vision_model_input.setPlainText("\n".join(models_list))
        else:
            single = vision.get("model")
            if single:
                self.vision_model_input.setPlainText(single)
            else:
                self.vision_model_input.setPlainText("\n".join(DEFAULT_MODELS))
        self.vision_base_url_input.setText(vision.get("base_url", ""))
        self.vision_base_url_input.setEnabled(vision_provider == "custom")

    def _open_prompt_editor(self):
        dialog = PromptEditDialog(self.system_prompt_input.toPlainText(), self)
        if dialog.exec():
            self.system_prompt_input.setPlainText(dialog.get_text())

    def _save(self):
        provider = "custom" if self.provider_combo.currentIndex() == 1 else "dashscope"
        model_map = {0: "tiny", 1: "base", 2: "small", 3: "medium", 4: "large"}
        self.config["llm"] = {
            "provider": provider,
            "api_key": self.api_key_input.text(),
            "model": self.model_input.text(),
            "base_url": self.base_url_input.text(),
            "system_prompt": self.system_prompt_input.toPlainText(),
            "temperature": self.temperature_spin.value(),
            "max_tokens": self.max_tokens_spin.value(),
        }
        self.config["sender"] = {
            "min_interval": self.min_interval_spin.value(),
            "max_interval": self.max_interval_spin.value(),
            "max_length": self.max_length_spin.value(),
        }
        self.config["audio"] = {
            "whisper_model": model_map.get(self.whisper_combo.currentIndex(), "base"),
            "language": "zh",
            "segment_length": self.segment_spin.value(),
        }
        self.config["danmu"] = {
            "enabled": self.danmu_check.isChecked(),
        }
        vision_provider_map = {0: "dashscope", 1: "zhipu", 2: "custom"}
        vision_provider = vision_provider_map.get(self.vision_provider_combo.currentIndex(), "dashscope")
        # 多行文本转模型列表，每行一个，去空行去首尾空格
        models_text = self.vision_model_input.toPlainText()
        models_list = [line.strip() for line in models_text.splitlines() if line.strip()]
        if not models_list:
            models_list = ["glm-4.6v-flash"]
        self.config["vision"] = {
            "enabled": self.vision_check.isChecked(),
            "provider": vision_provider,
            "api_key": self.vision_api_key_input.text(),
            "models": models_list,
            "base_url": self.vision_base_url_input.text(),
        }
        self.accept()

    def get_config(self) -> dict:
        return self.config


class CustomTitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setStyleSheet("background-color: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        
        self.logo = QLabel()
        icon_path = str(APP_DIR / "logo.png")
        if not os.path.exists(icon_path):
            icon_path = str(APP_DIR / "_internal" / "logo.png")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            self.logo.setPixmap(pixmap.scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.logo.setFixedSize(22, 22)
        
        self.title = QLabel(f"旁白 v{__version__}")
        self.title.setStyleSheet("color: #6b7280; font-size: 13px; font-weight: bold;")
        
        self.quote = QLabel("你爱造梦尽管试 我会合力设想")
        self.quote.setStyleSheet("color: #6b7280; font-size: 12px; font-style: italic; margin-left: 12px;")
        
        self.btn_help = QPushButton("帮助")
        self.btn_help.setFixedSize(60, 24)
        self.btn_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_help.setStyleSheet("QPushButton { background-color: transparent; border: none; color: #9ca3af; font-size: 12px; padding: 0; } QPushButton:hover { color: #111827; }")
        
        self.help_menu = QMenu(self)
        self.help_menu.setStyleSheet("QMenu { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; padding: 4px; } QMenu::item { padding: 6px 20px; color: #374151; font-size: 12px; } QMenu::item:selected { background-color: #f3f4f6; color: #111827; }")
        self.btn_help.setMenu(self.help_menu)
        
        self.btn_min = QPushButton("—")
        self.btn_min.setFixedSize(24, 24)
        self.btn_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_min.setStyleSheet("QPushButton { background-color: transparent; border: none; color: #9ca3af; font-size: 14px; padding: 0; } QPushButton:hover { color: #111827; }")
        self.btn_min.clicked.connect(self.window().showMinimized)
        
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet("QPushButton { background-color: transparent; border: none; color: #9ca3af; font-size: 14px; padding: 0; } QPushButton:hover { color: #ef4444; }")
        self.btn_close.clicked.connect(self.window().close)
        
        if os.path.exists(icon_path):
            layout.addWidget(self.logo)
            layout.addSpacing(6)
        layout.addWidget(self.title)
        layout.addWidget(self.quote)
        layout.addStretch()
        layout.addWidget(self.btn_help)
        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_close)
        
        self.start_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.start_pos is not None:
            delta = event.globalPosition().toPoint() - self.start_pos
            self.window().move(self.window().pos() + delta)
            self.start_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.start_pos = None


class MiniCompanionWindow(QWidget):
    def __init__(self, parent_main=None):
        super().__init__()
        self.parent_main = parent_main
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(360, 60)
        self._init_ui()
        self.start_pos = None

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.bg_frame = QFrame()
        self.bg_frame.setStyleSheet("QFrame { background-color: rgba(255, 255, 255, 0.96); border-radius: 20px; border: 1px solid rgba(229, 231, 235, 0.5); }")
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        self.bg_frame.setGraphicsEffect(shadow)
        
        bg_layout = QHBoxLayout(self.bg_frame)
        bg_layout.setContentsMargins(16, 4, 16, 4)
        
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color: #10b981; font-size: 14px;")
        
        self.scroll_text = QLabel("正在聆听...")
        self.scroll_text.setStyleSheet("color: #111827; font-size: 13px; border: none; background: transparent;")
        
        self.btn_expand = QPushButton("⛶")
        self.btn_expand.setFixedSize(28, 28)
        self.btn_expand.setStyleSheet("QPushButton { background-color: transparent; border: none; color: #6b7280; font-size: 16px; padding: 0; } QPushButton:hover { color: #111827; }")
        self.btn_expand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expand.clicked.connect(self._expand)
        
        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setFixedSize(28, 28)
        self.btn_stop.setStyleSheet("QPushButton { background-color: transparent; border: none; color: #ef4444; font-size: 16px; padding: 0; } QPushButton:hover { color: #b91c1c; }")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.clicked.connect(self._stop)
        
        bg_layout.addWidget(self.dot)
        bg_layout.addSpacing(8)
        bg_layout.addWidget(self.scroll_text, 1)
        bg_layout.addWidget(self.btn_expand)
        bg_layout.addWidget(self.btn_stop)
        
        layout.addWidget(self.bg_frame)

    def update_text(self, text, is_comment=False):
        if is_comment:
            text = f"✨回复: {text}"
            self.dot.setStyleSheet("color: #f59e0b; font-size: 14px;")
        else:
            self.dot.setStyleSheet("color: #10b981; font-size: 14px;")
        
        if len(text) > 16:
            text = text[:15] + "..."
        self.scroll_text.setText(text)

    def _expand(self):
        self.hide()
        if self.parent_main:
            self.parent_main.show()

    def _stop(self):
        if self.parent_main:
            self.parent_main._on_stop()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.start_pos is not None:
            delta = event.globalPosition().toPoint() - self.start_pos
            self.window().move(self.window().pos() + delta)
            self.start_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.start_pos = None


class MainWindow(QMainWindow):
    def __init__(self, config_path: str = None):
        super().__init__()
        # 默认配置路径：保存在用户数据目录
        if config_path is None:
            config_path = str(DATA_DIR / "config.yaml")
        self.config_path = config_path
        self.config = self._load_config()
        self._worker = None
        self._thread = None
        self._comment_count = 0
        self._log_history = []

        self.setWindowTitle(f"旁白 v{__version__}")
        icon_path = str(APP_DIR / "logo.png")
        if not os.path.exists(icon_path):
            icon_path = str(APP_DIR / "_internal" / "logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.setMinimumSize(840, 640)
        self.resize(980, 720)
        
        # --- 去除原生感：无边框 + 阴影 ---
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.mini_companion = MiniCompanionWindow(self)
        
        self._init_ui()
        self.setStyleSheet(STYLESHEET)

    def _load_config(self) -> dict:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return config if config else {}
        except Exception:
            return {}

    def _save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
        except Exception as e:
            self._append_log(f"保存配置失败: {e}", "#ef5350")

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        # 最外层带边距的布局，用于容纳阴影
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(20, 20, 20, 20)
        
        # 带有背景色和圆角的主框架
        self.main_frame = QFrame()
        self.main_frame.setObjectName("MainFrame")
        self.main_frame.setStyleSheet("#MainFrame { background-color: #F9FAFB; border-radius: 12px; }")
        
        # 添加阴影特效
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 8)
        self.main_frame.setGraphicsEffect(shadow)
        
        outer_layout.addWidget(self.main_frame)
        
        # 主框架内的内容布局
        main_layout = QVBoxLayout(self.main_frame)
        main_layout.setContentsMargins(0, 0, 0, 10)
        main_layout.setSpacing(8)

        # ── 顶部自定义标题栏 ──
        self.title_bar = CustomTitleBar(self)
        
        check_update_action = self.title_bar.help_menu.addAction("检查更新")
        check_update_action.triggered.connect(self._check_for_update_manual)
        guide_action = self.title_bar.help_menu.addAction("使用教程")
        guide_action.triggered.connect(self._show_welcome_guide)
        about_action = self.title_bar.help_menu.addAction("关于")
        about_action.triggered.connect(self._show_about)
        
        main_layout.addWidget(self.title_bar)

        # ── 控制栏 ──
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(20, 0, 20, 0)

        self.start_btn = QPushButton("启动")
        self.start_btn.setToolTip("启动引擎")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setFixedSize(52, 30)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start)
        
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setToolTip("停止引擎")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setFixedSize(52, 30)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        
        self.settings_btn = QPushButton("设置")
        self.settings_btn.setToolTip("打开设置")
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setFixedSize(52, 30)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self._on_settings)
        
        self.mini_btn = QPushButton("悬浮")
        self.mini_btn.setToolTip("收起为悬浮舱")
        self.mini_btn.setObjectName("miniBtn")
        self.mini_btn.setFixedSize(52, 30)
        self.mini_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mini_btn.setEnabled(False)
        self.mini_btn.clicked.connect(self._to_mini_mode)
        
        self.log_btn = QPushButton("日志")
        self.log_btn.setToolTip("查看运行日志")
        self.log_btn.setObjectName("logBtn")
        self.log_btn.setFixedSize(52, 30)
        self.log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_btn.clicked.connect(self._show_log_viewer)

        top_bar.addWidget(self.start_btn)
        top_bar.addWidget(self.stop_btn)
        top_bar.addWidget(self.settings_btn)
        top_bar.addWidget(self.mini_btn)
        top_bar.addWidget(self.log_btn)

        top_bar.addStretch()

        main_layout.addLayout(top_bar)
        
        # ── 主体双栏布局 ──
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(20, 10, 20, 10)
        content_layout.setSpacing(16)
        
        # 左侧：现场动态流 (35% 宽)
        left_panel = QVBoxLayout()
        left_panel.setSpacing(8)
        left_title = QLabel("现场动态")
        left_title.setStyleSheet("font-weight: bold; color: #9ca3af; font-size: 12px;")
        self.context_text = QTextEdit()
        self.context_text.setReadOnly(True)
        self.context_text.setPlaceholderText("安静地聆听中...")
        left_panel.addWidget(left_title)
        left_panel.addWidget(self.context_text)
        
        # 右侧：回复面板 (65% 宽)
        right_panel = QVBoxLayout()
        right_panel.setSpacing(8)
        right_title = QLabel("回复面板")
        right_title.setStyleSheet("font-weight: bold; color: #9ca3af; font-size: 12px;")
        self.comment_text = QTextEdit()
        self.comment_text.setReadOnly(True)
        self.comment_text.setPlaceholderText("等待生成回复...")
        right_panel.addWidget(right_title)
        right_panel.addWidget(self.comment_text)
        
        content_layout.addLayout(left_panel, 65)
        content_layout.addLayout(right_panel, 35)
        
        main_layout.addLayout(content_layout, 1)

        # ── 极简底栏状态（单行滚动状态流） ──
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(20, 4, 20, 10)
        self.custom_status = QLabel(f"旁白 v{__version__} | 就绪")
        self.custom_status.setStyleSheet("color: #9ca3af; font-size: 12px;")
        bottom_bar.addWidget(self.custom_status)
        bottom_bar.addStretch()
        main_layout.addLayout(bottom_bar)

        # 启动3秒后自动检查更新
        QTimer.singleShot(3000, self._check_for_update_auto)
        
        # 首次启动时显示新手引导
        if not self.config.get("_guide_shown"):
            QTimer.singleShot(500, self._show_welcome_guide_first_run)

    def _append_colored(self, text_edit: QTextEdit, text: str, color: str):
        """向文本框追加带颜色的文本"""
        cursor = text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        html = f'<span style="color:{color};">{text}</span><br>'
        cursor.insertHtml(html)
        text_edit.setTextCursor(cursor)
        text_edit.ensureCursorVisible()

    def _append_log(self, text: str, color: str = "#374151"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_history.append((timestamp, text, color))
        # 只保留最近500条
        if len(self._log_history) > 500:
            self._log_history = self._log_history[-500:]
        self.custom_status.setText(f"[{timestamp}] {text}")
        
        # 实时更新非模态日志弹窗
        if hasattr(self, '_log_dialog') and self._log_dialog and self._log_dialog.isVisible():
            self._log_dialog.add_log(timestamp, text, color)

    # ── 控制按钮 ──

    def _on_start(self):
        try:
            # 检查必要配置
            if not self.config.get("llm", {}).get("api_key"):
                CustomMessageBox.warning(self, "提示", "请先在设置中配置API密钥")
                self._on_settings()
                return

            self._save_config()

            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.settings_btn.setEnabled(False)
            self.mini_btn.setEnabled(True)

            self._worker = EngineWorker(self.config_path)
            self._thread = QThread()
            self._worker.moveToThread(self._thread)

            self._thread.started.connect(self._worker.run)
            self._worker.status_changed.connect(self._on_status)
            self._worker.danmu_received.connect(self._on_danmu)
            self._worker.transcription_received.connect(self._on_transcription)
            self._worker.comment_generated.connect(self._on_comment)
            self._worker.error_occurred.connect(self._on_error)
            self._worker.room_switched.connect(self._on_room_switch)
            self._worker.stopped.connect(self._on_engine_stopped)

            self._thread.start()
            self._append_log("引擎启动", "#4caf50")
            
            # 动态微型悬浮舱切换
            self.hide()
            self.mini_companion.show()
            self.mini_companion.update_text("引擎启动，等待接入...")
            
        except Exception as e:
            self._append_log(f"启动失败: {e}", "#ef5350")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.settings_btn.setEnabled(True)
            import traceback
            traceback.print_exc()

    def _on_stop(self):
        if self._worker:
            self._worker.stop_engine()
            self._append_log("正在停止引擎...", "#ff9800")

    @pyqtSlot()
    def _on_engine_stopped(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._worker = None
        self._thread = None

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.settings_btn.setEnabled(True)
        self.mini_btn.setEnabled(False)
        self.custom_status.setText(f"旁白 v{__version__} | 就绪")
        self._append_log("引擎已停止", "#374151")
        
        # 恢复大面板
        self.mini_companion.hide()
        self.show()

    @pyqtSlot(str)
    def _on_status(self, msg):
        # 过滤掉过于中二和死板的词，替换为自然词汇
        display_msg = msg
        if "初始化" in msg:
            display_msg = "正在准备..."
        self.custom_status.setText(f"旁白 v{__version__} | {display_msg}")
        self._append_log(display_msg, "#374151")
        self.mini_companion.update_text(display_msg)

    @pyqtSlot()
    def _to_mini_mode(self):
        if self._worker:
            self.hide()
            self.mini_companion.show()

    @pyqtSlot(str, str)
    def _on_danmu(self, username, content):
        display = f"💬 {username}: {content}" if username else f"💬 {content}"
        self._append_colored(self.context_text, display, "#4b5563") # 次要文字灰

    @pyqtSlot(str)
    def _on_transcription(self, text):
        self._append_colored(self.context_text, f"🎤 {text}", "#6b7280") # 浅灰

    @pyqtSlot(str)
    def _on_comment(self, text):
        self._comment_count += 1
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_colored(
            self.comment_text, f"[{timestamp}] {text}", "#111827" # 主文字黑
        )
        self._append_log(f"生成回复: {text}", "#374151")
        self.custom_status.setText(
            f"旁白 v{__version__} | 已发送 {self._comment_count} 条回复"
        )
        self.mini_companion.update_text(text, is_comment=True)

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._append_log(f"后台提示: {msg}", "#374151")

    @pyqtSlot()
    def _on_room_switch(self):
        """切换直播间时清除GUI中的记录"""
        self.context_text.clear()
        self.comment_text.clear()
        self._comment_count = 0
        self._append_log("切换直播间，已清空显示", "#374151")

    def _on_settings(self):
        try:
            dialog = SettingsDialog(self.config, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.config = dialog.get_config()
                self._save_config()
                # 热更新：如果引擎正在运行，实时更新配置
                if self._worker and self._worker.engine:
                    try:
                        self._worker.engine.config = self.config
                        if hasattr(self._worker.engine, 'llm_client') and self._worker.engine.llm_client:
                            self._worker.engine.llm_client.update_config(self.config.get("llm", {}))
                        self._append_log("配置已热更新（立即生效）", "#4caf50")
                    except Exception as e:
                        self._append_log(f"热更新失败: {e}，重启后生效", "#ff9800")
                else:
                    self._append_log("配置已保存", "#4fc3f7")
        except Exception as e:
            self._append_log(f"设置操作出错: {e}", "#ef5350")
            import traceback
            traceback.print_exc()

    # ── 自动更新 ──

    def _check_for_update_auto(self):
        """启动后自动检查更新（静默，有新版才弹窗）"""
        self._do_check_update(silent=True)

    def _check_for_update_manual(self):
        """手动检查更新（总是显示结果）"""
        self._do_check_update(silent=False)

    def _do_check_update(self, silent: bool):
        """后台线程检查更新"""
        # 防止重复检查（自动检查未完成时用户又手动点击）
        if hasattr(self, '_update_thread') and self._update_thread and self._update_thread.isRunning():
            if not silent:
                self._update_loading = self._show_loading("正在检查更新...")
            return
        
        # 手动检查时显示加载提示
        if not silent:
            self._update_loading = self._show_loading("正在检查更新...")
        
        try:
            from src.updater import AutoUpdater

            updater = AutoUpdater("atvkh/kuaishou-live-mate", __version__)

            class UpdateCheckWorker(QObject):
                done = pyqtSignal(dict)
                failed = pyqtSignal(str)

                @pyqtSlot()
                def run(self):
                    try:
                        result = updater.check_update()
                        self.done.emit(result)
                    except Exception as e:
                        self.failed.emit(str(e))

            self._update_worker = UpdateCheckWorker()
            self._update_thread = QThread()
            self._update_worker.moveToThread(self._update_thread)
            self._update_thread.started.connect(self._update_worker.run)
            self._update_worker.done.connect(lambda r: self._on_update_checked(r, silent))
            self._update_worker.failed.connect(lambda e: self._on_update_failed(e, silent))
            # 确保回调执行完毕后再退出线程
            self._update_worker.done.connect(self._update_thread.quit, Qt.ConnectionType.QueuedConnection)
            self._update_worker.failed.connect(self._update_thread.quit, Qt.ConnectionType.QueuedConnection)
            self._update_thread.start()
        except Exception as e:
            self._dismiss_loading()
            if not silent:
                self._append_log(f"检查更新失败: {e}", "#ff9800")

    def _show_loading(self, text):
        """显示一个极简的无边框加载提示"""
        dialog = QDialog(self)
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setFixedSize(240, 100)
        
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(16, 16, 16, 16)
        
        frame = QFrame()
        frame.setStyleSheet("QFrame { background-color: #ffffff; border-radius: 12px; border: 1px solid #e5e7eb; }")
        shadow = QGraphicsDropShadowEffect(dialog)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        frame.setGraphicsEffect(shadow)
        
        inner = QHBoxLayout(frame)
        inner.setContentsMargins(20, 16, 20, 16)
        inner.setSpacing(12)
        
        dot = QLabel("◌")
        dot.setStyleSheet("color: #9ca3af; font-size: 18px; border: none;")
        inner.addWidget(dot)
        
        label = QLabel(text)
        label.setStyleSheet("color: #374151; font-size: 13px; border: none;")
        inner.addWidget(label)
        inner.addStretch()
        
        outer.addWidget(frame)
        dialog.show()
        # 强制立即刷新UI，防止被后台线程起步卡住
        QApplication.processEvents()
        return dialog

    def _dismiss_loading(self):
        """关闭加载提示"""
        if hasattr(self, '_update_loading') and self._update_loading:
            self._update_loading.close()
            self._update_loading = None

    def _on_update_failed(self, error_msg: str, silent: bool):
        """更新检查失败回调"""
        self._dismiss_loading()
        if not silent:
            self._append_log(f"检查更新失败: {error_msg}", "#ff9800")
            CustomMessageBox.information(self, "检查更新", f"检查更新失败，请稍后重试。")

    def _on_update_checked(self, result: dict, silent: bool):
        """更新检查完成回调"""
        self._dismiss_loading()
        if not result.get("has_update"):
            if not silent:
                CustomMessageBox.information(self, "检查更新", f"已是最新版本 v{__version__}")
            return

        new_ver = result["latest_version"]
        notes = result.get("release_notes", "")
        msg = f"发现新版本 v{new_ver}！\n\n当前版本: v{__version__}\n\n"
        if notes:
            msg += f"更新内容:\n{notes[:300]}\n\n"
        msg += "是否立即下载并更新？"

        reply = CustomMessageBox.question(
            self, "发现新版本", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._download_and_install(result["download_url"])

    def _download_and_install(self, url: str):
        """下载installer并安装"""
        if not url:
            CustomMessageBox.warning(self, "更新失败", "未找到下载地址，请前往 GitHub 手动下载")
            return

        from src.updater import AutoUpdater
        updater = AutoUpdater("atvkh/kuaishou-live-mate", __version__)

        progress = QProgressDialog("正在下载更新...", "取消", 0, 100, self)
        progress.setWindowTitle("更新")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        class DownloadWorker(QObject):
            finished = pyqtSignal(str)
            progress = pyqtSignal(int, int)

            @pyqtSlot()
            def run(self):
                def on_progress(downloaded, total):
                    self.progress.emit(downloaded, total)
                path = updater.download_installer(url, on_progress)
                self.finished.emit(path)

        self._download_worker = DownloadWorker()
        self._download_thread = QThread()
        self._download_worker.moveToThread(self._download_thread)
        self._download_thread.started.connect(self._download_worker.run)
        self._download_worker.progress.connect(
            lambda d, t: progress.setValue(int(d * 100 / t) if t > 0 else 0)
        )
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.finished.connect(self._download_thread.quit)
        progress.canceled.connect(self._download_thread.quit)
        self._download_thread.start()

    def _on_download_finished(self, installer_path: str):
        """下载完成，执行安装"""
        if not installer_path:
            CustomMessageBox.warning(self, "更新失败", "下载失败，请稍后重试或前往 GitHub 手动下载")
            return

        CustomMessageBox.information(
            self, "下载完成",
            "更新已下载完成，程序将退出并开始安装，安装完成后会自动重启。"
        )

        from src.updater import AutoUpdater
        updater = AutoUpdater("atvkh/kuaishou-live-mate", __version__)
        updater.install_and_restart(installer_path)

    def _show_about(self):
        """显示关于对话框"""
        icon_path = str(APP_DIR / "logo.png")
        if not os.path.exists(icon_path):
            icon_path = str(APP_DIR / "_internal" / "logo.png")
            
        img_html = f"<img src='{icon_path}' width='48' height='48' style='margin-bottom: 10px;'><br>" if os.path.exists(icon_path) else ""
        
        CustomMessageBox.about(
            self, "关于",
            f"<div style='text-align: center;'>"
            f"{img_html}"
            f"<h3 style='margin-bottom: 4px;'>旁白 v{__version__}</h3>"
            f"<p style='color: #4b5563; margin-top: 0; margin-bottom: 2px;'>快手直播间 AI 互动助手</p>"
            f"<p style='color: #6b7280; font-size: 11px; margin-top: 0; margin-bottom: 12px;'>实时采集弹幕与主播语音，LLM生成评论自动发送</p>"
            f"<p style='margin-top: 12px;'>GitHub: <a href='https://github.com/atvkh/kuaishou-live-mate' style='color: #3b82f6; text-decoration: none;'>"
            f"github.com/atvkh/kuaishou-live-mate</a></p>"
            f"</div>"
        )

    def _show_welcome_guide(self):
        """手动打开新手引导"""
        guide = WelcomeGuide(self)
        guide.exec()

    def _show_welcome_guide_first_run(self):
        """首次启动时自动弹出新手引导，完成后记住"""
        guide = WelcomeGuide(self)
        guide.exec()
        self.config["_guide_shown"] = True
        self._save_config()

    def _show_log_viewer(self):
        """打开运行日志查看器"""
        if not hasattr(self, '_log_dialog') or self._log_dialog is None:
            self._log_dialog = LogViewerDialog(self._log_history, self)
        if not self._log_dialog.isVisible():
            self._log_dialog.show()
        self._log_dialog.activateWindow()

    def closeEvent(self, event):
        if self._worker:
            self._worker.stop_engine()
            if self._thread:
                self._thread.quit()
                self._thread.wait(5000)
        event.accept()
