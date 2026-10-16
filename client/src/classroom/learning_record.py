# -*- coding: utf-8 -*-
"""Local single-user learning records (CLASSROOM V2 · Agent F · Phase 2).

Stores **structured** study events (notes / mistakes / review / mastery) on the
local machine, survives app restarts, recovers from a corrupt file without
crashing, and supports GUI deletion.

Hard boundaries (from the contract, enforced here)
--------------------------------------------------
* **Not a multi-student system.** Every record carries ``scope="local-single-user"``
  and there is **no** user-id / account field anywhere.  This module must never be
  presented as per-student identity isolation.
* **No free-form private content by default.** Only ``prompt`` / ``answer`` text
  that the caller explicitly passes is stored; no recordings, no full dialogue.
* **Atomic + private on disk.** tmp file + ``os.replace``, mode ``0o600``.
* **Corrupt file → never crash.** Move aside to ``*.corrupt-<ts>`` and start empty,
  reporting ``recovered_from_corruption=True``.
"""

from __future__ import annotations

import json
import os
import time

SCOPE = "local-single-user"
ITEM_TYPES = ("note", "mistake", "review", "mastery")


class LearningRecordStore:
    """A small append-mostly store with derived views (mistakes / review / mastery)."""

    def __init__(self, path: str, *, max_records: int = 5000):
        self.path = str(path)
        self.max_records = int(max_records)
        self._records: list = []
        self.read_error = ""
        self.recovered_from_corruption = False
        self._load()

    # ---- persistence -------------------------------------------------------
    def _load(self) -> None:
        p = self.path
        if not p or not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("records"), list):
                raise ValueError("bad shape")
            self._records = [r for r in data["records"] if isinstance(r, dict)]
        except Exception as e:  # noqa: BLE001  — 损坏不得崩，转隔离后空启动
            self._quarantine(p, e)

    def _quarantine(self, p: str, err: Exception) -> None:
        self.read_error = "学习记录文件损坏（%s），已隔离并空启动" % type(err).__name__
        self.recovered_from_corruption = True
        try:
            os.replace(p, "%s.corrupt-%d" % (p, int(time.time())))
        except OSError:
            pass
        self._records = []

    def _persist(self) -> None:
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        tmp = "%s.%d.tmp" % (self.path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"scope": SCOPE, "version": 1, "records": self._records},
                      f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # ---- write -------------------------------------------------------------
    def add(self, *, course_id: str, lesson_id: str, item_id: str, item_type: str,
            prompt: str = "", answer: str = "", result: str = "",
            source: str = "local", ts: "float | None" = None) -> dict:
        if item_type not in ITEM_TYPES:
            raise ValueError("未知 item_type %r（不得静默写入）" % (item_type,))
        if not course_id:
            raise ValueError("course_id 必填（记录归属，非身份）")
        rec = {
            "course_id": str(course_id),
            "lesson_id": str(lesson_id or ""),
            "item_id": str(item_id or ""),
            "item_type": item_type,
            "prompt": str(prompt or "")[:2000],
            "answer": str(answer or "")[:2000],
            "result": str(result or "")[:200],
            "source": str(source or "local"),
            "ts": float(ts if ts is not None else time.time()),
            "scope": SCOPE,
        }
        self._records.append(rec)
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records:]
        self._persist()
        return rec

    # ---- read / derived views ---------------------------------------------
    def all(self) -> list:
        return list(self._records)

    def count(self) -> int:
        return len(self._records)

    def for_course(self, course_id: str) -> list:
        return [r for r in self._records if r["course_id"] == str(course_id)]

    def mistakes(self, course_id: "str | None" = None) -> list:
        """错题本：item_type=mistake 或 result in {wrong, incorrect}."""
        out = [r for r in self._records
               if r["item_type"] == "mistake" or r["result"] in ("wrong", "incorrect")]
        return [r for r in out if course_id is None or r["course_id"] == str(course_id)]

    def review_queue(self, course_id: "str | None" = None) -> list:
        """待复习：显式标记 review 的条目（去重按 item_id 保留最新）。"""
        latest: dict = {}
        for r in self._records:
            if r["item_type"] != "review":
                continue
            if course_id is not None and r["course_id"] != str(course_id):
                continue
            latest[r["course_id"] + "/" + r["item_id"]] = r
        return sorted(latest.values(), key=lambda r: r["ts"])

    def mastery(self, course_id: str) -> float:
        """掌握度 = 非错题记录 / 全部记录（0..1，无记录返回 0.0）。"""
        rows = self.for_course(course_id)
        if not rows:
            return 0.0
        good = sum(1 for r in rows if r["item_type"] != "mistake"
                   and r["result"] not in ("wrong", "incorrect"))
        return round(good / len(rows), 4)

    # ---- delete (GUI) ------------------------------------------------------
    def delete_one(self, index: int) -> dict:
        if not (0 <= index < len(self._records)):
            raise IndexError("记录下标越界：%d" % index)
        rec = self._records.pop(index)
        self._persist()
        return rec

    def delete_course(self, course_id: str) -> int:
        before = len(self._records)
        self._records = [r for r in self._records if r["course_id"] != str(course_id)]
        n = before - len(self._records)
        if n:
            self._persist()
        return n

    def clear(self) -> None:
        self._records = []
        self._persist()

    def snapshot(self) -> dict:
        """Non-sensitive summary for the UI / tests (never includes raw dialogue)."""
        return {"scope": SCOPE, "count": len(self._records),
                "mistakes": len(self.mistakes()),
                "review": len(self.review_queue()),
                "read_error": self.read_error,
                "recovered_from_corruption": self.recovered_from_corruption}
