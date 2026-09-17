from __future__ import annotations

import discord

from app.bot.faq_flow import FAQAnswer, FAQFlowService


def _discord_label(text: str, max_length: int = 100) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3] + "..."


async def _disable_current_view(interaction: discord.Interaction) -> None:
    if not interaction.message or not isinstance(interaction.message, discord.Message):
        return

    if not interaction.message.components:
        return

    current_view = discord.ui.View.from_message(interaction.message)
    for item in current_view.children:
        item.disabled = True

    try:
        await interaction.message.edit(view=current_view)
    except discord.HTTPException:
        pass


class FAQCategorySelect(discord.ui.Select):
    def __init__(
        self,
        faq_flow: FAQFlowService,
        message_id: int,
        discord_user_id: str,
        channel_id: str,
        original_message: str,
    ) -> None:
        self.faq_flow = faq_flow
        self.message_id = message_id
        self.discord_user_id = discord_user_id
        self.channel_id = channel_id
        self.original_message = original_message

        categories = faq_flow.list_categories()
        options = [
            discord.SelectOption(label=_discord_label(category), value=category)
            for category in categories
        ]
        super().__init__(
            placeholder="Select the issue category",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _disable_current_view(interaction)
        category = self.values[0]
        questions = self.faq_flow.list_questions(category)
        if not questions:
            ticket_id = self.faq_flow.create_pending_ticket(
                discord_user_id=self.discord_user_id,
                channel_id=self.channel_id,
                original_message=self.original_message,
                selected_category=category,
            )
            await interaction.followup.send(
                f"No FAQ is available for `{category}` yet. "
                f"I created ticket #{ticket_id} for manual support.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"You selected `{category}`. Please choose the specific issue:",
            view=FAQQuestionView(
                faq_flow=self.faq_flow,
                message_id=self.message_id,
                discord_user_id=self.discord_user_id,
                channel_id=self.channel_id,
                original_message=self.original_message,
                selected_category=category,
            ),
            ephemeral=True,
        )


class FAQQuestionSelect(discord.ui.Select):
    def __init__(
        self,
        faq_flow: FAQFlowService,
        message_id: int,
        discord_user_id: str,
        channel_id: str,
        original_message: str,
        selected_category: str,
    ) -> None:
        self.faq_flow = faq_flow
        self.message_id = message_id
        self.discord_user_id = discord_user_id
        self.channel_id = channel_id
        self.original_message = original_message
        self.selected_category = selected_category

        questions = faq_flow.list_questions(selected_category)
        options = [
            discord.SelectOption(
                label=_discord_label(question.label),
                value=str(question.id),
                description=_discord_label(question.description, 100)
                if question.description
                else None,
            )
            for question in questions
        ]
        options.append(
            discord.SelectOption(
                label="None of these",
                value="manual_support",
                description="Create a manual support ticket",
            )
        )

        super().__init__(
            placeholder="Select the specific issue",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _disable_current_view(interaction)
        selected_value = self.values[0]
        if selected_value == "manual_support":
            ticket_id = self.faq_flow.create_pending_ticket(
                discord_user_id=self.discord_user_id,
                channel_id=self.channel_id,
                original_message=self.original_message,
                selected_category=self.selected_category,
            )
            await interaction.followup.send(
                f"I created ticket #{ticket_id} for manual support.",
                ephemeral=True,
            )
            return

        answer = self.faq_flow.get_answer(int(selected_value))
        self.faq_flow.mark_message_answered(self.message_id, answer)
        await interaction.followup.send(
            content=_format_faq_answer(answer),
            view=FAQResolutionView(
                faq_flow=self.faq_flow,
                discord_user_id=self.discord_user_id,
                channel_id=self.channel_id,
                original_message=self.original_message,
                answer=answer,
            ),
            ephemeral=True,
        )


class FAQCategoryView(discord.ui.View):
    def __init__(
        self,
        faq_flow: FAQFlowService,
        message_id: int,
        discord_user_id: str,
        channel_id: str,
        original_message: str,
    ) -> None:
        super().__init__(timeout=1800)
        self.add_item(
            FAQCategorySelect(
                faq_flow=faq_flow,
                message_id=message_id,
                discord_user_id=discord_user_id,
                channel_id=channel_id,
                original_message=original_message,
            )
        )


class FAQQuestionView(discord.ui.View):
    def __init__(
        self,
        faq_flow: FAQFlowService,
        message_id: int,
        discord_user_id: str,
        channel_id: str,
        original_message: str,
        selected_category: str,
    ) -> None:
        super().__init__(timeout=1800)
        self.add_item(
            FAQQuestionSelect(
                faq_flow=faq_flow,
                message_id=message_id,
                discord_user_id=discord_user_id,
                channel_id=channel_id,
                original_message=original_message,
                selected_category=selected_category,
            )
        )


class FAQResolutionView(discord.ui.View):
    def __init__(
        self,
        faq_flow: FAQFlowService,
        discord_user_id: str,
        channel_id: str,
        original_message: str,
        answer: FAQAnswer,
    ) -> None:
        super().__init__(timeout=1800)
        self.faq_flow = faq_flow
        self.discord_user_id = discord_user_id
        self.channel_id = channel_id
        self.original_message = original_message
        self.answer = answer

    @discord.ui.button(label="Solved", style=discord.ButtonStyle.success)
    async def solved(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        button.disabled = True
        await interaction.response.edit_message(
            content="Glad this helped. I marked this FAQ answer as solved.",
            view=self,
        )

    @discord.ui.button(label="Need manual support", style=discord.ButtonStyle.danger)
    async def unresolved(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        button.disabled = True
        ticket_id = self.faq_flow.create_pending_ticket(
            discord_user_id=self.discord_user_id,
            channel_id=self.channel_id,
            original_message=self.original_message,
            selected_category=self.answer.category,
            selected_question=self.answer.question,
            issue_description="Player marked FAQ answer as unresolved.",
        )
        await interaction.response.edit_message(
            content=f"I created ticket #{ticket_id} for manual support.",
            view=self,
        )


def _format_faq_answer(answer: FAQAnswer) -> str:
    return (
        f"**{answer.question}**\n\n"
        f"{answer.answer}\n\n"
        "Did this solve your issue?"
    )
