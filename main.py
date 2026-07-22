"""直播伴侣 - 快手直播间AI互动助手"""

import os
# 修复protobuf旧版生成代码与新版库的兼容问题，必须在import protobuf之前设置
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
# 屏蔽huggingface_hub的symlinks警告（Windows不支持符号链接，回退到普通缓存即可）
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import sys
from PyQt6.QtWidgets import QApplication
from src.gui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("直播伴侣")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
