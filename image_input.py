"""Convert AstrBot image components into DSH Web RPC prompt parts."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Sequence
from pathlib import Path

import httpx

DEFAULT_MAX_IMAGES = 20
DEFAULT_MAX_IMAGE_BYTES = 3_670_016
DEFAULT_MAX_TOTAL_IMAGE_BYTES = 20 * 1024 * 1024
DEFAULT_CONVERSION_TIMEOUT_SECONDS = 30.0


class ImageInputError(ValueError):
    """A triggering QQ image could not become a supported DSH image part."""


def _media_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ImageInputError("image format must be PNG, JPEG, WebP, or GIF")


def _image_components(
    messages: Sequence[object],
    image_type: type,
    reply_type: type,
) -> list[object]:
    images: list[object] = []
    seen: set[int] = set()

    def append(component: object) -> None:
        identity = id(component)
        if identity not in seen:
            seen.add(identity)
            images.append(component)

    for component in messages:
        if isinstance(component, image_type):
            append(component)
        if not isinstance(component, reply_type):
            continue
        chain = getattr(component, "chain", None)
        if not isinstance(chain, list):
            continue
        for quoted in chain:
            if isinstance(quoted, image_type):
                append(quoted)
    return images


def _estimated_decoded_bytes(encoded: str) -> int:
    padding = len(encoded) - len(encoded.rstrip("="))
    return max(0, (len(encoded) * 3) // 4 - padding)


def _decode_bounded_base64(encoded: str, limit: int) -> bytes:
    normalized = "".join(encoded.split())
    if _estimated_decoded_bytes(normalized) > limit:
        raise ImageInputError(f"image exceeds the {limit} byte limit")
    try:
        data = base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ImageInputError("image component returned invalid Base64 data") from error
    if len(data) > limit:
        raise ImageInputError(f"image exceeds the {limit} byte limit")
    return data


def _read_local_bounded(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as source:
            data = source.read(limit + 1)
    except OSError as error:
        raise ImageInputError("image file could not be read") from error
    if len(data) > limit:
        raise ImageInputError(f"image exceeds the {limit} byte limit")
    return data


async def _read_remote_bounded(client: httpx.AsyncClient, url: str, limit: int) -> bytes:
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > limit:
                        raise ImageInputError(f"image exceeds the {limit} byte limit")
                except ValueError:
                    pass
            data = bytearray()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > limit:
                    raise ImageInputError(f"image exceeds the {limit} byte limit")
                data.extend(chunk)
            return bytes(data)
    except ImageInputError:
        raise
    except httpx.HTTPError as error:
        raise ImageInputError("image URL could not be downloaded") from error


def _image_source(image: object) -> str:
    source = getattr(image, "url", None) or getattr(image, "file", None)
    if not isinstance(source, str) or not source:
        raise ImageInputError("image component has no readable source")
    return source


async def _read_image_bounded(
    image: object,
    client: httpx.AsyncClient | None,
    limit: int,
) -> bytes:
    source = _image_source(image)
    if source.startswith("base64://"):
        return _decode_bounded_base64(source.removeprefix("base64://"), limit)
    if source.startswith("data:image/") and ";base64," in source:
        return _decode_bounded_base64(source.split(";base64,", 1)[1], limit)
    if source.startswith(("http://", "https://")):
        if client is None:
            raise ImageInputError("image URL client is unavailable")
        return await _read_remote_bounded(client, source, limit)
    path = Path(source[8:] if source.startswith("file:///") else source)
    return await asyncio.to_thread(_read_local_bounded, path, limit)


async def _extract_image_parts(
    images: Sequence[object],
    *,
    max_image_bytes: int,
    max_total_image_bytes: int,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None,
) -> list[dict[str, str]]:
    parts: list[dict[str, str]] = []
    total_bytes = 0
    needs_remote = any(_image_source(image).startswith(("http://", "https://")) for image in images)
    client = (
        httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            transport=transport,
        )
        if needs_remote
        else None
    )
    try:
        for image in images:
            remaining = max_total_image_bytes - total_bytes
            if remaining <= 0:
                raise ImageInputError(
                    f"combined images exceed the {max_total_image_bytes} byte limit"
                )
            limit = min(max_image_bytes, remaining)
            try:
                data = await _read_image_bounded(image, client, limit)
            except ImageInputError as error:
                if limit < max_image_bytes and "byte limit" in str(error):
                    raise ImageInputError(
                        f"combined images exceed the {max_total_image_bytes} byte limit"
                    ) from error
                if "byte limit" in str(error):
                    raise ImageInputError(
                        f"one image exceeds the {max_image_bytes} byte limit"
                    ) from error
                raise
            total_bytes += len(data)
            parts.append(
                {
                    "type": "image",
                    "mediaType": _media_type(data),
                    "data": base64.b64encode(data).decode("ascii"),
                }
            )
    finally:
        if client is not None:
            await client.aclose()
    return parts


async def extract_image_parts(
    messages: Sequence[object],
    image_type: type,
    reply_type: type,
    *,
    max_images: int = DEFAULT_MAX_IMAGES,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    max_total_image_bytes: int = DEFAULT_MAX_TOTAL_IMAGE_BYTES,
    timeout_seconds: float = DEFAULT_CONVERSION_TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, str]]:
    """Return ordered DSH image parts from the triggering and quoted messages."""

    if max_images <= 0 or max_image_bytes <= 0 or max_total_image_bytes <= 0:
        raise ValueError("image limits must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    images = _image_components(messages, image_type, reply_type)
    if len(images) > max_images:
        raise ImageInputError(f"one message may contain at most {max_images} images")
    if not images:
        return []
    try:
        return await asyncio.wait_for(
            _extract_image_parts(
                images,
                max_image_bytes=max_image_bytes,
                max_total_image_bytes=max_total_image_bytes,
                timeout_seconds=timeout_seconds,
                transport=transport,
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError as error:
        raise ImageInputError("image conversion timed out") from error


def has_image_input(
    messages: Sequence[object],
    image_type: type,
    reply_type: type,
) -> bool:
    """Return whether the triggering message or its quote contains an image."""

    return bool(_image_components(messages, image_type, reply_type))
