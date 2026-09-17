from __future__ import annotations


def normalize_server_id(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text[:1].lower() == "s":
        text = text[1:].strip()
    return text if text.isdigit() else None


def get_server_name(server_id: str | int | None, mapping: dict[str, str]) -> str | None:
    normalized = normalize_server_id(server_id)
    if normalized is None:
        return None
    return mapping.get(normalized)


def generate_discord_nickname(server_id: str | int, player_name: str, mapping: dict[str, str] | None = None) -> str:
    normalized = normalize_server_id(server_id)
    if normalized is None:
        raise ValueError("server_id must be numeric or S-prefixed numeric text")
    server_name = mapping.get(normalized) if mapping else f"S{normalized}"
    if not server_name:
        server_name = f"S{normalized}"
    return f"{server_name} {' '.join(player_name.split())}"
