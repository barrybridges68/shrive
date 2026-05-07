from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.db.utils import OperationalError, ProgrammingError
from django.utils.text import slugify


def _get_system_share_settings():
    try:
        from .models import SystemShareSettings

        return SystemShareSettings.objects.filter(pk=1).first()
    except (OperationalError, ProgrammingError):
        return None


def get_user_storage_root() -> Path:
    configured = _get_system_share_settings()
    root_value = configured.user_storage_root if configured and configured.user_storage_root else settings.FILESHARE_STORAGE_ROOT
    root = Path(root_value).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def normalise_relative_path(raw_path: str | None) -> str:
    raw_value = (raw_path or "").strip().strip("/")
    if not raw_value:
        return ""

    candidate = PurePosixPath(raw_value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise SuspiciousFileOperation("Invalid path.")
    return candidate.as_posix()


def build_url(base_url: str, **params: str) -> str:
    filtered = {key: value for key, value in params.items() if value}
    if not filtered:
        return base_url
    separator = '&' if '?' in base_url else '?'
    return f"{base_url}{separator}{urlencode(filtered)}"


def get_user_root(user) -> Path:
    safe_name = slugify(user.username) or "user"
    root = get_user_storage_root() / f"user_{user.pk}_{safe_name}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def delete_user_root(user) -> None:
    safe_name = slugify(user.username) or "user"
    root = get_user_storage_root() / f"user_{user.pk}_{safe_name}"
    if root.exists() and root.is_dir():
        shutil.rmtree(root)


def resolve_within(root: Path, relative_path: str = "") -> Path:
    clean_path = normalise_relative_path(relative_path)
    resolved_root = root.resolve()
    candidate = (resolved_root / clean_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise SuspiciousFileOperation("Invalid path.") from exc
    return candidate


def resolve_user_path(user, relative_path: str = "") -> Path:
    return resolve_within(get_user_root(user), relative_path)


def compute_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size

    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def get_user_usage(user) -> int:
    return compute_size(get_user_root(user))


def has_available_space(user, incoming_size: int) -> bool:
    profile = user.storage_profile
    if profile.quota_bytes <= 0:
        return False
    return get_user_usage(user) + max(incoming_size, 0) <= profile.quota_bytes


def save_uploaded_file(uploaded_file, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb+") as output_handle:
        for chunk in uploaded_file.chunks():
            output_handle.write(chunk)


def delete_entry(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def iter_directory(path: Path) -> list[dict]:
    entries = []
    if not path.exists() or not path.is_dir():
        return entries

    for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "is_dir": child.is_dir(),
                "size": compute_size(child) if child.is_dir() else stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                "path": child,
            }
        )
    return entries


def _build_global_readonly_roots() -> list[dict]:
    configured = _get_system_share_settings()
    if configured is not None:
        configured_roots = []
        seen_slugs = set()
        configured_paths = [line.strip() for line in (configured.readonly_storage_root or '').splitlines() if line.strip()]
        for index, raw_path in enumerate(configured_paths, start=1):
            configured_path = Path(raw_path).expanduser()
            if not configured_path.exists() or not configured_path.is_dir():
                continue

            resolved_path = configured_path.resolve()
            root_name = resolved_path.name or f"Read-only share {index}"
            base_slug = slugify(root_name) or f"read-only-share-{index}"
            slug = base_slug
            suffix = 2
            while slug in seen_slugs:
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            seen_slugs.add(slug)

            configured_roots.append(
                {
                    "name": root_name,
                    "slug": slug,
                    "path": resolved_path,
                }
            )

        return configured_roots

    roots = []
    for index, item in enumerate(getattr(settings, "FILESHARE_READONLY_ROOTS", []), start=1):
        if isinstance(item, dict):
            name = item.get("name") or f"Library {index}"
            slug = item.get("slug") or slugify(name) or f"library-{index}"
            raw_path = item.get("path")
        else:
            name = f"Library {index}"
            slug = f"library-{index}"
            raw_path = item

        if not raw_path:
            continue

        path = Path(raw_path).expanduser()
        if not path.exists():
            continue

        roots.append({"name": name, "slug": slug, "path": path.resolve()})
    return roots


def _build_user_readonly_roots(user, seen_slugs: set[str]) -> list[dict]:
    try:
        from .models import UserReadonlyShare

        queryset = UserReadonlyShare.objects.filter(user=user).order_by('name', 'path')
    except (OperationalError, ProgrammingError):
        return []

    user_roots = []
    for index, entry in enumerate(queryset, start=1):
        path = Path(entry.path).expanduser()
        if not path.exists() or not path.is_dir():
            continue

        resolved_path = path.resolve()
        root_name = entry.name or resolved_path.name or f"User read-only share {index}"
        base_slug = slugify(f"u{user.pk}-{root_name}") or f"u{user.pk}-read-only-share-{index}"
        slug = base_slug
        suffix = 2
        while slug in seen_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        seen_slugs.add(slug)

        user_roots.append(
            {
                "name": root_name,
                "slug": slug,
                "path": resolved_path,
            }
        )

    return user_roots


def get_readonly_roots(user=None) -> list[dict]:
    global_roots = _build_global_readonly_roots()
    if not user:
        return global_roots

    seen_slugs = {root['slug'] for root in global_roots}
    return global_roots + _build_user_readonly_roots(user, seen_slugs)


def get_readonly_root(slug: str, user=None) -> dict:
    for root in get_readonly_roots(user):
        if root["slug"] == slug:
            return root
    raise KeyError(slug)
