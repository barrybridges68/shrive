import logging
import os
import threading

from django.apps import apps
from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.utils import timezone

from .audit import audit_event


logger = logging.getLogger(__name__)
_worker_started = False
_worker_lock = threading.Lock()


def _cleanup_interval_seconds() -> int:
    configured = getattr(settings, 'FILESHARE_EXPIRED_LINK_CLEANUP_INTERVAL_SECONDS', 60)
    try:
        interval = int(configured)
    except (TypeError, ValueError):
        interval = 60
    return max(interval, 1)


def _background_cleanup_enabled() -> bool:
    if not getattr(settings, 'FILESHARE_ENABLE_EXPIRED_LINK_CLEANUP', True):
        return False

    # Prevent duplicate threads from Django's dev autoreloader parent process.
    if getattr(settings, 'DEBUG', False) and os.environ.get('RUN_MAIN') != 'true':
        return False

    return True


def prune_expired_links_once() -> None:
    now = timezone.now()
    shared_path_model = apps.get_model('drive', 'SharedPath')
    group_shared_path_model = apps.get_model('drive', 'GroupSharedPath')
    public_share_link_model = apps.get_model('drive', 'PublicShareLink')

    expired_shared_queryset = shared_path_model.objects.filter(expires_at__isnull=False, expires_at__lte=now)
    expired_group_queryset = group_shared_path_model.objects.filter(expires_at__isnull=False, expires_at__lte=now)
    expired_public_queryset = public_share_link_model.objects.filter(expires_at__isnull=False, expires_at__lte=now)

    expired_shared_count = expired_shared_queryset.count()
    expired_group_count = expired_group_queryset.count()
    expired_public_count = expired_public_queryset.count()

    if expired_shared_count:
        expired_shared_queryset.delete()
    if expired_group_count:
        expired_group_queryset.delete()
    if expired_public_count:
        expired_public_queryset.delete()

    total_deleted = expired_shared_count + expired_group_count + expired_public_count
    if total_deleted:
        audit_event(
            'storage.expired_links_pruned',
            shared_link_count=expired_shared_count,
            group_link_count=expired_group_count,
            public_link_count=expired_public_count,
            total_count=total_deleted,
        )


def _cleanup_worker_loop(interval_seconds: int) -> None:
    while True:
        try:
            prune_expired_links_once()
        except (OperationalError, ProgrammingError):
            # Database may be unavailable during startup/migrations.
            pass
        except Exception:
            logger.exception('Expired link cleanup worker failed during execution.')

        threading.Event().wait(interval_seconds)


def start_expired_link_cleanup_worker() -> None:
    global _worker_started

    if not _background_cleanup_enabled():
        return

    with _worker_lock:
        if _worker_started:
            return

        interval_seconds = _cleanup_interval_seconds()
        worker = threading.Thread(
            target=_cleanup_worker_loop,
            args=(interval_seconds,),
            name='fileshare-expired-link-cleaner',
            daemon=True,
        )
        worker.start()
        _worker_started = True
