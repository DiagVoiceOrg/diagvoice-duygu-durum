"""
Gelen ses yüklemelerini kalıcı dizine kaydet (Docker volume) ve admin oynatma API'si için metadata.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("diagvoice.audio_recordings")

AUDIT_AUDIO_STORAGE_ENABLED = os.environ.get("AUDIT_AUDIO_STORAGE_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)


def _default_storage_dir() -> Path:
    env = os.environ.get("AUDIT_AUDIO_STORAGE_DIR", "").strip()
    if env:
        return Path(env)
    # Yerel geliştirme: depo kökü data/audio_recordings (Docker’da env ile /data/audio_recordings)
    return Path(__file__).resolve().parents[2] / "data" / "audio_recordings"


AUDIT_AUDIO_STORAGE_DIR = _default_storage_dir()
AUDIT_AUDIO_STORAGE_MAX_BYTES = max(0, int(os.environ.get("AUDIT_AUDIO_STORAGE_MAX_BYTES", str(50 * 1024 * 1024))))

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_storage_dir() -> None:
    if not AUDIT_AUDIO_STORAGE_ENABLED:
        return
    try:
        AUDIT_AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        _log.exception("audio storage dir create failed path=%s", AUDIT_AUDIO_STORAGE_DIR)


def _sanitize_filename(name: str) -> str:
    base = (name or "audio").replace("\\", "_").replace("/", "_").strip()
    if not base:
        base = "audio"
    if len(base) > 120:
        stem, dot, ext = base.rpartition(".")
        if dot and len(ext) <= 8:
            base = f"{stem[:100]}.{ext}"
        else:
            base = base[:120]
    return _SAFE_NAME_RE.sub("_", base)


def _guess_extension(filename: str, content_type: str) -> str:
    lower = (filename or "").lower()
    for ext in (".webm", ".wav", ".mp3", ".ogg", ".m4a", ".mp4", ".flac"):
        if lower.endswith(ext):
            return ext
    ct = (content_type or "").lower()
    if "webm" in ct:
        return ".webm"
    if "wav" in ct:
        return ".wav"
    if "mpeg" in ct or "mp3" in ct:
        return ".mp3"
    if "ogg" in ct:
        return ".ogg"
    if "mp4" in ct or "m4a" in ct:
        return ".m4a"
    return ".bin"


def _resolve_stored_path(stored_rel: str) -> Optional[Path]:
    if not stored_rel or ".." in stored_rel.replace("\\", "/"):
        return None
    root = AUDIT_AUDIO_STORAGE_DIR.resolve()
    candidate = (AUDIT_AUDIO_STORAGE_DIR / stored_rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _write_recording_sync(
    *,
    tmp_path: str | None,
    body: bytes | None,
    original_filename: str,
    content_type: str,
) -> dict[str, Any]:
    ensure_storage_dir()
    date_part = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rec_id = uuid.uuid4().hex
    safe_name = _sanitize_filename(original_filename)
    ext = _guess_extension(safe_name, content_type)
    if not safe_name.lower().endswith(ext):
        safe_name = f"{Path(safe_name).stem}{ext}"
    day_dir = AUDIT_AUDIO_STORAGE_DIR / date_part
    day_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{rec_id}_{safe_name}"
    dest = day_dir / stored_name
    nbytes = 0
    if tmp_path:
        nbytes = os.path.getsize(tmp_path)
        if AUDIT_AUDIO_STORAGE_MAX_BYTES and nbytes > AUDIT_AUDIO_STORAGE_MAX_BYTES:
            raise ValueError(f"audio too large ({nbytes} bytes)")
        shutil.copy2(tmp_path, dest)
    elif body is not None:
        nbytes = len(body)
        if AUDIT_AUDIO_STORAGE_MAX_BYTES and nbytes > AUDIT_AUDIO_STORAGE_MAX_BYTES:
            raise ValueError(f"audio too large ({nbytes} bytes)")
        dest.write_bytes(body)
    else:
        raise ValueError("no audio source")
    stored_rel = f"{date_part}/{stored_name}"
    return {
        "id": rec_id,
        "stored_rel": stored_rel,
        "original_filename": original_filename[:200],
        "content_type": (content_type or "application/octet-stream")[:120],
        "bytes": nbytes,
    }


async def persist_request_audio(
    request: Any,
    *,
    tmp_path: str | None = None,
    body: bytes | None = None,
    original_filename: str = "audio",
    content_type: str = "application/octet-stream",
) -> Optional[dict[str, Any]]:
    """İsteğe bağlı ses kaydı — request.state.audio_recording (middleware MongoDB'ye yazar)."""
    if not AUDIT_AUDIO_STORAGE_ENABLED or request is None or not hasattr(request, "state"):
        return None
    if getattr(request.state, "audio_recording", None):
        return request.state.audio_recording
    try:
        meta = await asyncio.to_thread(
            _write_recording_sync,
            tmp_path=tmp_path,
            body=body,
            original_filename=original_filename,
            content_type=content_type,
        )
        request.state.audio_recording = meta
        return meta
    except Exception as e:
        _log.warning("audio persist skipped filename=%s err=%s", original_filename, e)
        return None


def resolve_recording_file(recording: Any) -> Optional[Path]:
    if not isinstance(recording, dict):
        return None
    stored_rel = recording.get("stored_rel") or recording.get("stored_name")
    if not isinstance(stored_rel, str):
        return None
    return _resolve_stored_path(stored_rel)
