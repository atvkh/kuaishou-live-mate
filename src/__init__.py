"""旁白 - 快手直播间AI互动助手"""

import sys
import os
from pathlib import Path

# 版本号（语义化版本，每次发版修改此处）
__version__ = "1.0.8"

# 应用根目录：exe模式下用exe所在目录，脚本模式下用项目根目录
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后，sys.executable 是 exe 路径
    APP_DIR = Path(sys.executable).parent
    # 用户数据目录：Windows标准 %APPDATA%\旁白\
    DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "旁白"
else:
    # 脚本模式下，取 main.py 所在目录（项目根目录）
    APP_DIR = Path(__file__).parent.parent
    # 开发模式下数据也放项目根目录，方便调试
    DATA_DIR = APP_DIR

# 确保数据目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
