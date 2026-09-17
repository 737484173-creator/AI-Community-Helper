from __future__ import annotations

from app.ai.ai_client import AIClient, StaticAIClient
from app.ai.faq_matcher import FAQMatch


FAQ_SYSTEM_PROMPT = """
You are a game community support assistant.
Answer only using the official FAQ answer provided by the operator.
Do not invent account binding, payment, player identity, VIP, or server data.
Keep the tone friendly, concise, and operationally safe.
""".strip()


class ChatAssistant:
    def __init__(self, ai_client: AIClient | None = None) -> None:
        self.ai_client = ai_client

    def generate_faq_reply(self, player_message: str, match: FAQMatch) -> str:
        if self.ai_client is None:
            return match.answer

        return self.ai_client.generate(
            system_prompt=FAQ_SYSTEM_PROMPT,
            user_prompt=(
                f"Player message:\n{player_message}\n\n"
                f"Matched FAQ question:\n{match.question}\n\n"
                f"Official FAQ answer:\n{match.answer}\n\n"
                "Rewrite the official answer for this player without adding new facts."
            ),
        )

    def generate_unresolved_reply(self) -> str:
        return StaticAIClient().fallback_response

