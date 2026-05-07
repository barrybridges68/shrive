from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from .models import SystemShareSettings


class SystemTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone_name = settings.TIME_ZONE
        try:
            configured_timezone = (
                SystemShareSettings.objects.filter(pk=1)
                .values_list('timezone_name', flat=True)
                .first()
            )
            if configured_timezone:
                timezone_name = configured_timezone
        except (OperationalError, ProgrammingError):
            # During migrations or first boot, settings table may not be available.
            timezone_name = settings.TIME_ZONE

        try:
            timezone.activate(ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            timezone.activate(ZoneInfo(settings.TIME_ZONE))

        return self.get_response(request)
