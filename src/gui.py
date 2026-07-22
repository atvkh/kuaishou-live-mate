"""GUI界面模块：PyQt6主窗口"""

import sys
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
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtGui import QFont, QColor, QTextCursor

from src.core import LiveCompanionEngine


# ─── 样式表 ───
STYLESHEET = """
QMainWindow {
    background-color: #f5f6fa;
}
QWidget {
    color: #2c3e50;
    font-family: "Microsoft YaHei", "SimHei", sans-serif;
    font-size: 13px;
}
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #dcdde1;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 18px;
    font-weight: bold;
    color: #2c3e50;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #2c3e50;
    font-size: 14px;
}
QPushButton {
    background-color: #3498db;
    border: 1px solid #2980b9;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 14px;
    font-weight: bold;
    color: #ffffff;
}
QPushButton:hover {
    background-color: #2980b9;
}
QPushButton:pressed {
    background-color: #1f618d;
}
QPushButton:disabled {
    background-color: #bdc3c7;
    color: #7f8c8d;
    border-color: #95a5a6;
}
QPushButton#startBtn {
    background-color: #27ae60;
    border-color: #219653;
    color: #ffffff;
}
QPushButton#startBtn:hover {
    background-color: #219653;
}
QPushButton#stopBtn {
    background-color: #e74c3c;
    border-color: #c0392b;
    color: #ffffff;
}
QPushButton#stopBtn:hover {
    background-color: #c0392b;
}
QTextEdit {
    background-color: #ffffff;
    border: 1px solid #bdc3c7;
    border-radius: 4px;
    padding: 5px;
    font-size: 14px;
    color: #2c3e50;
}
QTabWidget::pane {
    border: 1px solid #bdc3c7;
    border-radius: 4px;
    background-color: #ffffff;
}
QTabBar::tab {
    background-color: #ecf0f1;
    border: 1px solid #bdc3c7;
    padding: 8px 16px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: #34495e;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    border-bottom-color: #ffffff;
    color: #2c3e50;
    font-weight: bold;
}
QLabel {
    font-size: 13px;
    color: #2c3e50;
}
QLabel#statusLabel {
    font-size: 14px;
    font-weight: bold;
    padding: 4px 10px;
    border-radius: 4px;
    color: #27ae60;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #bdc3c7;
    border-radius: 4px;
    padding: 5px;
    font-size: 13px;
    color: #2c3e50;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #2c3e50;
    selection-background-color: #3498db;
    selection-color: #ffffff;
}
QCheckBox {
    color: #2c3e50;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QStatusBar {
    background-color: #e8e9ec;
    color: #576574;
    font-size: 12px;
}
QScrollBar:vertical {
    background-color: #ecf0f1;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #bdc3c7;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""


class EngineWorker(QObject):
    """在独立线程中运行引擎的工作器"""
    status_changed = pyqtSignal(str)
    danmu_received = pyqtSignal(str, str)  # username, content
    transcription_received = pyqtSignal(str)
    comment_generated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, config_path: str):
        super().__init__()
        self.config_path = config_path
        self.engine = None
        self._loop = None

    @pyqtSlot()
    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self.engine = LiveCompanionEngine(self.config_path)
        self.engine.on_status = self._emit_status
        self.engine.on_danmu = self._emit_danmu
        self.engine.on_transcription = self._emit_transcription
        self.engine.on_comment = self._emit_comment
        self.engine.on_error = self._emit_error

        try:
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


class SettingsDialog(QDialog):
    """设置对话框"""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(550)
        self.setMinimumHeight(600)
        self._init_ui()
        self._load_values()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── LLM 配置 ──
        llm_group = QGroupBox("LLM 配置")
        llm_layout = QFormLayout()

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["阿里云百炼(DashScope)", "自定义接口"])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        llm_layout.addRow("服务商:", self.provider_combo)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("输入你的API Key")
        llm_layout.addRow("API密钥:", self.api_key_input)

        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("如 qwen-turbo, qwen-plus, qwen-max")
        llm_layout.addRow("模型:", self.model_input)

        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("仅自定义接口需要")
        llm_layout.addRow("接口地址:", self.base_url_input)

        self.system_prompt_input = QTextEditField()
        self.system_prompt_input.setMaximumHeight(80)
        llm_layout.addRow("系统提示词:", self.system_prompt_input)

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        llm_layout.addRow("随机度:", self.temperature_spin)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(10, 500)
        llm_layout.addRow("最大字数限制:", self.max_tokens_spin)

        llm_group.setLayout(llm_layout)
        layout.addWidget(llm_group)

        # ── 快手配置 ──
        ks_group = QGroupBox("快手直播间")
        ks_layout = QFormLayout()

        cookie_hint = QLabel("启动后会自动打开浏览器，你手动进入想去的直播间即可，无需在此填写地址。\n首次使用需扫码登录，之后自动记住登录状态。")
        cookie_hint.setWordWrap(True)
        cookie_hint.setStyleSheet("color: #27ae60; font-size: 12px; padding: 5px;")
        ks_layout.addRow("", cookie_hint)

        ks_group.setLayout(ks_layout)
        layout.addWidget(ks_group)

        # ── 发送配置 ──
        sender_group = QGroupBox("评论发送")
        sender_layout = QFormLayout()

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
        sender_layout.addRow("评论最大字数:", self.max_length_spin)

        sender_group.setLayout(sender_layout)
        layout.addWidget(sender_group)

        # ── 音频配置 ──
        audio_group = QGroupBox("语音识别")
        audio_layout = QFormLayout()

        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(["tiny(最快)", "base(均衡)", "small(较准)", "medium(很准)", "large(最准)"])
        audio_layout.addRow("识别模型:", self.whisper_combo)

        self.segment_spin = QSpinBox()
        self.segment_spin.setRange(5, 30)
        self.segment_spin.setSuffix(" 秒")
        audio_layout.addRow("识别片段长度:", self.segment_spin)

        self.danmu_check = QCheckBox("启用弹幕采集")
        audio_layout.addRow("", self.danmu_check)

        audio_group.setLayout(audio_layout)
        layout.addWidget(audio_group)

        # ── 按钮 ──
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
        self.accept()

    def get_config(self) -> dict:
        return self.config


class MainWindow(QMainWindow):
    def __init__(self, config_path: str = "config.yaml"):
        super().__init__()
        self.config_path = config_path
        self.config = self._load_config()
        self._worker = None
        self._thread = None
        self._comment_count = 0

        self.setWindowTitle("直播伴侣 - 快手直播间AI互动助手")
        self.setMinimumSize(800, 600)
        self.resize(960, 700)
        self._init_ui()
        self.setStyleSheet(STYLESHEET)

    def _load_config(self) -> dict:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception:
            return {}

    def _save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ── 顶部控制栏 ──
        top_bar = QHBoxLayout()

        self.start_btn = QPushButton("启动")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.clicked.connect(self._on_start)
        top_bar.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        top_bar.addWidget(self.stop_btn)

        self.settings_btn = QPushButton("设置")
        self.settings_btn.clicked.connect(self._on_settings)
        top_bar.addWidget(self.settings_btn)

        top_bar.addStretch()

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusLabel")
        top_bar.addWidget(self.status_label)

        main_layout.addLayout(top_bar)

        # ── Tab 内容区 ──
        self.tab_widget = QTabWidget()

        # 弹幕 Tab
        self.danmu_text = QTextEdit()
        self.danmu_text.setReadOnly(True)
        self.danmu_text.setPlaceholderText("弹幕消息将显示在这里...")
        self.tab_widget.addTab(self.danmu_text, "弹幕")

        # 语音转录 Tab
        self.transcription_text = QTextEdit()
        self.transcription_text.setReadOnly(True)
        self.transcription_text.setPlaceholderText("语音转录内容将显示在这里...")
        self.tab_widget.addTab(self.transcription_text, "语音转录")

        # AI评论 Tab
        self.comment_text = QTextEdit()
        self.comment_text.setReadOnly(True)
        self.comment_text.setPlaceholderText("AI生成的评论将显示在这里...")
        self.tab_widget.addTab(self.comment_text, "AI评论")

        # 日志 Tab
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("运行日志...")
        self.tab_widget.addTab(self.log_text, "日志")

        main_layout.addWidget(self.tab_widget)

        # ── 状态栏 ──
        self.statusBar().showMessage("直播伴侣 v1.0 | 就绪")

    def _append_colored(self, text_edit: QTextEdit, text: str, color: str):
        """向文本框追加带颜色的文本"""
        cursor = text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        html = f'<span style="color:{color};">{text}</span><br>'
        cursor.insertHtml(html)
        text_edit.setTextCursor(cursor)
        text_edit.ensureCursorVisible()

    def _append_log(self, text: str, color: str = "#aaa"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_colored(self.log_text, f"[{timestamp}] {text}", color)

    # ── 控制按钮 ──

    def _on_start(self):
        # 检查必要配置
        if not self.config.get("llm", {}).get("api_key"):
            QMessageBox.warning(self, "提示", "请先在设置中配置API密钥")
            self._on_settings()
            return

        self._save_config()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.settings_btn.setEnabled(False)
        self.status_label.setText("启动中...")

        self._worker = EngineWorker(self.config_path)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.status_changed.connect(self._on_status)
        self._worker.danmu_received.connect(self._on_danmu)
        self._worker.transcription_received.connect(self._on_transcription)
        self._worker.comment_generated.connect(self._on_comment)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.stopped.connect(self._on_engine_stopped)

        self._thread.start()
        self._append_log("引擎启动", "#4caf50")

    def _on_stop(self):
        if self._worker:
            self.status_label.setText("正在停止...")
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
        self.status_label.setText("已停止")
        self._append_log("引擎已停止", "#ff9800")

    @pyqtSlot(str)
    def _on_status(self, msg):
        self.status_label.setText(msg)
        self.statusBar().showMessage(f"直播伴侣 v1.0 | {msg}")
        self._append_log(msg, "#4fc3f7")

    @pyqtSlot(str, str)
    def _on_danmu(self, username, content):
        timestamp = datetime.now().strftime("%H:%M:%S")
        display = f"[{timestamp}] {username}: {content}" if username else f"[{timestamp}] {content}"
        self._append_colored(self.danmu_text, display, "#1a1a1a")

    @pyqtSlot(str)
    def _on_transcription(self, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_colored(
            self.transcription_text, f"[{timestamp}] {text}", "#81c784"
        )

    @pyqtSlot(str)
    def _on_comment(self, text):
        self._comment_count += 1
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_colored(
            self.comment_text, f"[{timestamp}] #{self._comment_count} {text}", "#ffb74d"
        )
        self._append_log(f"生成评论: {text}", "#ffb74d")
        self.statusBar().showMessage(
            f"直播伴侣 v1.0 | 已发送 {self._comment_count} 条评论"
        )

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._append_log(f"错误: {msg}", "#ef5350")
        self.status_label.setText("出错")

    def _on_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config = dialog.get_config()
            self._save_config()
            self._append_log("配置已更新（重启后生效）", "#4fc3f7")

    def closeEvent(self, event):
        if self._worker:
            self._worker.stop_engine()
            if self._thread:
                self._thread.quit()
                self._thread.wait(5000)
        event.accept()
