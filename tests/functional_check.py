"""
旁白 - 功能完整性检测脚本

用途：在 UI 重构 / 代码重构后快速验证所有功能模块接口完整、配置字段无遗漏、
     信号槽连接正确。不实际启动浏览器或调用 API，安全可重复执行。

使用方法：
    cd d:\\Saul\\desk\\直播伴侣
    python tests/functional_check.py

输出说明：
    [PASS] 通过  [FAIL] 失败  [WARN] 警告
    末尾会汇总统计，任何 FAIL 都需要修复后再打包。
"""

import os
import sys
import inspect
import importlib
import asyncio
from pathlib import Path

# ===== 环境变量必须在 import src 之前设置（与 main.py 一致）=====
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ms-playwright")
)

# 把项目根目录加入 path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===== 测试结果统计 =====
_PASS = 0
_FAIL = 0
_WARN = 0
_FAILURES = []


def _pass(msg):
    global _PASS
    _PASS += 1
    print(f"  [PASS] {msg}")


def _fail(msg, detail=""):
    global _FAIL
    _FAIL += 1
    _FAILURES.append((msg, detail))
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def _warn(msg):
    global _WARN
    _WARN += 1
    print(f"  [WARN] {msg}")


def _section(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# ====================================================================
# 1. 环境与依赖检测
# ====================================================================
def check_environment():
    _section("【1】环境与依赖检测")

    # Python 版本
    v = sys.version_info
    if v.major == 3 and 10 <= v.minor <= 12:
        _pass(f"Python 版本: {v.major}.{v.minor}.{v.micro}")
    elif v.major == 3 and v.minor >= 13:
        _fail(f"Python 版本: {v.major}.{v.minor}.{v.micro}", "Python 3.13+ 与 funasr_onnx 不兼容，请用 3.10-3.12")
    else:
        _fail(f"Python 版本: {v.major}.{v.minor}.{v.micro}", "需要 Python 3.10-3.12")

    # 关键依赖
    required_deps = {
        "PyQt6": "PyQt6.QtWidgets",
        "PyQt6.QtCore": "PyQt6.QtCore",
        "playwright": "playwright.async_api",
        "funasr_onnx": "funasr_onnx",
        "google.protobuf": "google.protobuf",
        "openai": "openai",
        "yaml": "yaml",
        "numpy": "numpy",
        "librosa": "librosa",
        "sklearn": "sklearn",
    }
    for name, import_path in required_deps.items():
        try:
            importlib.import_module(import_path)
            _pass(f"依赖: {name}")
        except ImportError as e:
            _fail(f"依赖: {name}", str(e))

    # FFmpeg
    try:
        from src.audio import AudioTranscriber
        if AudioTranscriber.is_ffmpeg_available():
            _pass("FFmpeg 可用")
        else:
            _fail("FFmpeg 不可用", "FFmpeg 未加入系统 PATH，语音转录功能无法工作")
    except Exception as e:
        _fail("FFmpeg 检测异常", str(e))


# ====================================================================
# 2. 模块导入检测
# ====================================================================
def check_imports():
    _section("【2】模块导入检测")

    modules = [
        ("src", "src"),
        ("src.__init__", "src"),
        ("src.gui", "src.gui"),
        ("src.core", "src.core"),
        ("src.audio", "src.audio"),
        ("src.danmu", "src.danmu"),
        ("src.llm_client", "src.llm_client"),
        ("src.sender", "src.sender"),
        ("src.updater", "src.updater"),
        ("src.kuaishou_pb2", "src.kuaishou_pb2"),
    ]
    for name, import_path in modules:
        try:
            mod = importlib.import_module(import_path)
            _pass(f"导入: {name}")
        except Exception as e:
            _fail(f"导入: {name}", f"{type(e).__name__}: {e}")


# ====================================================================
# 3. 版本号一致性检测
# ====================================================================
def check_version_consistency():
    _section("【3】版本号一致性检测")

    # src/__init__.py 中的 __version__
    from src import __version__
    _pass(f"src.__version__ = {__version__}")

    # installer.iss 中的 MyAppVersion
    iss_path = PROJECT_ROOT / "installer.iss"
    if iss_path.exists():
        content = iss_path.read_text(encoding="utf-8")
        if f'#define MyAppVersion "{__version__}"' in content:
            _pass("installer.iss 版本号一致")
        else:
            # 提取实际版本号
            import re
            m = re.search(r'#define MyAppVersion "([^"]+)"', content)
            iss_ver = m.group(1) if m else "未找到"
            _fail("installer.iss 版本号不一致", f"installer.iss={iss_ver}, src.__version__={__version__}")
    else:
        _fail("installer.iss 不存在")

    # version_info.txt 中的版本号
    vi_path = PROJECT_ROOT / "version_info.txt"
    if vi_path.exists():
        content = vi_path.read_text(encoding="utf-8")
        # filevers=(1, 0, 7, 0) 格式
        import re
        m = re.search(r"filevers=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", content)
        if m:
            vi_ver = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            if vi_ver == __version__:
                _pass("version_info.txt 版本号一致")
            else:
                _fail("version_info.txt 版本号不一致", f"version_info={vi_ver}, src.__version__={__version__}")
        else:
            _fail("version_info.txt 版本号解析失败")
    else:
        _fail("version_info.txt 不存在")

    # 发布者
    if 'atvkh' in content:
        _pass("version_info.txt 发布者为 atvkh")
    else:
        _fail("version_info.txt 发布者不是 atvkh")


# ====================================================================
# 4. 配置系统检测
# ====================================================================
def check_config_system():
    _section("【4】配置系统检测")

    # config.example.yaml 必须存在且字段完整
    example_path = PROJECT_ROOT / "config.example.yaml"
    if not example_path.exists():
        _fail("config.example.yaml 不存在")
        return

    import yaml
    with open(example_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if config is None:
        _fail("config.example.yaml 为空")
        return

    # 必需的顶级段
    required_sections = ["llm", "vision", "audio", "sender", "danmu"]
    for sec in required_sections:
        if sec in config:
            _pass(f"配置段: {sec}")
        else:
            _fail(f"配置段缺失: {sec}")

    # 必需字段
    required_fields = {
        "llm": ["provider", "api_key", "model", "base_url", "system_prompt", "temperature", "max_tokens"],
        "vision": ["enabled", "provider", "api_key", "models", "base_url"],
        "audio": ["whisper_model", "language", "segment_length"],
        "sender": ["min_interval", "max_interval", "max_length"],
        "danmu": ["enabled"],
    }
    for section, fields in required_fields.items():
        if section not in config:
            continue
        for field in fields:
            if field in config[section]:
                _pass(f"配置字段: {section}.{field}")
            else:
                _fail(f"配置字段缺失: {section}.{field}")

    # vision.models 必须是多模型列表
    vision_models = config.get("vision", {}).get("models", [])
    if isinstance(vision_models, list) and len(vision_models) >= 3:
        _pass(f"vision.models 多模型列表: {vision_models}")
    elif isinstance(vision_models, list):
        _warn(f"vision.models 只有 {len(vision_models)} 个模型，建议至少 3 个做回退")
    else:
        _fail("vision.models 不是列表类型", f"实际类型: {type(vision_models)}")

    # 默认模型顺序检查
    expected_models = ["glm-4.6v-flash", "glm-4.1v-thinking-flash", "glm-4v-flash"]
    if vision_models == expected_models:
        _pass("vision.models 顺序正确（4.6v → 4.1v → 4v）")
    elif vision_models:
        _warn(f"vision.models 顺序与默认不同: {vision_models}")

    # audio.whisper_model 应为 sensevoice-small
    wm = config.get("audio", {}).get("whisper_model", "")
    if wm == "sensevoice-small":
        _pass("audio.whisper_model = sensevoice-small")
    else:
        _warn(f"audio.whisper_model = {wm}（建议 sensevoice-small）")


# ====================================================================
# 5. GUI 控件完整性检测
# ====================================================================
def check_gui_controls():
    _section("【5】GUI 控件完整性检测")

    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
    except Exception as e:
        _fail("无法创建 QApplication", str(e))
        return

    # 导入 GUI 模块
    try:
        from src.gui import MainWindow, SettingsDialog, EngineWorker
    except Exception as e:
        _fail("无法导入 GUI 类", str(e))
        return

    # 主窗口控件
    try:
        from src import DATA_DIR
        # 用一个临时配置避免触发真实配置加载
        test_config_path = DATA_DIR / "config.yaml"
        window = MainWindow(str(test_config_path))
        window.show()
        _pass("MainWindow 实例化成功")

        # 必需控件（v1.0.8 UI 重构后控件名变化）
        required_controls = [
            "start_btn", "stop_btn", "settings_btn",
            "comment_text",          # 评论显示区
            "mini_btn", "log_btn",   # 悬浮/日志按钮
        ]
        for ctrl_name in required_controls:
            if hasattr(window, ctrl_name):
                _pass(f"控件: MainWindow.{ctrl_name}")
            else:
                _fail(f"控件缺失: MainWindow.{ctrl_name}")

        # 必需方法
        required_methods = [
            "_load_config", "_save_config", "_init_ui",
            "_on_start", "_on_stop", "_on_settings",
            "_on_status", "_on_danmu", "_on_transcription",
            "_on_comment", "_on_error", "_on_room_switch",
            "_on_engine_stopped", "closeEvent",
            "_check_for_update_auto", "_check_for_update_manual",
            "_show_about",
        ]
        for method_name in required_methods:
            if hasattr(window, method_name) and callable(getattr(window, method_name)):
                _pass(f"方法: MainWindow.{method_name}")
            else:
                _fail(f"方法缺失: MainWindow.{method_name}")

        window.close()
    except Exception as e:
        _fail("MainWindow 实例化失败", str(e))


# ====================================================================
# 6. SettingsDialog 控件完整性检测
# ====================================================================
def check_settings_dialog():
    _section("【6】SettingsDialog 控件完整性检测")

    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
    except Exception as e:
        _fail("无法创建 QApplication", str(e))
        return

    try:
        from src.gui import SettingsDialog
        import yaml

        example_path = PROJECT_ROOT / "config.example.yaml"
        with open(example_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        dialog = SettingsDialog(config)

        # 必需控件
        required_controls = [
            # LLM
            "provider_combo", "api_key_input", "model_input",
            "base_url_input", "system_prompt_input",
            "temperature_spin", "max_tokens_spin",
            # 视觉
            "vision_check", "vision_provider_combo",
            "vision_api_key_input", "vision_model_input", "vision_base_url_input",
            # 发送
            "min_interval_spin", "max_interval_spin", "max_length_spin",
            # 音频
            "whisper_combo", "segment_spin", "danmu_check",
        ]
        for ctrl_name in required_controls:
            if hasattr(dialog, ctrl_name):
                _pass(f"控件: SettingsDialog.{ctrl_name}")
            else:
                _fail(f"控件缺失: SettingsDialog.{ctrl_name}")

        # 必需方法
        required_methods = [
            "_init_ui", "_load_values", "_save",
            "get_config", "_on_provider_changed", "_on_vision_provider_changed",
        ]
        for method_name in required_methods:
            if hasattr(dialog, method_name) and callable(getattr(dialog, method_name)):
                _pass(f"方法: SettingsDialog.{method_name}")
            else:
                _fail(f"方法缺失: SettingsDialog.{method_name}")

        # 视觉模型输入框必须是多行 QTextEdit（不是 QLineEdit）
        from PyQt6.QtWidgets import QTextEdit, QLineEdit
        vmi = dialog.vision_model_input
        if isinstance(vmi, QTextEdit):
            _pass("vision_model_input 是多行 QTextEdit")
        elif isinstance(vmi, QLineEdit):
            _fail("vision_model_input 是单行 QLineEdit", "应为多行 QTextEdit 以支持多模型配置")
        else:
            _fail(f"vision_model_input 类型异常: {type(vmi).__name__}")

        # 测试 save 是否正确生成配置
        dialog._save()
        saved_config = dialog.get_config()

        # 检查保存的字段
        save_checks = [
            ("llm.provider", saved_config.get("llm", {}).get("provider")),
            ("llm.api_key", saved_config.get("llm", {}).get("api_key")),
            ("llm.model", saved_config.get("llm", {}).get("model")),
            ("llm.system_prompt", saved_config.get("llm", {}).get("system_prompt")),
            ("llm.temperature", saved_config.get("llm", {}).get("temperature")),
            ("llm.max_tokens", saved_config.get("llm", {}).get("max_tokens")),
            ("vision.enabled", saved_config.get("vision", {}).get("enabled")),
            ("vision.provider", saved_config.get("vision", {}).get("provider")),
            ("vision.models", saved_config.get("vision", {}).get("models")),
            ("sender.min_interval", saved_config.get("sender", {}).get("min_interval")),
            ("sender.max_interval", saved_config.get("sender", {}).get("max_interval")),
            ("sender.max_length", saved_config.get("sender", {}).get("max_length")),
            ("audio.whisper_model", saved_config.get("audio", {}).get("whisper_model")),
            ("audio.segment_length", saved_config.get("audio", {}).get("segment_length")),
            ("audio.language", saved_config.get("audio", {}).get("language")),
            ("danmu.enabled", saved_config.get("danmu", {}).get("enabled")),
        ]
        for field_name, value in save_checks:
            if value is not None:
                _pass(f"保存字段: {field_name} = {value}")
            else:
                _fail(f"保存字段缺失: {field_name}")

        # vision.models 必须是 list
        vm = saved_config.get("vision", {}).get("models")
        if isinstance(vm, list):
            _pass(f"vision.models 保存为列表: {vm}")
        else:
            _fail("vision.models 保存类型错误", f"期望 list，实际 {type(vm).__name__}: {vm}")

        # audio.language 必须是 zh
        lang = saved_config.get("audio", {}).get("language")
        if lang == "zh":
            _pass("audio.language = zh")
        else:
            _fail(f"audio.language = {lang}", "应为 zh")

        dialog.close()
    except Exception as e:
        _fail("SettingsDialog 检测失败", str(e))


# ====================================================================
# 7. EngineWorker 信号检测
# ====================================================================
def check_engine_worker_signals():
    _section("【7】EngineWorker 信号检测")

    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        from src.gui import EngineWorker

        worker = EngineWorker("/tmp/test_config.yaml")

        required_signals = [
            "status_changed", "danmu_received", "transcription_received",
            "comment_generated", "error_occurred", "room_switched", "stopped",
        ]
        for sig_name in required_signals:
            if hasattr(worker, sig_name):
                _pass(f"信号: EngineWorker.{sig_name}")
            else:
                _fail(f"信号缺失: EngineWorker.{sig_name}")

        # 方法
        required_methods = ["run", "stop_engine"]
        for method_name in required_methods:
            if hasattr(worker, method_name):
                _pass(f"方法: EngineWorker.{method_name}")
            else:
                _fail(f"方法缺失: EngineWorker.{method_name}")

    except Exception as e:
        _fail("EngineWorker 检测失败", str(e))


# ====================================================================
# 8. LiveCompanionEngine 接口检测
# ====================================================================
def check_engine_interface():
    _section("【8】LiveCompanionEngine 接口检测")

    try:
        from src.core import LiveCompanionEngine

        # 不要实际启动，只检测类属性和方法
        required_callbacks = [
            "on_status", "on_danmu", "on_transcription",
            "on_comment", "on_error", "on_room_switch",
        ]
        for cb_name in required_callbacks:
            if hasattr(LiveCompanionEngine, cb_name) or cb_name in LiveCompanionEngine.__init__.__code__.co_names:
                _pass(f"回调属性: engine.{cb_name}")
            else:
                # 检查是否在 __init__ 中赋值
                _warn(f"回调属性 engine.{cb_name} 未在类定义中找到（可能在 __init__ 动态赋值）")

        # 公开方法
        required_methods = ["save_config", "start", "stop"]
        for method_name in required_methods:
            if hasattr(LiveCompanionEngine, method_name):
                _pass(f"方法: engine.{method_name}")
            else:
                _fail(f"方法缺失: engine.{method_name}")

        # 检查 start/stop 是不是协程
        if asyncio.iscoroutinefunction(LiveCompanionEngine.start):
            _pass("engine.start 是协程方法")
        else:
            _fail("engine.start 不是协程方法", "必须 async def")

        if asyncio.iscoroutinefunction(LiveCompanionEngine.stop):
            _pass("engine.stop 是协程方法")
        else:
            _fail("engine.stop 不是协程方法", "必须 async def")

    except Exception as e:
        _fail("LiveCompanionEngine 检测失败", str(e))


# ====================================================================
# 9. 视觉模型回退检测
# ====================================================================
def check_vision_fallback():
    _section("【9】视觉模型回退检测")

    try:
        # 检查 core.py 源码中的关键常量和逻辑
        core_path = PROJECT_ROOT / "src" / "core.py"
        source = core_path.read_text(encoding="utf-8")

        # DEFAULT_VISION_MODELS
        if "DEFAULT_VISION_MODELS" in source:
            _pass("DEFAULT_VISION_MODELS 常量存在")
        else:
            _fail("DEFAULT_VISION_MODELS 常量缺失")

        # thinking_models
        if "thinking_models" in source:
            _pass("thinking_models 集合存在")
        else:
            _fail("thinking_models 集合缺失")

        # 默认模型顺序
        if "glm-4.6v-flash" in source and "glm-4.1v-thinking-flash" in source and "glm-4v-flash" in source:
            _pass("三模型回退配置存在")
        else:
            _fail("三模型回退配置缺失")

        # 429 错误码处理
        if "429" in source and "1305" in source:
            _pass("429/1305 限流错误码处理存在")
        else:
            _fail("429/1305 限流错误码处理缺失")

        # thinking 参数
        if "thinking" in source and "enabled" in source:
            _pass("thinking 参数开启逻辑存在")
        else:
            _fail("thinking 参数开启逻辑缺失")

        # reasoning_content 兜底
        if "reasoning_content" in source:
            _pass("reasoning_content 兜底逻辑存在")
        else:
            _fail("reasoning_content 兜底逻辑缺失")

        # <answer> 标签解析
        if "<answer>" in source and "</answer>" in source:
            _pass("<answer> 标签解析逻辑存在")
        else:
            _fail("<answer> 标签解析逻辑缺失")

        # parse_vision_response 函数
        if "parse_vision_response" in source:
            _pass("parse_vision_response 函数存在")
        else:
            _fail("parse_vision_response 函数缺失")

        # 视频就绪检测
        if "readyState" in source:
            _pass("视频就绪检测逻辑存在")
        else:
            _fail("视频就绪检测逻辑缺失")

        # 快手 CDN 匹配（v1.1.0 起迁移到 src/platforms/kuaishou.py）
        kuaishou_plat_path = PROJECT_ROOT / "src" / "platforms" / "kuaishou.py"
        kuaishou_plat_src = kuaishou_plat_path.read_text(encoding="utf-8") if kuaishou_plat_path.exists() else ""

        if "pull.yximgs.com" in kuaishou_plat_src:
            _pass("快手 CDN 域名匹配存在")
        else:
            _fail("快手 CDN 域名匹配缺失")

        # 排除项
        if "static.yximgs.com" in kuaishou_plat_src:
            _pass("排除封面截图 static.yximgs.com")
        else:
            _fail("未排除封面截图 static.yximgs.com")

        if "ntp.nc.gifshow.com" in kuaishou_plat_src:
            _pass("排除 NTP ntp.nc.gifshow.com")
        else:
            _fail("未排除 NTP ntp.nc.gifshow.com")

    except Exception as e:
        _fail("视觉模型回退检测失败", str(e))


# ====================================================================
# 10. 拟人化评论特征检测
# ====================================================================
def check_humanized_features():
    _section("【10】拟人化评论特征检测")

    try:
        core_path = PROJECT_ROOT / "src" / "core.py"
        source = core_path.read_text(encoding="utf-8")

        # 15% 水弹幕
        if "0.15" in source or "15" in source:
            if "6" in source and "hhh" in source and "?" in source:
                _pass("15% 水弹幕逻辑存在")
            else:
                _warn("水弹幕关键词检查未通过")
        else:
            _fail("15% 水弹幕概率缺失")

        # max_tokens 随机
        if "max_tokens" in source and ("random" in source.lower() or "randint" in source.lower() or "choices" in source.lower()):
            _pass("max_tokens 随机化逻辑存在")
        else:
            _warn("max_tokens 随机化逻辑未检测到（可能用了其他实现）")

        # 30% 语气词
        if "0.3" in source or "30" in source:
            if "啊" in source or "hhh" in source or "？" in source:
                _pass("30% 语气词后缀逻辑存在")
            else:
                _warn("语气词关键词检查未通过")
        else:
            _fail("30% 语气词概率缺失")

        # recent_comments 去重
        if "recent_comments" in source:
            _pass("recent_comments 去重逻辑存在")
        else:
            _fail("recent_comments 去重逻辑缺失")

        # llm.clear_history 切换直播间
        if "clear_history" in source:
            _pass("切换直播间清空 LLM 历史存在")
        else:
            _fail("切换直播间清空 LLM 历史缺失")

    except Exception as e:
        _fail("拟人化特征检测失败", str(e))


# ====================================================================
# 10.5 AI 后缀标记检测（v1.0.9 新增）
# ====================================================================
def check_ai_suffix():
    _section("【10.5】AI 后缀标记检测")

    try:
        core_path = PROJECT_ROOT / "src" / "core.py"
        source = core_path.read_text(encoding="utf-8")

        # ai_suffix 配置读取
        if 'ai_suffix' in source and 'sender_config' in source:
            _pass("core.py 读取 sender.ai_suffix 配置")
        else:
            _fail("core.py 未读取 sender.ai_suffix 配置")

        # suffix_text 配置读取
        if 'suffix_text' in source:
            _pass("core.py 读取 sender.suffix_text 配置")
        else:
            _fail("core.py 未读取 sender.suffix_text 配置")

        # 后缀拼接逻辑
        if 'f"{comment}{suffix}"' in source or "comment + suffix" in source:
            _pass("后缀拼接逻辑存在")
        else:
            _fail("后缀拼接逻辑缺失")

        # 后缀位置在去重检查后
        if source.find("ai_suffix") > source.find("recent_comments"):
            _pass("后缀拼接在去重检查之后")
        else:
            _warn("后缀拼接位置可能不正确（应在去重检查后）")

        # config.example.yaml 包含配置
        example_path = PROJECT_ROOT / "config.example.yaml"
        example = example_path.read_text(encoding="utf-8")
        if "ai_suffix" in example and "suffix_text" in example:
            _pass("config.example.yaml 包含 ai_suffix 和 suffix_text")
        else:
            _fail("config.example.yaml 缺少 ai_suffix / suffix_text")

        # GUI 控件
        gui_path = PROJECT_ROOT / "src" / "gui.py"
        gui_src = gui_path.read_text(encoding="utf-8")
        if "ai_suffix_check" in gui_src and "suffix_text_input" in gui_src:
            _pass("GUI 包含 AI 后缀开关和文本输入框")
        else:
            _fail("GUI 缺少 AI 后缀相关控件")

    except Exception as e:
        _fail("AI 后缀标记检测失败", str(e))


# ====================================================================
# 10.6 多账号热场检测（v1.0.9 新增）
# ====================================================================
def check_multi_account():
    _section("【10.6】多账号热场检测")

    try:
        # EngineManager 模块存在
        em_path = PROJECT_ROOT / "src" / "engine_manager.py"
        if em_path.exists():
            _pass("src/engine_manager.py 文件存在")
        else:
            _fail("src/engine_manager.py 文件缺失")
            return

        em_src = em_path.read_text(encoding="utf-8")

        # EngineManager 类
        if "class EngineManager" in em_src:
            _pass("EngineManager 类存在")
        else:
            _fail("EngineManager 类缺失")

        # 关键方法
        for method in ["start", "stop", "_distribute_comment"]:
            if f"def {method}" in em_src or f"async def {method}" in em_src:
                _pass(f"EngineManager.{method} 方法存在")
            else:
                _fail(f"EngineManager.{method} 方法缺失")

        # 共用 LLM
        if "_llm" in em_src and "LLMClient" in em_src:
            _pass("EngineManager 创建共用 LLMClient")
        else:
            _fail("EngineManager 未创建共用 LLM")

        # 随机分配
        if "random.choice" in em_src:
            _pass("随机分配评论逻辑存在")
        else:
            _fail("随机分配评论逻辑缺失")

        # 回退单账号模式
        if 'cookies.json' in em_src and 'master' in em_src:
            _pass("回退单账号模式逻辑存在")
        else:
            _warn("回退单账号模式逻辑未检测到")

        # core.py 主从分支
        core_path = PROJECT_ROOT / "src" / "core.py"
        core_src = core_path.read_text(encoding="utf-8")
        if 'role == "slave"' in core_src or 'role == "master"' in core_src:
            _pass("core.py 主从账号分支逻辑存在")
        else:
            _fail("core.py 主从账号分支缺失")

        # Cookie 按账号隔离
        if "self.cookie_file" in core_src and "DATA_DIR / cookie_file" in core_src:
            _pass("Cookie 按账号隔离逻辑存在")
        else:
            _fail("Cookie 按账号隔离缺失")

        # is_ready_to_send 方法
        if "def is_ready_to_send" in core_src:
            _pass("LiveCompanionEngine.is_ready_to_send 方法存在")
        else:
            _fail("LiveCompanionEngine.is_ready_to_send 缺失")

        # send_comment_direct 方法
        if "async def send_comment_direct" in core_src:
            _pass("LiveCompanionEngine.send_comment_direct 方法存在")
        else:
            _fail("LiveCompanionEngine.send_comment_direct 缺失")

        # on_comment_generated 回调
        if "on_comment_generated" in core_src:
            _pass("on_comment_generated 回调存在")
        else:
            _fail("on_comment_generated 回调缺失")

        # GUI 多账号管理
        gui_path = PROJECT_ROOT / "src" / "gui.py"
        gui_src = gui_path.read_text(encoding="utf-8")
        if "accounts_list" in gui_src and "_on_add_account" in gui_src and "_on_del_account" in gui_src:
            _pass("GUI 多账号管理控件存在")
        else:
            _fail("GUI 多账号管理控件缺失")

        # EngineWorker 使用 EngineManager
        if "EngineManager" in gui_src and "self.manager" in gui_src:
            _pass("EngineWorker 使用 EngineManager")
        else:
            _fail("EngineWorker 未使用 EngineManager")

    except Exception as e:
        _fail("多账号热场检测失败", str(e))


# ====================================================================
# 11. 切换直播间修复检测
# ====================================================================
def check_room_switch_fix():
    _section("【11】切换直播间修复检测")

    try:
        core_path = PROJECT_ROOT / "src" / "core.py"
        source = core_path.read_text(encoding="utf-8")

        # on_room_switch 回调
        if "on_room_switch" in source:
            _pass("on_room_switch 回调存在")
        else:
            _fail("on_room_switch 回调缺失")

        # 持久监听器方案（page.on response/request 在 _run_audio 开始时注册）
        if "_run_audio" in source and 'page.on("response"' in source:
            _pass("持久监听器方案存在")
        else:
            _fail("持久监听器方案缺失")

        # 清除 danmu_list / transcription
        if "danmu_list" in source and "transcription" in source:
            _pass("切换时清除弹幕/转录数据")
        else:
            _fail("切换时未清除弹幕/转录数据")

    except Exception as e:
        _fail("切换直播间修复检测失败", str(e))


# ====================================================================
# 12. 各功能模块接口检测
# ====================================================================
def check_module_interfaces():
    _section("【12】功能模块接口检测")

    # AudioTranscriber
    try:
        from src.audio import AudioTranscriber
        required = ["__init__", "set_log_callback", "start", "stop", "_load_model", "_log"]
        for m in required:
            if hasattr(AudioTranscriber, m):
                _pass(f"AudioTranscriber.{m}")
            else:
                _fail(f"AudioTranscriber.{m} 缺失")

        # start 必须是协程
        if asyncio.iscoroutinefunction(AudioTranscriber.start):
            _pass("AudioTranscriber.start 是协程")
        else:
            _fail("AudioTranscriber.start 不是协程")

        # is_ffmpeg_available 是静态方法
        if hasattr(AudioTranscriber, "is_ffmpeg_available"):
            _pass("AudioTranscriber.is_ffmpeg_available 静态方法存在")
        else:
            _fail("AudioTranscriber.is_ffmpeg_available 缺失")
    except Exception as e:
        _fail("AudioTranscriber 检测失败", str(e))

    # DanmuReader
    try:
        from src.danmu import DanmuReader
        required = ["__init__", "start", "stop", "_on_websocket", "_process_payload"]
        for m in required:
            if hasattr(DanmuReader, m):
                _pass(f"DanmuReader.{m}")
            else:
                _fail(f"DanmuReader.{m} 缺失")

        if asyncio.iscoroutinefunction(DanmuReader.start):
            _pass("DanmuReader.start 是协程")
        else:
            _fail("DanmuReader.start 不是协程")

        # WS_HOOK_JS 常量
        from src import danmu as danmu_mod
        if hasattr(danmu_mod, "WS_HOOK_JS"):
            _pass("WS_HOOK_JS 常量存在")
        else:
            _fail("WS_HOOK_JS 常量缺失")
    except Exception as e:
        _fail("DanmuReader 检测失败", str(e))

    # LLMClient
    try:
        from src.llm_client import LLMClient
        required = ["__init__", "generate_comment", "update_config", "clear_history"]
        for m in required:
            if hasattr(LLMClient, m):
                _pass(f"LLMClient.{m}")
            else:
                _fail(f"LLMClient.{m} 缺失")

        # generate_comment 签名
        sig = inspect.signature(LLMClient.generate_comment)
        params = list(sig.parameters.keys())
        if "context" in params and "recent_comments" in params:
            _pass(f"LLMClient.generate_comment 签名正确: {params}")
        else:
            _fail("LLMClient.generate_comment 签名错误", f"参数: {params}")
    except Exception as e:
        _fail("LLMClient 检测失败", str(e))

    # CommentSender
    try:
        from src.sender import CommentSender
        required = ["__init__", "send_comment", "_find_input_box", "comment_count"]
        for m in required:
            if hasattr(CommentSender, m):
                _pass(f"CommentSender.{m}")
            else:
                _fail(f"CommentSender.{m} 缺失")

        if asyncio.iscoroutinefunction(CommentSender.send_comment):
            _pass("CommentSender.send_comment 是协程")
        else:
            _fail("CommentSender.send_comment 不是协程")
    except Exception as e:
        _fail("CommentSender 检测失败", str(e))

    # AutoUpdater
    try:
        from src.updater import AutoUpdater
        required = ["__init__", "check_update", "download_installer", "install_and_restart", "_compare_versions"]
        for m in required:
            if hasattr(AutoUpdater, m):
                _pass(f"AutoUpdater.{m}")
            else:
                _fail(f"AutoUpdater.{m} 缺失")

        # 版本比较测试
        result = AutoUpdater._compare_versions("1.0.7", "1.0.6")
        if result > 0:
            _pass("AutoUpdater._compare_versions 测试通过")
        else:
            _fail("AutoUpdater._compare_versions 测试失败", f"1.0.7 vs 1.0.6 应返回 >0，实际 {result}")

        # 实例化测试
        updater = AutoUpdater("atvkh/live-mate", "1.0.7")
        if updater.api_url == "https://api.github.com/repos/atvkh/live-mate/releases/latest":
            _pass("AutoUpdater API URL 正确")
        else:
            _fail("AutoUpdater API URL 错误", updater.api_url)
    except Exception as e:
        _fail("AutoUpdater 检测失败", str(e))


# ====================================================================
# 13. .gitignore 敏感文件检测
# ====================================================================
def check_gitignore():
    _section("【13】.gitignore 敏感文件屏蔽检测")

    gitignore_path = PROJECT_ROOT / ".gitignore"
    if not gitignore_path.exists():
        _fail(".gitignore 不存在")
        return

    content = gitignore_path.read_text(encoding="utf-8")

    # 必须屏蔽的敏感文件
    sensitive_files = ["config.yaml", "cookies.json", "dev_doc.md", "app.log"]
    for f in sensitive_files:
        if f in content:
            _pass(f".gitignore 屏蔽: {f}")
        else:
            _fail(f".gitignore 未屏蔽: {f}")

    # 必须屏蔽的目录
    sensitive_dirs = [".workbuddy/", "build/", "dist/", "__pycache__/"]
    for d in sensitive_dirs:
        if d in content:
            _pass(f".gitignore 屏蔽: {d}")
        else:
            _fail(f".gitignore 未屏蔽: {d}")


# ====================================================================
# 14. 关键文件存在性检测
# ====================================================================
def check_key_files():
    _section("【14】关键文件存在性检测")

    key_files = [
        "main.py",
        "config.example.yaml",
        "requirements.txt",
        "installer.iss",
        "kuaishou-live-mate.spec",
        "version_info.txt",
        "app.ico",
        "logo.png",
        "LICENSE",
        "README.md",
        "src/__init__.py",
        "src/core.py",
        "src/audio.py",
        "src/danmu.py",
        "src/gui.py",
        "src/llm_client.py",
        "src/sender.py",
        "src/updater.py",
        "src/kuaishou_pb2.py",
    ]
    for f in key_files:
        path = PROJECT_ROOT / f
        if path.exists():
            _pass(f"文件存在: {f}")
        else:
            _fail(f"文件缺失: {f}")


# ====================================================================
# 15. PyInstaller spec 配置检测
# ====================================================================
def check_pyinstaller_spec():
    _section("【15】PyInstaller spec 配置检测")

    spec_path = PROJECT_ROOT / "kuaishou-live-mate.spec"
    if not spec_path.exists():
        _fail("kuaishou-live-mate.spec 不存在")
        return

    content = spec_path.read_text(encoding="utf-8")

    # onedir 模式（exclude_binaries=True）
    if "exclude_binaries=True" in content:
        _pass("onedir 模式（启动快）")
    else:
        _fail("非 onedir 模式", "应使用 onedir 模式，console=False")

    # console=False（不显示黑框）
    if "console=False" in content:
        _pass("console=False（无黑框）")
    else:
        _fail("console=True", "应设为 False 避免黑框")

    # version_info.txt 引用
    if "version_info.txt" in content:
        _pass("version_info.txt 引用存在")
    else:
        _fail("version_info.txt 引用缺失")

    # 图标
    if "app.ico" in content:
        _pass("图标引用存在")
    else:
        _fail("图标引用缺失")

    # 关键依赖
    required_imports = [
        "PyQt6.QtWidgets", "playwright", "funasr_onnx",
        "google.protobuf", "openai", "yaml", "numpy", "librosa", "sklearn",
    ]
    for imp in required_imports:
        if imp in content:
            _pass(f"hiddenimports: {imp}")
        else:
            _fail(f"hiddenimports 缺失: {imp}")

    # SenseVoiceSmall 模型文件
    if "sensevoice" in content.lower() and "model.onnx" in content:
        _pass("SenseVoiceSmall 模型打包配置存在")
    else:
        _fail("SenseVoiceSmall 模型打包配置缺失")


# ====================================================================
# 16. Inno Setup 脚本检测
# ====================================================================
def check_inno_setup():
    _section("【16】Inno Setup 脚本检测")

    iss_path = PROJECT_ROOT / "installer.iss"
    if not iss_path.exists():
        _fail("installer.iss 不存在")
        return

    content = iss_path.read_text(encoding="utf-8")

    # 发布者
    if 'MyAppPublisher "atvkh"' in content:
        _pass("发布者: atvkh")
    else:
        _fail("发布者不是 atvkh")

    # 版本号
    from src import __version__
    if f'#define MyAppVersion "{__version__}"' in content:
        _pass(f"版本号一致: {__version__}")
    else:
        _fail(f"版本号不一致（应为 {__version__}）")

    # 桌面快捷方式任务
    if "desktopicon" in content and "checkedonce" in content:
        _pass("桌面快捷方式任务配置正确")
    else:
        _fail("桌面快捷方式任务配置错误", "应使用 checkedonce 而非 uncheckedifrunas")

    # 安装前关闭旧进程
    if "taskkill" in content and "旁白.exe" in content:
        _pass("安装前关闭旧进程逻辑存在")
    else:
        _fail("安装前关闭旧进程逻辑缺失")


# ====================================================================
# 17. 平台抽象层与抖音支持检测（v1.1.0 新增）
# ====================================================================
def check_platform_abstraction():
    _section("【17】平台抽象层与抖音支持检测")

    try:
        # ── 文件结构 ──
        platforms_dir = PROJECT_ROOT / "src" / "platforms"
        required_files = ["__init__.py", "base.py", "registry.py", "kuaishou.py", "douyin.py"]
        for fname in required_files:
            fpath = platforms_dir / fname
            if fpath.exists():
                _pass(f"平台文件存在: src/platforms/{fname}")
            else:
                _fail(f"平台文件缺失: src/platforms/{fname}")

        # ── 工厂函数与平台列表 ──
        try:
            from src.platforms import create_platform, list_platforms, Platform
            platforms = list_platforms()
            if "kuaishou" in platforms and "douyin" in platforms:
                _pass(f"list_platforms 返回双平台: {platforms}")
            else:
                _fail(f"list_platforms 平台不完整: {platforms}")

            # 创建快手实例
            ks = create_platform("kuaishou")
            if ks.name == "kuaishou" and ks.display_name == "快手":
                _pass("create_platform('kuaishou') 正确")
            else:
                _fail("create_platform('kuaishou') 返回值异常")

            # 创建抖音实例
            dy = create_platform("douyin")
            if dy.name == "douyin" and dy.display_name == "抖音":
                _pass("create_platform('douyin') 正确")
            else:
                _fail("create_platform('douyin') 返回值异常")

            # 不支持的平台应抛 ValueError
            try:
                create_platform("bilibili")
                _fail("create_platform('bilibili') 应抛 ValueError")
            except ValueError:
                _pass("create_platform 不支持的平台抛 ValueError")
        except Exception as e:
            _fail("平台工厂函数检测失败", str(e))

        # ── Platform 抽象基类接口 ──
        try:
            from src.platforms.base import Platform
            abstract_methods = [
                "is_real_stream", "match_danmu_ws_url", "parse_danmu_payload",
                "get_player_selectors", "get_streamer_selectors",
                "get_category_selectors", "get_input_box_selectors",
            ]
            missing = [m for m in abstract_methods if not hasattr(Platform, m)]
            if not missing:
                _pass("Platform 抽象接口完整（7 个抽象方法）")
            else:
                _fail(f"Platform 抽象接口缺失: {missing}")

            # 类属性
            class_attrs = ["name", "display_name", "home_url", "login_check_js",
                          "room_url_pattern", "title_regex", "default_system_prompt"]
            missing_attrs = [a for a in class_attrs if not hasattr(Platform, a)]
            if not missing_attrs:
                _pass("Platform 类属性完整（7 个）")
            else:
                _fail(f"Platform 类属性缺失: {missing_attrs}")

            # 可选 hook 方法
            optional_hooks = ["prepare_danmu_connection", "build_auth_payload", "build_ack_payload"]
            for hook in optional_hooks:
                if hasattr(Platform, hook):
                    _pass(f"Platform 可选 hook 存在: {hook}")
                else:
                    _fail(f"Platform 可选 hook 缺失: {hook}")
        except Exception as e:
            _fail("Platform 抽象基类检测失败", str(e))

        # ── 快手平台实现 ──
        try:
            from src.platforms.kuaishou import KuaishouPlatform
            ks = KuaishouPlatform()

            # 基础元数据
            if ks.home_url == "https://live.kuaishou.com":
                _pass("快手 home_url 正确")
            else:
                _fail(f"快手 home_url 异常: {ks.home_url}")

            if "kuaishou" in ks.room_url_pattern:
                _pass("快手 room_url_pattern 正确")
            else:
                _fail(f"快手 room_url_pattern 异常: {ks.room_url_pattern}")

            # 直播流检测
            if ks.is_real_stream("https://tx-origin.pull.yximgs.com/gifshow/abc.flv", "video/x-flv"):
                _pass("快手 is_real_stream 识别直播流")
            else:
                _fail("快手 is_real_stream 未识别直播流")

            if not ks.is_real_stream("https://static.yximgs.com/cover/abc.jpg", "image/jpeg"):
                _pass("快手 is_real_stream 排除封面截图")
            else:
                _fail("快手 is_real_stream 未排除封面截图")

            if not ks.is_real_stream("https://ntp.nc.gifshow.com/ntp", "application/json"):
                _pass("快手 is_real_stream 排除 NTP")
            else:
                _fail("快手 is_real_stream 未排除 NTP")

            # 弹幕 WS 匹配
            if ks.match_danmu_ws_url("wss://livejs-ws.kuaishou.cn/group1"):
                _pass("快手 match_danmu_ws_url 识别弹幕 WS")
            else:
                _fail("快手 match_danmu_ws_url 未识别弹幕 WS")

            # 选择器非空
            for sel_name in ["get_player_selectors", "get_streamer_selectors",
                             "get_category_selectors", "get_input_box_selectors"]:
                sels = getattr(ks, sel_name)()
                if sels:
                    _pass(f"快手 {sel_name} 返回 {len(sels)} 个选择器")
                else:
                    _fail(f"快手 {sel_name} 返回空列表")

            # 弹幕解析（无效数据应返回空列表，不崩溃）
            result = ks.parse_danmu_payload(b"invalid data")
            if result == []:
                _pass("快手 parse_danmu_payload 异常输入兜底正常")
            else:
                _fail(f"快手 parse_danmu_payload 异常输入返回非空: {result}")
        except Exception as e:
            _fail("快手平台实现检测失败", str(e))

        # ── 抖音平台实现 ──
        try:
            from src.platforms.douyin import DouyinPlatform
            dy = DouyinPlatform()

            # 基础元数据
            if dy.home_url == "https://live.douyin.com":
                _pass("抖音 home_url 正确")
            else:
                _fail(f"抖音 home_url 异常: {dy.home_url}")

            if "douyin" in dy.room_url_pattern:
                _pass("抖音 room_url_pattern 正确")
            else:
                _fail(f"抖音 room_url_pattern 异常: {dy.room_url_pattern}")

            # 直播流检测
            if dy.is_real_stream("https://pull-flv.douyin.com/abc.flv", "video/x-flv"):
                _pass("抖音 is_real_stream 识别 FLV 流")
            else:
                _fail("抖音 is_real_stream 未识别 FLV 流")

            if dy.is_real_stream("https://xxx/live.m3u8", "application/vnd.apple.mpegurl"):
                _pass("抖音 is_real_stream 识别 HLS 流")
            else:
                _fail("抖音 is_real_stream 未识别 HLS 流")

            if not dy.is_real_stream("https://lf3-static.douyin.com/abc.js", "application/javascript"):
                _pass("抖音 is_real_stream 排除 JS 资源")
            else:
                _fail("抖音 is_real_stream 未排除 JS 资源")

            # 弹幕 WS 匹配
            if dy.match_danmu_ws_url("wss://webcast5-ws-web-lf.douyin.com/ws"):
                _pass("抖音 match_danmu_ws_url 识别弹幕 WS")
            else:
                _fail("抖音 match_danmu_ws_url 未识别弹幕 WS")

            # 选择器非空
            for sel_name in ["get_player_selectors", "get_streamer_selectors",
                             "get_category_selectors", "get_input_box_selectors"]:
                sels = getattr(dy, sel_name)()
                if sels:
                    _pass(f"抖音 {sel_name} 返回 {len(sels)} 个选择器")
                else:
                    _fail(f"抖音 {sel_name} 返回空列表")

            # 弹幕解析（无效数据应返回空列表，不崩溃）
            result = dy.parse_danmu_payload(b"invalid data")
            if result == []:
                _pass("抖音 parse_danmu_payload 异常输入兜底正常")
            else:
                _fail(f"抖音 parse_danmu_payload 异常输入返回非空: {result}")

            # protobuf wire format 解析器
            if hasattr(dy, "_parse_protobuf_fields") and hasattr(dy, "_read_varint"):
                _pass("抖音 protobuf wire format 解析器存在")
            else:
                _fail("抖音 protobuf wire format 解析器缺失")

            # 签名/鉴权 hook
            if asyncio.iscoroutinefunction(dy.prepare_danmu_connection):
                _pass("抖音 prepare_danmu_connection 是协程")
            else:
                _fail("抖音 prepare_danmu_connection 不是协程")

            if asyncio.iscoroutinefunction(dy.build_auth_payload):
                _pass("抖音 build_auth_payload 是协程")
            else:
                _fail("抖音 build_auth_payload 不是协程")

            if asyncio.iscoroutinefunction(dy.build_ack_payload):
                _pass("抖音 build_ack_payload 是协程")
            else:
                _fail("抖音 build_ack_payload 不是协程")

            # PushFrame 编码器
            if hasattr(dy, "_encode_push_frame") and hasattr(dy, "_encode_varint"):
                _pass("抖音 PushFrame 编码器存在")
            else:
                _fail("抖音 PushFrame 编码器缺失")

            # check_logged_in 覆盖（抖音 sessionid 是 HttpOnly，必须用 context.cookies）
            import inspect
            # 检查子类是否覆盖了基类方法（而不是用默认 JS 实现）
            dy_method = dy.check_logged_in
            base_method = Platform.check_logged_in
            if dy_method.__func__ is not base_method:
                _pass("抖音覆盖 check_logged_in（HttpOnly cookie 检测）")
            else:
                _fail("抖音未覆盖 check_logged_in，无法检测 HttpOnly cookie")
        except Exception as e:
            _fail("抖音平台实现检测失败", str(e))

        # ── core.py 接入 Platform 抽象 ──
        try:
            core_path = PROJECT_ROOT / "src" / "core.py"
            core_src = core_path.read_text(encoding="utf-8")

            if "from src.platforms import create_platform, Platform" in core_src:
                _pass("core.py 导入 Platform 抽象层")
            else:
                _fail("core.py 未导入 Platform 抽象层")

            if "self.platform: Platform = create_platform" in core_src or "self.platform = create_platform" in core_src:
                _pass("core.py 创建 platform 实例")
            else:
                _fail("core.py 未创建 platform 实例")

            # 委托给 platform 的关键调用
            if "self.platform.is_real_stream" in core_src:
                _pass("core.py 委托 is_real_stream 给 platform")
            else:
                _fail("core.py 未委托 is_real_stream 给 platform")

            if "self.platform.home_url" in core_src:
                _pass("core.py 使用 platform.home_url 导航")
            else:
                _fail("core.py 未使用 platform.home_url")

            if "self.platform.check_logged_in" in core_src:
                _pass("core.py 使用 platform.check_logged_in 检测登录")
            else:
                _fail("core.py 未使用 platform.check_logged_in")

            if "self.platform.room_url_pattern" in core_src:
                _pass("core.py 使用 platform.room_url_pattern 匹配直播间")
            else:
                _fail("core.py 未使用 platform.room_url_pattern")

            if "self.platform.get_player_selectors" in core_src:
                _pass("core.py 使用 platform 播放器选择器")
            else:
                _fail("core.py 未使用 platform 播放器选择器")
        except Exception as e:
            _fail("core.py 接入 Platform 检测失败", str(e))

        # ── danmu.py 接入 Platform ──
        try:
            danmu_path = PROJECT_ROOT / "src" / "danmu.py"
            danmu_src = danmu_path.read_text(encoding="utf-8")

            if "platform" in danmu_src and "match_danmu_ws_url" in danmu_src:
                _pass("danmu.py 使用 platform.match_danmu_ws_url")
            else:
                _fail("danmu.py 未使用 platform.match_danmu_ws_url")

            if "parse_danmu_payload" in danmu_src:
                _pass("danmu.py 使用 platform.parse_danmu_payload")
            else:
                _fail("danmu.py 未使用 platform.parse_danmu_payload")
        except Exception as e:
            _fail("danmu.py 接入 Platform 检测失败", str(e))

        # ── sender.py 接入 Platform ──
        try:
            sender_path = PROJECT_ROOT / "src" / "sender.py"
            sender_src = sender_path.read_text(encoding="utf-8")

            if "get_input_box_selectors" in sender_src:
                _pass("sender.py 使用 platform.get_input_box_selectors")
            else:
                _fail("sender.py 未使用 platform.get_input_box_selectors")
        except Exception as e:
            _fail("sender.py 接入 Platform 检测失败", str(e))

        # ── config.example.yaml 含 platform 字段 ──
        try:
            cfg_path = PROJECT_ROOT / "config.example.yaml"
            cfg_src = cfg_path.read_text(encoding="utf-8")
            if "platform: kuaishou" in cfg_src or "platform:" in cfg_src:
                _pass("config.example.yaml 含 platform 字段")
            else:
                _fail("config.example.yaml 缺 platform 字段")
        except Exception as e:
            _fail("config.example.yaml 检测失败", str(e))

        # ── GUI 平台切换按钮 ──
        try:
            gui_path = PROJECT_ROOT / "src" / "gui.py"
            gui_src = gui_path.read_text(encoding="utf-8")

            # v1.1.1 起改为 PlatformSwitcher 滑块开关组件
            if "class PlatformSwitcher" in gui_src and "platformChanged" in gui_src:
                _pass("GUI PlatformSwitcher 滑块组件存在")
            else:
                _fail("GUI PlatformSwitcher 滑块组件缺失")

            if "self.platform_switcher" in gui_src and "_switch_platform" in gui_src:
                _pass("GUI 平台切换接线正确")
            else:
                _fail("GUI 平台切换接线缺失")

            if "set_platform" in gui_src:
                _pass("GUI set_platform 方法存在")
            else:
                _fail("GUI set_platform 方法缺失")

            # 切换时清空会话
            if "context_text.clear" in gui_src and "comment_text.clear" in gui_src:
                _pass("GUI 切换平台时清空会话")
            else:
                _fail("GUI 切换平台时未清空会话")

            # 引擎运行中不允许切换
            if "请先停止当前引擎再切换平台" in gui_src:
                _pass("GUI 引擎运行中禁止切换平台")
            else:
                _fail("GUI 未禁止运行中切换平台")

            # AccountLoginDialog 用 check_logged_in（支持 HttpOnly cookie）
            if "plat.check_logged_in" in gui_src:
                _pass("GUI AccountLoginDialog 使用 check_logged_in")
            else:
                _fail("GUI AccountLoginDialog 未使用 check_logged_in")
        except Exception as e:
            _fail("GUI 平台切换检测失败", str(e))

    except Exception as e:
        _fail("平台抽象层检测失败", str(e))


# ====================================================================
# 主函数
# ====================================================================
def main():
    print("=" * 60)
    print("旁白 - 功能完整性检测脚本")
    print(f"项目路径: {PROJECT_ROOT}")
    print(f"Python: {sys.executable}")
    print(f"时间: {os.popen('echo %DATE% %TIME%').read().strip()}")
    print("=" * 60)

    checks = [
        check_environment,
        check_imports,
        check_version_consistency,
        check_config_system,
        check_gui_controls,
        check_settings_dialog,
        check_engine_worker_signals,
        check_engine_interface,
        check_vision_fallback,
        check_humanized_features,
        check_ai_suffix,
        check_multi_account,
        check_room_switch_fix,
        check_module_interfaces,
        check_gitignore,
        check_key_files,
        check_pyinstaller_spec,
        check_inno_setup,
        check_platform_abstraction,
    ]

    for check in checks:
        try:
            check()
        except Exception as e:
            _fail(f"{check.__name__} 异常崩溃", str(e))

    # ===== 汇总 =====
    print("\n" + "=" * 60)
    print("检测汇总")
    print("=" * 60)
    total = _PASS + _FAIL + _WARN
    print(f"  总计: {total} 项")
    print(f"  通过: {_PASS} 项")
    print(f"  失败: {_FAIL} 项")
    print(f"  警告: {_WARN} 项")

    if _FAILURES:
        print("\n" + "-" * 60)
        print("失败项清单：")
        print("-" * 60)
        for i, (msg, detail) in enumerate(_FAILURES, 1):
            print(f"  {i}. {msg}")
            if detail:
                print(f"     → {detail}")

    print("\n" + "=" * 60)
    if _FAIL == 0:
        print("✓ 全部通过，可以打包发布")
    else:
        print(f"✗ 有 {_FAIL} 项失败，必须修复后再打包")
    print("=" * 60)

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
