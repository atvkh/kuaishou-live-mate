"""平台工厂：根据平台名创建对应 Platform 实例"""

from src.platforms.base import Platform
from src.platforms.kuaishou import KuaishouPlatform
from src.platforms.douyin import DouyinPlatform


def create_platform(name: str) -> Platform:
    """根据平台名创建 Platform 实例

    Args:
        name: 平台标识 "kuaishou" / "douyin"

    Returns:
        Platform 实例

    Raises:
        ValueError: 不支持的平台
    """
    name_lower = (name or "").lower().strip()
    if name_lower == "kuaishou":
        return KuaishouPlatform()
    if name_lower == "douyin":
        return DouyinPlatform()
    raise ValueError(f"不支持的平台: {name}（支持: kuaishou, douyin）")


def list_platforms() -> list[str]:
    """返回支持的平台标识列表"""
    return ["kuaishou", "douyin"]
