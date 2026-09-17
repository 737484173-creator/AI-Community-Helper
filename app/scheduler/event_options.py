from __future__ import annotations

import json


OPTION_MARKERS = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J")


def parse_event_options(raw_options: str | None) -> list[str]:
    if not raw_options:
        return []
    options: list[str] = []
    for line in raw_options.replace(",", "\n").splitlines():
        option = line.strip()
        if option:
            options.append(option)
    return options[: len(OPTION_MARKERS)]


def options_to_json(options: list[str]) -> str | None:
    cleaned = [option.strip() for option in options if option.strip()]
    if not cleaned:
        return None
    return json.dumps(cleaned[: len(OPTION_MARKERS)], ensure_ascii=True)


def options_from_json(options_json: str | None) -> list[str]:
    if not options_json:
        return []
    loaded = json.loads(options_json)
    if not isinstance(loaded, list):
        return []
    return [str(option) for option in loaded][: len(OPTION_MARKERS)]


def format_event_content(
    content: str,
    event_type: str,
    event_options_json: str | None,
) -> str:
    options = options_from_json(event_options_json)
    if not options:
        return content

    option_lines = [
        f"{OPTION_MARKERS[index]}. {option}" for index, option in enumerate(options)
    ]
    return "\n\n".join(
        [
            content,
            "Options:\n" + "\n".join(option_lines),
            _action_line(event_type),
        ]
    )


def _action_line(event_type: str) -> str:
    normalized = event_type.lower()
    if normalized == "poll":
        return "React with the matching option letter to vote."
    if normalized == "quiz":
        return "Reply or react with the matching option letter."
    if normalized == "survey":
        return "React with the matching option letter to share your preference."
    return "Review the options above."


def map_poll_results_to_options(
    poll_result: dict[str, int],
    event_options_json: str | None,
) -> dict:
    options = options_from_json(event_options_json)
    if not options:
        return {"raw_reactions": poll_result, "option_results": []}

    option_results = []
    for index, option in enumerate(options):
        marker = OPTION_MARKERS[index]
        count = _reaction_count_for_marker(poll_result, marker)
        option_results.append(
            {
                "marker": marker,
                "option": option,
                "count": count,
            }
        )
    return {
        "raw_reactions": poll_result,
        "option_results": option_results,
    }


def poll_results_to_json(
    poll_result: dict[str, int],
    event_options_json: str | None,
) -> str:
    mapped = map_poll_results_to_options(poll_result, event_options_json)
    return json.dumps(mapped, ensure_ascii=True, sort_keys=True)


def format_option_winner(poll_result_json: str | None) -> str | None:
    if not poll_result_json:
        return None
    data = json.loads(poll_result_json)
    if not isinstance(data, dict):
        return None
    option_results = data.get("option_results")
    if not option_results:
        return None
    winner = max(option_results, key=lambda item: int(item.get("count", 0)))
    return f"{winner.get('marker')}. {winner.get('option')} ({winner.get('count')} votes)"


def _reaction_count_for_marker(poll_result: dict[str, int], marker: str) -> int:
    candidates = {
        marker,
        marker.lower(),
        f"{marker}\ufe0f\u20e3",
        f"{marker.lower()}\ufe0f\u20e3",
        _regional_indicator(marker),
    }
    return sum(int(count) for emoji, count in poll_result.items() if str(emoji) in candidates)


def _regional_indicator(marker: str) -> str:
    codepoint = 0x1F1E6 + (ord(marker.upper()) - ord("A"))
    return chr(codepoint)
