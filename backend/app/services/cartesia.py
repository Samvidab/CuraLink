"""Cartesia streaming STT/TTS adapters (server-side only; the key never reaches the browser).

Contract per docs.cartesia.ai STT and TTS WebSocket references:
- STT: wss .../stt/websocket?model&encoding&sample_rate&cartesia_version; binary PCM
  frames in; text "finalize" -> transcript(s) then "flush_done"; text "close" -> "done".
- TTS: wss .../tts/websocket?cartesia_version; JSON generation requests per context_id;
  "chunk" messages carry base64 audio; {"context_id", "cancel": true} stops a context.
"""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import Protocol
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect

from app.config import get_settings

log = logging.getLogger("curalink.cartesia")


class SttStream(Protocol):
    async def send_audio(self, pcm: bytes) -> None: ...
    async def finalize(self) -> str: ...
    def partials(self) -> AsyncIterator[str]: ...
    async def close(self) -> None: ...


class TtsStream(Protocol):
    def speak(self, text: str, context_id: str) -> AsyncIterator[bytes]: ...
    async def cancel(self, context_id: str) -> None: ...
    async def close(self) -> None: ...


def _headers() -> dict[str, str]:
    return {"X-API-Key": get_settings().cartesia_api_key or ""}


class CartesiaStt:
    def __init__(self, ws: ClientConnection):
        self.ws = ws
        self._final: list[str] = []
        self._partials: asyncio.Queue[str] = asyncio.Queue()
        self._flushed = asyncio.Event()
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def open(cls) -> "CartesiaStt":
        s = get_settings()
        q = urlencode({"model": s.cartesia_stt_model, "encoding": "pcm_s16le", "sample_rate": s.voice_input_sample_rate, "cartesia_version": s.cartesia_version, "language": "en"})
        return cls(await connect(f"{s.cartesia_stt_url}?{q}", additional_headers=_headers(), max_size=2**20))

    async def _read(self) -> None:
        async for raw in self.ws:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            t = msg.get("type")
            if t == "transcript":
                if msg.get("is_final"):
                    self._final.append(msg.get("text", ""))
                    await self._partials.put("".join(self._final))
                else:
                    await self._partials.put("".join(self._final) + msg.get("text", ""))
            elif t == "flush_done":
                self._flushed.set()
            elif t == "error":
                log.warning("cartesia stt error %s %s", msg.get("status_code"), msg.get("title"))
                self._flushed.set()

    async def send_audio(self, pcm: bytes) -> None:
        await self.ws.send(pcm)

    async def finalize(self) -> str:
        self._flushed.clear()
        await self.ws.send("finalize")
        try:
            await asyncio.wait_for(self._flushed.wait(), timeout=8)
        except TimeoutError:
            log.warning("cartesia stt finalize timed out")
        text, self._final = "".join(self._final).strip(), []
        return text

    async def partials(self) -> AsyncIterator[str]:
        while True:
            yield await self._partials.get()

    async def close(self) -> None:
        try:
            await self.ws.send("close")
        except Exception:
            pass
        self._reader.cancel()
        await self.ws.close()


class CartesiaTts:
    def __init__(self, ws: ClientConnection):
        self.ws = ws
        self._queues: dict[str, asyncio.Queue] = {}
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def open(cls) -> "CartesiaTts":
        s = get_settings()
        q = urlencode({"cartesia_version": s.cartesia_version})
        return cls(await connect(f"{s.cartesia_tts_url}?{q}", additional_headers=_headers(), max_size=2**22))

    async def _read(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            q = self._queues.get(msg.get("context_id", ""))
            if q is None:
                continue  # late message for a cancelled context: dropped
            t = msg.get("type")
            if t == "chunk" and msg.get("data"):
                await q.put(base64.b64decode(msg["data"]))
            if t in ("done", "error") or msg.get("done"):
                if t == "error":
                    log.warning("cartesia tts error %s %s", msg.get("status_code"), msg.get("title"))
                await q.put(None)

    async def speak(self, text: str, context_id: str) -> AsyncIterator[bytes]:
        s = get_settings()
        q: asyncio.Queue = asyncio.Queue()
        self._queues[context_id] = q
        await self.ws.send(json.dumps({
            "model_id": s.cartesia_tts_model,
            "transcript": text,
            "voice": {"id": s.cartesia_voice_id},
            "language": "en",
            "context_id": context_id,
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": s.voice_output_sample_rate},
            "continue": False,
        }))
        try:
            while (chunk := await q.get()) is not None:
                yield chunk
        finally:
            self._queues.pop(context_id, None)

    async def cancel(self, context_id: str) -> None:
        q = self._queues.pop(context_id, None)
        if q is not None:
            await q.put(None)
        try:
            await self.ws.send(json.dumps({"context_id": context_id, "cancel": True}))
        except Exception:
            pass

    async def close(self) -> None:
        self._reader.cancel()
        await self.ws.close()
