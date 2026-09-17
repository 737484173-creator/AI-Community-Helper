from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol

from app.scheduler.event_options import options_from_json

if TYPE_CHECKING:
    import discord


class EventPublisher(Protocol):
    def publish(
        self,
        channel_id: str,
        title: str,
        content: str,
        event_type: str,
        event_options_json: str | None = None,
        image_path: str | None = None,
    ) -> str:
        """Publish an event and return the Discord message id."""


@dataclass
class InMemoryEventPublisher:
    published_messages: list[dict[str, str]]

    def __init__(self) -> None:
        self.published_messages = []

    def publish(
        self,
        channel_id: str,
        title: str,
        content: str,
        event_type: str,
        event_options_json: str | None = None,
        image_path: str | None = None,
    ) -> str:
        message_id = f"test-message-{len(self.published_messages) + 1}"
        self.published_messages.append(
            {
                "message_id": message_id,
                "channel_id": channel_id,
                "title": title,
                "content": content,
                "event_type": event_type,
                "event_options_json": event_options_json or "",
                "image_path": image_path or "",
                "uses_native_poll": str(should_use_native_poll(event_type, event_options_json)),
            }
        )
        return message_id


class DiscordEventPublisher:
    def __init__(self, client: "discord.Client", timeout_seconds: int = 20) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds

    def publish(
        self,
        channel_id: str,
        title: str,
        content: str,
        event_type: str,
        event_options_json: str | None = None,
        image_path: str | None = None,
    ) -> str:
        future = asyncio.run_coroutine_threadsafe(
            self._publish(
                channel_id,
                title,
                content,
                event_type,
                event_options_json,
                image_path,
            ),
            self.client.loop,
        )
        return str(future.result(timeout=self.timeout_seconds))

    async def _publish(
        self,
        channel_id: str,
        title: str,
        content: str,
        event_type: str,
        event_options_json: str | None = None,
        image_path: str | None = None,
    ) -> int:
        import discord

        channel = self.client.get_channel(int(channel_id))
        if channel is None:
            channel = await self.client.fetch_channel(int(channel_id))

        sendable_channel: Any = channel
        if not hasattr(sendable_channel, "send"):
            raise RuntimeError(f"Discord channel does not support send: {channel_id}")

        missing_permissions = _missing_channel_permissions(
            sendable_channel,
            needs_attachment=bool(image_path),
            needs_poll=should_use_native_poll(event_type, event_options_json),
        )
        if missing_permissions:
            raise RuntimeError(
                f"Discord Bot is missing permissions in channel {channel_id}: "
                + ", ".join(missing_permissions)
            )

        attachment = discord.File(image_path) if image_path else None
        try:
            if should_use_native_poll(event_type, event_options_json):
                poll = build_discord_poll(discord, title, event_options_json)
                send_options: dict[str, Any] = {"content": content, "poll": poll}
                if attachment is not None:
                    send_options["file"] = attachment
                message = await sendable_channel.send(**send_options)
            else:
                send_options = {}
                if attachment is not None:
                    send_options["file"] = attachment
                message = await sendable_channel.send(
                    format_event_message(title, content, event_type),
                    **send_options,
                )
        finally:
            if attachment is not None:
                attachment.close()
        return int(message.id)


def _missing_channel_permissions(
    channel: Any,
    *,
    needs_attachment: bool,
    needs_poll: bool,
) -> list[str]:
    guild = getattr(channel, "guild", None)
    bot_member = getattr(guild, "me", None)
    permissions_for = getattr(channel, "permissions_for", None)
    if bot_member is None or not callable(permissions_for):
        return []

    permissions = permissions_for(bot_member)
    required = [
        ("View Channel", "view_channel", True),
        ("Send Messages", "send_messages", True),
        ("Attach Files", "attach_files", needs_attachment),
        ("Send Polls", "send_polls", needs_poll),
    ]
    return [
        label
        for label, attribute, is_required in required
        if is_required and not bool(getattr(permissions, attribute, False))
    ]


def format_event_message(title: str, content: str, event_type: str) -> str:
    return f"**[{event_type}] {title}**\n\n{content}"


def should_use_native_poll(event_type: str, event_options_json: str | None) -> bool:
    return event_type == "Poll" and bool(options_from_json(event_options_json))


def build_discord_poll(discord_module, title: str, event_options_json: str | None):
    options = options_from_json(event_options_json)
    if len(options) < 2:
        raise RuntimeError("Discord native Poll requires at least 2 options.")
    if len(options) > 10:
        raise RuntimeError("Discord native Poll supports at most 10 options.")

    poll = discord_module.Poll(question=title, duration=timedelta(days=7), multiple=False)
    for option in options:
        poll.add_answer(text=option)
    return poll
