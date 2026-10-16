"""BEHAVIOR-1 gateway link: routing / memory / workbench → Qwen session.

The gateway stays an **execution layer**: `modules/intent` decides, `modules/
memory` + `modules/adapters` provide data, this link renders the instruction
block and hot-applies it to the Qwen session **only at a safe boundary**
(IDLE/LISTENING — no active generation, no active TTS, no active pacer
output; verified mechanically in `PHASE-3-SESSION-UPDATE-SPIKE.md`).

The link is purely additive to the R-1f turn engine: it listens to Qwen text
events, never touches the Opus/pacer data plane, never blocks audio handling
beyond one bounded instruction send, and degrades fail-soft everywhere.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
from pathlib import Path

log = logging.getLogger("rtl.behavior")


def _ensure_modules_importable():
    """Make `modules/` importable in both layouts (repo dev / container /app)."""
    here = Path(__file__).resolve()
    for base in (here.parents[1], here.parents[2]):
        if (base / "modules").is_dir():
            if str(base) not in sys.path:
                sys.path.insert(0, str(base))
            return str(base)
    return None


_MODULES_ROOT = _ensure_modules_importable()

from modules.adapters.workbench import Result as WBResult          # noqa: E402
from modules.adapters.workbench import WorkbenchClient            # noqa: E402
from modules.intent import behavior as intent                      # noqa: E402
from modules.intent.behavior import (BehaviorState, Decision,      # noqa: E402
                                     render_instructions,
                                     render_workbench_block)
from modules.knowledge.store import (KnowledgeStore,               # noqa: E402
                                     render_knowledge_block)
from modules.memory.store import (BoundaryViolation, MemoryStore,   # noqa: E402
                                  render_memory_block)
from modules.policy.persona import DEFAULT_POLICY, PolicyStore      # noqa: E402

WB_FETCH_TIMEOUT = 1.2      # bounded inline workbench fetch
APPLY_SEND_TIMEOUT = 0.8    # bounded instruction hot-apply send
KB_TOP_K = 3                # bounded knowledge retrieval per turn
KB_PROBE_MIN_SCORE = 2      # implicit probes need >1 token hit (noise guard)
MEM_CONTEXT_LIMIT = 4       # bounded memory injection per turn
UNKNOWN_WORD_RE = re.compile(r"(不懂|不认识|不知道|没见过)")


class BehaviorLink:
    """One per client connection (mirrors the QwenClient lifetime)."""

    def __init__(self, conn, qwen, *, config=None):
        self.conn = conn
        self.qwen = qwen
        self.state = BehaviorState()
        self.stats = {
            "decisions": 0, "hot_applies": 0, "hot_apply_skips_identical": 0,
            "hot_apply_failures": 0, "boundary_deferrals": 0, "temp_intents": 0,
            "pref_saves": 0, "pref_forgets": 0, "weak_words": 0,
            "workbench_answers": 0, "workbench_unavailable": 0,
            "workbench_prefetches": 0, "clarify": 0, "readback_mismatches": 0,
            "knowledge_queries": 0, "knowledge_hits": 0, "knowledge_misses": 0,
            "memory_injections": 0, "policy_reloads": 0, "memory_reloads": 0,
            "knowledge_reloads": 0,
        }
        self.memory = None
        mem_path = getattr(config, "MEMORY_FILE", "") if config is not None else ""
        if mem_path:
            self.memory = MemoryStore(mem_path).load()
            try:
                self.state.saved_prefs = dict(self.memory.preferences())
                if self.state.saved_prefs.get("speed"):
                    self.state.speed = self.state.saved_prefs["speed"]
                if self.state.saved_prefs.get("difficulty"):
                    self.state.difficulty = self.state.saved_prefs["difficulty"]
            except Exception as e:  # noqa: BLE001
                log.warning("memory preferences load failed: %r", e)
        wb_url = getattr(config, "WORKBENCH_BASE_URL", "") if config is not None else ""
        self.workbench = WorkbenchClient(wb_url) if wb_url else None
        self.knowledge = None
        kb_path = getattr(config, "KNOWLEDGE_FILE", "") if config is not None else ""
        if kb_path:
            try:
                self.knowledge = KnowledgeStore(kb_path).load()
            except Exception as e:  # noqa: BLE001
                log.warning("knowledge store load failed: %r", e)
                self.knowledge = None
        # PERSONA-POLICY V1: the active policy drives every rendered instruction.
        self.policy_store = None
        pol_path = getattr(config, "POLICY_FILE", "") if config is not None else ""
        if pol_path:
            try:
                self.policy_store = PolicyStore(pol_path).load()
            except Exception as e:  # noqa: BLE001
                log.warning("policy store load failed: %r", e)
                self.policy_store = None
        self._policy = (self.policy_store.active().get("policy")
                        if self.policy_store else DEFAULT_POLICY)
        self._pending = False
        self._pending_decision = None
        self._wb_block = None
        self._kb_block = None
        self._mem_block = None
        self._applying = False
        self._apply_task = None
        self._prefetch_task = None
        self._last_sent = None
        self._last_item_id = None
        self._last_decision_log = None
        # deterministic initial instruction (memory preferences + active policy)
        self.qwen.set_instructions(
            render_instructions(self.state, Decision(),
                                preferences=self.state.saved_prefs,
                                policy=self._policy))

    def _maybe_reload_stores(self):
        """Pick up control-plane edits (admin) at the next turn.

        Policy hot-reloads (applied at the safe boundary like any instruction
        update); memory/knowledge stores refresh when their file changed.  All
        reloads are fail-soft and never touch the audio plane.
        """
        if self.policy_store is not None:
            try:
                if self.policy_store.reload_if_changed():
                    active = self.policy_store.active()
                    self._policy = active.get("policy") or self._policy
                    self.stats["policy_reloads"] += 1
                    log.info("behavior: policy hot-reload v%s", active.get("version"))
            except Exception as e:  # noqa: BLE001
                log.warning("policy reload failed: %r", e)
        if self.memory is not None:
            try:
                if self.memory.reload_if_changed():
                    self.state.saved_prefs = dict(self.memory.preferences())
                    # A store reload refreshes the SAVED preferences, but it must not
                    # silently revert a preference the learner set explicitly this
                    # session: an explicit current request outranks the saved value
                    # (adversarial finding RED-J-R3-03).
                    if (self.state.saved_prefs.get("speed")
                            and "speed" not in self.state.explicit_prefs):
                        self.state.speed = self.state.saved_prefs["speed"]
                    if (self.state.saved_prefs.get("difficulty")
                            and "difficulty" not in self.state.explicit_prefs):
                        self.state.difficulty = self.state.saved_prefs["difficulty"]
                    self.stats["memory_reloads"] += 1
            except Exception as e:  # noqa: BLE001
                log.warning("memory reload failed: %r", e)
        if self.knowledge is not None:
            try:
                if self.knowledge.reload_if_changed():
                    self.stats["knowledge_reloads"] += 1
            except Exception as e:  # noqa: BLE001
                log.warning("knowledge reload failed: %r", e)

    # ---- rendering --------------------------------------------------------

    def refresh_base_instructions(self):
        """Recompute the base instructions (used before a reconnect)."""
        self._maybe_reload_stores()
        self.qwen.set_instructions(render_instructions(
            self.state, Decision(), preferences=self.state.saved_prefs,
            policy=self._policy))

    def _render_for_apply(self):
        self._maybe_reload_stores()
        if self._pending_decision is not None:
            # keep the language computed from the actual turn text (mirroring)
            dec = self._pending_decision
        else:
            dec = Decision()
            dec.effective_language = intent.effective_language(self.state, "")
        return render_instructions(self.state, dec,
                                   workbench_block=self._wb_block,
                                   knowledge_block=self._kb_block,
                                   memory_block=self._mem_block,
                                   preferences=self.state.saved_prefs,
                                   policy=self._policy)

    # ---- Qwen event hook --------------------------------------------------

    async def on_qwen_event(self, obj):
        try:
            etype = obj.get("type")
            if etype == "conversation.item.input_audio_transcription.completed":
                await self._on_input_completed(obj)
            elif etype == "response.done":
                if self.state.temporary_intent is not None:
                    self.state.temporary_intent = None
                    self._pending = True
                    self._pending_decision = None
                    self._wb_block = None
                    self._kb_block = None
                    self._mem_block = None
                    self.schedule_apply()
            elif etype == "session.updated":
                self._check_readback(obj)
        except Exception as e:  # noqa: BLE001  (never disturb the turn engine)
            log.warning("behavior hook error (%s): %r", obj.get("type"), e)

    def _check_readback(self, obj):
        """session.updated echo verification (round-1 lesson: echo ≠ validation)."""
        try:
            echo = (obj.get("session") or {}).get("instructions")
            if echo is None or self._last_sent is None:
                return
            if echo.strip()[:80] != self._last_sent.strip()[:80]:
                self.stats["readback_mismatches"] += 1
                log.warning("behavior: instruction read-back mismatch "
                            "(echo head %r)", str(echo)[:60])
        except Exception:  # noqa: BLE001
            pass

    async def _on_input_completed(self, obj):
        text = (obj.get("transcript") or "").strip()
        item_id = obj.get("item_id")
        if item_id and item_id == self._last_item_id:
            return
        self._last_item_id = item_id
        if not text:
            return

        # Control-plane edits (admin) must be visible to THIS turn's routing,
        # memory side effects and retrieval — reload before doing anything.
        self._maybe_reload_stores()

        decision = intent.route(text, self.state, policy=self._policy)
        self.stats["decisions"] += 1
        self._last_decision_log = (decision.kind, decision.activity,
                                   decision.temporary)
        log.info("behavior decision kind=%s activity=%s temp=%s lang=%s "
                 "speed=%s diff=%s wb=%s clarify=%s",
                 decision.kind, self.state.main_activity, decision.temporary,
                 decision.effective_language, self.state.speed,
                 self.state.difficulty, decision.needs_workbench,
                 decision.clarify)

        # ---- memory side effects (explicit only) -------------------------
        await self._memory_side_effects(decision, text)

        # ---- workbench data (bounded; degrades honestly) ------------------
        self._wb_block = None
        if decision.needs_workbench:
            self._wb_block = await self._workbench_block(decision.needs_workbench)

        # ---- knowledge retrieval (bounded, local, ephemeral) --------------
        self._kb_block = None
        if self.knowledge is not None and decision.knowledge_query:
            self._kb_block = self._knowledge_block(decision)

        # ---- learner memory (relevance-filtered, bounded, ephemeral) ------
        self._mem_block = self._memory_block(text)

        if decision.temporary:
            self.stats["temp_intents"] += 1
        if decision.clarify:
            self.stats["clarify"] += 1

        self._pending = True
        self._pending_decision = decision
        await self._maybe_apply()

    async def _memory_side_effects(self, decision, text):
        if self.memory is None:
            return
        op = (decision.memory or {}).get("op")
        try:
            if op == "save":
                key = decision.memory.get("key")
                value = decision.memory.get("value")
                self.memory.save_preference(key, value)
                self.stats["pref_saves"] += 1
                log.info("memory preference saved key=%s value=%s", key, value)
            elif op == "forget":
                removed = self.memory.forget()
                self.stats["pref_forgets"] += 1
                log.info("memory preference forgotten: %s", removed)
                self.state.saved_prefs = dict(self.memory.preferences())
        except BoundaryViolation as e:
            log.warning("memory boundary violation refused: %s", e)
        except Exception as e:  # noqa: BLE001
            log.warning("memory side effect failed: %r", e)
        # small, explicit weak-vocabulary observation (safe subset)
        if (decision.temporary == intent.EXPLAIN_WORD
                and decision.params.get("word")
                and UNKNOWN_WORD_RE.search(text)):
            try:
                it = self.memory.note_weak_word(decision.params["word"])
                if it is not None:
                    self.stats["weak_words"] += 1
            except Exception as e:  # noqa: BLE001
                log.warning("weak-word observation failed: %r", e)

    async def _workbench_block(self, kind):
        if self.workbench is None:
            self.stats["workbench_unavailable"] += 1
            return render_workbench_block(None, kind=kind)
        try:
            coro = (self.workbench.continue_lesson() if kind == "continue_lesson"
                    else self.workbench.query_progress(
                        "review" if kind == "review" else None))
            res = await asyncio.wait_for(coro, WB_FETCH_TIMEOUT)
        except asyncio.TimeoutError:
            res = WBResult(ok=False, reason="timeout")
        except Exception as e:  # noqa: BLE001
            log.warning("workbench fetch failed: %r", e)
            res = WBResult(ok=False, reason="upstream_error")
        if res.ok:
            self.stats["workbench_answers"] += 1
            return render_workbench_block(res, kind=kind)
        self.stats["workbench_unavailable"] += 1
        log.info("workbench unavailable (%s) — degrade line used", res.reason)
        return render_workbench_block(None, kind=kind)

    def _knowledge_block(self, decision):
        """Bounded local retrieval; returns a block only when it can help.

        Explicit knowledge asks always get a block (honest empty line on a miss);
        implicit probes inject nothing on a miss (the turn continues untouched).
        """
        query = decision.knowledge_query or ""
        min_score = 1 if decision.knowledge_explicit else KB_PROBE_MIN_SCORE
        try:
            results = self.knowledge.search(query, top_k=KB_TOP_K,
                                            min_score=min_score)
        except Exception as e:  # noqa: BLE001
            log.warning("knowledge search failed: %r", e)
            results = []
        self.stats["knowledge_queries"] += 1
        if results:
            self.stats["knowledge_hits"] += 1
            return render_knowledge_block(query, results)
        self.stats["knowledge_misses"] += 1
        if decision.knowledge_explicit:
            return render_knowledge_block(query, [])
        return None

    def _memory_block(self, text):
        """Relevance-filtered memory injection (bounded; None when nothing fits)."""
        if self.memory is None:
            return None
        try:
            items = self.memory.context(text, limit=MEM_CONTEXT_LIMIT)
        except Exception as e:  # noqa: BLE001
            log.warning("memory context failed: %r", e)
            return None
        if not items:
            return None
        self.stats["memory_injections"] += 1
        return render_memory_block(items)

    # ---- safe-boundary apply ---------------------------------------------

    def schedule_apply(self):
        """Sync hint (from boundary hooks); schedules one apply attempt."""
        if not self._pending:
            return
        if self._apply_task is not None and not self._apply_task.done():
            return
        try:
            self._apply_task = asyncio.ensure_future(self._maybe_apply())
        except Exception:  # noqa: BLE001
            self._apply_task = None

    async def _maybe_apply(self):
        if not self._pending or self._applying:
            return
        if not self.conn.is_safe_boundary():
            self.stats["boundary_deferrals"] += 1
            log.info("behavior: apply deferred (not a safe boundary)")
            return
        self._applying = True
        try:
            text = self._render_for_apply()
            if text == self._last_sent or text == self.qwen.instructions:
                self._pending = False
                self._pending_decision = None
                self.stats["hot_apply_skips_identical"] += 1
                return
            ok = False
            try:
                ok = await asyncio.wait_for(
                    self.qwen.send_instructions_update(text), APPLY_SEND_TIMEOUT)
            except asyncio.TimeoutError:
                ok = False
            except Exception as e:  # noqa: BLE001
                log.warning("behavior hot-apply send failed: %r", e)
                ok = False
            if ok:
                self._last_sent = text
                self.stats["hot_applies"] += 1
                self._pending = False
                self._pending_decision = None
                self._wb_block = None
                self._kb_block = None
                self._mem_block = None
                log.info("behavior hot-apply at safe boundary ok")
            else:
                self.stats["hot_apply_failures"] += 1
                log.warning("behavior hot-apply not sent (will retry at the "
                            "next boundary)")
        finally:
            self._applying = False

    # ---- other hooks -------------------------------------------------------

    def on_speech_started(self):
        """Prefetch the workbench state while the user is still speaking."""
        if self.workbench is None:
            return
        if self._prefetch_task is not None and not self._prefetch_task.done():
            return
        try:
            self._prefetch_task = asyncio.ensure_future(self._prefetch())
        except Exception:  # noqa: BLE001
            self._prefetch_task = None

    async def _prefetch(self):
        try:
            ok = await asyncio.wait_for(self.workbench.refresh(), WB_FETCH_TIMEOUT)
            if ok:
                self.stats["workbench_prefetches"] += 1
        except asyncio.TimeoutError:
            pass
        except Exception as e:  # noqa: BLE001
            log.info("workbench prefetch failed: %r", e)

    async def close(self):
        for t in (self._apply_task, self._prefetch_task):
            if t is not None and not t.done():
                t.cancel()
                try:
                    await asyncio.gather(t, return_exceptions=True)
                except BaseException:  # noqa: BLE001
                    pass
        self._apply_task = None
        self._prefetch_task = None
        if self.workbench is not None:
            try:
                await self.workbench.close()
            except Exception:  # noqa: BLE001
                pass

    # ---- evidence ----------------------------------------------------------

    def snapshot(self):
        return {
            "activity": self.state.main_activity,
            "scenario": self.state.scenario,
            "temporary_intent": (self.state.temporary_intent or {}).get("name"),
            "language_override": self.state.language_override,
            "speed": self.state.speed,
            "difficulty": self.state.difficulty,
            "recent_word": self.state.recent_word,
            "pending_apply": self._pending,
            "policy_version": (self.policy_store.active().get("version")
                               if self.policy_store else None),
            "stats": dict(self.stats),
        }