from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from app.bot.command_service import BotCommandService
from app.bot.discord_views import FAQCategoryView
from app.bot.message_handler import IncomingDiscordMessage, MessageHandler

if TYPE_CHECKING:
    from app.bot.discord_bot import CommunityOperationBot


def register_commands(bot: "CommunityOperationBot") -> None:
    command_service = BotCommandService(bot.db_path)

    @bot.tree.command(name="help", description="Open guided FAQ support.")
    async def help_command(interaction: discord.Interaction) -> None:
        message_result = bot.message_handler.handle_incoming_message(
            IncomingDiscordMessage(
                discord_user_id=str(interaction.user.id),
                channel_id=str(interaction.channel_id),
                content="/help",
            )
        )
        categories = bot.faq_flow.list_categories()
        if not categories:
            ticket = command_service.create_ticket(
                discord_user_id=str(interaction.user.id),
                channel_id=str(interaction.channel_id),
                issue="/help",
            )
            await interaction.response.send_message(ticket.response, ephemeral=True)
            return

        await interaction.response.send_message(
            "Please select the type of issue you are experiencing:",
            view=FAQCategoryView(
                faq_flow=bot.faq_flow,
                message_id=message_result.message_id,
                discord_user_id=str(interaction.user.id),
                channel_id=str(interaction.channel_id),
                original_message="/help",
            ),
            ephemeral=True,
        )

    @bot.tree.command(name="faq", description="Ask a question and search the FAQ.")
    @app_commands.describe(question="Player question to search in the FAQ knowledge base.")
    async def faq_command(interaction: discord.Interaction, question: str) -> None:
        result = bot.message_handler.handle_incoming_message(
            IncomingDiscordMessage(
                discord_user_id=str(interaction.user.id),
                channel_id=str(interaction.channel_id),
                content=question,
            )
        )
        if result.ai_reply:
            await interaction.response.send_message(result.ai_reply, ephemeral=True)
        else:
            await interaction.response.send_message(
                "I could not find a confident FAQ answer. Use /ticket to request manual support.",
                ephemeral=True,
            )

    @bot.tree.command(name="ticket", description="Create a manual support ticket.")
    @app_commands.describe(issue="Issue description for the operation team.")
    async def ticket_command(interaction: discord.Interaction, issue: str) -> None:
        result = command_service.create_ticket(
            discord_user_id=str(interaction.user.id),
            channel_id=str(interaction.channel_id),
            issue=issue,
        )
        await interaction.response.send_message(result.response, ephemeral=True)

    @bot.tree.command(name="report", description="Generate a community report.")
    @app_commands.describe(report_type="daily or weekly")
    async def report_command(interaction: discord.Interaction, report_type: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            result = command_service.generate_report(report_type)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(result.response, ephemeral=True)

    @bot.tree.command(name="event", description="Schedule a community event.")
    @app_commands.describe(
        title="Event title",
        content="Event content",
        event_type="Poll, Survey, Announcement, or Quiz",
        publish_time="YYYY-MM-DD HH:MM:SS",
        repeat_rule="none, daily, or weekly:friday:18:00",
        options="Optional poll/survey/quiz options, comma-separated.",
    )
    async def event_command(
        interaction: discord.Interaction,
        title: str,
        content: str,
        event_type: str,
        publish_time: str,
        repeat_rule: str = "none",
        options: str = "",
    ) -> None:
        result = command_service.schedule_event(
            title=title,
            content=content,
            event_type=event_type,
            channel_id=str(interaction.channel_id),
            publish_time=publish_time,
            repeat_rule=repeat_rule,
            options=options,
        )
        await interaction.response.send_message(result.response, ephemeral=True)
