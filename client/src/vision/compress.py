"""图像校验与压缩（VISION V0.6）。

validate/plan 纯逻辑可测；cv2 延迟导入（缺失环境跳过压缩测试）。
EXIF：cv2.imencode 重编码天然去除元数据。
"""
MAX_EDGE = 1280
MAX_BYTES = 190 * 1024          # 与网关 send_image 守卫一致
MIN_INTERVAL_S = 5.0
MAX_PER_MIN = 6


def validate_jpeg(raw):
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 3:
        return False, "empty"
    if bytes(raw[:3]) != b"\xff\xd8\xff":
        return False, "not_jpeg"
    if len(raw) > MAX_BYTES:
        return False, "too_large"
    return True, ""


def compress_plan(w, h):
    scale = min(1.0, MAX_EDGE / float(max(w, h, 1)))
    return int(max(1, round(w * scale))), int(max(1, round(h * scale)))


def compress_jpeg(raw, max_bytes=MAX_BYTES):
    """JPEG → 重编码（去 EXIF）→ 逐级降质至 ≤max_bytes。返回 (bytes, quality) 或 (None, 0)。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None, 0
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None, 0
    h, w = img.shape[:2]
    tw, th = compress_plan(w, h)
    if (tw, th) != (w, h):
        img = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
    q = 0.85
    while q >= 0.4:
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(q * 100)])
        if ok and len(buf.tobytes()) <= max_bytes:
            return buf.tobytes(), q
        q = round(q - 0.1, 2)
    return None, 0
