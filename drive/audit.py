import json
import logging
from datetime import datetime, timezone


audit_logger = logging.getLogger('fileshare.audit')


def _stringify(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_stringify(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _stringify(item) for key, item in value.items()}
    return str(value)


def _extract_actor(request=None, user=None):
    actor = user or getattr(request, 'user', None)
    if actor and getattr(actor, 'is_authenticated', False):
        return {
            'username': actor.get_username(),
            'user_id': actor.pk,
        }
    return {
        'username': None,
        'user_id': None,
    }


def _extract_request_meta(request):
    if not request:
        return {}

    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    ip_address = forwarded_for.split(',')[0].strip() if forwarded_for else request.META.get('REMOTE_ADDR')
    return {
        'method': request.method,
        'path': request.get_full_path(),
        'ip_address': ip_address,
    }


def audit_event(event, *, request=None, user=None, success=True, **details):
    payload = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'event': event,
        'success': bool(success),
    }
    payload.update(_extract_actor(request=request, user=user))
    payload.update(_extract_request_meta(request))
    payload['details'] = _stringify(details)

    audit_logger.info(json.dumps(payload, sort_keys=True, ensure_ascii=True))
