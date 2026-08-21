import asyncio
import base64

import httpx
import pytest

from image_input import ImageInputError, extract_image_parts


class FakeImage:
    def __init__(self, data: bytes | None = None, *, source: str | None = None) -> None:
        if source is None:
            if data is None:
                source = "invalid://missing"
            else:
                source = f"base64://{base64.b64encode(data).decode('ascii')}"
        self.file = source
        self.url = ""


class FakeReply:
    def __init__(self, chain: list[object] | None) -> None:
        self.chain = chain


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff\xe0", "image/jpeg"),
        (b"GIF89a", "image/gif"),
        (b"RIFF\x04\x00\x00\x00WEBP", "image/webp"),
    ],
)
async def test_extract_image_parts_detects_supported_media(
    data: bytes,
    media_type: str,
) -> None:
    image = FakeImage(data)

    assert await extract_image_parts([image], FakeImage, FakeReply) == [
        {
            "type": "image",
            "mediaType": media_type,
            "data": base64.b64encode(data).decode("ascii"),
        }
    ]


@pytest.mark.asyncio
async def test_extract_image_parts_reads_quoted_images_and_deduplicates_objects() -> None:
    image = FakeImage(b"GIF87a")

    parts = await extract_image_parts(
        [image, FakeReply([image, object()])],
        FakeImage,
        FakeReply,
    )

    assert len(parts) == 1
    assert parts[0]["mediaType"] == "image/gif"


@pytest.mark.asyncio
async def test_extract_image_parts_ignores_missing_reply_chain() -> None:
    assert await extract_image_parts([FakeReply(None)], FakeImage, FakeReply) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "image",
    [FakeImage(b"not-an-image"), FakeImage()],
)
async def test_extract_image_parts_rejects_unreadable_or_unsupported_images(
    image: FakeImage,
) -> None:
    with pytest.raises(ImageInputError):
        await extract_image_parts([image], FakeImage, FakeReply)


@pytest.mark.asyncio
async def test_extract_image_parts_enforces_count_before_conversion() -> None:
    first = FakeImage(b"GIF87a")
    second = FakeImage(b"GIF89a")

    with pytest.raises(ImageInputError, match="at most 1"):
        await extract_image_parts(
            [first, second],
            FakeImage,
            FakeReply,
            max_images=1,
        )


@pytest.mark.asyncio
async def test_extract_image_parts_accepts_exact_byte_limits_and_rejects_overflow() -> None:
    data = b"\x89PNG\r\n\x1a\n"
    images = [FakeImage(data), FakeImage(data)]

    parts = await extract_image_parts(
        images,
        FakeImage,
        FakeReply,
        max_image_bytes=len(data),
        max_total_image_bytes=len(data) * 2,
    )
    assert len(parts) == 2

    with pytest.raises(ImageInputError, match="one image exceeds"):
        await extract_image_parts(
            [FakeImage(data)],
            FakeImage,
            FakeReply,
            max_image_bytes=len(data) - 1,
        )
    with pytest.raises(ImageInputError, match="combined images exceed"):
        await extract_image_parts(
            images,
            FakeImage,
            FakeReply,
            max_total_image_bytes=len(data) * 2 - 1,
        )


@pytest.mark.asyncio
async def test_extract_image_parts_enforces_batch_timeout() -> None:
    async def delayed(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=b"GIF89a")

    with pytest.raises(ImageInputError, match="timed out"):
        await extract_image_parts(
            [FakeImage(source="https://images.test/slow.gif")],
            FakeImage,
            FakeReply,
            timeout_seconds=0.001,
            transport=httpx.MockTransport(delayed),
        )


@pytest.mark.asyncio
async def test_remote_image_stream_stops_at_byte_limit() -> None:
    async def oversized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"GIF89a-overflow")

    with pytest.raises(ImageInputError, match="one image exceeds"):
        await extract_image_parts(
            [FakeImage(source="https://images.test/large.gif")],
            FakeImage,
            FakeReply,
            max_image_bytes=6,
            transport=httpx.MockTransport(oversized),
        )


@pytest.mark.asyncio
async def test_local_image_reads_only_up_to_limit(tmp_path) -> None:
    image = tmp_path / "pixel.gif"
    image.write_bytes(b"GIF89a-overflow")

    with pytest.raises(ImageInputError, match="one image exceeds"):
        await extract_image_parts(
            [FakeImage(source=str(image))],
            FakeImage,
            FakeReply,
            max_image_bytes=6,
        )
