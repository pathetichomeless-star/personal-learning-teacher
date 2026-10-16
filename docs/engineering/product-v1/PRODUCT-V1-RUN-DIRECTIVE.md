PRODUCT V1 FINAL COMPLETION RUN
MULTI-AGENT + PDCA CLOSED-LOOP EXECUTION
ONE FINAL HUMAN ACCEPTANCE ONLY

==================================================
MISSION
==================================================

Complete ALL remaining Product V1 work from the CURRENT canonical repository
state in ONE continuous run.

Use:

- MULTI-AGENT execution
- ONE Lead Agent as the ONLY product-code writer
- independent read-only reviewer agents
- PDCA closed-loop management for EVERY phase
- automatic repair/review loops until acceptance criteria pass
- NO intermediate product-owner human testing

Final target:

Knowledge V1
+ Memory V1
+ Persona / Teaching Policy V1
+ ADMIN-2
+ Unified Admin UI
+ existing Behavior / Workbench / Client Transcript
+ full cross-module integration
+ independent multi-agent review
+ isolated NAS Product-V1 test sidecar
+ Mac client armed
+ ONE final unified human acceptance script
→ STOP

Do not stop after individual phases merely to ask the product owner to test.

==================================================
CURRENT EXPECTED BASELINE
==================================================

Expected latest state includes:

- vocabulary accuracy audit COMPLETE
- vocab routing/policy fixes COMPLETE
- GUI transcript fix COMPLETE
- real-Qwen budget lock recorded

Expected latest HEAD is approximately:

3f1da03

But DO NOT blindly trust the hash.

First mechanically verify:

git status
git log
branch
remote
worktree
latest relevant commits
current NAS sidecars
Mac OTA target

If HEAD differs, perform a READ-ONLY reconciliation.

Proceed only if the repository clearly contains:

- vocab commit 049401a or equivalent descendant
- budget-lock docs commit 3f1da03 or equivalent descendant
- GUI transcript fix
- Behavior-1
- Memory-1 minimal
- Workbench-1
- ADMIN-1

Do not discard valid newer work.

==================================================
GLOBAL EXECUTION GOVERNANCE
==================================================

ONE LEAD AGENT = ONLY PRODUCT CODE WRITER.

All other agents are reviewers/auditors.

Reviewer agents may:

- inspect
- search
- run tests
- inspect deployments
- produce reports
- identify BLOCKER / MAJOR / MINOR findings

Reviewer agents MUST NOT modify shared product source.

Only the Lead may:

- edit product source
- edit deployment files
- apply reviewer fixes
- commit implementation changes

This prevents concurrent writers from corrupting the repository.

==================================================
PDCA OPERATING MODEL — MANDATORY
==================================================

EVERY phase must run a complete PDCA cycle.

--------------------------------
P — PLAN
--------------------------------

Before modifying code:

1. read-only audit current implementation
2. identify authoritative ownership boundaries
3. identify exact files/interfaces to touch
4. define explicit acceptance criteria
5. define rollback
6. define test matrix
7. identify frozen surfaces
8. identify expected risks

Persist the plan.

--------------------------------
D — DO
--------------------------------

Implement only the authorized phase scope.

Rules:

- smallest coherent change
- preserve ownership boundaries
- reversible changes
- no speculative refactors
- no duplicated sources of truth
- no unnecessary changes to frozen realtime/audio code

--------------------------------
C — CHECK
--------------------------------

After implementation:

1. deterministic tests
2. integration tests
3. static/boundary/security checks
4. relevant reviewer-agent audit
5. regression against previously accepted capabilities

Classify findings:

BLOCKER
MAJOR
MINOR
INFO

--------------------------------
A — ACT
--------------------------------

If BLOCKER or MAJOR:

Lead fixes automatically.

Then repeat:

PLAN delta
→ DO fix
→ CHECK
→ ACT

until:

BLOCKERS = 0
MAJORS = 0

MINOR findings may remain only if:

- documented
- non-blocking
- no security/privacy/data-integrity/realtime risk

Do NOT ask the product owner for decisions unless a true authorization
boundary is reached.

==================================================
GLOBAL PDCA TRACKING
==================================================

Maintain:

docs/engineering/product-v1/PDCA-BOARD.md

For every phase record:

PHASE =
PLAN =
DO =
CHECK =
ACT =
BLOCKERS =
MAJORS =
MINORS =
TESTS =
REVIEWER =
STATUS =

Status values:

PLANNED
IN_PROGRESS
CHECKING
REWORK
PASS
DEFERRED_BY_AUTHORIZATION

No phase is COMPLETE until its PDCA state is PASS.

==================================================
MULTI-AGENT ROLES
==================================================

LEAD
- only writer
- owns implementation
- owns fixes
- owns deployment
- owns final integration

AGENT A — Architecture / ownership
Checks:
- module boundaries
- source-of-truth correctness
- realtime separation
- no duplicate state ownership

AGENT B — Knowledge
Checks:
- ingestion
- retrieval
- chunking
- deletion
- provenance
- context bounds
- privacy
- no legacy RAG ownership

AGENT C — Memory
Checks:
- memory classes
- save/edit/delete/forget
- provenance
- per-user isolation
- no Workbench progress duplication
- no transcript/audio persistence

AGENT D — Persona / Teaching / Admin UX
Checks:
- role/persona model
- language policy
- teaching policy
- precedence
- preview/apply/rollback
- Chinese-first Admin UX

AGENT E — Security / Privacy / Rollback
Checks:
- auth
- secret handling
- audit logs
- fail-closed
- destructive confirmations
- filesystem permissions
- rollback paths
- no internet exposure

AGENT F — Integration / Realtime / Regression
Checks:
- R-1f invariants
- Behavior
- transcript
- barge-in
- reconnect
- concurrency
- final product readiness

Every reviewer writes:

docs/engineering/product-v1/reviews/agent-<A-F>.md

Lead fixes BLOCKER / MAJOR findings.

Reviewer must re-check after fixes.

Final required:

AGENT_A = PASS
AGENT_B = PASS
AGENT_C = PASS
AGENT_D = PASS
AGENT_E = PASS
AGENT_F = PASS

==================================================
LOCKED REALTIME / AUDIO SURFACES
==================================================

DO NOT change:

- native Qwen Audio↔Audio architecture
- provider
- production model
- production voice
- VAD threshold
- VAD silence timing
- 20 ms media frame
- 15 ms send-start guard
- 5 ms pacing slack
- Opus behavior
- FIFO behavior
- generation ownership
- barge-in behavior
- pacing gates
- existing R-1f accounting semantics

Do NOT introduce:

- ASR → LLM → TTS cascade
- second conversational LLM
- model replacement
- voice replacement

Text-plane/control-plane additions are allowed only when they preserve
all frozen realtime behavior.

==================================================
REAL QWEN BUDGET — HARD LOCK
==================================================

REAL_QWEN_TOTAL_USED = 4/4
REMAINING = 0

NO additional automated real-Qwen session may be opened.

This includes:

- smoke
- spike
- vocabulary verification
- final integration
- admin test
- knowledge test
- persona test

Forbidden.

Remaining work must use:

- deterministic tests
- mock Qwen
- protocol tests
- structural tests
- integration tests
- static verification
- read-only inspection

Existing real-session drivers are historical tooling only.

DO NOT RUN THEM.

The next real conversational session belongs exclusively to the product
owner during final unified human acceptance.

==================================================
PHASE 0 — BASELINE / ROLLBACK / PDCA INIT
==================================================

PLAN:

Capture:

START_COMMIT =
branch =
remote =
worktree =
tracked files =
current containers =
primary realtime StartedAt / Restarts =
Workbench StartedAt / Restarts =
legacy XiaoZhi StartedAt / Restarts =
MVP sidecar status =
Mac OTA target =

Verify accepted capabilities:

R-1f
ADMIN-1
CLIENT transcript GUI
Behavior-1
Vocabulary accuracy
Memory-1 minimal
Workbench-1 read-only

Create:

- rollback git tag
- git bundle
- baseline manifest
- PDCA-BOARD.md

CHECK:

- no secrets tracked
- no learner raw transcript tracked
- no real learner data committed
- repository clean

ACT:

fix hygiene issues before continuing.

PHASE 0 must PASS.

==================================================
PHASE 1 — KNOWLEDGE V1
==================================================

Build product-owned Knowledge V1.

AUTHORITATIVE STORE:

OURS.

Do NOT use legacy `ai_rag_*` as the source of truth.

Stable IDs:

ds_
doc_
chk_

Data model:

Dataset
Document
Chunk
Source metadata
Tags
CreatedAt
UpdatedAt
Status
Content hash
Provenance
Optional source URI

Required operations:

- create dataset
- rename dataset
- enable / disable dataset
- list datasets
- delete dataset with preview + confirmation
- add document
- inspect document
- delete document
- rebuild chunks
- list chunks
- search/retrieve
- diagnostics
- source attribution

Supported ingestion path for V1:

- plain text
- Markdown
- PDF-derived text through supported extraction path

Do not build OCR unless genuinely necessary.

Retrieval requirements:

- deterministic top-k interface
- bounded context
- maximum injection size
- disabled datasets excluded
- provenance retained
- empty-result honesty
- malformed-document handling
- duplicate-content handling

Conversation integration:

user turn
→ Behavior decides whether Knowledge may help
→ bounded Knowledge retrieval
→ ephemeral contextual instruction
→ native Qwen Audio↔Audio response

Knowledge MUST NOT:

- become Memory
- contain Workbench progress
- store raw conversation transcripts automatically
- replace Qwen

Tests:

KNOWLEDGE1_TESTS

cover:

ingestion
chunking
search
top-k
empty
duplicate
malformed
disable
delete
provenance
context bound
privacy
concurrency

Produce:

docs/engineering/product-v1/KNOWLEDGE-V1.md

PDCA until PASS.

==================================================
PHASE 2 — MEMORY V1
==================================================

Upgrade Memory-1 minimal.

Workbench remains authoritative for:

lesson
progress
PASS
REVIEW
REPEAT
mastery
review date
next review
course completion
current lesson

Memory MUST NEVER duplicate those.

Allowed Memory entity classes:

preference
profile_fact
vocab_item
habit
continuity

Each item:

id
user_id
entity_type
key
value
source
confidence
created_at
updated_at
optional expires_at

Required operations:

save
list
search
inspect
edit
delete
forget
forget-by-category
category summary

Requirements:

- per-user partition
- atomic persistence
- fail-soft corrupted storage
- caps
- provenance
- confidence
- bounded conversational injection
- relevance filtering
- explicit user save
- explicit user forget

Never store:

raw audio
whole transcripts
secrets
Workbench progress

Hard boundary rejection:

progress
lesson
mastery
pass
review
repeat
next_review
course
课程进度
掌握度
复习日期

Tests:

MEMORY_V1_TESTS

including boundary abuse tests.

Produce:

docs/engineering/product-v1/MEMORY-V1.md

PDCA until PASS.

==================================================
PHASE 3 — PERSONA / ROLE / TEACHING POLICY V1
==================================================

Create one authoritative product-owned structured policy system.

NOT another LLM.

PERSONA:

assistant name
role description
tone
personality
teaching philosophy
default response length

LANGUAGE:

Chinese default
English-practice policy
explanation language
code-switch policy
explicit request priority

TEACHING:

correction frequency
correction style
vocabulary format
canonical spelling rule
pronunciation / IPA
grammar explanation
difficulty
speaking speed
encouragement style

ACTIVITY POLICY:

CHAT
PRACTICE_CONVERSATION
SPEAKING_PRACTICE
VOCAB_LEARN
VOCAB_REVIEW
READING
LISTENING
CONTINUE_LESSON

TEMP INTENT POLICY:

EXPLAIN_WORD
EXPLAIN_GRAMMAR
TRANSLATE
QUERY_PROGRESS
SAVE_PREFERENCE

Precedence:

hard rule
>
explicit current user request
>
saved learner preference
>
current activity
>
auto/default

Requirements:

- internal labels never spoken
- one authoritative renderer
- no duplicated prompts across modules
- bounded rendered instruction
- validation
- version
- preview
- apply
- read-back
- rollback
- audit

Use proven instructions-only `session.update` path.

Hot apply ONLY at safe boundary.

Never hot-apply:

model
voice
VAD
audio formats

Tests:

PERSONA_POLICY_TESTS

Produce:

docs/engineering/product-v1/PERSONA-POLICY-V1.md

PDCA until PASS.

==================================================
PHASE 4 — ADMIN-2 CONTROL PLANE
==================================================

Build ADMIN-2 on accepted ADMIN-1.

ADMIN-1 endpoints remain backward-compatible.

Every write:

AUTH
→ VALIDATE
→ PREVIEW
→ EXPLICIT APPLY
→ READ-BACK
→ AUDIT
→ ROLLBACK where meaningful

No silent mutation.

Required ADMIN-2 APIs:

PERSONA / POLICY
- active
- versions
- preview
- apply
- rollback

MEMORY
- list
- search
- inspect
- edit
- delete
- category clear with confirmation
- boundary diagnostics

KNOWLEDGE
- datasets CRUD
- documents CRUD
- enable/disable
- rebuild/index
- retrieval test
- diagnostics

WORKBENCH
- READ-ONLY status
- current lesson
- progress
- reviews
- freshness

NO Workbench write route.

BEHAVIOR
- active policy
- routing diagnostics
- bounded recent routing metadata
- no raw transcript persistence

REALTIME
retain:

health
version
sessions
metrics
telemetry
diag-summary

Security:

- same bearer model
- fail closed
- token file preferred
- constant-time compare
- no secrets in body/log
- audit logs sanitized

Do not add `/admin/diag/reset`.

Tests:

ADMIN2_TESTS
ADMIN_SECURITY_TESTS

Produce:

docs/engineering/product-v1/ADMIN-2.md

PDCA until PASS.

==================================================
PHASE 5 — UNIFIED ADMIN UI
==================================================

Build ONE coherent Chinese-first operator interface.

Navigation:

仪表盘
实时状态
诊断
角色与教学
记忆
知识库
课程进度

Optional:
意图 / 路由诊断

--------------------------------
Dashboard
--------------------------------

gateway health
model/provider/voice read-only
persona version
Memory counts
Knowledge counts
Workbench state
degradation warnings

--------------------------------
角色与教学
--------------------------------

structured fields
validation
preview
rendered-instruction preview
apply
read-back
version history
rollback

--------------------------------
记忆
--------------------------------

categories
items
search
edit
delete
forget category
provenance
confidence

Clearly display:

“课程进度由 Workbench 管理，不存储在记忆中。”

--------------------------------
知识库
--------------------------------

datasets
documents
ingestion
enabled/disabled
search tester
retrieval results
sources
delete preview
rebuild status

--------------------------------
Workbench
--------------------------------

READ-ONLY

current lesson
progress
review due
fresh/stale status

Clearly show:

只读

--------------------------------
Diagnostics
--------------------------------

gateway
Memory boundary
Knowledge health
Workbench health
policy version
routing health

Requirements:

- no raw JSON required for common actions
- destructive action confirmation
- desktop responsive
- LAN-only
- no public dependencies

Tests:

UI contracts
API integration
security
destructive confirmation
preview/apply/rollback

PDCA until PASS.

==================================================
PHASE 6 — CROSS-MODULE PRODUCT INTEGRATION
==================================================

Integrate:

native Qwen Audio↔Audio
+
Behavior
+
Vocabulary policy
+
Persona/Policy
+
Memory
+
Knowledge
+
Workbench
+
Client transcript GUI
+
Admin

Ownership:

Workbench
= course progress authority

Memory
= learner preferences/profile/continuity

Knowledge
= reference/document information

Persona
= teaching policy

Behavior
= current activity/temp intent/context routing

Gateway
= realtime/session orchestration

Admin
= control plane only

No ownership duplication.

Required machine scenarios:

1.
“我们随便聊聊”
→ Chinese chat

2.
“我们练一下酒店英语”
→ English hotel practice

3.
“accommodation 是什么意思？”
→ correct canonical spelling
→ pronunciation separate
→ meaning/example
→ automatic resume

4.
“以后解释单词先用中文，记住”
→ Memory save

5.
new session
→ preference applied

6.
“忘掉这个偏好”
→ Memory removed

7.
“继续上次的课”
→ Workbench real current lesson

8.
“我学到哪里了？”
→ Workbench authoritative progress

9.
question answerable by Knowledge
→ bounded retrieval injected

10.
Knowledge miss
→ no fabricated database result

11.
Admin persona change
→ preview
→ apply
→ read-back
→ safe-boundary policy reflects new config in mock integration

12.
reconnect
→ transcript clears
→ persisted Memory remains
→ Workbench remains authoritative

13.
two concurrent sessions
→ isolated session state

==================================================
PHASE 7 — MASTER TEST MATRIX
==================================================

Run:

R1F_REGRESSION
CLIENT_UI_TESTS
GUI_TRANSCRIPT_LIVE_TESTS
CLIENT_UI_INTEGRATION
BEHAVIOR1_TESTS
VOCAB_ACCURACY_TESTS
MEMORY_V1_TESTS
KNOWLEDGE1_TESTS
WORKBENCH1_TESTS
PERSONA_POLICY_TESTS
ADMIN1_TESTS
ADMIN2_TESTS
ADMIN_SECURITY_TESTS
PRODUCT_V1_INTEGRATION
CONCURRENCY_TESTS
RECONNECT_TESTS
BARGE_IN_TESTS
PRIVACY_BOUNDARY_TESTS

Re-assert:

20 ms
15 ms
5 ms
provider
model
voice
VAD
Opus
FIFO
barge-in
generation ownership

No drift.

Required:

WORKBENCH_WRITES = 0
MEMORY_PROGRESS_DUPLICATION = 0
KNOWLEDGE_PROGRESS_DUPLICATION = 0
SECRET_LEAKS = 0
UNAUTH_WRITES = 0

PDCA until all blocking tests PASS.

==================================================
PHASE 8 — MULTI-AGENT FINAL REVIEW
==================================================

Run Agents A–F independently.

Each reviewer:

- reads actual implementation
- reads tests
- examines ownership boundaries
- examines deploy plan
- writes raw report
- classifies BLOCKER / MAJOR / MINOR

Lead fixes all BLOCKER and MAJOR.

Then reviewer reruns.

Continue PDCA loop until:

AGENT_A = PASS
AGENT_B = PASS
AGENT_C = PASS
AGENT_D = PASS
AGENT_E = PASS
AGENT_F = PASS

Do not fake consensus.

Persist all reports.

==================================================
PHASE 9 — PRODUCT V1 NAS TEST SIDECAR
==================================================

Deploy an isolated Product V1 TEST SIDECAR.

Do NOT replace:

primary xiaozhi-rtl-bridge
Workbench
legacy XiaoZhi

Primary must remain untouched.

Persist only Product V1 stores:

Memory
Knowledge
Persona/policy versions
Audit log

Use correct uid/filesystem permissions.

Runtime secrets only.

LAN only.

Machine verification:

health
OTA
WS hello
admin auth matrix
persona preview/apply/read-back/rollback
Memory CRUD
Knowledge CRUD
Knowledge search
Workbench GET-only
routing integration with mock Qwen
no token leak
no unauthorized routes

NO real Qwen session.

==================================================
PHASE 10 — MAC CLIENT ARM
==================================================

Keep accepted GUI transcript fix.

Backup Mac config.

Point OTA to Product V1 TEST SIDECAR.

Record:

backup path
before SHA256
after SHA256
changed fields
OTA result
WS result
rollback command

Do not change unrelated config.

==================================================
PHASE 11 — ONE FINAL HUMAN ACCEPTANCE
==================================================

Prepare but DO NOT RUN.

Write:

docs/engineering/product-v1/FINAL-HUMAN-ACCEPTANCE.md

Use Chinese.

Maximum about 20–25 scenarios.

Cover:

1 Chinese natural chat
2 English free conversation
3 hotel scenario
4 canonical vocabulary spelling
5 pronunciation / IPA
6 explanation → automatic resume
7 repeat
8 continue
9 speed
10 difficulty
11 activity switch
12 Memory save
13 new-session Memory
14 Memory forget
15 Knowledge hit
16 Knowledge miss
17 Workbench continue lesson
18 Workbench progress
19 Admin persona change
20 GUI streaming/final
21 interruption
22 no old-audio resume
23 reconnect
24 subjective static/buzz
25 basic Admin operation

This is the ONLY human validation requested.

Do not ask for intermediate tests.

==================================================
PHASE 12 — FINAL PDCA CLOSEOUT
==================================================

Global PLAN:
compare final system against Product V1 mission.

Global DO:
complete all required implementation/deployment.

Global CHECK:

- all phase PDCA = PASS
- all test suites acceptable
- all reviewers PASS
- primary untouched
- Workbench write count 0
- real-Qwen budget respected
- rollback available
- test sidecar healthy
- Mac client armed
- human script prepared

Global ACT:

fix any final BLOCKER / MAJOR automatically.

Repeat global CHECK/ACT until:

BLOCKERS = 0
MAJORS = 0

Then:

commit
clean worktree
final report
STOP

==================================================
FINAL REPORT
==================================================

Return a concise final block containing:

PRODUCT_V1_COMPLETION_RUN =

START_COMMIT =
END_COMMIT =
WORKTREE =

PDCA_PHASE_0 =
PDCA_KNOWLEDGE =
PDCA_MEMORY =
PDCA_PERSONA =
PDCA_ADMIN2 =
PDCA_ADMIN_UI =
PDCA_INTEGRATION =
PDCA_DEPLOYMENT =
PDCA_FINAL =

KNOWLEDGE1 =
MEMORY_V1 =
PERSONA_POLICY_V1 =
ADMIN2 =
UNIFIED_ADMIN_UI =
WORKBENCH_READ_ONLY =
VOCAB_ACCURACY =
CLIENT_TRANSCRIPT_GUI =

R1F_REGRESSION =
BEHAVIOR1_TESTS =
VOCAB_ACCURACY_TESTS =
MEMORY_V1_TESTS =
KNOWLEDGE1_TESTS =
WORKBENCH1_TESTS =
PERSONA_POLICY_TESTS =
ADMIN1_TESTS =
ADMIN2_TESTS =
ADMIN_SECURITY_TESTS =
PRODUCT_V1_INTEGRATION =
CONCURRENCY_TESTS =
PRIVACY_BOUNDARY_TESTS =

AGENT_A =
AGENT_B =
AGENT_C =
AGENT_D =
AGENT_E =
AGENT_F =

REAL_QWEN_USED = 4/4
REAL_QWEN_REMAINING = 0
REAL_QWEN_BUDGET_VIOLATION = NO

PRIMARY_REALTIME_TOUCHED = NO
WORKBENCH_WRITES = 0
AUDIO_ARCHITECTURE_CHANGED = NO
PUBLIC_EXPOSURE = NO
CREDENTIAL_ROTATION = NO

PRODUCT_V1_TEST_SIDECAR =
MAC_CLIENT_ARMED =
FINAL_HUMAN_ACCEPTANCE_SCRIPT =

BLOCKERS =
MAJORS =
MINORS =

PRODUCT_V1_READY_FOR_SINGLE_HUMAN_ACCEPTANCE =
SAFE_TO_PROMOTE_TO_PRIMARY = NO
HUMAN_ACCEPTANCE_REQUIRED = YES

STOP.

==================================================
ABSOLUTE STOP BOUNDARIES
==================================================

Do NOT continue into:

avatar / digital human
camera / vision
ESP32-P4 implementation
i5 hardware frontend implementation
production promotion
primary realtime replacement
soak test
credential rotation
license choice
public-internet exposure

The only permitted endpoint of this run is:

PRODUCT_V1_READY_FOR_SINGLE_HUMAN_ACCEPTANCE = YES

then STOP.