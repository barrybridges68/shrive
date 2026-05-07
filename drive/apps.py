from django.apps import AppConfig


class DriveConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'drive'
    verbose_name = 'File Share'

    def ready(self):
        import drive.signals  # noqa: F401
        from .expiry_cleanup import start_expired_link_cleanup_worker

        start_expired_link_cleanup_worker()
