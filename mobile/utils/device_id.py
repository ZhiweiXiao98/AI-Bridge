import uuid


def generate_device_id() -> str:
    """生成唯一设备标识，格式: Mobile_xxxxxxxx"""
    return f"Mobile_{uuid.uuid4().hex[:8]}"
