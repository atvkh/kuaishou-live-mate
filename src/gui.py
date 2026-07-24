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
    QProgressDialog, QMenu, QMenuBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, pyqtSlot, QTimer
from PyQt6.QtGui import QTextCursor, QIcon

from src.core import LiveCompanionEngine
from src import APP_DIR, DATA_DIR, __version__


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
    cursor: pointer;
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

        self.system_prompt_input = QTextEditField()
        self.system_prompt_input.setMaximumHeight(60)
        llm_layout.addRow("系统提示词:", self.system_prompt_input)

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

        self.vision_check = QCheckBox("启用截图识别直播类型")
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

        self.danmu_check = QCheckBox("启用弹幕采集")
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

        self.setWindowTitle(f"旁白 v{__version__}")
        # 查找图标：exe模式下图标.png可能在_internal子目录
        icon_path = str(APP_DIR / "图标.png")
        if not os.path.exists(icon_path):
            icon_path = str(APP_DIR / "_internal" / "图标.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(800, 600)
        self.resize(960, 700)
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
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ── 顶部控制栏 ──
        top_bar = QHBoxLayout()

        self.start_btn = QPushButton("启动")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start)
        top_bar.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        top_bar.addWidget(self.stop_btn)

        self.settings_btn = QPushButton("设置")
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self.statusBar().showMessage(f"旁白 v{__version__} | 就绪")

        # ── 菜单栏 ──
        menubar = self.menuBar()
        help_menu = menubar.addMenu("帮助")
        check_update_action = help_menu.addAction("检查更新")
        check_update_action.triggered.connect(self._check_for_update_manual)
        about_action = help_menu.addAction("关于")
        about_action.triggered.connect(self._show_about)

        # 启动3秒后自动检查更新
        QTimer.singleShot(3000, self._check_for_update_auto)

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
        try:
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
            self._worker.room_switched.connect(self._on_room_switch)
            self._worker.stopped.connect(self._on_engine_stopped)

            self._thread.start()
            self._append_log("引擎启动", "#4caf50")
        except Exception as e:
            self._append_log(f"启动失败: {e}", "#ef5350")
            self.status_label.setText("启动失败")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.settings_btn.setEnabled(True)
            import traceback
            traceback.print_exc()

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
        self.statusBar().showMessage(f"旁白 v{__version__} | {msg}")
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
            f"旁白 v{__version__} | 已发送 {self._comment_count} 条评论"
        )

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._append_log(f"错误: {msg}", "#ef5350")
        self.status_label.setText("出错")

    @pyqtSlot()
    def _on_room_switch(self):
        """切换直播间时清除GUI中的弹幕/转录/评论记录"""
        self.danmu_text.clear()
        self.transcription_text.clear()
        self.comment_text.clear()
        self._comment_count = 0
        self._append_log("已切换直播间，清除旧记录", "#4fc3f7")

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
        try:
            from src.updater import AutoUpdater

            updater = AutoUpdater("atvkh/kuaishou-live-mate", __version__)

            class UpdateCheckWorker(QObject):
                done = pyqtSignal(dict)

                @pyqtSlot()
                def run(self):
                    result = updater.check_update()
                    self.done.emit(result)

            self._update_worker = UpdateCheckWorker()
            self._update_thread = QThread()
            self._update_worker.moveToThread(self._update_thread)
            self._update_thread.started.connect(self._update_worker.run)
            self._update_worker.done.connect(lambda r: self._on_update_checked(r, silent))
            self._update_worker.done.connect(self._update_thread.quit)
            self._update_thread.start()
        except Exception as e:
            if not silent:
                self._append_log(f"检查更新失败: {e}", "#ff9800")

    def _on_update_checked(self, result: dict, silent: bool):
        """更新检查完成回调"""
        if not result["has_update"]:
            if not silent:
                QMessageBox.information(self, "检查更新", f"已是最新版本 v{__version__}")
            return

        new_ver = result["latest_version"]
        notes = result.get("release_notes", "")
        msg = f"发现新版本 v{new_ver}！\n\n当前版本: v{__version__}\n\n"
        if notes:
            msg += f"更新内容:\n{notes[:300]}\n\n"
        msg += "是否立即下载并更新？"

        reply = QMessageBox.question(
            self, "发现新版本", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._download_and_install(result["download_url"])

    def _download_and_install(self, url: str):
        """下载installer并安装"""
        if not url:
            QMessageBox.warning(self, "更新失败", "未找到下载地址，请前往 GitHub 手动下载")
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
            QMessageBox.warning(self, "更新失败", "下载失败，请稍后重试或前往 GitHub 手动下载")
            return

        reply = QMessageBox.information(
            self, "下载完成",
            "更新已下载完成，程序将退出并开始安装，安装完成后会自动重启。",
            QMessageBox.StandardButton.Ok,
        )

        from src.updater import AutoUpdater
        updater = AutoUpdater("atvkh/kuaishou-live-mate", __version__)
        updater.install_and_restart(installer_path)

    def _show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self, "关于",
            f"<h3>旁白 v{__version__}</h3>"
            f"<p>快手直播间AI互动助手</p>"
            f"<p>实时采集弹幕与主播语音，LLM生成评论自动发送</p>"
            f"<p>GitHub: <a href='https://github.com/atvkh/kuaishou-live-mate'>"
            f"github.com/atvkh/kuaishou-live-mate</a></p>"
        )

    def closeEvent(self, event):
        if self._worker:
            self._worker.stop_engine()
            if self._thread:
                self._thread.quit()
                self._thread.wait(5000)
        event.accept()
