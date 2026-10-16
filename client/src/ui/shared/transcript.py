"""CLIENT-UI-1 transcript store: learner-facing conversation bubbles.

Pure Python (no Qt, no audio imports) so every frontend (GUI / TUI / CLI) can share it and
so it is deterministically testable.  In-memory only: **no transcript persistence by
default** — the current conversation display is not long-term Memory.

Contract (mechanically observed gateway message, `build_transcript`):

    {"type": "transcript", "role": "user"|"assistant", "delta": <partial text or null>,
     "text": <completed text or null>, "final": bool, "interrupted": bool, "turn": int|null}

Bubble states: STREAMING → FINAL, or STREAMING → INTERRUPTED.  Interrupted assistant turns
never fabricate the unplayed text: the bubble keeps whatever text was actually received and
is marked INTERRUPTED.
"""

MAX_MESSAGES = 200

STREAMING = "STREAMING"
FINAL = "FINAL"
INTERRUPTED = "INTERRUPTED"

ROLES = ("user", "assistant")


class TranscriptStore:
    """Bounded, defensive store for the current session transcript."""

    def __init__(self, max_messages=MAX_MESSAGES):
        self._items = []
        self._max = int(max_messages)

    # ---- public API --------------------------------------------------------

    def apply(self, message):
        """Apply one gateway transcript message.

        Returns the new snapshot when something changed, or ``None`` when the message was
        ignored (duplicate / stale / malformed) so the UI is never asked to redraw.
        """
        if not isinstance(message, dict) or message.get("type") != "transcript":
            return None
        role = message.get("role")
        if role not in ROLES:
            return None
        turn = message.get("turn")
        delta = message.get("delta")
        text = message.get("text")
        final = bool(message.get("final"))
        interrupted = bool(message.get("interrupted"))

        # ASR-UI NEW-1 fix: USER transcripts carry a stable per-utterance turn
        # id (upstream item identity stamped by the gateway).  Address the
        # item's own bubble directly — concurrent items never interfere, and a
        # late `completed` closes its OWN bubble instead of being dropped as
        # stale.  The numeric stale rule is kept for the assistant role (R-F
        # generation isolation) and for legacy id-less user chains.
        if role == "user" and turn is not None and not interrupted:
            return self._apply_user_item(turn, delta, text, final)

        newest = self._newest_turn(role)
        if turn is not None and newest is not None and turn < newest:
            return None                                    # stale event for an older turn

        if interrupted:
            return self._apply_interrupted(role, turn, text)

        current = self._current(role, turn)
        if delta and current is not None and current["state"] == FINAL:
            return None                        # late audio for a completed turn is stale
        if delta:
            if current is None:
                current = self._push(role, "", STREAMING, turn)
            current["text"] += str(delta)
            if final:
                current["state"] = FINAL
            return self.snapshot()

        if text is not None:
            if current is None:
                current = self._push(role, "", STREAMING, turn)
            new_text = str(text)
            if current["state"] == FINAL:
                # A COMPLETED turn is immutable: no later event may rewrite its text.
                # (adversarial finding R-F-1 — a late `response.audio_transcript.done`
                # for a superseded response was re-attributed to the newest turn and
                # overwrote the text the learner had already seen.)
                return None
            current["text"] = new_text
            if final:
                current["state"] = FINAL
            return self.snapshot()

        if final:
            if current is None:
                current = self._push(role, "", STREAMING, turn)
            if current["state"] == FINAL:
                return None                                # duplicate final
            current["state"] = FINAL
            return self.snapshot()
        return None

    def _apply_user_item(self, turn, delta, text, final):
        """ASR-UI NEW-1 fix: per-item state for user transcripts.

        Each upstream input item (stable `turn` identity from the gateway)
        owns exactly one bubble.  Concurrent items never share state; a
        finalized utterance is immutable; a late `completed` closes its OWN
        bubble.  Insertion order = first-event order (chronological).
        """
        current = None
        for item in reversed(self._items):
            if item["role"] == "user" and item["turn"] == turn:
                current = item
                break
        if current is not None and current["state"] == FINAL:
            return None                    # finalized utterance is immutable
        if current is None:
            current = self._push("user", "", STREAMING, turn)
        if delta:
            current["text"] += str(delta)
        if text is not None:
            current["text"] = str(text)
        if final:
            current["state"] = FINAL
        return self.snapshot()

    def mark_interrupted(self, role="assistant"):
        """Local fallback: mark the streaming turn as interrupted (e.g. a client-side abort)."""
        current = None
        for item in reversed(self._items):
            if item["role"] == role:
                current = item
                break
        if current is None or current["state"] != STREAMING:
            return None
        current["state"] = INTERRUPTED
        return self.snapshot()

    def reset(self):
        """Drop the current session transcript (reconnect / new session)."""
        if not self._items:
            return None
        self._items.clear()
        return self.snapshot()

    def snapshot(self):
        return [dict(item) for item in self._items]

    def text_lines(self, limit=12):
        """Compact rendering helper for the TUI/CLI frontends."""
        out = []
        for item in self._items[-limit:]:
            label = "你" if item["role"] == "user" else "老师"
            suffix = {"STREAMING": "…", "FINAL": "", "INTERRUPTED": "（已打断）"}[item["state"]]
            out.append("%s: %s%s" % (label, item["text"], suffix))
        return out

    # ---- internals ---------------------------------------------------------

    def _push(self, role, text, state, turn):
        item = {"role": role, "text": text, "state": state, "turn": turn}
        self._items.append(item)
        while len(self._items) > self._max:
            self._items.pop(0)
        return item

    def _newest_turn(self, role):
        for item in reversed(self._items):
            if item["role"] == role and item["turn"] is not None:
                return item["turn"]
        return None

    def _current(self, role, turn):
        """The open (STREAMING) bubble for this role, honouring the turn key."""
        for item in reversed(self._items):
            if item["role"] != role:
                continue
            if item["state"] == STREAMING:
                if turn is None or item["turn"] is None or item["turn"] == turn:
                    return item
                return None
            if turn is not None and item["turn"] == turn:
                return item                                # allow a final to close it
            return None
        return None

    def _apply_interrupted(self, role, turn, text):
        """Mark the open turn interrupted (never inventing text)."""
        current = self._current(role, turn)
        if current is not None and current["state"] == STREAMING:
            if text:
                current["text"] = str(text)
            current["state"] = INTERRUPTED
            return self.snapshot()
        # nothing streaming: record an honest interrupted bubble with whatever text we have
        existing = None
        for item in reversed(self._items):
            if item["role"] == role and (turn is None or item["turn"] == turn):
                existing = item
                break
        if existing is not None:
            if existing["state"] == FINAL:
                return None                    # a completed turn is never re-marked
            if existing["state"] != INTERRUPTED:
                existing["state"] = INTERRUPTED
                return self.snapshot()
            return None
        self._push(role, str(text or ""), INTERRUPTED, turn)
        return self.snapshot()