from django.contrib import admin
from django.template.defaultfilters import filesizeformat

from .models import AdminTodoItem, SharedPath, SystemShareSettings, UserReadonlyShare, UserStorageProfile, UserTransferStats


@admin.register(UserStorageProfile)
class UserStorageProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'quota_display', 'used_display', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('used_display', 'created_at', 'updated_at')

    def quota_display(self, obj):
        return filesizeformat(obj.quota_bytes)

    quota_display.short_description = 'Quota'

    def used_display(self, obj):
        return filesizeformat(obj.used_bytes())

    used_display.short_description = 'Used'


@admin.register(SharedPath)
class SharedPathAdmin(admin.ModelAdmin):
    list_display = ('owner', 'target_user', 'relative_path', 'permission', 'updated_at')
    list_filter = ('permission',)
    search_fields = ('owner__username', 'target_user__username', 'relative_path')


@admin.register(UserReadonlyShare)
class UserReadonlyShareAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'path', 'created_at')
    search_fields = ('user__username', 'name', 'path')


@admin.register(UserTransferStats)
class UserTransferStatsAdmin(admin.ModelAdmin):
    list_display = ('user', 'uploaded_display', 'downloaded_display', 'last_upload_at', 'last_download_at', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('updated_at',)

    def uploaded_display(self, obj):
        return filesizeformat(obj.uploaded_bytes)

    uploaded_display.short_description = 'Uploaded'

    def downloaded_display(self, obj):
        return filesizeformat(obj.downloaded_bytes)

    downloaded_display.short_description = 'Downloaded'


@admin.register(SystemShareSettings)
class SystemShareSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_storage_root', 'readonly_storage_root', 'updated_at')


@admin.register(AdminTodoItem)
class AdminTodoItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'owner', 'priority', 'status', 'created_at', 'updated_at')
    list_filter = ('priority', 'status')
    search_fields = ('title', 'description', 'owner__username', 'owner__email')
