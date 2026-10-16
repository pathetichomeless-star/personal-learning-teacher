"""采样级 PCM 缓冲.

输出回调混音使用的线程安全 FIFO

R-1f（rev-9 A.12）：每个实例持有单调递增的 `pcm_fifo_instance_id`；
`pull()` 内按 (I1)/(I2)/(I3) 规则计数（部分欠载、部分补零、排空边沿）；
所有 `pcm_fifo_*` 计数均为「每实例单调」，实例重建后不复用旧值。
计数仅做整数自增，回调内无 I/O、无日志、无时间读取。
"""

import itertools
import threading
from collections import deque

import numpy as np

_FIFO_IDS = itertools.count(1)


class PcmFifo:
    """采样级 PCM FIFO（float32 单声道，线程安全）.

    写入端在 asyncio 线程，读取端在音频输出回调线程；
    用于 TTS / 音乐分流后在输出回调中混音。

    - push：超出容量丢最旧（记入 dropped）
    - pull：返回定长块，数据不足补零；完全无数据返回 None
    """

    def __init__(self, max_samples: int):
        self._chunks: deque = deque()
        self._offset = 0  # 首块已消费的样本数
        self._size = 0  # 可读样本总数
        self._max = int(max_samples)
        self._lock = threading.Lock()
        self.dropped = 0
        # ---- R-1f (A.12) instance identity + per-instance counters --------
        self.instance_id = next(_FIFO_IDS)
        self.pcm_fifo_partial_underfill_events = 0
        self.pcm_fifo_partial_zero_pad_samples = 0
        self.pcm_fifo_drained_to_empty_events = 0
        self.pcm_fifo_peak_samples = 0

    @property
    def size(self) -> int:
        return self._size

    def push(self, pcm: np.ndarray) -> None:
        """追加 float32 单声道数据；容量超限时丢最旧."""
        if pcm.ndim > 1:
            pcm = pcm.reshape(-1)
        if pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)
        with self._lock:
            self._chunks.append(pcm)
            self._size += len(pcm)
            while self._size > self._max and self._chunks:
                head = self._chunks[0]
                remain = len(head) - self._offset
                drop = min(remain, self._size - self._max)
                self._offset += drop
                self._size -= drop
                self.dropped += drop
                if self._offset >= len(head):
                    self._chunks.popleft()
                    self._offset = 0
            if self._size > self.pcm_fifo_peak_samples:
                self.pcm_fifo_peak_samples = self._size

    def pull(self, n: int) -> np.ndarray | None:
        """取 n 个样本；无数据返回 None，不足补零."""
        with self._lock:
            if self._size == 0:
                # (I1) whole-empty branch — no drained edge (nothing consumed)
                return None
            size_before = self._size            # (I3) captured before consumption
            out = np.zeros(n, dtype=np.float32)
            filled = 0
            while filled < n and self._chunks:
                head = self._chunks[0]
                avail = len(head) - self._offset
                take = min(avail, n - filled)
                out[filled : filled + take] = head[
                    self._offset : self._offset + take
                ]
                filled += take
                self._offset += take
                self._size -= take
                if self._offset >= len(head):
                    self._chunks.popleft()
                    self._offset = 0
            missing = n - filled                # (I2) partial counting
            if missing > 0:                     # 0 < available_samples < n
                self.pcm_fifo_partial_underfill_events += 1
                self.pcm_fifo_partial_zero_pad_samples += missing
            if size_before > 0 and self._size == 0:
                self.pcm_fifo_drained_to_empty_events += 1
            return out

    def clear(self) -> int:
        """清空，返回丢弃的样本数（不产生排空边沿）."""
        with self._lock:
            count = self._size
            self._chunks.clear()
            self._offset = 0
            self._size = 0
            return count

    def snapshot_locked(self):
        """Lock-held atomic read of the FIFO scalars (rev-9 M-1).

        Used only by the T2 stop snapshot / T2-B end snapshot, which need
        size and drained_events to be mutually consistent.  Not called from
        the realtime callback.
        """
        with self._lock:
            return {
                "instance_id": self.instance_id,
                "size": self._size,
                "dropped": self.dropped,
                "partial_underfill_events": self.pcm_fifo_partial_underfill_events,
                "partial_zero_pad_samples": self.pcm_fifo_partial_zero_pad_samples,
                "drained_to_empty_events": self.pcm_fifo_drained_to_empty_events,
                "peak_samples": self.pcm_fifo_peak_samples,
            }

    def snapshot(self):
        """GIL-atomic per-counter read (window-START snapshots, A.12)."""
        return {
            "instance_id": self.instance_id,
            "size": self._size,
            "dropped": self.dropped,
            "partial_underfill_events": self.pcm_fifo_partial_underfill_events,
            "partial_zero_pad_samples": self.pcm_fifo_partial_zero_pad_samples,
            "drained_to_empty_events": self.pcm_fifo_drained_to_empty_events,
            "peak_samples": self.pcm_fifo_peak_samples,
        }