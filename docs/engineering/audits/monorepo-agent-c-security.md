# AGENT C — 密钥 / 隐私审计（只读）

- 仓库：`<project-root>`（根 git 仓库，分支 `main`，本仓库无 remote）
- 范围：`git ls-files` = 896 个文件；工作树可共享范围（tracked ∪ untracked-non-ignored）= 899 个文件
- 方法：只读。从私有源独立构建密钥值集合后，对两个范围做内容扫描。**报告只含计数与路径，不含任何密钥值，命中以 `<len=N>` 掩码表示。**
- 结论：**C_SECURITY = PASS**（tracked/shareable 范围内未发现真实密钥或真实学习者音频/转写）

---

## 0. 独立构建的密钥值集合（5 项，来源只读）

从以下私有源提取 `KEY=VALUE` 字面量（键含 PASSWORD/SECRET/TOKEN/API_KEY/WORKSPACE；跳过空值 / `change_me` / `${…}` 占位）：

`secrets/qwen-realtime.env`、`secrets/qwen-realtime.env.save`、`secrets/nas-db-secrets.env`、`secrets/credentials.env`、`rtl-lab/secrets/qwen-realtime.env`；另补充 `config-backups/*.json` 与 `nas-deploy/docker-compose_all.yml` 中的候选（后者经确认全部为 `${VAR}` 引用，无字面量）。

| 值（掩码） | 键名 |
|---|---|
| `<match len=116>` | QWEN_REALTIME_API_KEY |
| `<match len=19>` | QWEN_REALTIME_WORKSPACE_ID |
| `<match len=32>` | MYSQL_ROOT_PASSWORD |
| `<match len=32>` | REDIS_PASSWORD |
| `<match len=54>` | WEBSOCKET_ACCESS_TOKEN（来自 `config-backups/*.json` 的 `SYSTEM_OPTIONS/NETWORK`） |

`credentials.env` 中 ALIYUN/XFYUN 相关键为空值；`rtl-lab/secrets/qwen-realtime.env` 的 KEY/WORKSPACE 为空 → 均跳过。

---

## 1. 类别计数（两个范围）

| 类别 | (a) TRACKED (896) | (b) SHAREABLE (899) |
|---|---|---|
| QWEN_API_KEY | 0 | 0 |
| MYSQL_PASSWORD | 0 | 0 |
| REDIS_PASSWORD | 0 | 0 |
| ADMIN_PASSWORD / manager (SPRING_*) | 0 | 0 |
| SSH_PRIVATE_KEY (`-----BEGIN .*PRIVATE KEY-----`) | 0 | 0 |
| PRIVATE_CONFIG（含运行时/客户端真实凭据的配置） | 0 | 0 |
| PRIVATE_BACKUP（`config-backups/`、`admin0-backups/`、`rtl-lab-backups/`） | 0 | 0 |
| REAL_LEARNER_AUDIO（批准目录之外的音频） | 0 | 0 |
| REAL_LEARNER_TRANSCRIPT（含真实转写内容） | 0 | 0 |

**范围 (b) 与 (a) 的差异**：仅有 3 个未跟踪但可共享的文件，均为其他审计代理产出，逐个扫描为 clean：

- `docs/engineering/audits/monorepo-agent-a-git-history.md`
- `docs/engineering/audits/monorepo-agent-b-source-integrity.md`
- `docs/engineering/audits/monorepo-agent-d-license.md`

`git ls-files --others --exclude-standard` 的结果集除此之外为空。（本报告自身也是未跟踪可共享文件。）

### 1.1 关键字命中的澄清（非真实隐私）

- 关键字 `"transcripts":` / `input_audio_transcription` 命中 4 个 tracked 文件，均为**代码标识符或事件类型名**，无任何真实转写内容，判为 clean：
  - `gateway/app/diag.py`（`snapshot()["transcripts"]` 字典键）
  - `gateway/app/turns.py`（`conversation.item.input_audio_transcription.delta/.completed` 事件名）
  - `gateway/tests/r1c_probe.py`（`diag_transcripts` 取值）
  - `docs/engineering/deploy-log.md`（部署日志中提及上述事件名与已打码的 workspace id，无学习者语句）
- 音频扩展名命中 407 个 tracked 文件，全部为 `client/assets/sounds/<locale>/*.wav`（37 个语言 × 11 个 UI 提示音，静态应用音效资源），**非**学习者录音，判为 clean。
- `client/src/ui/gui/qml/controls/XTextField.qml` 命中 `Password` 为 QML 组件 `echoMode` 字段，非凭据。

---

## 2. 逐项验证

### 1) `git ls-files` 中私有目录路径计数 = **0**
已按前缀与路径段两种方式核对，以下均为 0：
`secrets/`、`logs/`、`config-backups/`、`admin0-backups/`、`rtl-lab-backups/`、`rtl-lab/evidence/`、`py-xiaozhi/`、`nas-deploy/`、`.workbuddy/`。
另：tracked 中无 `*.env`（非 example）、无 `*.pem/*.key/*.p12`、无 `id_rsa*/id_ed25519*`、无 `.netrc`；唯一的 `*.example` 为 `deploy/legacy-xiaozhi/.env.example`。

### 2) 合成测试音频仅存在于 `gateway/tests/assets/`（批准可共享）
- `gateway/tests/assets/u1.pcm16k.raw`（75 668 B）
- `gateway/tests/assets/u2.pcm16k.raw`（403 036 B）
- `gateway/tests/assets/u3.pcm16k.raw`（120 250 B）
其他位置无 `.raw/.opus/.bin/.pcm` 抓包文件。
- 备注（非阻塞）：`gateway/docs/r1f-implementation-report.md:43` 仍以文本引用迁移前旧路径 `rtl-lab/tests/assets/u{1,2,3}.pcm16k.raw`（仅为文档字符串，无实际文件）。

### 3) 无真实真人测试录制/转写被跟踪
- `rtl-lab/evidence/r1f_ht_*` 出现在 `git ls-files` 的次数 = **0**；实际存在于私密区 `rtl-lab/evidence/`（11 个文件），并同时被 `.gitignore` 的 `rtl-lab/evidence/**`、`**/r1f_ht_*`、`*.raw` 等覆盖。✓
- `gateway/docs/r1f-human-test-closeout.md`（tracked）经逐段核查仅含工程元数据（机器门限结果、观测标签），**不含**任何学习者语句/音频内容；`.env` 结项中引用的证据文件均只以文件名出现。判为 clean。

### 4) `deploy/legacy-xiaozhi/**` 无遗留字面量凭据
该子树共 4 个文件，均属 tracked：
- `deploy/legacy-xiaozhi/.env.example`
- `deploy/legacy-xiaozhi/compose_all.template.yml`
- `deploy/legacy-xiaozhi/docker-compose.yml`
- `deploy/legacy-xiaozhi/docker-compose_all.yml`

扫描结果：**字面量凭据 = 0**；仅含 `${VAR}` 引用与 `.env.example` 的 `change_me_*` 占位（`change_me_mysql_root_password` / `change_me_druid_db_password` / `change_me_redis_password`，计 3 个，预期且允许）。✓

### 5) `.git/info/exclude` 临时排除（迁移期间）
`.git/info/exclude` 当前内容：`py-xiaozhi/`、`rtl-lab/`、`nas-deploy/`。

- 归因：上述三目录内的文件在 `git check-ignore -v` 中**均**被判定由 `.git/info/exclude` 命中。
- **若退役时删除这三条，将有 44 条路径变为可被跟踪**（工作树实测：以「仅应用根 `.gitignore`」口径复算得到）：

  - `nas-deploy/`（4）：`.env.example`、`compose_all.template.yml`、`docker-compose.yml`、`docker-compose_all.yml`
  - `py-xiaozhi/`（1）：以**嵌套 git 仓库**形式出现（`py-xiaozhi/.git` 存在），退役后为 embedded repo 条目，其内部文件不会逐个入 index
  - `rtl-lab/`（39）：
    - `Dockerfile`、`README.md`、`docker-compose.yml`、`config/config.json`
    - `app/`：`__init__.py`、`audio.py`、`counters.py`、`diag.py`、`http.py`、`main.py`、`protocol.py`、`qwen.py`、`turns.py`、`ws.py`
    - `tests/`：`leak_repro.py`、`mock_qwen_server.py`、`r1c_audio_analysis.py`、`r1c_content_compare.py`、`r1c_probe.py`、`r1f_client_tests.py`、`r1f_real_probe.py`、`r1f_runtime.py`、`r1f_tests.py`、`selfcheck.py`
    - 文档：`r1f-agent-b-playout-audit.md`、`r1f-agent-f-review.md`、`r1f-agent-f-review-rev3..rev9.md`、`r1f-design-review.md`、`r1f-human-test-closeout.md`、`r1f-implementation-report.md`、`r1f-rev7/8/9-po-decision.md`

- **该 44 条路径的明文扫描结果：0 密钥值、0 SSH 私钥、0 真实学习者证据。** 仅两处字面量命中为良性：`nas-deploy/.env.example` 的 `change_me_*` 占位；`rtl-lab/app/qwen.py` 的 `Authorization: Bearer` 头部构造（代码）。
- **重要澄清**：真正敏感的私密物**并非**仅依赖该临时排除——
  - `rtl-lab/evidence/**`（学习者音频/转写证据）由 `.gitignore` 的 `rtl-lab/evidence/**` 等独立覆盖；
  - `rtl-lab/secrets/` 由 `**/secrets/`、`*.env` 独立覆盖；
  - `nas-deploy/data/`、`nas-deploy/monitor/` 由 `.gitignore` 同名规则独立覆盖。
  - 即：退役 `info/exclude` 后，变为可跟踪的只有**不含真实密钥**的 legacy 源码/文档/示例；**学习者证据与密钥文件不会因此泄漏**。
- 另注：`rtl-lab/**` 与 `py-xiaozhi/**` 中大部分文档/源码与 tracked 的 `gateway/**`、`docs/**` 互为副本（例如 `rtl-lab/r1f-human-test-closeout.md` 与 `gateway/docs/r1f-human-test-closeout.md` 内容完全一致）。建议在退役 `info/exclude` 前，用 `.gitignore` 显式覆盖这 44 条或直接删除/迁出，以免 shareable 面扩大。

### 6) 已知误报清除（均按要求保留、不计为密钥）
- `NOTICE.md` 中 `third-party-content`：存在（许可证/归属用语），**非密钥**。✓
- `deploy/legacy-xiaozhi/.env.example` 中 `change_me_*`：3 个占位，**非密钥**。✓

---

## 3. 其他观察（非阻塞，仅供迁移参考）

- `docs/reference/config.yaml`（tracked，legacy 客户端模板）：其 `api_key/access_token/token/secret_*` 等取值绝大多数为中文说明/`xxx`/`your_*` 占位；唯一的 32-hex 字面量（`get_weather.api_key`）在文件内自带注释「这个密钥是项目共用的 key……每天有 1000 次免费调用」，属**上游公开共享/演示 key**，非本仓库私有密钥；平台自身对该值在仓库内仅此一处出现。判为 clean。
- `nas-deploy/docker-compose_all.yml` 的 `SPRING_DATASOURCE_DRUID_PASSWORD`、`SPRING_DATA_REDIS_PASSWORD`、`MYSQL_ROOT_PASSWORD` 等均为 `${VAR}` 引用，无字面量。

---

## 4. 结论

- tracked 与 shareable 两个范围内，全部密钥类别计数为 0；SSH 私钥 0；真实学习者音频/转写 0。
- 私有目录入 ls-files 计数 0；合成音频限定于 `gateway/tests/assets/`；真人测试产物仅存于被忽略的私密区；legacy 部署树无字面量凭据；两个已知误报已清除。
- 唯一需在迁移收尾时处理的是 **`.git/info/exclude` 退役导致的 44 条 legacy 路径可跟踪化**——其中不含任何真实密钥或学习者隐私，但建议以 `.gitignore` 固化覆盖。

**C_SECURITY = PASS**