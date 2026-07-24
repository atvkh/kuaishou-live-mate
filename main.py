"""旁白 - 快手直播间AI互动助手"""

import os
# 修复protobuf旧版生成代码与新版库的兼容问题，必须在import protobuf之前设置
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
# 屏蔽huggingface_hub的symlinks警告（Windows不支持符号链接，回退到普通缓存即可）
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
# 关键：指定Playwright浏览器安装路径到用户目录，避免打包后找不到浏览器
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ms-playwright")
)

import sys
import traceback
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMessageBox
from src.gui import MainWindow


def _get_log_path():
    """获取日志文件路径（与config同目录）"""
    try:
        from src import DATA_DIR
        return str(DATA_DIR / "app.log")
    except Exception:
        return str(Path.home() / "旁白" / "app.log")


def _log_error(msg: str):
    """写入错误日志文件"""
    try:
        log_path = _get_log_path()
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


def global_exception_handler(exc_type, exc_value, exc_tb):
    """全局未捕获异常处理：记录日志 + 弹窗提示"""
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _log_error(f"未捕获异常:\n{error_msg}")
    # 尝试弹窗显示
    try:
        app = QApplication.instance()
        if app:
            QMessageBox.critical(
                None, "程序出错",
                f"程序发生错误，请查看日志：\n\n{error_msg[:500]}\n\n日志路径：{_get_log_path()}"
            )
    except Exception:
        pass


def main():
    # 安装全局异常捕获
    sys.excepthook = global_exception_handler

    app = QApplication(sys.argv)
    app.setApplicationName("旁白")

    try:
        window = MainWindow()
        window.show()
        _log_error("程序启动成功")
        sys.exit(app.exec())
    except Exception as e:
        error_msg = traceback.format_exc()
        _log_error(f"启动失败:\n{error_msg}")
        try:
            QMessageBox.critical(
                None, "启动失败",
                f"程序启动失败：\n\n{error_msg[:500]}\n\n日志路径：{_get_log_path()}"
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
