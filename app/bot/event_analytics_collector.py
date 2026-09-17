from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.scheduler.event_options import OPTION_MARKERS

if TYPE_CHECKING:
    import discord


@dataclass(frozen=True)
class EventMetrics:
    participant_count: int
    reaction_count: int
    poll_result: dict[str, int]

    def to_json(self) -> str:
        return json.dumps(self.poll_result, ensure_ascii=True, sort_keys=True)


class EventAnalyticsCollector(Protocol):
    def collect(self, channel_id: str, discord_message_id: str) -> EventMetrics:
        """Collect metrics for a published Discord event message."""


class InMemoryEventAnalyticsCollector:
    def __init__(self, metrics_by_message_id: dict[str, EventMetrics] | None = None) -> None:
        self.metrics_by_message_id = metrics_by_message_id or {}

    def collect(self, channel_id: str, discord_message_id: str) -> EventMetrics:
        return self.metrics_by_message_id.get(
            discord_message_id,
            EventMetrics(participant_count=0, reaction_count=0, poll_result={}),
        )


class DiscordEventAnalyticsCollector:
    def __init__(self, client: "discord.Client", timeout_seconds: int = 20) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds

    def collect(self, channel_id: str, discord_message_id: str) -> EventMetrics:
        future = asyncio.run_coroutine_threadsafe(
            self._collect(channel_id, discord_message_id),
            self.client.loop,
        )
        return future.result(timeout=self.timeout_seconds)

    async def _collect(self, channel_id: str, discord_message_id: str) -> EventMetrics:
        channel = self.client.get_channel(int(channel_id))
        if channel is None:
            channel = await self.client.fetch_channel(int(channel_id))
        if not hasattr(channel, "fetch_message"):
            raise RuntimeError(f"Discord channel does not support fetch_message: {channel_id}")

        message = await channel.fetch_message(int(discord_message_id))
        poll = getattr(message, "poll", None)
        if poll is not None:
            poll_results: dict[str, int] = {}
            total_votes = int(getattr(poll, "total_votes", 0) or 0)
            for index, answer in enumerate(getattr(poll, "answers", [])):
                marker = OPTION_MARKERS[index] if index < len(OPTION_MARKERS) else str(index + 1)
                poll_results[marker] = int(getattr(answer, "vote_count", 0) or 0)

            return EventMetrics(
                participant_count=total_votes,
                reaction_count=total_votes,
                poll_result=poll_results,
            )

        reaction_counts: dict[str, int] = {}
        participant_ids: set[int] = set()
        reaction_count = 0

        for reaction in message.reactions:
            emoji = str(reaction.emoji)
            count = int(reaction.count)
            reaction_counts[emoji] = count
            reaction_count += count
            async for user in reaction.users():
                if not user.bot:
                    participant_ids.add(int(user.id))

        return EventMetrics(
            participant_count=len(participant_ids),
            reaction_count=reaction_count,
            poll_result=reaction_counts,
        )
