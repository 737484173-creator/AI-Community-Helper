from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.bot.event_publisher import DiscordEventPublisher, InMemoryEventPublisher
from app.database.migrations.init_db import init_database
from app.database.repositories.event_repository import EventRepository
from app.event_assets import (
    EventImageValidationError,
    delete_event_image,
    resolve_event_image_path,
    save_event_image,
    validate_event_image,
)
from app.scheduler.event_jobs import EventPublishService
from app.utils.time_utils import parse_datetime


def _png_bytes(width: int = 16, height: int = 10) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), color=(37, 99, 235)).save(output, format="PNG")
    return output.getvalue()


def test_event_image_is_validated_saved_and_resolved(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    image_info = validate_event_image(_png_bytes())

    assert image_info.extension == ".png"
    assert (image_info.width, image_info.height) == (16, 10)

    stored_path = save_event_image(db_path, _png_bytes())
    resolved_path = resolve_event_image_path(db_path, stored_path)

    assert stored_path.startswith("event_assets/")
    assert resolved_path is not None
    assert resolved_path.read_bytes() == _png_bytes()

    delete_event_image(db_path, stored_path)
    assert not resolved_path.exists()


def test_event_image_validation_rejects_invalid_payload() -> None:
    with pytest.raises(EventImageValidationError, match="有效"):
        validate_event_image(b"not an image")


def test_event_image_path_cannot_escape_asset_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside"):
        resolve_event_image_path(tmp_path / "community.db", "../secret.png")


def test_event_repository_and_scheduler_preserve_image_attachment(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    stored_path = save_event_image(db_path, _png_bytes())
    EventRepository(db_path).create(
        title="Image announcement",
        content="Please review the image below.",
        event_type="Announcement",
        channel_id="channel-1",
        publish_time="2026-09-08 18:00:00",
        status="Scheduled",
        event_image_path=stored_path,
    )

    event = EventRepository(db_path).list_scheduled()[0]
    assert event["event_image_path"] == stored_path

    publisher = InMemoryEventPublisher()
    EventPublishService(publisher, db_path).publish_due_events(
        now=parse_datetime("2026-09-08 18:00:01")
    )

    expected_path = resolve_event_image_path(db_path, stored_path)
    assert publisher.published_messages[0]["image_path"] == str(expected_path)


def test_discord_publisher_sends_image_with_message(tmp_path: Path) -> None:
    image_path = tmp_path / "announcement.png"
    image_path.write_bytes(_png_bytes())

    class _Message:
        id = 42

    class _Channel:
        def __init__(self) -> None:
            self.sent_args = ()
            self.sent_kwargs = {}

        async def send(self, *args, **kwargs):
            self.sent_args = args
            self.sent_kwargs = kwargs
            return _Message()

    channel = _Channel()

    class _Client:
        def get_channel(self, _channel_id: int):
            return channel

    publisher = DiscordEventPublisher(_Client())
    message_id = asyncio.run(
        publisher._publish(
            "123",
            "Picture update",
            "Details are in the image.",
            "Announcement",
            image_path=str(image_path),
        )
    )

    assert message_id == 42
    assert channel.sent_args == ("**[Announcement] Picture update**\n\nDetails are in the image.",)
    assert channel.sent_kwargs["file"].filename == "announcement.png"


def test_discord_publisher_sends_image_with_native_poll(tmp_path: Path) -> None:
    image_path = tmp_path / "poll.png"
    image_path.write_bytes(_png_bytes())

    class _Message:
        id = 43

    class _Channel:
        def __init__(self) -> None:
            self.sent_kwargs = {}

        async def send(self, **kwargs):
            self.sent_kwargs = kwargs
            return _Message()

    channel = _Channel()

    class _Client:
        def get_channel(self, _channel_id: int):
            return channel

    publisher = DiscordEventPublisher(_Client())
    message_id = asyncio.run(
        publisher._publish(
            "123",
            "Choose one",
            "Vote below.",
            "Poll",
            event_options_json='["A", "B"]',
            image_path=str(image_path),
        )
    )

    assert message_id == 43
    assert channel.sent_kwargs["content"] == "Vote below."
    assert channel.sent_kwargs["file"].filename == "poll.png"
    assert channel.sent_kwargs["poll"].question == "Choose one"


def test_discord_publisher_reports_missing_attachment_permission(tmp_path: Path) -> None:
    image_path = tmp_path / "announcement.png"
    image_path.write_bytes(_png_bytes())

    class _Permissions:
        view_channel = True
        send_messages = True
        attach_files = False
        send_polls = True

    class _Guild:
        me = object()

    class _Channel:
        guild = _Guild()

        def permissions_for(self, _member):
            return _Permissions()

        async def send(self, *args, **kwargs):
            raise AssertionError("send must not run without attachment permission")

    channel = _Channel()

    class _Client:
        def get_channel(self, _channel_id: int):
            return channel

    publisher = DiscordEventPublisher(_Client())
    with pytest.raises(RuntimeError, match="Attach Files"):
        asyncio.run(
            publisher._publish(
                "123",
                "Picture update",
                "Details are in the image.",
                "Announcement",
                image_path=str(image_path),
            )
        )
