# Course Schema v1 — 勘误（Errata）No.1：SHA-256 正则放宽

- 文档类型：**勘误（errata）**，**不是**结构变更，**不是**版本升级
- 适用契约：`classroom.course.bundle` v1（冻结唯一 Course Schema）
- 上游依据：`CLASSROOM_V2_CONTRACT_FIX_01A` 一.4 / 一.3；产品负责人 `DELIVERY GATE 02` 一.4
- 影响文件：
  - 权威：`modules/curriculum/course_schema.v1.json` + `modules/curriculum/course_schema.py`
  - 镜像：`client/src/classroom/course_schema.v1.json` + `client/src/classroom/course_schema.py`
- 生成：总控工程 Agent（TC）· `2026-10-12`

---

## 1. 变更内容（唯一变更）

| 字段 | 旧（v1 原文） | 新（v1 勘误后） |
|---|---|---|
| `source_doc_hash`（`if/then` 分支内 pattern） | `^sha256:[0-9a-f]{64}$` | `^(?:sha256:)?[0-9a-f]{64}$` |
| `source_file_sha256`（`if/then` 分支内 pattern） | `^sha256:[0-9a-f]{64}$` | `^(?:sha256:)?[0-9a-f]{64}$` |

**除此以外，v1 未做任何其他改动**：字段集、层级、枚举、`version`(const 1)、`schema`(const `classroom.course.bundle`)、`course_id` / `doc_id` 正则、`local-demo` 三绑定强制 `null` 等**全部不变**。

代码侧同时新增（**不改变校验语义，只统一比较/展示口径**）：

- `SHA256_RE`（放宽后的接受形式）、`SHA256_CANON_RE`（规范形式，仍严格）
- `canonical_sha256(v)`：把裸 hex 或带前缀统一规范为 `sha256:<64hex>`
- `sha256_matches(a, b)`：`source_doc_hash` 与知识库 `content_hash` 的**统一比较口径**
- `file_hash_display(v)`：展示统一规范化；无真实原文件哈希 → 「原文件哈希待确认」

---

## 2. 为什么必须改（不是"顺手放宽"）

**实测事实**（`gateway/tests/knowledge_hash_format_tests.py`，隔离 `KnowledgeStore` 采样，`production_storage_touched = False`）：

| 项 | 真实返回值 | 旧 v1 正则 | 结论 |
|---|---|---|---|
| `doc_id` | `doc_9b2274c42441` | `^doc_[A-Za-z0-9]{4,64}$` | ✅ 匹配 |
| `content_hash` | `7a2229a8…874a`（**裸 64 hex，无前缀**） | `^sha256:[0-9a-f]{64}$` | ❌ **误拒** |

根因：`modules/knowledge/store.py:140 _content_hash()` → `hashlib.sha256(...).hexdigest()`，输出**裸 hex**；`store.py:623` 的 `doc_id` 亦为 `"doc_" + uuid4().hex[:12]`。

⇒ 若不放宽，**真实知识库返回的 `content_hash` 会被 schema 判为非法，正式课程（`user-textbook` / `admin-knowledge`）永远无法通过校验**。这是"契约与真实存储不符"的缺陷，属**勘误**性质。

---

## 3. 向后兼容证明（关键）

**命题**：令 `L(old)` = 旧正则接受的全部字符串集合，`L(new)` = 新正则接受集合。则

```
L(old) ⊆ L(new)
```

**证明**：旧正则要求字符串形如 `sha256:` + 64 个小写 hex。新正则为 `(?:sha256:)?` + 64 个小写 hex，即可选前缀。任何满足旧形式的字符串都满足新形式（取前缀存在分支）。∎

**推论（对消费方的意义）**：

1. **任何在旧 v1 下合法的课程文档，在新 v1 下仍然合法** → 已发布/已落盘的课程**无需迁移**、无需重签、无需重新校验失败重试。
2. **`version` 语义不变**（仍 `const 1`）→ 以 `version == 1` 作分派的消费方（客户端校验器、镜像、迁移工具）**不受影响**，因此**不需要升版本号**。
3. 被扩张的**恰好**是「小写裸 64hex」这一类；**大写裸 hex、长度错、非 hex、双前缀等仍一律拒绝** → fail-closed 语义**未被削弱**。

**注意方向性（诚实声明）**：这是一次**接受集单调扩张**（宽松化）。它确实使「旧口径下非法的裸 hex」变为合法——这正是本次勘误的**目的**（那些裸 hex 是**真实知识库值**）。扩张集经测试证明**不多不少恰为裸 64hex**。

---

## 4. 测试与证据（可复现）

| 测试 | 结果 | 覆盖 |
|---|---|---|
| `gateway/tests/schema_v1_errata_tests.py` | **18/18** | 语料包含性、受限穷举网格（前缀×分隔符×长度×大小写）、确定性随机 20000 例性质测试、扩张类精确性、fail-closed 未削弱（端到端）、结构与版本面未变、权威↔镜像 pattern 集合一致 |
| `gateway/tests/knowledge_hash_format_tests.py` | **23/23** | 真实隔离 KB 采样；`H02c/H02d` 固定"旧严格正则误拒真实值"的冲突证据；`H08a–f` **裸 hex ↔ `sha256:` 前缀四种交叉组合**（一.3） |
| `gateway/tests/course_schema_consistency_tests.py` | **16/16** | 权威↔镜像一致性（JSON 逐字节 sha256 相等；`.py` 仅 docstring 不同、代码体 AST 一致） |

证据 JSON：`docs/engineering/product-v1/classroom-v2/evidence/{schema_v1_errata_tests,knowledge_hash_format_tests,course_schema_consistency_tests}.json`。

---

## 5. 变更记录（非静默）

| 时间 | 动作 | 依据 |
|---|---|---|
| 2026-10-12 | 发现冲突：真实 KB `content_hash` 为裸 hex，旧正则误拒 | CONTRACT_FIX_01A 一.4 实测 |
| 2026-10-12 | 放宽两处 pattern + 新增规范化/比较函数，两侧同步 | 同上 |
| 2026-10-12 | 记录为本勘误文档 + 向后兼容证明测试（18/18） | DELIVERY GATE 02 一.4 |
| 2026-10-12 | 补 `H08a–f` 交叉测试；`AGENT_PLAN §3.6/§3.7.1` 口径同步 | DELIVERY GATE 02 一.3 |

**未采用**的做法（明确否决）：

- ❌ **升版本号到 v2** —— 无结构变更，升版本会迫使所有消费方改分派逻辑，且会误导"结构不兼容"；
- ❌ **静默改正则不记录** —— 属产品负责人明令禁止的"自行静默变更"；
- ❌ **放宽 `SHA256_CANON_RE`（规范形式）** —— 规范形式必须保持严格，否则展示/比较失去基准。

---

## 6. 回滚

本勘误是**纯正则放宽 + 新增纯函数**，回滚影响面极小：把两处 pattern 恢复为 `^sha256:[0-9a-f]{64}$` 并同步镜像即可（`canonical_sha256` / `sha256_matches` / `file_hash_display` 可安全保留，它们对带前缀值行为不变）。
**但回滚会使真实知识库返回值再次被误拒**——因此不建议回滚；如需收紧，应改为在**绑定校验层**额外要求"值确实来自 store 回读"，而非在正则层排除裸 hex。
