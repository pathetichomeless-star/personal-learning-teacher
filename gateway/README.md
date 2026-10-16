# XiaoZhi Realtime Lab Bridge (`xiaozhi-rtl-bridge`)

Isolated, local-only XiaoZhi-protocol bridge that speaks **real end-to-end Qwen
Realtime speech-to-speech**. By default it runs in **mock mode** against a local
fake upstream (`tests/mock_qwen_server.py`) — no cloud, no API keys. Switching to
the real Qwen service is a pure env/secret change (no code change).

## Purpose
Exercise a XiaoZhi client through the full pipeline: hello handshake, listen
start/stop/detect, barge-in/abort, microphone uplink (Opus 16k) → Qwen realtime,
and Qwen PCM downlink → Opus 24k → client.

## Ports
| Port | Protocol | Purpose |
|------|----------|---------|
| 8110 | WebSocket | `ws://<host>:8110/xiaozhi/v1/` |
| 8111 | HTTP      | `GET /health`, `GET|POST /xiaozhi/ota/` |

`GET /health` is served on **both** ports.

## Run (on the NAS)
```sh
cd /volume1/docker/xiaozhi-realtime-lab
docker compose up -d --build
# start the mock upstream (mock mode only)
docker exec -d xiaozhi-rtl-bridge python /app/tests/mock_qwen_server.py --port 9977 --scenario normal
docker exec xiaozhi-rtl-bridge python /app/tests/selfcheck.py normal
```

## Health
```sh
curl -s http://192.0.2.1:8111/health
curl -s -X POST http://192.0.2.1:8111/xiaozhi/ota/
```

## Configuration
Defaults live in `config/config.json`; each key can be overridden by the
identically named environment variable (set in `docker-compose.yml`):
`PUBLIC_WS_URL`, `WS_PORT`, `HTTP_PORT`, `FRAME_MS`, `DL_QUEUE_MAX`,
`QWEN_MODE`, `QWEN_WS_URL`, `QWEN_WORKSPACE_ID`, `QWEN_MODEL`, `QWEN_VOICE`,
`QWEN_SECRET_FILE`, `QWEN_RECONNECT_MAX`, `QWEN_RECONNECT_BASE_MS`,
`QWEN_STABLE_RESET_S`.

`QWEN_RECONNECT_MAX` is a **per-client-session** budget of total reconnect
attempts; once exhausted the bridge stops retrying for the rest of that client
connection. The budget is replenished only after the upstream has stayed
healthy for `QWEN_STABLE_RESET_S` seconds (default 30).

`QWEN_MODE` is `mock` (default) or `real`. In mock mode the upstream defaults to
`ws://127.0.0.1:9977`.

### Switching to the real Qwen service (no code change)
1. Fill `/volume1/docker/xiaozhi-realtime-lab/secrets/qwen-realtime.env`
   (template at `~/Desktop/小智/secrets/qwen-realtime.env`): API key,
   workspace id, region `cn-beijing`, model, voice.
2. Set `QWEN_MODE=real` in `docker-compose.yml` (leave `QWEN_WS_URL` unset so it
   is derived as `wss://{workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model={model}`).
3. `docker compose up -d xiaozhi-rtl-bridge` (no rebuild needed for env-only changes).
   If region != `cn-beijing` or the key/workspace is missing, the bridge logs an
   error, keeps `qwen_connected=false`, and does **not** crash.

## Self-check
`python /app/tests/selfcheck.py [scenario]` runs the static checks (codec, health,
OTA, hello, mock handshake) plus the scenario-specific check. Run each scenario by
restarting the mock with `--scenario <name>`.

## Rollback
```sh
cd /volume1/docker/xiaozhi-realtime-lab && docker compose down
rm -rf /volume1/docker/xiaozhi-realtime-lab
```