from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import threading
import time

from .paths import TRANSFER_DIR, UPLOAD_DIR


class UploadNotFound(Exception):
    pass


class UploadForbidden(Exception):
    pass


class OffsetMismatch(Exception):
    def __init__(self, current_offset: int):
        super().__init__(f"Upload offset mismatch; current offset is {current_offset}")
        self.current_offset = current_offset


class UploadTooLargeChunk(Exception):
    pass


@dataclass
class UploadSession:
    upload_id: str
    original_name: str
    final_name: str
    size: int
    resume_key: str
    owner_key: str
    created_at: float
    updated_at: float

    @property
    def part_path(self) -> Path:
        return TRANSFER_DIR / f"{self.upload_id}.part"

    @property
    def meta_path(self) -> Path:
        return TRANSFER_DIR / f"{self.upload_id}.json"

    def as_meta(self) -> dict:
        return {
            "upload_id": self.upload_id,
            "original_name": self.original_name,
            "final_name": self.final_name,
            "size": self.size,
            "resume_key": self.resume_key,
            "owner_key": self.owner_key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class CompletedUpload:
    upload_id: str
    owner_key: str
    final_name: str
    size: int
    completed_at: float

    @property
    def meta_path(self) -> Path:
        return TRANSFER_DIR / f"{self.upload_id}.done.json"

    def as_meta(self) -> dict:
        return {
            "upload_id": self.upload_id,
            "owner_key": self.owner_key,
            "final_name": self.final_name,
            "size": self.size,
            "completed_at": self.completed_at,
        }


class ResumableUploadManager:
    """Disk-backed resumable upload sessions.

    A chunk may be interrupted halfway through. The bytes that reached disk remain
    valid, and the next status request reports the exact byte offset to resume from.
    """

    SESSION_TTL = 24 * 60 * 60
    COMPLETED_TTL = 60 * 60
    MAX_CHUNK_SIZE = 16 * 1024 * 1024

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: dict[str, UploadSession] = {}
        self._session_locks: dict[str, threading.RLock] = {}
        self._resume_index: dict[tuple[str, str], str] = {}
        self._completed: dict[str, CompletedUpload] = {}
        TRANSFER_DIR.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    def _load_from_disk(self):
        now = time.time()
        with self._lock:
            for meta_path in TRANSFER_DIR.glob("*.json"):
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    continue

                if meta_path.name.endswith(".done.json"):
                    try:
                        item = CompletedUpload(
                            upload_id=str(data["upload_id"]),
                            owner_key=str(data["owner_key"]),
                            final_name=Path(str(data["final_name"])).name,
                            size=int(data["size"]),
                            completed_at=float(data["completed_at"]),
                        )
                    except Exception:
                        continue
                    if now - item.completed_at <= self.COMPLETED_TTL:
                        self._completed[item.upload_id] = item
                    else:
                        meta_path.unlink(missing_ok=True)
                    continue

                try:
                    session = UploadSession(
                        upload_id=str(data["upload_id"]),
                        original_name=Path(str(data["original_name"])).name,
                        final_name=Path(str(data["final_name"])).name,
                        size=int(data["size"]),
                        resume_key=str(data["resume_key"]),
                        owner_key=str(data["owner_key"]),
                        created_at=float(data["created_at"]),
                        updated_at=float(data["updated_at"]),
                    )
                except Exception:
                    continue

                if (
                    not session.part_path.exists()
                    or session.size < 0
                    or session.part_path.stat().st_size > session.size
                    or now - session.updated_at > self.SESSION_TTL
                ):
                    session.part_path.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    continue

                self._sessions[session.upload_id] = session
                self._session_locks[session.upload_id] = threading.RLock()
                self._resume_index[(session.owner_key, session.resume_key)] = session.upload_id

            self._cleanup_locked(now)

    def init_upload(
        self,
        *,
        name: str,
        size: int,
        resume_key: str,
        owner_key: str,
    ) -> tuple[UploadSession, int, bool]:
        safe_name = Path(name or "").name
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("invalid filename")
        if size < 0:
            raise ValueError("invalid size")
        if not resume_key or len(resume_key) > 512:
            raise ValueError("invalid resume key")

        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            index_key = (owner_key, resume_key)
            existing_id = self._resume_index.get(index_key)
            if existing_id:
                existing = self._sessions.get(existing_id)
                if (
                    existing
                    and existing.original_name == safe_name
                    and existing.size == size
                    and existing.part_path.exists()
                ):
                    existing.updated_at = now
                    self._save_session_locked(existing)
                    return existing, existing.part_path.stat().st_size, True
                self._resume_index.pop(index_key, None)

            final_name = self._unique_final_name_locked(safe_name)
            upload_id = secrets.token_urlsafe(24)
            session = UploadSession(
                upload_id=upload_id,
                original_name=safe_name,
                final_name=final_name,
                size=size,
                resume_key=resume_key,
                owner_key=owner_key,
                created_at=now,
                updated_at=now,
            )
            session.part_path.touch(exist_ok=False)
            self._sessions[upload_id] = session
            self._session_locks[upload_id] = threading.RLock()
            self._resume_index[index_key] = upload_id
            self._save_session_locked(session)
            return session, 0, False

    def status(self, upload_id: str, owner_key: str) -> dict:
        with self._lock:
            self._cleanup_locked(time.time())
            completed = self._completed.get(upload_id)
            if completed:
                self._check_owner(completed.owner_key, owner_key)
                return {
                    "upload_id": upload_id,
                    "offset": completed.size,
                    "size": completed.size,
                    "complete": True,
                    "name": completed.final_name,
                }

            session = self._get_session_locked(upload_id, owner_key)
            session_lock = self._session_locks[upload_id]

        with session_lock:
            if not session.part_path.exists():
                raise UploadNotFound()
            return {
                "upload_id": upload_id,
                "offset": session.part_path.stat().st_size,
                "size": session.size,
                "complete": False,
                "name": session.final_name,
            }

    def append_chunk(
        self,
        *,
        upload_id: str,
        owner_key: str,
        offset: int,
        content_length: int,
        stream,
    ) -> int:
        if content_length < 0 or content_length > self.MAX_CHUNK_SIZE:
            raise UploadTooLargeChunk()

        with self._lock:
            session = self._get_session_locked(upload_id, owner_key)
            session.updated_at = time.time()
            self._save_session_locked(session)
            session_lock = self._session_locks[upload_id]

        with session_lock:
            current = session.part_path.stat().st_size
            if offset != current:
                raise OffsetMismatch(current)
            if current + content_length > session.size:
                raise ValueError("chunk exceeds declared file size")

            remaining = content_length
            try:
                with session.part_path.open("ab") as dest:
                    while remaining:
                        chunk = stream.read(min(64 * 1024, remaining))
                        if not chunk:
                            raise ConnectionError("upload body ended before Content-Length")
                        dest.write(chunk)
                        remaining -= len(chunk)
                    dest.flush()
            finally:
                # A network drop can happen in the middle of a chunk. Whatever reached
                # disk is a valid resume point and must be persisted.
                with self._lock:
                    if upload_id in self._sessions:
                        session.updated_at = time.time()
                        self._save_session_locked(session)

            return session.part_path.stat().st_size

    def complete(self, upload_id: str, owner_key: str) -> tuple[str, bool]:
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            completed = self._completed.get(upload_id)
            if completed:
                self._check_owner(completed.owner_key, owner_key)
                return completed.final_name, False

            session = self._get_session_locked(upload_id, owner_key)
            session_lock = self._session_locks[upload_id]

        with session_lock:
            with self._lock:
                # Re-check after waiting for any in-flight chunk for this upload.
                session = self._get_session_locked(upload_id, owner_key)
                current = session.part_path.stat().st_size
                if current != session.size:
                    raise OffsetMismatch(current)

                final_name = session.final_name
                final_path = UPLOAD_DIR / final_name
                if final_path.exists():
                    final_name = self._unique_final_name_locked(session.original_name, exclude_upload_id=upload_id)
                    final_path = UPLOAD_DIR / final_name

                session.part_path.replace(final_path)
                session.meta_path.unlink(missing_ok=True)
                self._sessions.pop(upload_id, None)
                self._session_locks.pop(upload_id, None)
                self._resume_index.pop((session.owner_key, session.resume_key), None)

                completed = CompletedUpload(
                    upload_id=upload_id,
                    owner_key=session.owner_key,
                    final_name=final_name,
                    size=session.size,
                    completed_at=now,
                )
                self._completed[upload_id] = completed
                self._save_completed_locked(completed)
                return final_name, True

    def _get_session_locked(self, upload_id: str, owner_key: str) -> UploadSession:
        session = self._sessions.get(upload_id)
        if not session:
            raise UploadNotFound()
        self._check_owner(session.owner_key, owner_key)
        if not session.part_path.exists():
            raise UploadNotFound()
        return session

    @staticmethod
    def _check_owner(expected: str, actual: str):
        if not secrets.compare_digest(expected, actual):
            raise UploadForbidden()

    def _unique_final_name_locked(self, requested_name: str, exclude_upload_id: str | None = None) -> str:
        safe = Path(requested_name).name
        candidate = safe
        stem = Path(safe).stem
        suffix = Path(safe).suffix
        counter = 1

        reserved = {
            session.final_name
            for upload_id, session in self._sessions.items()
            if upload_id != exclude_upload_id
        }
        while (UPLOAD_DIR / candidate).exists() or candidate in reserved:
            candidate = f"{stem}_{counter}{suffix}"
            counter += 1
        return candidate

    def _save_session_locked(self, session: UploadSession):
        self._atomic_write_json(session.meta_path, session.as_meta())

    def _save_completed_locked(self, completed: CompletedUpload):
        self._atomic_write_json(completed.meta_path, completed.as_meta())

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict):
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temp.replace(path)

    def _cleanup_locked(self, now: float):
        expired_sessions = [
            upload_id
            for upload_id, session in self._sessions.items()
            if now - session.updated_at > self.SESSION_TTL
        ]
        for upload_id in expired_sessions:
            session = self._sessions.pop(upload_id)
            self._session_locks.pop(upload_id, None)
            self._resume_index.pop((session.owner_key, session.resume_key), None)
            session.part_path.unlink(missing_ok=True)
            session.meta_path.unlink(missing_ok=True)

        expired_completed = [
            upload_id
            for upload_id, completed in self._completed.items()
            if now - completed.completed_at > self.COMPLETED_TTL
        ]
        for upload_id in expired_completed:
            completed = self._completed.pop(upload_id)
            completed.meta_path.unlink(missing_ok=True)


upload_manager = ResumableUploadManager()
