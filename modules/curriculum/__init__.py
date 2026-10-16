# -*- coding: utf-8 -*-
"""CLASSROOM V2 课程数据契约（v1）—— 单一事实源所在包。

权威实现：:mod:`modules.curriculum.course_schema`
机器可读 schema：``course_schema.v1.json``（同目录）

客户端的**冻结镜像**位于 ``client/src/classroom/course_schema.py`` 与
``client/src/classroom/course_schema.v1.json``；两侧由
``gateway/tests/course_schema_consistency_tests.py`` 断言同版本一致。
客户端为独立 PyInstaller 包，**不得**在运行期依赖本包路径。
"""
