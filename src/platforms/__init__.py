"""平台抽象层：支持多直播间平台（快手/抖音/...）

导出：
- Platform: 抽象基类
- create_platform: 工厂函数
- list_platforms: 支持的平台列表
"""

from src.platforms.base import Platform
from src.platforms.registry import create_platform, list_platforms
from src.platforms.kuaishou import KuaishouPlatform
from src.platforms.douyin import DouyinPlatform

__all__ = [
    "Platform",
    "create_platform",
    "list_platforms",
    "KuaishouPlatform",
    "DouyinPlatform",
]
