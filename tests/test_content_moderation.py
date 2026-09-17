from app.bot.content_moderation import (
    analyze_public_message,
    public_message_risk_level,
    should_capture_public_message,
)


def test_public_monitor_captures_profane_game_chat_message() -> None:
    assert should_capture_public_message("what the hell is this", "💬│game-chat") is True


def test_public_monitor_captures_risk_messages_in_chat_oriented_channels() -> None:
    assert should_capture_public_message("what the hell is this", "📌│ask_for_help") is True
    assert should_capture_public_message("This is trash!!!", "🥝│suggestion-discussion") is True


def test_public_monitor_captures_heated_game_chat_message() -> None:
    result = analyze_public_message("This game is broken!!!")

    assert result.should_capture is True
    assert result.reason is not None


def test_public_monitor_ignores_normal_game_chat_message() -> None:
    assert should_capture_public_message("Good match today", "game-chat") is False


def test_public_monitor_ignores_other_channels() -> None:
    assert should_capture_public_message("what the hell is this", "off-topic") is False


def test_public_message_risk_level_matches_dashboard_and_chat_monitor_semantics() -> None:
    assert public_message_risk_level("you are an idiot") == "高风险"
    assert public_message_risk_level("this is the worst!!!") == "中风险"
    assert public_message_risk_level("hello everyone") is None
