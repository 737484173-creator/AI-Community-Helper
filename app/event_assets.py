from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.database.db import get_db_path


MAX_EVENT_IMAGE_BYTES = 8 * 1024 * 1024
MAX_EVENT_IMAGE_PIXELS = 40_000_000
EVENT_IMAGE_DIRECTORY = "event_assets"
EVENT_IMAGE_EXTENSIONS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}


class EventImageValidationError(ValueError):
    pass


@dataclass(frozen=True)
class EventImageInfo:
    extension: str
    width: int
    height: int


def validate_event_image(payload: bytes) -> EventImageInfo:
    if not payload:
        raise EventImageValidationError("图片文件为空，请重新选择。")
    if len(payload) > MAX_EVENT_IMAGE_BYTES:
        raise EventImageValidationError("配图不能超过 8 MB。")

    try:
        with Image.open(BytesIO(payload)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            if width <= 0 or height <= 0:
                raise EventImageValidationError("无法识别图片尺寸。")
            if width * height > MAX_EVENT_IMAGE_PIXELS:
                raise EventImageValidationError("图片尺寸过大，请压缩后重新上传。")
            image.verify()
    except EventImageValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise EventImageValidationError("文件不是有效的 JPG、PNG 或 WebP 图片。") from exc

    extension = EVENT_IMAGE_EXTENSIONS.get(image_format)
    if extension is None:
        raise EventImageValidationError("仅支持 JPG、PNG 和 WebP 图片。")
    return EventImageInfo(extension=extension, width=width, height=height)


def save_event_image(db_path: str | Path | None, payload: bytes) -> str:
    image_info = validate_event_image(payload)
    asset_directory = _asset_directory(db_path)
    asset_directory.mkdir(parents=True, exist_ok=True)

    image_path = asset_directory / f"{uuid4().hex}{image_info.extension}"
    pending_path = image_path.with_suffix(f"{image_path.suffix}.tmp")
    try:
        pending_path.write_bytes(payload)
        pending_path.replace(image_path)
    finally:
        pending_path.unlink(missing_ok=True)

    return f"{EVENT_IMAGE_DIRECTORY}/{image_path.name}"


def resolve_event_image_path(
    db_path: str | Path | None,
    stored_path: str | None,
) -> Path | None:
    if not stored_path:
        return None

    relative_path = Path(stored_path)
    if relative_path.is_absolute():
        raise ValueError("Activity image path must be relative to the database directory.")

    asset_directory = _asset_directory(db_path)
    resolved_path = (_database_path(db_path).parent / relative_path).resolve()
    if not resolved_path.is_relative_to(asset_directory):
        raise ValueError("Activity image path points outside the event asset directory.")
    return resolved_path


def delete_event_image(db_path: str | Path | None, stored_path: str | None) -> None:
    image_path = resolve_event_image_path(db_path, stored_path)
    if image_path is not None:
        image_path.unlink(missing_ok=True)


def _database_path(db_path: str | Path | None) -> Path:
    return (Path(db_path) if db_path else get_db_path()).resolve()


def _asset_directory(db_path: str | Path | None) -> Path:
    return (_database_path(db_path).parent / EVENT_IMAGE_DIRECTORY).resolve()
