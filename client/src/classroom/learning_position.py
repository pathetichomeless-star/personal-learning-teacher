# -*- coding: utf-8 -*-
"""学习位置持久化（HUMAN_GUI_ACCEPTANCE_FIX01 · P1-1）。

与 ``learning_record.py`` 同级的最小模块：只记「学到哪里」，
不复用学习记录条目契约（ITEM_TYPES 属冻结面，不扩枚举）。

结构约束（与 learning_record 一致）：
* 原子写（tmp + ``os.replace``）、权限 600；
* 损坏文件 → 隔离为 ``*.corrupt-<ts>`` 后空启动，绝不崩溃、绝不静默丢数据掩盖；
* 不含任何用户身份字段（本地单用户，与学习记录同 scope）。
"""

from __future__ import annotations

import json
import os
import time

SCOPE = "local-single-user"


class LearningPositionStore:
    """按课程隔离的「学习位置 + 最近学习」持久化。"""

    def __init__(self, path: str):
        self.path = str(path)
        self.read_error = ""
        self.recovered_from_corruption = False
        self._data: dict = {"scope": SCOPE, "version": 1,
                            "courses": {}, "last": None}
        self._load()

    # ---- persistence -------------------------------------------------------
    def _load(self) -> None:
        p = self.path
        if not p or not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("bad shape")
            self._data = {
                "scope": SCOPE, "version": 1,
                "courses": data.get("courses") if isinstance(data.get("courses"), dict) else {},
                "last": data.get("last") if isinstance(data.get("last"), dict) else None,
            }
        except Exception as e:  # noqa: BLE001 —— 损坏不得崩，转隔离后空启动
            self.read_error = "学习位置文件损坏（%s），已隔离并空启动" % type(e).__name__
            self.recovered_from_corruption = True
            try:
                os.replace(p, "%s.corrupt-%d" % (p, int(time.time())))
            except OSError:
                pass

    def _persist(self) -> None:
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        tmp = "%s.%d.tmp" % (self.path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # ---- read --------------------------------------------------------------
    def for_course(self, course_id: str) -> dict:
        """返回 ``{"lesson_id","lesson_index","slide_index","updated"}`` 或 ``{}``。"""
        row = self._data["courses"].get(str(course_id or ""))
        return dict(row) if isinstance(row, dict) else {}

    @property
    def last(self) -> dict:
        return dict(self._data["last"]) if isinstance(self._data.get("last"), dict) else {}

    # ---- write -------------------------------------------------------------
    def save(self, *, course_id: str, lesson_id: str, lesson_index: int,
             slide_index: int, title: str = "") -> None:
        if not course_id:
            return
        row = {"lesson_id": str(lesson_id or ""), "lesson_index": int(lesson_index),
               "slide_index": int(slide_index), "title": str(title or ""),
               "updated": time.time()}
        self._data["courses"][str(course_id)] = row
        self._data["last"] = {"course_id": str(course_id), **row}
        self._persist()

    def clear_course(self, course_id: str) -> None:
        self._data["courses"].pop(str(course_id or ""), None)
        if (self._data.get("last") or {}).get("course_id") == str(course_id or ""):
            self._data["last"] = None
        self._persist()
