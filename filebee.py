"""FileBee integration boundary.

Important: no public FileBee.live upload API contract was verifiable at build time.
The adapter is therefore OFF by default. If FileBee supplies an official endpoint,
configure it in the environment; uploads are sent as streaming multipart/form-data.
"""
import aiohttp
import time
from typing import Any, AsyncIterator, Awaitable, Callable
from urllib.parse import urlparse

from config import (
    FILEBEE_UPLOAD_URL, FILEBEE_API_TOKEN, FILEBEE_AUTH_HEADER,
    FILEBEE_AUTH_PREFIX, FILEBEE_FILE_FIELD, FILEBEE_RESPONSE_URL_FIELD,
    FILEBEE_UPLOAD_TIMEOUT,
)


class FileBeeError(RuntimeError):
    pass


def is_filebee_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (host == "filebee.live" or host.endswith(".filebee.live"))
    except Exception:
        return False


def _read_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _find_share_url(payload: Any) -> str | None:
    keys = {"url", "shareurl", "share_url", "downloadurl", "download_url", "link", "fileurl", "file_url"}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in keys and isinstance(value, str) and is_filebee_url(value):
                return value
        for value in payload.values():
            found = _find_share_url(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_share_url(value)
            if found:
                return found
    return None


class FileBeeClient:
    def __init__(self) -> None:
        self.session: aiohttp.ClientSession | None = None

    @property
    def configured(self) -> bool:
        return bool(FILEBEE_UPLOAD_URL)

    async def start(self) -> None:
        if not self.configured:
            return
        timeout = aiohttp.ClientTimeout(total=FILEBEE_UPLOAD_TIMEOUT, sock_connect=30, sock_read=300)
        self.session = aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=5))

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def upload_stream(
        self,
        chunks: AsyncIterator[bytes],
        filename: str,
        mime_type: str,
        file_size: int,
        on_progress: Callable[[int], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise FileBeeError(
                "Automatic FileBee upload is not enabled. FileBee.live's public upload API "
                "could not be verified. Upload at https://filebee.live/ and send the resulting "
                "share URL to this bot, or configure an official FILEBEE_UPLOAD_URL supplied by FileBee."
            )
        if not self.session:
            raise FileBeeError("FileBee upload adapter is not initialized")

        transferred = 0
        last_report = 0.0

        async def tracked() -> AsyncIterator[bytes]:
            nonlocal transferred, last_report
            async for chunk in chunks:
                if not chunk:
                    continue
                transferred += len(chunk)
                now = time.monotonic()
                if on_progress and (now - last_report >= 5):
                    last_report = now
                    await on_progress(transferred)
                yield chunk
            if on_progress:
                await on_progress(transferred)

        multipart = aiohttp.MultipartWriter("form-data")
        payload = aiohttp.payload.AsyncIterablePayload(
            tracked(), content_type=mime_type or "application/octet-stream"
        )
        payload.set_content_disposition("form-data", name=FILEBEE_FILE_FIELD, filename=filename)
        multipart.append_payload(payload)
        headers = {"User-Agent": "FileBeeTelegramBot/1.0"}
        if FILEBEE_API_TOKEN:
            headers[FILEBEE_AUTH_HEADER] = f"{FILEBEE_AUTH_PREFIX}{FILEBEE_API_TOKEN}"

        try:
            async with self.session.post(FILEBEE_UPLOAD_URL, data=multipart, headers=headers) as response:
                raw = await response.text()
                if response.status < 200 or response.status >= 300:
                    raise FileBeeError(f"Configured FileBee endpoint returned HTTP {response.status}: {raw[:400]}")
                try:
                    data = await response.json(content_type=None)
                except Exception as exc:
                    raise FileBeeError("Configured FileBee endpoint returned a non-JSON response; check its API contract") from exc
                candidate = _read_path(data, FILEBEE_RESPONSE_URL_FIELD) if FILEBEE_RESPONSE_URL_FIELD else None
                url = candidate if isinstance(candidate, str) and is_filebee_url(candidate) else _find_share_url(data)
                if not url:
                    raise FileBeeError(
                        "Upload endpoint responded but no FileBee share URL was found. Configure "
                        "FILEBEE_RESPONSE_URL_FIELD to match the official API response."
                    )
                return {"url": url, "size": transferred or file_size}
        except aiohttp.ClientError as exc:
            raise FileBeeError(f"FileBee upload request failed: {exc}") from exc
