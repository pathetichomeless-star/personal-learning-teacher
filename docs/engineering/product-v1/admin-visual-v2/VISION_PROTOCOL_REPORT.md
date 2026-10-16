VISION_PROTOCOL_REPORT
date=<2026-10-09 UTC>
SOURCES=<all official Aliyun/Alibaba Cloud Model Studio docs, URLs listed per section>
REALTIME_VISION_SUPPORT=<YES — doc-verified. The DashScope Qwen-Omni-Realtime WebSocket API (the exact protocol the gateway already speaks) accepts image input via the client event `input_image_buffer.append` on the SAME realtime session, with base64 JPEG, no session.update opt-in required for basic image input. See EVENT_SEQUENCE below.>
OFFICIAL_ALTERNATIVE=<not needed for realtime vision; noted anyway: the repo's client (py-xiaozhi) already ships a side-call pattern — MCP camera tool → OpenAI-compatible HTTP to GLM-4V-plus (client/src/mcp/tools/camera/vl_camera.py:32-41), result injected as text into the conversation. Valid fallback if realtime image input misbehaves, but NOT required by docs.>
EVENT_SEQUENCE=<doc-verified, quoted from https://help.aliyun.com/zh/model-studio/client-events (and mirror https://docs.qwencloud.com/api-reference/real-time-multimodal/client-events):

1) Client sends image (exact shape from docs):
```json
{
    "event_id": "event_xxx",
    "type": "input_image_buffer.append",
    "image": "xxx"    // base64-encoded JPG/JPEG, required
}
```

2) Commit (VAD mode): server auto-commits; in Manual mode client sends:
```json
{
    "event_id": "event_B4o9RHSTWobB5OQdEHLTo",
    "type": "input_audio_buffer.commit"
}
```
Docs (verbatim): "若客户端已发送过 input_image_buffer.append 事件，input_audio_buffer.commit 事件将同时提交图像缓冲区。" / "The image buffer is submitted with the audio buffer through the input_audio_buffer.commit event."

3) Server responds with the existing events the gateway already handles:
```json
{"type": "input_audio_buffer.committed"}          // existing in gateway flow
{"type": "conversation.item.created", ...}         // user item created from committed buffers
{"type": "response.created"} → {"type": "response.audio.delta", ...} → {"type": "response.done"}
```
(no new response-side event names are introduced by image input per the official lifecycle table, https://www.alibabacloud.com/help/tc/model-studio/realtime)

4) Optional cost optimization via session.update — ONLY for Qwen3.8-Omni-Flash-Realtime (gateway default model, gateway/app/qwen.py:38), set BEFORE first audio (docs verbatim: "应在发送首段音频前设置，音频输入开始后不可修改"):
```json
{
  "type": "session.update",
  "session": {
    "video": {
      "input": {
        "representation_compact": "normal"   // default "none"; "normal" = 1/4 tokens
      }
    }
  }
}
```

5) Ordering constraint (docs verbatim): "发送 input_image_buffer.append 事件前，至少已发送过一次 input_audio_buffer.append 事件。" — at least one input_audio_buffer.append must have been sent before the first input_image_buffer.append.>
SIZE_FPS_LIMITS=<official numbers (https://help.aliyun.com/zh/model-studio/client-events, verbatim):
- 图像格式必须为 JPG 或 JPEG
- 建议分辨率 480p 或 720p 以获得最佳性能，最高不超过 1080p
- 单张图片经 Base64 编码后不得超过 256KB，建议编码前原始图片大小不超过 190KB
- 建议以 1 张/秒的频率向服务端发送图像
- 图片数据需经过 Base64 编码
(no other fps/size limits documented)>
SESSION_ASSOCIATION=<images are sent on the SAME WebSocket realtime session as audio — no separate session/request id. Gateway already holds exactly one QwenClient per XiaoZhi connection (gateway/app/qwen.py:284 "One Qwen realtime session per XiaoZhi client connection"); `_qwen_session_id` is captured from session.created (gateway/app/qwen.py:475-487). Vision input therefore binds to the audio session implicitly by sharing the connection; no doc-verified cross-session image reference exists.>
INTERRUPTION_CLEANUP=<doc-verified behavior:
- Barge-in during model response: server emits input_audio_buffer.speech_started; official example code (https://help.aliyun.com/zh/model-studio/realtime) shows the client calling response.cancel on speech_started while a response is in flight — gateway already does exactly this via send_cancel() with a 3s benign-error grace window (gateway/app/qwen.py:681-685, qwen.py:593-602).
- Buffer cleanup: input_audio_buffer.clear → server replies input_audio_buffer.cleared. UNCERTAIN: docs do not name a separate input_image_buffer.clear event or explicitly state that clear wipes the image buffer; do not assume it does.
- No image-specific server events (e.g. input_image_buffer.committed) are documented; the image buffer's commit is signaled only through the audio commit path. Anything beyond that is UNCERTAIN.>
COST_QUOTA=<official pricing (https://www.alibabacloud.com/help/en/model-studio/billing-for-model-studio, China(Beijing) USD per 1M tokens, qwen3.8-omni-flash-realtime): input text/images/video $0.212, input audio $0.848, output text $0.636, output audio $1.696. Singapore: $0.23/$0.93/$0.70/$1.87. Images are billed in the same "Input: text/images/video" token bucket as text (cheaper than audio tokens). Free quota: 1M tokens, Singapore only, valid 90 days. session.video.input.representation_compact="normal" reduces video/image token count to 1/4 of "none" (official Token 计算 doc reference in client-events page). CN console lists CNY prices (输入音频 6元/M, 输出文本 4.5元/M) — verify full CNY table at billing time.>
IMPLEMENTATION_RECOMMENDATION=<V0 path, strictly behind MOCK boundary:
1. Doc-verified and safe to implement now against the mock upstream (deploy/product-sidecar/probe_product_v1.py must be extended to accept and ack input_image_buffer.append — the current mock surface has no image events):
   a. gateway/app/qwen.py: add send_image(jpeg_bytes) mirroring send_append (qwen.py:675-679): base64-encode JPEG and send {"type":"input_image_buffer.append","image":<b64>}. Guard: connected state, JPEG only, <256KB post-encode (enforce <190KB raw per doc recommendation), rate-limit 1/s (doc recommendation).
   b. Enforce the doc-verified ordering rule: refuse input_image_buffer.append until at least one input_audio_buffer.append was sent in the session.
   c. Barge-in path unchanged: existing response.cancel flow already matches official interruption semantics.
2. UNCERTAIN / must be verified in a REAL session before production (do NOT hard-depend on these):
   - Exact server ack events for the image buffer (no input_image_buffer.committed documented).
   - Whether input_audio_buffer.clear also clears the image buffer.
   - Whether representation_compact is accepted mid-session for an already-running audio session (docs: must be set before first audio → in practice means set inside _session_update_msg() at connect time, qwen.py:658-673, only when a vision flag is on).
   - Whether input_image_buffer.append during an active response is accepted or must wait for response.done (undocumented; safest V0 policy: only send images while no response is in flight).
   - Real cost of image tokens at 1 fps on qwen3.8-omni-flash-realtime.
3. Mock boundary contract: image events pass through the existing TEXT-frame dispatch untouched (gateway forwards unknown upstream events — qwen.py:604-623 logs unidentified frames and still dispatches), so no reader-loop change is needed; only the mock needs image-event handling.
4. Fallback (proven in-repo): if realtime image path fails verification, reuse the py-xiaozhi MCP camera side-call pattern (vl_camera.py) injecting the VL answer as text into the session via conversation.item.create / existing text plane.>
CONFIDENCE=<HIGH for the core claim: input_image_buffer.append event name, exact JSON shape, JPEG/base64/size/fps limits, audio-first ordering, commit-coupling with input_audio_buffer.commit, and representation_compact session field are all quoted verbatim from official Aliyun Model Studio docs (help.aliyun.com / alibabacloud.com) and corroborated by an official mirror (docs.qwencloud.com). MEDIUM for interruption/buffer-clear specifics (docs silent on image-buffer clear semantics — explicitly marked UNCERTAIN above). No guessed event names appear in the doc-verified set; everything unverified stays behind the MOCK boundary.>

---

## Local audit appendix (read-only, branch admin-visual-v2 @ e51d9a5)

- Upstream client: gateway/app/qwen.py — endpoint `wss://{workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=...` (qwen.py:36-38, 266-269), matches the official 接入指南 for qwen3.8-omni-flash-realtime / qwen3.5-omni-*-realtime (https://help.aliyun.com/document_detail/2950095.html). Handshake: wait session.created → send session.update (model/voice/instructions/pcm16 in+out/server_vad threshold 0.5 silence 800ms, qwen.py:658-673). Audio: input_audio_buffer.append base64 (qwen.py:675-679). Cancel: response.cancel (qwen.py:681-685). Close: session.finish (qwen.py:687-689). Mid-session instructions-only session.update already exists (BEHAVIOR-1, qwen.py:644-656) — a precedent for an optional vision session.update, but vision enabling needs no opt-in per docs (only optional token-saving video.input).
- Event loop: gateway/app/ws.py:13-34 (one Connection per device WS) → gateway/app/turns.py dispatcher; all upstream TEXT frames dispatched via on_event, unknown types logged and forwarded (qwen.py:604-623) — image path needs no dispatch changes.
- Client vision today: client/src/mcp/tools/camera/vl_camera.py — MCP tool, OpenAI-compatible HTTP side call to GLM-4V-plus (Zhipu), base64 JPEG, result returned as MCP tool output text. No realtime image events in client protocol.
- Test surface: deploy/product-sidecar/probe_product_v1.py — mock upstream handles session.created/session.update→session.updated/session.finish/conversation.item.input_audio_transcription.completed/response.created/response.audio.delta/response.audio.done/response.done (probe_product_v1.py:130-176); device side hello/listen/abort (236-348). No image events — must be added for V0 tests.

## Source URLs
1. https://help.aliyun.com/zh/model-studio/client-events (客户端事件: input_image_buffer.append, session.video, limits)
2. https://help.aliyun.com/document_detail/2950095.html (Qwen-Omni-Realtime WebSocket 接入指南: endpoints, VAD/Manual flows, MCP)
3. https://www.alibabacloud.com/help/tc/model-studio/realtime + https://help.aliyun.com/zh/model-studio/realtime (realtime overview: event lifecycle table incl. input_image_buffer.append; interruption example code)
4. https://docs.qwencloud.com/api-reference/real-time-multimodal/client-events (official mirror, corroborates event shapes/limits)
5. https://www.alibabacloud.com/help/en/model-studio/billing-for-model-studio + https://bailian.console.aliyun.com/?tab=doc#/doc (pricing qwen3.8-omni-flash-realtime)
