from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.contrib.auth.models import User
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from secrets import token_hex
from urllib.parse import quote_plus

from .audit import audit_event
from .models import UserStorageProfile, UserTransferStats
from .storage import delete_user_root


def build_random_github_style_avatar_url(user: User) -> str:
    seed = quote_plus(f'{user.username}-{token_hex(8)}')
    return f'https://api.dicebear.com/9.x/identicon/svg?seed={seed}'


@receiver(post_save, sender=User)
def ensure_storage_profile(sender, instance, created, **kwargs):
    if created:
        UserStorageProfile.objects.get_or_create(
            user=instance,
            defaults={
                "quota_bytes": settings.FILESHARE_DEFAULT_QUOTA_BYTES,
                "avatar_url": build_random_github_style_avatar_url(instance),
            },
        )
        UserTransferStats.objects.get_or_create(user=instance)


@receiver(post_delete, sender=User)
def cleanup_user_storage(sender, instance, **kwargs):
    delete_user_root(instance)


@receiver(user_logged_in)
def audit_user_logged_in(sender, request, user, **kwargs):
    audit_event('auth.login', request=request, user=user, success=True)


@receiver(user_logged_out)
def audit_user_logged_out(sender, request, user, **kwargs):
    audit_event('auth.logout', request=request, user=user, success=True)


@receiver(user_login_failed)
def audit_user_login_failed(sender, credentials, request, **kwargs):
    audit_event(
        'auth.login_failed',
        request=request,
        success=False,
        username=(credentials or {}).get('username'),
    )
