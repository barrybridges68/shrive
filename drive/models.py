from django.conf import settings
from django.contrib.auth.models import Group, User
from django.db import models


class UserStorageProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='storage_profile')
    quota_bytes = models.PositiveBigIntegerField(default=settings.FILESHARE_DEFAULT_QUOTA_BYTES)
    avatar_url = models.URLField(max_length=500, blank=True, default='')
    webdav_api_key_hash = models.CharField(max_length=255, blank=True, default='')
    webdav_api_key_value = models.CharField(max_length=128, blank=True, default='')
    webdav_api_key_created_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f"{self.user.username} storage profile"

    def used_bytes(self):
        from .storage import get_user_usage

        return get_user_usage(self.user)


class UserTransferStats(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='transfer_stats')
    uploaded_bytes = models.PositiveBigIntegerField(default=0)
    downloaded_bytes = models.PositiveBigIntegerField(default=0)
    last_upload_at = models.DateTimeField(null=True, blank=True)
    last_download_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f"{self.user.username} transfer stats"


class UserReadonlyShare(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='readonly_shares')
    name = models.CharField(max_length=255)
    path = models.CharField(max_length=1024)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['user__username', 'name', 'path']

    def __str__(self):
        return f"{self.user.username} readonly share: {self.name}"


class AdminTodoItem(models.Model):
    class Priority(models.IntegerChoices):
        LOW = 1, 'Low'
        MEDIUM = 2, 'Medium'
        HIGH = 3, 'High'
        URGENT = 4, 'Urgent'

    class Status(models.TextChoices):
        TODO = 'todo', 'To do'
        IN_PROGRESS = 'in_progress', 'In progress'
        BLOCKED = 'blocked', 'Blocked'
        PAUSED = 'paused', 'Paused'
        DONE = 'done', 'Done'

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_todo_items')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', '-priority', 'created_at']

    def __str__(self):
        return self.title


class SharedPath(models.Model):
    class Permission(models.TextChoices):
        VIEW = 'view', 'View only'
        EDIT = 'edit', 'Edit'

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shares_created')
    target_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shares_received')
    relative_path = models.CharField(max_length=500)
    permission = models.CharField(max_length=12, choices=Permission.choices, default=Permission.VIEW)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['owner__username', 'target_user__username', 'relative_path']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'target_user', 'relative_path'],
                name='drive_unique_shared_path',
            )
        ]

    def __str__(self):
        return f"{self.owner.username} -> {self.target_user.username}: {self.relative_path}"


class GroupSharedPath(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='group_shares_created')
    target_group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='group_shares_received')
    relative_path = models.CharField(max_length=500)
    permission = models.CharField(max_length=12, choices=SharedPath.Permission.choices, default=SharedPath.Permission.VIEW)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['owner__username', 'target_group__name', 'relative_path']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'target_group', 'relative_path'],
                name='drive_unique_group_shared_path',
            )
        ]

    def __str__(self):
        return f"{self.owner.username} -> group:{self.target_group.name}: {self.relative_path}"


class PublicShareLink(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='public_shares_created')
    relative_path = models.CharField(max_length=500)
    token = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['owner__username', 'relative_path']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'relative_path'],
                name='drive_unique_public_share_path',
            )
        ]

    def __str__(self):
        return f"{self.owner.username} public: {self.relative_path}"


class UploadShareLink(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='upload_links_created')
    relative_path = models.CharField(max_length=500)
    token = models.CharField(max_length=64, unique=True)
    uploader_email = models.EmailField(max_length=320)
    recipient_label = models.CharField(max_length=255)
    expires_at = models.DateTimeField(null=True, blank=True)
    uploaded_files_count = models.PositiveIntegerField(default=0)
    last_uploaded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['owner__username', 'relative_path', 'uploader_email']

    def __str__(self):
        return f"{self.owner.username} upload: {self.relative_path}"


class SystemShareSettings(models.Model):
    user_storage_root = models.CharField(max_length=1024, blank=True)
    readonly_storage_root = models.TextField(blank=True)
    public_share_base_url = models.URLField(max_length=500, blank=True)
    public_share_link_lifetime = models.CharField(max_length=16, default='never')
    timezone_name = models.CharField(max_length=64, default=settings.TIME_ZONE)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'System share settings'
        verbose_name_plural = 'System share settings'

    def __str__(self):
        return 'System share settings'

    @classmethod
    def get_solo(cls):
        return cls.objects.get_or_create(pk=1)[0]
