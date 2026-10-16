"""WebSocket endpoint: handshake, dispatch, and per-connection lifecycle."""

import logging

from aiohttp import WSMsgType, web

from .admin.registry import sessions as admin_sessions   # ADMIN-1 passive observer
from .turns import Connection

log = logging.getLogger("rtl.ws")


async def ws_handler(request, config):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    conn = Connection(ws, config)
    # ADMIN-1: lifecycle-only registration (no locks, no hot-path work, weak ref held)
    admin_sessions.register(conn)
    await conn.on_connect()
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await conn.handle_text(msg.data)
            elif msg.type == WSMsgType.BINARY:
                conn.handle_binary(msg.data)
            elif msg.type == WSMsgType.ERROR:
                log.warning("WS error: %s", ws.exception())
                break
    except Exception as e:
        log.warning("WS handler error: %s", e)
    finally:
        admin_sessions.discard(conn)
        await conn.close()
    return ws