from collections import deque
import base64
import binascii
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from io import BytesIO
import mimetypes
from pathlib import Path, PurePosixPath
import shutil
from tempfile import SpooledTemporaryFile
from urllib.parse import quote, unquote, urlparse
import xml.etree.ElementTree as ET
import zipfile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import Group, User
from django.core import signing
from django.core.mail import send_mail
from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.validators import validate_email
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.utils.crypto import get_random_string
from django.views.decorators.csrf import csrf_exempt

try:
    from PIL import Image, UnidentifiedImageError

    PILLOW_AVAILABLE = True
except ImportError:
    Image = None
    UnidentifiedImageError = Exception
    PILLOW_AVAILABLE = False

from .forms import (
    AdminGroupCreateForm,
    AdminGroupRenameForm,
    AdminQuotaUpdateForm,
    AdminShareRootSettingsForm,
    AdminTodoItemForm,
    AdminUserCreateForm,
    FolderCreateForm,
    InitialSetupForm,
    ShareGrantForm,
    UploadForm,
    allowed_share_targets_queryset,
)
from .audit import audit_event
from .models import AdminTodoItem, GroupSharedPath, PublicShareLink, SharedPath, SystemShareSettings, UploadShareLink, UserReadonlyShare, UserStorageProfile, UserTransferStats
from .storage import (
    build_url,
    compute_size,
    delete_entry,
    get_readonly_root,
    get_readonly_roots,
    get_user_root,
    get_user_storage_root,
    get_user_usage,
    has_available_space,
    iter_directory,
    normalise_relative_path,
    resolve_user_path,
    resolve_within,
    save_uploaded_file,
)


def extract_configured_readonly_paths(raw_value: str) -> list[str]:
    return [line.strip() for line in (raw_value or '').splitlines() if line.strip()]


def initial_setup_complete() -> bool:
    return User.objects.filter(is_superuser=True).exists()


def apply_form_styles(form):
    for field in form.fields.values():
        field.widget.attrs.setdefault('class', 'form-control')


def append_form_errors(request, form):
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)


def record_user_transfer(user, *, uploaded_bytes: int = 0, downloaded_bytes: int = 0) -> None:
    if not user or not user.is_authenticated:
        return

    upload_amount = max(int(uploaded_bytes or 0), 0)
    download_amount = max(int(downloaded_bytes or 0), 0)
    if upload_amount == 0 and download_amount == 0:
        return

    stats, _ = UserTransferStats.objects.get_or_create(user=user)
    timestamp = datetime.now(timezone.utc)

    if upload_amount:
        stats.uploaded_bytes += upload_amount
        stats.last_upload_at = timestamp
    if download_amount:
        stats.downloaded_bytes += download_amount
        stats.last_download_at = timestamp
    stats.save()


def active_shares_queryset():
    now = datetime.now(timezone.utc)
    return SharedPath.objects.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def active_group_shares_queryset():
    now = datetime.now(timezone.utc)
    return GroupSharedPath.objects.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def active_public_shares_queryset():
    now = datetime.now(timezone.utc)
    return PublicShareLink.objects.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def active_upload_links_queryset():
    now = datetime.now(timezone.utc)
    return UploadShareLink.objects.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def resolve_public_share_expires_at(lifetime: str):
    value = (lifetime or 'never').strip().lower()
    now = datetime.now(timezone.utc)
    if value == 'day':
        return now + timedelta(days=1)
    if value == 'week':
        return now + timedelta(weeks=1)
    if value == 'month':
        return now + timedelta(days=30)
    return None


def resolve_upload_link_expires_at(request):
    expires_in_hours = (request.POST.get('expires_in_hours') or '').strip()
    expires_at_value = (request.POST.get('expires_at') or '').strip()

    if expires_in_hours and expires_at_value:
        raise ValidationError('Choose either an expiry duration or an exact expiry time, not both.')

    resolved_expires_at = None
    if expires_in_hours:
        try:
            duration_hours = float(expires_in_hours)
        except ValueError as exc:
            raise ValidationError('Select a valid expiry duration.') from exc

        if duration_hours <= 0:
            raise ValidationError('Expiry duration must be greater than zero.')

        resolved_expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
    elif expires_at_value:
        try:
            parsed_expires_at = datetime.strptime(expires_at_value, '%Y-%m-%dT%H:%M')
        except ValueError as exc:
            raise ValidationError('Enter a valid expiry time.') from exc

        resolved_expires_at = dj_timezone.make_aware(parsed_expires_at, dj_timezone.get_current_timezone())

    if resolved_expires_at and resolved_expires_at <= dj_timezone.now():
        raise ValidationError('Expiry must be in the future.')

    return resolved_expires_at


def make_path_token(relative_path: str, scope_key: str) -> str:
    return signing.dumps({'path': relative_path, 'scope': scope_key}, salt='drive.path-token')


def resolve_path_token(token: str | None, scope_key: str) -> str:
    if not token:
        raise SuspiciousFileOperation('Missing path token.')

    try:
        payload = signing.loads(token, salt='drive.path-token')
    except signing.BadSignature as exc:
        raise SuspiciousFileOperation('Invalid path token.') from exc

    if payload.get('scope') != scope_key:
        raise SuspiciousFileOperation('Invalid path scope.')

    return normalise_relative_path(payload.get('path'))


def safe_leaf_name(raw_name: str) -> str:
    leaf_name = Path(raw_name or '').name.strip()
    if not leaf_name or leaf_name in {'.', '..'}:
        raise SuspiciousFileOperation('Invalid file name.')
    return leaf_name


def safe_upload_relative_path(raw_name: str) -> str:
    candidate_raw = (raw_name or '').replace('\\', '/').strip().strip('/')
    if not candidate_raw:
        raise SuspiciousFileOperation('Invalid file name.')

    candidate = PurePosixPath(candidate_raw)
    if candidate.is_absolute() or any(part in {'', '.', '..'} for part in candidate.parts):
        raise SuspiciousFileOperation('Invalid file name.')
    return candidate.as_posix()


CLIPBOARD_SESSION_KEY = 'fileshare.clipboard'


def get_clipboard_entries(request) -> list[dict]:
    raw_entries = request.session.get(CLIPBOARD_SESSION_KEY, [])
    valid_entries = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        path_value = str(item.get('path') or '').strip()
        if not path_value:
            continue
        operation = str(item.get('operation') or 'copy').lower()
        if operation not in {'copy', 'cut'}:
            operation = 'copy'
        branch_root = str(item.get('branch_root') or '').strip()
        valid_entries.append(
            {
                'path': path_value,
                'name': str(item.get('name') or ''),
                'operation': operation,
                'branch_root': branch_root,
            }
        )
    return valid_entries


def set_clipboard_entries(request, entries: list[dict]) -> None:
    cleaned_entries = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        path_value = str(item.get('path') or '').strip()
        if not path_value:
            continue
        operation = str(item.get('operation') or 'copy').lower()
        if operation not in {'copy', 'cut'}:
            operation = 'copy'
        branch_root = str(item.get('branch_root') or '').strip()
        cleaned_entries.append(
            {
                'path': path_value,
                'name': str(item.get('name') or ''),
                'operation': operation,
                'branch_root': branch_root,
            }
        )
    request.session[CLIPBOARD_SESSION_KEY] = cleaned_entries
    request.session.modified = True


def make_copy_name(original_name: str, index: int) -> str:
    stem = Path(original_name).stem
    suffix = Path(original_name).suffix
    if not stem and suffix:
        stem = original_name
        suffix = ''

    if index <= 1:
        return f'{stem} - Copy{suffix}'
    return f'{stem} - Copy ({index}){suffix}'


def next_copy_destination(current_dir: Path, source_name: str) -> Path:
    candidate = resolve_within(current_dir, source_name)
    if not candidate.exists():
        return candidate

    copy_index = 1
    while True:
        candidate_name = make_copy_name(source_name, copy_index)
        candidate = resolve_within(current_dir, candidate_name)
        if not candidate.exists():
            return candidate
        copy_index += 1


def copy_entry(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination)
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def path_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def handle_clipboard_actions(
    request,
    *,
    acting_user,
    scope_root,
    scope_key: str,
    current_dir: Path,
    destination_owner=None,
    can_paste: bool,
) -> bool:
    action = request.POST.get('action')

    if action in {'copy_selection', 'cut_selection'}:
        is_cut = action == 'cut_selection'
        clipboard_operation = 'cut' if is_cut else 'copy'
        raw_tokens = request.POST.getlist('path_tokens')
        if not raw_tokens and request.POST.get('path_token'):
            raw_tokens = [request.POST.get('path_token')]

        if not raw_tokens:
            messages.error(request, f'Select at least one item to {clipboard_operation}.')
            return True

        selected_entries = []
        invalid_count = 0
        missing_count = 0

        for token in raw_tokens:
            try:
                relative_path = resolve_path_token(token, scope_key)
                source_path = resolve_within(scope_root, relative_path)
            except (SuspiciousFileOperation, Http404):
                invalid_count += 1
                continue

            if source_path == scope_root or not source_path.exists():
                missing_count += 1
                continue

            selected_entries.append(
                {
                    'path': str(source_path),
                    'name': source_path.name,
                    'operation': clipboard_operation,
                    'branch_root': str(scope_root.resolve()),
                }
            )

        if not selected_entries:
            messages.error(request, f'No valid items were added to the {clipboard_operation} clipboard.')
            return True

        set_clipboard_entries(request, selected_entries)
        audit_event(
            'storage.clipboard_cut' if is_cut else 'storage.clipboard_copy',
            request=request,
            user=acting_user,
            copied_count=len(selected_entries),
            invalid_count=invalid_count,
            missing_count=missing_count,
        )
        if is_cut:
            messages.success(request, f'Cut {len(selected_entries)} item(s). Paste to move them.')
        else:
            messages.success(request, f'Copied {len(selected_entries)} item(s) to clipboard.')
        if invalid_count:
            messages.error(request, f'{invalid_count} selected item(s) were invalid and were skipped.')
        if missing_count:
            messages.warning(request, f'{missing_count} selected item(s) no longer exist and were skipped.')
        return True

    if action == 'paste_clipboard':
        if not can_paste or destination_owner is None:
            messages.error(request, 'You do not have permission to paste into this location.')
            return True

        clipboard_entries = get_clipboard_entries(request)
        if not clipboard_entries:
            messages.error(request, 'Clipboard is empty. Copy something first.')
            return True

        pasted_count = 0
        missing_count = 0
        blocked_count = 0
        branch_blocked_count = 0
        quota_blocked_count = 0
        failed_count = 0
        same_folder_count = 0
        copied_bytes = 0
        pasted_copy_count = 0
        pasted_cut_count = 0
        has_cut_entries = False
        remaining_entries = []

        for item in clipboard_entries:
            source = Path(item['path'])
            operation = item.get('operation', 'copy')
            is_cut = operation == 'cut'
            has_cut_entries = has_cut_entries or is_cut
            keep_in_clipboard = not is_cut

            if is_cut:
                source_branch_root = str(item.get('branch_root') or '').strip()
                if source_branch_root:
                    try:
                        branch_root = Path(source_branch_root).resolve()
                    except OSError:
                        branch_root = None
                    if branch_root and not path_within_root(current_dir, branch_root):
                        branch_blocked_count += 1
                        keep_in_clipboard = True
                        remaining_entries.append(item)
                        continue

            if not source.exists():
                missing_count += 1
                keep_in_clipboard = is_cut
                if keep_in_clipboard:
                    remaining_entries.append(item)
                continue

            if source.is_dir() and (current_dir == source or current_dir.is_relative_to(source)):
                blocked_count += 1
                keep_in_clipboard = is_cut
                if keep_in_clipboard:
                    remaining_entries.append(item)
                continue

            if is_cut and source.parent == current_dir:
                same_folder_count += 1
                keep_in_clipboard = True
                remaining_entries.append(item)
                continue

            required_size = compute_size(source)
            needs_quota_check = True
            if is_cut and path_within_root(source, get_user_root(destination_owner)):
                needs_quota_check = False

            if needs_quota_check and not has_available_space(destination_owner, required_size):
                quota_blocked_count += 1
                keep_in_clipboard = is_cut
                if keep_in_clipboard:
                    remaining_entries.append(item)
                continue

            destination = next_copy_destination(current_dir, source.name)
            try:
                if is_cut:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(destination))
                else:
                    copy_entry(source, destination)
            except OSError:
                failed_count += 1
                keep_in_clipboard = is_cut
                if keep_in_clipboard:
                    remaining_entries.append(item)
                continue

            pasted_count += 1
            copied_bytes += required_size
            if is_cut:
                pasted_cut_count += 1
            else:
                pasted_copy_count += 1

            if keep_in_clipboard:
                remaining_entries.append(item)

        if has_cut_entries:
            set_clipboard_entries(request, remaining_entries)

        if pasted_count:
            record_user_transfer(acting_user, uploaded_bytes=copied_bytes)
            audit_event(
                'storage.paste_clipboard',
                request=request,
                user=acting_user,
                pasted_count=pasted_count,
                pasted_copy_count=pasted_copy_count,
                pasted_cut_count=pasted_cut_count,
                missing_count=missing_count,
                blocked_count=blocked_count,
                branch_blocked_count=branch_blocked_count,
                same_folder_count=same_folder_count,
                quota_blocked_count=quota_blocked_count,
                failed_count=failed_count,
                bytes=copied_bytes,
            )
            messages.success(request, f'Pasted {pasted_count} item(s).')
        else:
            messages.error(request, 'No clipboard items were pasted.')

        if missing_count:
            messages.warning(request, f'{missing_count} clipboard item(s) no longer exist and were skipped.')
        if blocked_count:
            messages.error(request, f'{blocked_count} item(s) cannot be pasted into their own child folders.')
        if branch_blocked_count:
            messages.error(request, f'{branch_blocked_count} cut item(s) cannot be pasted outside their original branch.')
        if same_folder_count:
            messages.warning(request, f'{same_folder_count} cut item(s) are already in this folder and were skipped.')
        if quota_blocked_count:
            messages.error(request, f'{quota_blocked_count} item(s) were skipped because they exceed available quota.')
        if failed_count:
            messages.error(request, f'{failed_count} item(s) could not be copied due to file system errors.')
        return True

    return False


def shell_context(request) -> dict:
    readonly_roots = get_readonly_roots(request.user) if request.user.is_authenticated else get_readonly_roots()
    todo_enabled = bool(getattr(settings, 'FILESHARE_ENABLE_ADMIN_TODO', True))
    clipboard_count = len(get_clipboard_entries(request)) if hasattr(request, 'session') else 0
    if not request.user.is_authenticated:
        return {
            'incoming_share_count': 0,
            'admin_todo_count': 0,
            'admin_todo_enabled': todo_enabled,
            'user_avatar_url': '',
            'readonly_root_count': len(readonly_roots),
            'clipboard_count': clipboard_count,
            'quota_bytes': None,
            'used_bytes': None,
            'usage_percent': 0,
            'show_quota': False,
        }

    profile, _ = UserStorageProfile.objects.get_or_create(
        user=request.user,
        defaults={'quota_bytes': settings.FILESHARE_DEFAULT_QUOTA_BYTES},
    )
    used_bytes = get_user_usage(request.user)
    usage_percent = int((used_bytes / profile.quota_bytes) * 100) if profile.quota_bytes else 0
    incoming_share_count = (
        active_shares_queryset().filter(target_user=request.user).count()
        + active_group_shares_queryset().filter(target_group__in=request.user.groups.all()).count()
    )
    return {
        'incoming_share_count': incoming_share_count,
        'admin_todo_count': AdminTodoItem.objects.count() if request.user.is_staff and todo_enabled else 0,
        'admin_todo_enabled': todo_enabled,
        'user_avatar_url': profile.avatar_url,
        'readonly_root_count': len(readonly_roots),
        'clipboard_count': clipboard_count,
        'quota_bytes': profile.quota_bytes,
        'used_bytes': used_bytes,
        'usage_percent': min(usage_percent, 100),
        'show_quota': True,
    }


def render_shell(request, template_name: str, context: dict):
    merged_context = shell_context(request)
    merged_context.update(context)
    return render(request, template_name, merged_context)


def make_breadcrumbs(root_label: str, base_url: str, current_path: str) -> list[dict]:
    breadcrumbs = [{'label': root_label, 'url': base_url}]
    if not current_path:
        return breadcrumbs

    partial = []
    for part in current_path.split('/'):
        partial.append(part)
        breadcrumbs.append({'label': part, 'url': build_url(base_url, path='/'.join(partial))})
    return breadcrumbs


def parent_url(base_url: str, current_path: str) -> str | None:
    if not current_path:
        return None
    parent = PurePosixPath(current_path).parent
    if str(parent) == '.':
        return base_url
    return build_url(base_url, path=parent.as_posix())


def classify_file_icon(path: Path, is_dir: bool) -> tuple[str, str]:
    if is_dir:
        return 'bi-folder-fill', 'folder'

    suffix = path.suffix.lower()
    mime_type, _ = mimetypes.guess_type(path.name)

    if suffix == '.pdf':
        return 'bi-filetype-pdf', 'file-pdf'
    if suffix in {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz'}:
        return 'bi-file-earmark-zip', 'file-archive'
    if suffix in {'.xls', '.xlsx', '.ods', '.csv'}:
        return 'bi-file-earmark-spreadsheet', 'file-sheet'
    if suffix in {'.ppt', '.pptx', '.odp', '.key'}:
        return 'bi-file-earmark-slides', 'file-slides'
    if suffix in {'.doc', '.docx', '.odt', '.rtf'}:
        return 'bi-file-earmark-richtext', 'file-doc'
    if suffix in {'.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.html', '.css', '.scss', '.java', '.c', '.cpp', '.cs', '.go', '.rs', '.php', '.rb', '.sh', '.md', '.yml', '.yaml', '.xml'}:
        return 'bi-file-earmark-code', 'file-code'

    if mime_type:
        if mime_type.startswith('image/'):
            return 'bi-file-earmark-image', 'file-image'
        if mime_type.startswith('video/'):
            return 'bi-file-earmark-play', 'file-video'
        if mime_type.startswith('audio/'):
            return 'bi-file-earmark-music', 'file-audio'
        if mime_type.startswith('text/'):
            return 'bi-file-earmark-text', 'file-text'

    return 'bi-file-earmark-fill', 'file'


def can_edit_text_file(path: Path) -> bool:
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type and mime_type.startswith('text/'):
        return True

    # Markdown files should always open in the in-browser editor.
    if path.suffix.lower() == '.md':
        return True

    configured_extensions = {
        extension.lower() if str(extension).startswith('.') else f'.{str(extension).lower()}'
        for extension in getattr(settings, 'FILESHARE_TEXT_EDITOR_EXTENSIONS', [])
        if str(extension).strip()
    }
    return path.suffix.lower() in configured_extensions


def read_text_file(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace')


def save_text_file(path: Path, content: str) -> None:
    path.write_text(content, encoding='utf-8')


def render_text_editor(
    request,
    *,
    path: Path,
    active_nav: str,
    page_title: str,
    page_description: str,
    breadcrumbs: list[dict],
    back_url: str,
    can_edit: bool,
):
    if request.method == 'POST':
        if not can_edit:
            raise Http404('This file is read only.')
        save_text_file(path, request.POST.get('content', ''))
        audit_event('file.edit_text', request=request, file_path=str(path), success=True)
        messages.success(request, 'File saved.')
        return redirect(request.get_full_path())

    return render_shell(
        request,
        'drive/text_editor.html',
        {
            'active_nav': active_nav,
            'page_title': page_title,
            'page_description': page_description,
            'breadcrumbs': breadcrumbs,
            'back_url': back_url,
            'file_name': path.name,
            'file_content': read_text_file(path),
            'can_edit_text': can_edit,
        },
    )


def serialise_entries(
    entries,
    root_path,
    browse_base_url,
    download_base_url,
    share_records_by_path=None,
    *,
    scope_key: str,
    owner_scope_key: str | None = None,
):
    share_records_by_path = share_records_by_path or {}
    serialised = []
    owner_scope = owner_scope_key or scope_key
    for entry in entries:
        relative_path = entry['path'].relative_to(root_path).as_posix()
        share_records = share_records_by_path.get(relative_path, [])
        icon_name, icon_tone = classify_file_icon(entry['path'], entry['is_dir'])
        serialised.append(
            {
                'name': entry['name'],
                'is_dir': entry['is_dir'],
                'size': entry['size'],
                'modified_at': entry['modified_at'],
                'icon_name': icon_name,
                'icon_tone': icon_tone,
                'scope_path_token': make_path_token(relative_path, scope_key),
                'owner_path_token': make_path_token(relative_path, owner_scope),
                'browse_url': build_url(browse_base_url, path=relative_path) if entry['is_dir'] else None,
                'download_url': build_url(download_base_url, path=relative_path),
                'open_url': build_url(download_base_url.replace('/download/', '/open/'), path=relative_path)
                if not entry['is_dir'] and can_open_file(entry['path'])
                else None,
                'thumbnail_url': build_url(download_base_url.replace('/download/', '/thumb/'), path=relative_path)
                if not entry['is_dir'] and can_thumbnail_file(entry['path'])
                else None,
                'share_list': [
                    {
                        'username': share.target_user.username,
                        'permission': share.get_permission_display(),
                        'expires_at': share.expires_at,
                    }
                    for share in share_records
                ],
                'share_records': share_records,
            }
        )
    return serialised


def handle_write_actions(request, *, acting_user, storage_owner, scope_root, current_dir) -> bool:
    action = request.POST.get('action')
    scope_key = f'scope:{storage_owner.pk}'

    if action == 'create_folder':
        form = FolderCreateForm(request.POST)
        if form.is_valid():
            new_folder = resolve_within(current_dir, form.cleaned_data['name'])
            if new_folder.exists():
                audit_event(
                    'storage.create_folder',
                    request=request,
                    user=acting_user,
                    success=False,
                    storage_owner=storage_owner.username,
                    folder=str(new_folder),
                    reason='already_exists',
                )
                messages.error(request, 'A file or folder with that name already exists.')
            else:
                new_folder.mkdir(parents=True, exist_ok=False)
                audit_event(
                    'storage.create_folder',
                    request=request,
                    user=acting_user,
                    storage_owner=storage_owner.username,
                    folder=str(new_folder),
                )
                messages.success(request, 'Folder created.')
        else:
            append_form_errors(request, form)
        return True

    if action == 'create_text_file':
        try:
            file_name = safe_leaf_name(request.POST.get('name'))
        except SuspiciousFileOperation:
            messages.error(request, 'Enter a valid file name.')
            return True

        if not Path(file_name).suffix:
            file_name = f'{file_name}.txt'

        new_file = resolve_within(current_dir, file_name)
        if new_file.exists():
            audit_event(
                'storage.create_text_file',
                request=request,
                user=acting_user,
                success=False,
                storage_owner=storage_owner.username,
                file_path=str(new_file),
                reason='already_exists',
            )
            messages.error(request, 'A file or folder with that name already exists.')
        else:
            try:
                new_file.write_text('', encoding='utf-8')
            except OSError:
                audit_event(
                    'storage.create_text_file',
                    request=request,
                    user=acting_user,
                    success=False,
                    storage_owner=storage_owner.username,
                    file_path=str(new_file),
                    reason='os_error',
                )
                messages.error(request, 'The text file could not be created.')
            else:
                audit_event(
                    'storage.create_text_file',
                    request=request,
                    user=acting_user,
                    storage_owner=storage_owner.username,
                    file_path=str(new_file),
                )
                messages.success(request, 'Text file created.')
        return True

    if action == 'upload':
        uploaded_files = []
        for key in request.FILES.keys():
            if key == 'file' or key == 'folder' or key.startswith('file') or key.startswith('folder'):
                files_for_key = request.FILES.getlist(key)
                hinted_paths = request.POST.getlist(f'upload_path_{key}')
                for index, uploaded_file in enumerate(files_for_key):
                    path_hint = hinted_paths[index] if index < len(hinted_paths) else None
                    uploaded_files.append((uploaded_file, path_hint))
        if not uploaded_files:
            form = UploadForm(request.POST, request.FILES)
            append_form_errors(request, form)
            return True

        is_single_upload = len(uploaded_files) == 1
        for uploaded_file, path_hint in uploaded_files:
            try:
                upload_relative_path = safe_upload_relative_path(path_hint or uploaded_file.name)
            except SuspiciousFileOperation:
                if is_single_upload:
                    messages.error(request, 'Invalid file name.')
                else:
                    messages.error(request, f'Skipped invalid file name: {uploaded_file.name}')
                continue

            destination = resolve_within(current_dir, upload_relative_path)
            if destination.exists():
                if is_single_upload:
                    messages.error(request, 'A file with that name already exists.')
                else:
                    messages.error(request, f'{upload_relative_path}: a file with that name already exists.')
                continue

            if destination.parent.exists() and not destination.parent.is_dir():
                if is_single_upload:
                    messages.error(request, 'Parent path is not a folder.')
                else:
                    messages.error(request, f'{upload_relative_path}: parent path is not a folder.')
                continue

            if not has_available_space(storage_owner, uploaded_file.size):
                if is_single_upload:
                    messages.error(request, 'Upload would exceed the quota assigned to this storage space.')
                else:
                    messages.error(request, f'{upload_relative_path}: upload would exceed the quota assigned to this storage space.')
                continue

            try:
                save_uploaded_file(uploaded_file, destination)
            except OSError:
                if is_single_upload:
                    messages.error(request, 'Upload failed due to an invalid destination path.')
                else:
                    messages.error(request, f'{upload_relative_path}: upload failed due to an invalid destination path.')
                continue

            record_user_transfer(acting_user, uploaded_bytes=uploaded_file.size)
            audit_event(
                'storage.upload',
                request=request,
                user=acting_user,
                storage_owner=storage_owner.username,
                file_path=str(destination),
                bytes=uploaded_file.size,
            )

            if is_single_upload:
                messages.success(request, 'File uploaded.')
            else:
                messages.success(request, f'{upload_relative_path}: uploaded.')
        return True

    if action == 'delete':
        try:
            relative_path = resolve_path_token(request.POST.get('path_token'), scope_key)
        except SuspiciousFileOperation:
            messages.error(request, 'That request could not be validated.')
            return True
        target = resolve_within(scope_root, relative_path)
        if target == scope_root or not target.exists():
            messages.error(request, 'That item could not be found.')
        else:
            delete_entry(target)
            audit_event(
                'storage.delete',
                request=request,
                user=acting_user,
                storage_owner=storage_owner.username,
                path=str(target),
            )
            messages.success(request, 'Item deleted.')
        return True

    if action == 'bulk_delete':
        raw_tokens = request.POST.getlist('path_tokens')
        if not raw_tokens:
            messages.error(request, 'Select at least one item to delete.')
            return True

        deleted_count = 0
        invalid_count = 0
        missing_count = 0

        for token in raw_tokens:
            try:
                relative_path = resolve_path_token(token, scope_key)
            except SuspiciousFileOperation:
                invalid_count += 1
                continue

            try:
                target = resolve_within(scope_root, relative_path)
            except (Http404, SuspiciousFileOperation):
                invalid_count += 1
                continue

            if target == scope_root or not target.exists():
                missing_count += 1
                continue

            delete_entry(target)
            deleted_count += 1

        if deleted_count:
            audit_event(
                'storage.bulk_delete',
                request=request,
                user=acting_user,
                storage_owner=storage_owner.username,
                deleted_count=deleted_count,
                missing_count=missing_count,
                invalid_count=invalid_count,
            )
            messages.success(request, f'{deleted_count} item(s) deleted.')
        if missing_count:
            messages.warning(request, f'{missing_count} item(s) could not be found.')
        if invalid_count:
            messages.error(request, f'{invalid_count} selected item(s) were invalid and were skipped.')
        if deleted_count == 0 and missing_count == 0 and invalid_count == 0:
            messages.error(request, 'No items were deleted.')
        return True

    if action == 'share' and acting_user == storage_owner:
        share_data = request.POST.copy()
        try:
            share_data['relative_path'] = resolve_path_token(request.POST.get('path_token'), scope_key)
        except SuspiciousFileOperation:
            messages.error(request, 'That request could not be validated.')
            return True

        form = ShareGrantForm(acting_user, share_data)
        if form.is_valid():
            if form.cleaned_data.get('target_group'):
                shared_path, created = GroupSharedPath.objects.update_or_create(
                    owner=acting_user,
                    target_group=form.cleaned_data['target_group'],
                    relative_path=form.cleaned_data['relative_path'],
                    defaults={
                        'permission': form.cleaned_data['permission'],
                        'expires_at': form.cleaned_data.get('resolved_expires_at'),
                    },
                )
                target_name = f'group:{form.cleaned_data["target_group"].name}'
            else:
                shared_path, created = SharedPath.objects.update_or_create(
                    owner=acting_user,
                    target_user=form.cleaned_data['target_user'],
                    relative_path=form.cleaned_data['relative_path'],
                    defaults={
                        'permission': form.cleaned_data['permission'],
                        'expires_at': form.cleaned_data.get('resolved_expires_at'),
                    },
                )
                target_name = form.cleaned_data['target_user'].username
            audit_event(
                'sharing.grant',
                request=request,
                user=acting_user,
                owner=acting_user.username,
                target=target_name,
                relative_path=shared_path.relative_path,
                permission=shared_path.permission,
                created=created,
            )
            if created:
                messages.success(request, 'Item shared.')
            else:
                messages.success(request, 'Sharing permissions updated.')
        else:
            append_form_errors(request, form)
        return True

    if action == 'create_public_link' and acting_user == storage_owner:
        try:
            relative_path = resolve_path_token(request.POST.get('path_token'), scope_key)
            target = resolve_within(scope_root, relative_path)
        except (SuspiciousFileOperation, Http404):
            messages.error(request, 'That request could not be validated.')
            return True

        if target == scope_root or not target.exists():
            messages.error(request, 'That item could not be found.')
            return True

        configured_share_settings = SystemShareSettings.get_solo()
        resolved_expires_at = resolve_public_share_expires_at(configured_share_settings.public_share_link_lifetime)

        public_link, created = PublicShareLink.objects.get_or_create(
            owner=acting_user,
            relative_path=relative_path,
            defaults={
                'token': get_random_string(40),
                'expires_at': resolved_expires_at,
            },
        )
        if public_link.expires_at != resolved_expires_at:
            public_link.expires_at = resolved_expires_at
            public_link.save(update_fields=['expires_at', 'updated_at'])

        configured_public_base_url = (configured_share_settings.public_share_base_url or '').strip().rstrip('/')
        public_path = reverse('drive:public-browse', args=[public_link.token])
        public_url = f'{configured_public_base_url}{public_path}' if configured_public_base_url else request.build_absolute_uri(public_path)
        messages.success(request, f'Shareable link: {public_url}')
        audit_event(
            'sharing.public_link_created' if created else 'sharing.public_link_reused',
            request=request,
            user=acting_user,
            relative_path=relative_path,
            token=public_link.token,
        )
        return True

    if action == 'create_upload_link' and acting_user == storage_owner:
        try:
            relative_path = resolve_path_token(request.POST.get('path_token'), scope_key)
            target = resolve_within(scope_root, relative_path)
        except (SuspiciousFileOperation, Http404):
            messages.error(request, 'That request could not be validated.')
            return True

        if target == scope_root or not target.exists() or not target.is_dir():
            messages.error(request, 'Upload-only links can be created only for existing folders.')
            return True

        uploader_email = (request.POST.get('uploader_email') or '').strip().lower()
        recipient_label = acting_user.username

        if not uploader_email:
            messages.error(request, 'Uploader email is required.')
            return True

        try:
            validate_email(uploader_email)
        except ValidationError:
            messages.error(request, 'Enter a valid uploader email address.')
            return True

        configured_share_settings = SystemShareSettings.get_solo()
        try:
            resolved_expires_at = resolve_upload_link_expires_at(request)
        except ValidationError as exc:
            messages.error(request, exc.message)
            return True

        if resolved_expires_at is None:
            resolved_expires_at = resolve_public_share_expires_at(configured_share_settings.public_share_link_lifetime)

        upload_link = UploadShareLink.objects.create(
            owner=acting_user,
            relative_path=relative_path,
            token=get_random_string(40),
            uploader_email=uploader_email,
            recipient_label=recipient_label,
            expires_at=resolved_expires_at,
        )

        configured_public_base_url = (configured_share_settings.public_share_base_url or '').strip().rstrip('/')
        upload_path = reverse('drive:public-upload', args=[upload_link.token])
        upload_url = f'{configured_public_base_url}{upload_path}' if configured_public_base_url else request.build_absolute_uri(upload_path)
        messages.success(request, f'Upload-only link: {upload_url}')
        audit_event(
            'sharing.upload_link_created',
            request=request,
            user=acting_user,
            relative_path=relative_path,
            token=upload_link.token,
            uploader_email=uploader_email,
            recipient=recipient_label,
        )
        return True

    if action == 'bulk_share' and acting_user == storage_owner:
        raw_tokens = request.POST.getlist('path_tokens')
        if not raw_tokens:
            messages.error(request, 'Select at least one item to share.')
            return True

        valid_relative_paths = []
        invalid_count = 0
        for token in raw_tokens:
            try:
                relative_path = resolve_path_token(token, scope_key)
                valid_relative_paths.append(relative_path)
            except SuspiciousFileOperation:
                invalid_count += 1

        if not valid_relative_paths:
            messages.error(request, 'That request could not be validated.')
            return True

        first_share_data = request.POST.copy()
        first_share_data['relative_path'] = valid_relative_paths[0]
        form = ShareGrantForm(acting_user, first_share_data)
        if not form.is_valid():
            append_form_errors(request, form)
            return True

        created_count = 0
        updated_count = 0
        for relative_path in valid_relative_paths:
            if form.cleaned_data.get('target_group'):
                shared_path, created = GroupSharedPath.objects.update_or_create(
                    owner=acting_user,
                    target_group=form.cleaned_data['target_group'],
                    relative_path=relative_path,
                    defaults={
                        'permission': form.cleaned_data['permission'],
                        'expires_at': form.cleaned_data.get('resolved_expires_at'),
                    },
                )
            else:
                shared_path, created = SharedPath.objects.update_or_create(
                    owner=acting_user,
                    target_user=form.cleaned_data['target_user'],
                    relative_path=relative_path,
                    defaults={
                        'permission': form.cleaned_data['permission'],
                        'expires_at': form.cleaned_data.get('resolved_expires_at'),
                    },
                )
            if created:
                created_count += 1
            else:
                updated_count += 1

        if created_count:
            target_name = (
                f'group:{form.cleaned_data["target_group"].name}'
                if form.cleaned_data.get('target_group')
                else form.cleaned_data['target_user'].username
            )
            audit_event(
                'sharing.bulk_grant',
                request=request,
                user=acting_user,
                owner=acting_user.username,
                target=target_name,
                created_count=created_count,
                updated_count=updated_count,
                invalid_count=invalid_count,
            )
            messages.success(request, f'{created_count} item(s) shared.')
        if updated_count:
            messages.success(request, f'{updated_count} item(s) updated with new sharing settings.')
        if invalid_count:
            messages.error(request, f'{invalid_count} selected item(s) were invalid and were skipped.')
        return True

    if action == 'revoke' and acting_user == storage_owner:
        share = get_object_or_404(SharedPath, pk=request.POST.get('share_id'), owner=acting_user)
        revoked_target = share.target_user.username
        revoked_path = share.relative_path
        share.delete()
        audit_event(
            'sharing.revoke',
            request=request,
            user=acting_user,
            owner=acting_user.username,
            target=revoked_target,
            relative_path=revoked_path,
        )
        messages.success(request, 'Share removed.')
        return True

    return False


def serve_file(path):
    if not path.exists() or not path.is_file():
        raise Http404('File not found.')
    return FileResponse(path.open('rb'), as_attachment=True, filename=path.name)


def serve_download(path: Path):
    if not path.exists():
        raise Http404('File not found.')
    if path.is_file():
        return serve_file(path)

    archive_file = SpooledTemporaryFile(max_size=10 * 1024 * 1024)
    with zipfile.ZipFile(archive_file, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
        wrote_entries = False
        for child in path.rglob('*'):
            archive_name = child.relative_to(path).as_posix()
            if child.is_dir():
                archive.writestr(f'{archive_name}/', '')
                wrote_entries = True
                continue
            archive.write(child, arcname=archive_name)
            wrote_entries = True

        if not wrote_entries:
            archive.writestr('.keep', '')

    archive_file.seek(0)
    return FileResponse(
        archive_file,
        as_attachment=True,
        filename=f'{path.name or "folder"}.zip',
        content_type='application/zip',
    )


def can_open_file(path: Path) -> bool:
    if can_edit_text_file(path):
        return True

    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type:
        return (
            mime_type.startswith('image/')
            or mime_type.startswith('video/')
            or mime_type.startswith('audio/')
            or mime_type == 'application/pdf'
        )

    suffix = path.suffix.lower()
    return suffix in {
        '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg',
        '.pdf',
        '.mp4', '.webm', '.ogv', '.mov', '.m4v', '.mkv',
        '.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac',
    }


def can_thumbnail_file(path: Path) -> bool:
    if not PILLOW_AVAILABLE:
        return False
    mime_type, _ = mimetypes.guess_type(path.name)
    return bool(mime_type and mime_type.startswith('image/'))


def get_inline_content_type(path: Path) -> str | None:
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type:
        return mime_type

    fallback_types = {
        '.txt': 'text/plain',
        '.md': 'text/markdown',
        '.csv': 'text/csv',
        '.log': 'text/plain',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.bmp': 'image/bmp',
        '.svg': 'image/svg+xml',
        '.pdf': 'application/pdf',
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.ogv': 'video/ogg',
        '.mov': 'video/quicktime',
        '.m4v': 'video/x-m4v',
        '.mkv': 'video/x-matroska',
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.ogg': 'audio/ogg',
        '.m4a': 'audio/mp4',
        '.aac': 'audio/aac',
        '.flac': 'audio/flac',
    }
    return fallback_types.get(path.suffix.lower())


def serve_file_inline(path: Path):
    if not path.exists() or not path.is_file():
        raise Http404('File not found.')
    if not can_open_file(path):
        raise Http404('This file type cannot be opened in the browser.')

    return FileResponse(
        path.open('rb'),
        as_attachment=False,
        filename=path.name,
        content_type=get_inline_content_type(path),
    )


def serve_thumbnail(path: Path, size: int = 88):
    if not path.exists() or not path.is_file():
        raise Http404('File not found.')
    if not can_thumbnail_file(path):
        raise Http404('Thumbnail unavailable for this file type.')

    try:
        with Image.open(path) as source_image:
            thumb = source_image.copy()
            thumb.thumbnail((size, size), Image.Resampling.LANCZOS)

            if thumb.mode not in {'RGB', 'RGBA'}:
                thumb = thumb.convert('RGB')

            buffer = BytesIO()
            thumb.save(buffer, format='PNG', optimize=True)
            buffer.seek(0)
    except (OSError, UnidentifiedImageError):
        raise Http404('Thumbnail unavailable for this file.')

    return HttpResponse(buffer.getvalue(), content_type='image/png')


WEBDAV_ALLOWED_METHODS = ['OPTIONS', 'PROPFIND', 'GET', 'HEAD', 'PUT', 'DELETE', 'MKCOL', 'COPY', 'MOVE']
WEBDAV_API_KEY_PREFIX = 'shrivedav'


def _webdav_method_not_allowed():
    response = HttpResponse(status=405)
    response['Allow'] = ', '.join(WEBDAV_ALLOWED_METHODS)
    return response


def _webdav_unauthorized_response() -> HttpResponse:
    response = HttpResponse(status=401)
    response['WWW-Authenticate'] = 'Basic realm="Shrive WebDAV"'
    return response


def _webdav_get_authenticated_user(request):
    if request.user.is_authenticated:
        return request.user

    auth_header = (request.META.get('HTTP_AUTHORIZATION') or '').strip()
    if not auth_header:
        return None

    api_key = None
    if auth_header.lower().startswith('bearer '):
        api_key = auth_header[7:].strip()
    elif auth_header.lower().startswith('basic '):
        encoded_credentials = auth_header[6:].strip()
        try:
            decoded_credentials = base64.b64decode(encoded_credentials).decode('utf-8')
        except (binascii.Error, UnicodeDecodeError):
            return None

        _, separator, password = decoded_credentials.partition(':')
        api_key = (password if separator else decoded_credentials).strip()

    if not api_key:
        return None

    return _webdav_user_from_api_key(api_key)


def _make_webdav_api_key_for_user(user: User) -> str:
    token = get_random_string(48)
    return f'{WEBDAV_API_KEY_PREFIX}.{user.pk}.{token}'


def _webdav_user_from_api_key(api_key: str):
    if not api_key:
        return None

    parts = api_key.split('.', 2)
    if len(parts) != 3:
        return None
    if parts[0] != WEBDAV_API_KEY_PREFIX:
        return None

    try:
        user_id = int(parts[1])
    except ValueError:
        return None

    profile = (
        UserStorageProfile.objects.select_related('user')
        .filter(user_id=user_id, user__is_active=True)
        .first()
    )
    if not profile or not profile.webdav_api_key_hash:
        return None

    if not check_password(api_key, profile.webdav_api_key_hash):
        return None
    return profile.user


def _webdav_relative_path(resource_path: str | None) -> str:
    raw = (resource_path or '').strip('/')
    return normalise_relative_path(raw)


def _webdav_href(relative_path: str, is_dir: bool) -> str:
    if not relative_path:
        return '/dav/'

    encoded_parts = [quote(part, safe='') for part in relative_path.split('/')]
    href = '/dav/' + '/'.join(encoded_parts)
    if is_dir and not href.endswith('/'):
        href += '/'
    return href


def _webdav_status_line(status_code: int) -> str:
    phrases = {
        200: 'OK',
        201: 'Created',
        204: 'No Content',
        404: 'Not Found',
    }
    return f'HTTP/1.1 {status_code} {phrases.get(status_code, "")}'.strip()


def _webdav_propstat(parent: ET.Element, status_code: int, *, resource: Path):
    propstat = ET.SubElement(parent, '{DAV:}propstat')
    prop = ET.SubElement(propstat, '{DAV:}prop')

    ET.SubElement(prop, '{DAV:}displayname').text = resource.name or '/'

    resource_type = ET.SubElement(prop, '{DAV:}resourcetype')
    if resource.is_dir():
        ET.SubElement(resource_type, '{DAV:}collection')

    stat_result = resource.stat()
    modified_at = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)
    created_at = datetime.fromtimestamp(stat_result.st_ctime, tz=timezone.utc)
    ET.SubElement(prop, '{DAV:}getlastmodified').text = format_datetime(modified_at, usegmt=True)
    ET.SubElement(prop, '{DAV:}creationdate').text = created_at.isoformat()

    if resource.is_file():
        ET.SubElement(prop, '{DAV:}getcontentlength').text = str(stat_result.st_size)
        content_type = get_inline_content_type(resource) or 'application/octet-stream'
        ET.SubElement(prop, '{DAV:}getcontenttype').text = content_type

    ET.SubElement(propstat, '{DAV:}status').text = _webdav_status_line(status_code)


def _webdav_propfind_response(root: Path, relative_path: str, depth: str) -> HttpResponse:
    target = resolve_within(root, relative_path)
    if not target.exists():
        raise Http404('File not found.')

    ET.register_namespace('', 'DAV:')
    multistatus = ET.Element('{DAV:}multistatus')

    resources = [target]
    include_children = depth.strip().lower() != '0'
    if include_children and target.is_dir():
        resources.extend(sorted(target.iterdir(), key=lambda child: (not child.is_dir(), child.name.lower())))

    for resource in resources:
        resource_relative = resource.relative_to(root).as_posix() if resource != root else ''
        response_node = ET.SubElement(multistatus, '{DAV:}response')
        ET.SubElement(response_node, '{DAV:}href').text = _webdav_href(resource_relative, resource.is_dir())
        _webdav_propstat(response_node, 200, resource=resource)

    xml_payload = ET.tostring(multistatus, encoding='utf-8', xml_declaration=True)
    return HttpResponse(xml_payload, status=207, content_type='application/xml; charset=utf-8')


def _webdav_destination_relative_path(request) -> str:
    destination = (request.META.get('HTTP_DESTINATION') or '').strip()
    if not destination:
        raise SuspiciousFileOperation('Missing destination header.')

    parsed = urlparse(destination)
    destination_path = unquote(parsed.path or destination)
    base_path = '/dav/'
    if destination_path == '/dav':
        destination_path = base_path

    if not destination_path.startswith(base_path):
        raise SuspiciousFileOperation('Destination must stay under /dav/.')

    return _webdav_relative_path(destination_path[len(base_path):])


def _webdav_has_quota_capacity(user, extra_size: int) -> bool:
    profile, _ = UserStorageProfile.objects.get_or_create(
        user=user,
        defaults={'quota_bytes': settings.FILESHARE_DEFAULT_QUOTA_BYTES},
    )
    if profile.quota_bytes <= 0:
        return False
    return get_user_usage(user) + max(extra_size, 0) <= profile.quota_bytes


@csrf_exempt
def webdav_endpoint(request, resource_path: str = ''):
    if request.method not in WEBDAV_ALLOWED_METHODS:
        return _webdav_method_not_allowed()

    acting_user = _webdav_get_authenticated_user(request)
    if not acting_user:
        return _webdav_unauthorized_response()

    root = get_user_root(acting_user)
    try:
        relative_path = _webdav_relative_path(resource_path)
        target = resolve_within(root, relative_path)
    except SuspiciousFileOperation:
        return HttpResponse(status=400)

    if request.method == 'OPTIONS':
        response = HttpResponse(status=204)
        response['Allow'] = ', '.join(WEBDAV_ALLOWED_METHODS)
        response['DAV'] = '1'
        response['MS-Author-Via'] = 'DAV'
        return response

    if request.method == 'PROPFIND':
        depth = request.META.get('HTTP_DEPTH', '1')
        try:
            return _webdav_propfind_response(root, relative_path, depth)
        except (SuspiciousFileOperation, Http404):
            return HttpResponse(status=404)

    if request.method in {'GET', 'HEAD'}:
        if not target.exists() or not target.is_file():
            return HttpResponse(status=404)

        response = FileResponse(
            target.open('rb'),
            as_attachment=False,
            filename=target.name,
            content_type=get_inline_content_type(target),
        )
        return response

    if request.method == 'PUT':
        if not relative_path:
            return HttpResponse(status=405)
        if target.exists() and target.is_dir():
            return HttpResponse(status=409)

        if not target.parent.exists() or not target.parent.is_dir():
            return HttpResponse(status=409)

        content = request.body
        incoming_size = len(content)
        existing_size = target.stat().st_size if target.exists() and target.is_file() else 0
        extra_size = incoming_size - existing_size
        if extra_size > 0 and not _webdav_has_quota_capacity(acting_user, extra_size):
            return HttpResponse(status=507)

        created = not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        audit_event('storage.webdav_put', request=request, user=acting_user, path=str(target), bytes=incoming_size)
        return HttpResponse(status=201 if created else 204)

    if request.method == 'MKCOL':
        if not relative_path:
            return HttpResponse(status=405)
        if request.body:
            return HttpResponse(status=415)
        if target.exists():
            return HttpResponse(status=405)
        if not target.parent.exists() or not target.parent.is_dir():
            return HttpResponse(status=409)

        target.mkdir(parents=False, exist_ok=False)
        audit_event('storage.webdav_mkcol', request=request, user=acting_user, path=str(target))
        return HttpResponse(status=201)

    if request.method == 'DELETE':
        if not relative_path:
            return HttpResponse(status=403)
        if not target.exists():
            return HttpResponse(status=404)

        delete_entry(target)
        audit_event('storage.webdav_delete', request=request, user=acting_user, path=str(target))
        return HttpResponse(status=204)

    if request.method in {'COPY', 'MOVE'}:
        if not relative_path:
            return HttpResponse(status=403)
        if not target.exists():
            return HttpResponse(status=404)

        try:
            destination_relative = _webdav_destination_relative_path(request)
        except SuspiciousFileOperation:
            return HttpResponse(status=400)

        if not destination_relative:
            return HttpResponse(status=403)

        destination = resolve_within(root, destination_relative)
        overwrite = (request.META.get('HTTP_OVERWRITE', 'T').strip().upper() != 'F')
        destination_exists = destination.exists()

        if destination == target:
            if request.method == 'MOVE':
                return HttpResponse(status=204)
            return HttpResponse(status=403)

        if target.is_dir() and (destination == target or destination.is_relative_to(target)):
            return HttpResponse(status=403)
        if destination.parent.exists() and not destination.parent.is_dir():
            return HttpResponse(status=409)
        if not destination.parent.exists():
            return HttpResponse(status=409)
        if destination_exists and not overwrite:
            return HttpResponse(status=412)

        if request.method == 'COPY':
            source_size = compute_size(target)
            destination_size = compute_size(destination) if destination_exists else 0
            extra_size = source_size - destination_size
            if extra_size > 0 and not _webdav_has_quota_capacity(acting_user, extra_size):
                return HttpResponse(status=507)

        if destination_exists:
            delete_entry(destination)

        if request.method == 'COPY':
            copy_entry(target, destination)
            audit_event('storage.webdav_copy', request=request, user=acting_user, source=str(target), destination=str(destination))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(destination))
            audit_event('storage.webdav_move', request=request, user=acting_user, source=str(target), destination=str(destination))

        return HttpResponse(status=204 if destination_exists else 201)

    return _webdav_method_not_allowed()


def home(request):
    if not initial_setup_complete():
        return redirect('drive:setup')
    if not request.user.is_authenticated:
        return redirect('drive:login')
    return redirect('drive:space')


def setup_view(request):
    if initial_setup_complete():
        if request.user.is_authenticated:
            return redirect('drive:space')
        return redirect('drive:login')

    form = InitialSetupForm(request.POST or None)
    apply_form_styles(form)
    if request.method == 'POST' and form.is_valid():
        admin_user = User.objects.create_superuser(
            username=form.cleaned_data['username'],
            email=form.cleaned_data['email'],
            password=form.cleaned_data['password1'],
        )
        authenticated_user = User.objects.get(pk=admin_user.pk)
        authenticated_user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, authenticated_user)
        audit_event('auth.initial_admin_created', request=request, user=authenticated_user, created_username=admin_user.username)
        messages.success(request, 'Administrator account created.')
        return redirect('drive:space')

    return render_shell(
        request,
        'drive/setup.html',
        {
            'form': form,
            'active_nav': '',
        },
    )


def login_view(request):
    if not initial_setup_complete():
        return redirect('drive:setup')
    if request.user.is_authenticated:
        return redirect('drive:space')

    form = AuthenticationForm(request, data=request.POST or None)
    apply_form_styles(form)
    if request.method == 'POST' and not form.is_valid():
        audit_event(
            'auth.login_rejected',
            request=request,
            success=False,
            username=request.POST.get('username', ''),
        )
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        return redirect('drive:space')

    return render_shell(
        request,
        'drive/login.html',
        {
            'form': form,
            'active_nav': '',
        },
    )


@login_required
def account_view(request):
    if request.user.is_staff:
        return redirect('drive:admin-users')

    profile, _ = UserStorageProfile.objects.get_or_create(
        user=request.user,
        defaults={'quota_bytes': settings.FILESHARE_DEFAULT_QUOTA_BYTES},
    )
    transfer_stats, _ = UserTransferStats.objects.get_or_create(user=request.user)
    used_bytes = get_user_usage(request.user)
    quota_bytes = profile.quota_bytes
    usage_percent = min(int((used_bytes / quota_bytes) * 100), 100) if quota_bytes else 0

    form = PasswordChangeForm(user=request.user)
    apply_form_styles(form)
    if request.method == 'POST':
        action = (request.POST.get('action') or 'change_password').strip()

        if action == 'regenerate_webdav_api_key':
            generated_webdav_api_key = _make_webdav_api_key_for_user(request.user)
            profile.webdav_api_key_hash = make_password(generated_webdav_api_key)
            profile.webdav_api_key_value = generated_webdav_api_key
            profile.webdav_api_key_created_at = dj_timezone.now()
            profile.save(update_fields=['webdav_api_key_hash', 'webdav_api_key_value', 'webdav_api_key_created_at', 'updated_at'])
            audit_event('account.webdav_api_key_regenerated', request=request, user=request.user)
            messages.success(request, 'A new WebDAV API key was generated.')

        elif action == 'revoke_webdav_api_key':
            profile.webdav_api_key_hash = ''
            profile.webdav_api_key_value = ''
            profile.webdav_api_key_created_at = None
            profile.save(update_fields=['webdav_api_key_hash', 'webdav_api_key_value', 'webdav_api_key_created_at', 'updated_at'])
            audit_event('account.webdav_api_key_revoked', request=request, user=request.user)
            messages.success(request, 'WebDAV API key revoked.')

        else:
            form = PasswordChangeForm(user=request.user, data=request.POST)
            apply_form_styles(form)
            if form.is_valid():
                updated_user = form.save()
                update_session_auth_hash(request, updated_user)
                audit_event('account.password_changed', request=request, user=updated_user)
                messages.success(request, 'Your password has been updated.')
                return redirect('drive:account')
            append_form_errors(request, form)

    return render_shell(
        request,
        'drive/account.html',
        {
            'active_nav': 'account',
            'form': form,
            'webdav_api_key_created_at': profile.webdav_api_key_created_at,
            'has_webdav_api_key': bool(profile.webdav_api_key_hash),
            'webdav_api_key_value': profile.webdav_api_key_value,
            'stats': {
                'used_bytes': used_bytes,
                'quota_bytes': quota_bytes,
                'usage_percent': usage_percent,
                'uploaded_bytes': transfer_stats.uploaded_bytes,
                'downloaded_bytes': transfer_stats.downloaded_bytes,
                'last_upload_at': transfer_stats.last_upload_at,
                'last_download_at': transfer_stats.last_download_at,
                'last_login': request.user.last_login,
            },
        },
    )


@login_required
def admin_users(request):
    if not request.user.is_staff:
        raise Http404('Page not found.')

    create_form = AdminUserCreateForm(
        initial={
            'quota_gib': settings.FILESHARE_DEFAULT_QUOTA_BYTES / (1024 ** 3),
            'readonly_storage_roots': '',
        }
    )
    group_form = AdminGroupCreateForm()
    apply_form_styles(group_form)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_user':
            create_form = AdminUserCreateForm(request.POST)
            if create_form.is_valid():
                readonly_roots = [
                    Path(raw_path).expanduser()
                    for raw_path in extract_configured_readonly_paths(create_form.cleaned_data['readonly_storage_roots'])
                ]
                invalid_roots = [path for path in readonly_roots if not path.exists() or not path.is_dir()]
                if invalid_roots:
                    messages.error(
                        request,
                        'Each user-specific read-only share root must exist and be a directory. '
                        f'Invalid: {", ".join(str(path) for path in invalid_roots)}',
                    )
                else:
                    random_password = get_random_string(
                        14,
                        allowed_chars='abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789',
                    )
                    new_user = User.objects.create_user(
                        username=create_form.cleaned_data['username'],
                        email=create_form.cleaned_data['email'],
                        password=random_password,
                    )
                    new_user.is_staff = create_form.cleaned_data['is_staff']
                    new_user.save(update_fields=['is_staff'])
                    UserStorageProfile.objects.update_or_create(
                        user=new_user,
                        defaults={'quota_bytes': create_form.quota_bytes},
                    )
                    for path in readonly_roots:
                        resolved_path = path.resolve()
                        UserReadonlyShare.objects.create(
                            user=new_user,
                            name=resolved_path.name or str(resolved_path),
                            path=str(resolved_path),
                        )
                    messages.success(
                        request,
                        f'User "{new_user.username}" created. Temporary password: {random_password}',
                    )
                    if readonly_roots:
                        messages.success(
                            request,
                            f'Configured {len(readonly_roots)} user-specific read-only share root(s) for "{new_user.username}".',
                        )
                    if new_user.email:
                        sent_count = send_mail(
                            subject='Your Shrive account details',
                            message=(
                                f'Hello {new_user.username},\n\n'
                                'An account has been created for you on Shrive.\n\n'
                                f'Username: {new_user.username}\n'
                                f'Temporary password: {random_password}\n\n'
                                'Please sign in and change your password as soon as possible.'
                            ),
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=[new_user.email],
                            fail_silently=True,
                        )
                        if sent_count:
                            messages.success(request, f'Password email sent to {new_user.email}.')
                        else:
                            messages.warning(request, f'User created but email could not be sent to {new_user.email}.')
                    else:
                        messages.warning(request, 'User created without email address. Password email was not sent.')
                    audit_event(
                        'admin.user_created',
                        request=request,
                        user=request.user,
                        created_username=new_user.username,
                        is_staff=new_user.is_staff,
                    )
                    return redirect('drive:admin-users')
            append_form_errors(request, create_form)

        elif action == 'set_quota':
            quota_form = AdminQuotaUpdateForm(request.POST)
            if quota_form.is_valid():
                target_user = get_object_or_404(User, pk=quota_form.cleaned_data['user_id'])
                profile, _ = UserStorageProfile.objects.get_or_create(
                    user=target_user,
                    defaults={'quota_bytes': settings.FILESHARE_DEFAULT_QUOTA_BYTES},
                )
                profile.quota_bytes = quota_form.quota_bytes
                profile.save()
                audit_event(
                    'admin.user_quota_updated',
                    request=request,
                    user=request.user,
                    target_username=target_user.username,
                    quota_bytes=profile.quota_bytes,
                )
                messages.success(request, f'Quota updated for "{target_user.username}".')
                return redirect('drive:admin-users')
            append_form_errors(request, quota_form)

        elif action == 'update_user':
            target_user = get_object_or_404(User, pk=request.POST.get('user_id'))
            quota_form = AdminQuotaUpdateForm(
                {
                    'user_id': target_user.id,
                    'quota_gib': request.POST.get('quota_gib'),
                }
            )

            if quota_form.is_valid():
                readonly_roots = [
                    Path(raw_path).expanduser()
                    for raw_path in extract_configured_readonly_paths(request.POST.get('readonly_storage_roots', ''))
                ]
                invalid_roots = [path for path in readonly_roots if not path.exists() or not path.is_dir()]
                if invalid_roots:
                    messages.error(
                        request,
                        'Each user-specific read-only share root must exist and be a directory. '
                        f'Invalid: {", ".join(str(path) for path in invalid_roots)}',
                    )
                    return redirect('drive:admin-users')

                requested_staff = bool(request.POST.get('is_staff'))
                if target_user.is_superuser:
                    requested_staff = True

                if target_user == request.user and not requested_staff:
                    messages.error(request, 'You cannot remove your own admin access from this page.')
                    return redirect('drive:admin-users')

                target_user.email = (request.POST.get('email') or '').strip()
                target_user.is_staff = requested_staff
                target_user.save(update_fields=['email', 'is_staff'])

                requested_group_ids = [group_id for group_id in request.POST.getlist('groups') if group_id]
                selected_groups = Group.objects.filter(pk__in=requested_group_ids).order_by('name')
                if len(set(requested_group_ids)) != selected_groups.count():
                    messages.error(request, 'One or more selected groups could not be found.')
                    return redirect('drive:admin-users')
                target_user.groups.set(selected_groups)

                profile, _ = UserStorageProfile.objects.get_or_create(
                    user=target_user,
                    defaults={'quota_bytes': settings.FILESHARE_DEFAULT_QUOTA_BYTES},
                )
                profile.quota_bytes = quota_form.quota_bytes
                profile.save(update_fields=['quota_bytes'])

                UserReadonlyShare.objects.filter(user=target_user).delete()
                for path in readonly_roots:
                    resolved_path = path.resolve()
                    UserReadonlyShare.objects.create(
                        user=target_user,
                        name=resolved_path.name or str(resolved_path),
                        path=str(resolved_path),
                    )

                audit_event(
                    'admin.user_updated',
                    request=request,
                    user=request.user,
                    target_username=target_user.username,
                    is_staff=target_user.is_staff,
                    group_count=selected_groups.count(),
                    readonly_root_count=len(readonly_roots),
                )
                messages.success(request, f'User "{target_user.username}" updated.')
                return redirect('drive:admin-users')

            append_form_errors(request, quota_form)

        elif action == 'delete_user':
            target_user = get_object_or_404(User, pk=request.POST.get('user_id'))
            if target_user == request.user:
                messages.error(request, 'You cannot delete your own account from this page.')
            elif target_user.is_superuser:
                messages.error(request, 'Superuser accounts cannot be removed from this page.')
            else:
                target_username = target_user.username
                target_user.delete()
                audit_event('admin.user_deleted', request=request, user=request.user, target_username=target_username)
                messages.success(request, f'User "{target_username}" removed.')
            return redirect('drive:admin-users')

        elif action == 'reset_user_password':
            target_user = get_object_or_404(User, pk=request.POST.get('user_id'))
            random_password = get_random_string(
                14,
                allowed_chars='abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789',
            )
            target_user.set_password(random_password)
            target_user.save(update_fields=['password'])
            audit_event('admin.user_password_reset', request=request, user=request.user, target_username=target_user.username)
            messages.success(
                request,
                f'Password reset for "{target_user.username}". Temporary password: {random_password}',
            )
            return redirect('drive:admin-users')

        elif action == 'create_group':
            group_form = AdminGroupCreateForm(request.POST)
            apply_form_styles(group_form)
            if group_form.is_valid():
                new_group = Group.objects.create(name=group_form.cleaned_data['name'])
                audit_event('admin.group_created', request=request, user=request.user, group_name=new_group.name)
                messages.success(request, f'Group "{new_group.name}" created.')
                return redirect('drive:admin-users')
            append_form_errors(request, group_form)

        elif action == 'delete_group':
            group = get_object_or_404(Group, pk=request.POST.get('group_id'))
            group_name = group.name
            group.delete()
            audit_event('admin.group_deleted', request=request, user=request.user, group_name=group_name)
            messages.success(request, f'Group "{group_name}" deleted.')
            return redirect('drive:admin-users')

        elif action == 'rename_group':
            rename_form = AdminGroupRenameForm(request.POST)
            if rename_form.is_valid():
                group = get_object_or_404(Group, pk=rename_form.cleaned_data['group_id'])
                old_name = group.name
                new_name = rename_form.cleaned_data['name']
                if old_name == new_name:
                    messages.info(request, 'Group name is unchanged.')
                    return redirect('drive:admin-users')

                group.name = new_name
                group.save(update_fields=['name'])
                audit_event(
                    'admin.group_renamed',
                    request=request,
                    user=request.user,
                    old_name=old_name,
                    new_name=new_name,
                    group_id=group.id,
                )
                messages.success(request, f'Group "{old_name}" renamed to "{new_name}".')
                return redirect('drive:admin-users')

            append_form_errors(request, rename_form)

    group_choices = Group.objects.order_by('name')
    profile_map = {
        profile.user_id: profile for profile in UserStorageProfile.objects.select_related('user').all()
    }
    readonly_share_map: dict[int, list[str]] = {}
    for share in UserReadonlyShare.objects.select_related('user').order_by('name', 'path'):
        readonly_share_map.setdefault(share.user_id, []).append(share.path)

    managed_users = []
    for managed_user in User.objects.order_by('username'):
        profile = profile_map.get(managed_user.id)
        quota_bytes = profile.quota_bytes if profile else settings.FILESHARE_DEFAULT_QUOTA_BYTES
        used_bytes = get_user_usage(managed_user)
        managed_users.append(
            {
                'id': managed_user.id,
                'username': managed_user.username,
                'email': managed_user.email,
                'avatar_url': profile.avatar_url if profile else '',
                'group_ids': list(managed_user.groups.values_list('id', flat=True)),
                'is_superuser': managed_user.is_superuser,
                'is_staff': managed_user.is_staff,
                'is_active': managed_user.is_active,
                'quota_bytes': quota_bytes,
                'quota_gib': quota_bytes / (1024 ** 3),
                'used_bytes': used_bytes,
                'usage_percent': min(int((used_bytes / quota_bytes) * 100), 100) if quota_bytes else 0,
                'can_delete': not managed_user.is_superuser and managed_user != request.user,
                'readonly_storage_roots': readonly_share_map.get(managed_user.id, []),
            }
        )

    readonly_roots_data = {u['id']: u['readonly_storage_roots'] for u in managed_users}

    return render_shell(
        request,
        'drive/admin_users.html',
        {
            'active_nav': 'admin-users',
            'create_form': create_form,
            'group_form': group_form,
            'group_choices': group_choices,
            'managed_users': managed_users,
            'readonly_roots_data': readonly_roots_data,
        },
    )


@login_required
def admin_settings(request):
    if not request.user.is_staff:
        raise Http404('Page not found.')

    configured_settings = SystemShareSettings.get_solo()
    profile, _ = UserStorageProfile.objects.get_or_create(
        user=request.user,
        defaults={'quota_bytes': settings.FILESHARE_DEFAULT_QUOTA_BYTES},
    )
    password_form = PasswordChangeForm(user=request.user)
    apply_form_styles(password_form)
    settings_form = AdminShareRootSettingsForm(
        initial={
            'user_storage_root': configured_settings.user_storage_root or str(get_user_storage_root()),
            'readonly_storage_roots': configured_settings.readonly_storage_root
            or '\n'.join(str(root['path']) for root in get_readonly_roots()),
            'public_share_base_url': configured_settings.public_share_base_url or '',
            'public_share_link_lifetime': configured_settings.public_share_link_lifetime or 'never',
            'timezone_name': configured_settings.timezone_name or 'UTC',
        }
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'set_share_roots':
            settings_form = AdminShareRootSettingsForm(request.POST)
            if settings_form.is_valid():
                user_root = Path(settings_form.cleaned_data['user_storage_root']).expanduser()
                readonly_roots = [
                    Path(raw_path).expanduser()
                    for raw_path in extract_configured_readonly_paths(settings_form.cleaned_data['readonly_storage_roots'])
                ]

                user_root.mkdir(parents=True, exist_ok=True)
                invalid_roots = [path for path in readonly_roots if not path.exists() or not path.is_dir()]
                if invalid_roots:
                    messages.error(
                        request,
                        'Each read-only share root must exist and be a directory. '
                        f'Invalid: {", ".join(str(path) for path in invalid_roots)}',
                    )
                else:
                    configured_settings.user_storage_root = str(user_root.resolve())
                    configured_settings.readonly_storage_root = '\n'.join(
                        str(path.resolve()) for path in readonly_roots
                    )
                    configured_settings.public_share_base_url = settings_form.cleaned_data['public_share_base_url']
                    configured_settings.public_share_link_lifetime = settings_form.cleaned_data['public_share_link_lifetime']
                    configured_settings.timezone_name = settings_form.cleaned_data['timezone_name']
                    configured_settings.save(update_fields=['user_storage_root', 'readonly_storage_root', 'public_share_base_url', 'public_share_link_lifetime', 'timezone_name', 'updated_at'])
                    audit_event(
                        'admin.share_roots_updated',
                        request=request,
                        user=request.user,
                        user_storage_root=configured_settings.user_storage_root,
                        readonly_root_count=len(readonly_roots),
                        public_share_base_url=configured_settings.public_share_base_url,
                        public_share_link_lifetime=configured_settings.public_share_link_lifetime,
                        timezone_name=configured_settings.timezone_name,
                    )
                    messages.success(request, 'Share roots updated.')
                    return redirect('drive:admin-settings')
            else:
                append_form_errors(request, settings_form)

        elif action == 'change_password':
            password_form = PasswordChangeForm(user=request.user, data=request.POST)
            apply_form_styles(password_form)
            if password_form.is_valid():
                updated_user = password_form.save()
                update_session_auth_hash(request, updated_user)
                audit_event('admin.password_changed', request=request, user=updated_user)
                messages.success(request, 'Your password has been updated.')
                return redirect('drive:admin-settings')
            append_form_errors(request, password_form)

        elif action == 'regenerate_webdav_api_key':
            generated_webdav_api_key = _make_webdav_api_key_for_user(request.user)
            profile.webdav_api_key_hash = make_password(generated_webdav_api_key)
            profile.webdav_api_key_value = generated_webdav_api_key
            profile.webdav_api_key_created_at = dj_timezone.now()
            profile.save(update_fields=['webdav_api_key_hash', 'webdav_api_key_value', 'webdav_api_key_created_at', 'updated_at'])
            audit_event('admin.webdav_api_key_regenerated', request=request, user=request.user)
            messages.success(request, 'A new WebDAV API key was generated.')

        elif action == 'revoke_webdav_api_key':
            profile.webdav_api_key_hash = ''
            profile.webdav_api_key_value = ''
            profile.webdav_api_key_created_at = None
            profile.save(update_fields=['webdav_api_key_hash', 'webdav_api_key_value', 'webdav_api_key_created_at', 'updated_at'])
            audit_event('admin.webdav_api_key_revoked', request=request, user=request.user)
            messages.success(request, 'WebDAV API key revoked.')

    return render_shell(
        request,
        'drive/admin_settings.html',
        {
            'active_nav': 'admin-settings',
            'password_form': password_form,
            'settings_form': settings_form,
            'webdav_api_key_created_at': profile.webdav_api_key_created_at,
            'has_webdav_api_key': bool(profile.webdav_api_key_hash),
            'webdav_api_key_value': profile.webdav_api_key_value,
        },
    )


@login_required
def admin_stats(request):
    if not request.user.is_staff:
        raise Http404('Page not found.')

    profile_map = {
        profile.user_id: profile for profile in UserStorageProfile.objects.select_related('user').all()
    }
    transfer_map = {
        stat.user_id: stat for stat in UserTransferStats.objects.select_related('user').all()
    }

    user_rows = []
    total_storage_used = 0
    total_uploaded = 0
    total_downloaded = 0

    for managed_user in User.objects.order_by('username'):
        used_bytes = get_user_usage(managed_user)
        profile = profile_map.get(managed_user.id)
        transfer = transfer_map.get(managed_user.id)
        quota_bytes = profile.quota_bytes if profile else settings.FILESHARE_DEFAULT_QUOTA_BYTES
        uploaded_bytes = transfer.uploaded_bytes if transfer else 0
        downloaded_bytes = transfer.downloaded_bytes if transfer else 0

        total_storage_used += used_bytes
        total_uploaded += uploaded_bytes
        total_downloaded += downloaded_bytes

        user_rows.append(
            {
                'username': managed_user.username,
                'email': managed_user.email,
                'role': (
                    'Superuser'
                    if managed_user.is_superuser
                    else 'Staff'
                    if managed_user.is_staff
                    else 'User'
                ),
                'uploaded_bytes': uploaded_bytes,
                'downloaded_bytes': downloaded_bytes,
                'used_bytes': used_bytes,
                'quota_bytes': quota_bytes,
                'usage_percent': min(int((used_bytes / quota_bytes) * 100), 100) if quota_bytes else 0,
                'last_login': managed_user.last_login,
                'last_upload_at': transfer.last_upload_at if transfer else None,
                'last_download_at': transfer.last_download_at if transfer else None,
            }
        )

    return render_shell(
        request,
        'drive/admin_stats.html',
        {
            'active_nav': 'admin-stats',
            'total_users': len(user_rows),
            'total_storage_used': total_storage_used,
            'total_uploaded': total_uploaded,
            'total_downloaded': total_downloaded,
            'user_stats': user_rows,
        },
    )


@login_required
def admin_todo(request):
    if not request.user.is_staff or not getattr(settings, 'FILESHARE_ENABLE_ADMIN_TODO', True):
        raise Http404('Page not found.')

    create_form = AdminTodoItemForm(initial={'priority': AdminTodoItem.Priority.MEDIUM, 'status': AdminTodoItem.Status.TODO})

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_todo':
            create_form = AdminTodoItemForm(request.POST)
            if create_form.is_valid():
                todo_item = create_form.save(commit=False)
                todo_item.owner = request.user
                todo_item.save()
                audit_event('admin.todo_created', request=request, user=request.user, todo_id=todo_item.id, title=todo_item.title)
                messages.success(request, 'Todo item created.')
                return redirect('drive:admin-todo')
            append_form_errors(request, create_form)

        elif action == 'update_todo':
            todo_item = get_object_or_404(AdminTodoItem, pk=request.POST.get('todo_id'))
            update_form = AdminTodoItemForm(request.POST, instance=todo_item)
            if update_form.is_valid():
                owner_id = request.POST.get('owner_id')
                new_owner = get_object_or_404(User, pk=owner_id, is_staff=True, is_active=True)

                updated_item = update_form.save(commit=False)
                updated_item.owner = new_owner
                updated_item.save()
                audit_event('admin.todo_updated', request=request, user=request.user, todo_id=updated_item.id, owner=new_owner.username)
                messages.success(request, 'Todo item updated.')
                return redirect('drive:admin-todo')
            append_form_errors(request, update_form)

        elif action == 'delete_todo':
            todo_item = get_object_or_404(AdminTodoItem, pk=request.POST.get('todo_id'))
            deleted_todo_id = todo_item.id
            todo_item.delete()
            audit_event('admin.todo_deleted', request=request, user=request.user, todo_id=deleted_todo_id)
            messages.success(request, 'Todo item deleted.')
            return redirect('drive:admin-todo')

    todo_items = AdminTodoItem.objects.select_related('owner').order_by('status', '-priority', 'created_at')
    return render_shell(
        request,
        'drive/admin_todo.html',
        {
            'active_nav': 'admin-todo',
            'create_form': create_form,
            'priority_choices': AdminTodoItem.Priority.choices,
            'status_choices': AdminTodoItem.Status.choices,
            'owner_choices': User.objects.filter(is_staff=True, is_active=True).order_by('username'),
            'todo_items': todo_items,
        },
    )


def audit_log_file_path() -> Path:
    return Path(settings.LOGS_DIR) / 'audit.log'


@login_required
def admin_logs(request):
    if not request.user.is_staff:
        raise Http404('Page not found.')

    line_options = [100, 250, 500, 1000, 2000]
    default_line_count = 500
    requested_line_count = request.GET.get('lines')

    try:
        line_count = int(requested_line_count) if requested_line_count else default_line_count
    except (TypeError, ValueError):
        line_count = default_line_count

    if line_count not in line_options:
        line_count = default_line_count

    log_path = audit_log_file_path()
    log_lines = []
    log_read_error = ''

    if log_path.exists() and log_path.is_file():
        try:
            with log_path.open('r', encoding='utf-8', errors='replace') as log_file:
                log_lines = list(deque(log_file, maxlen=line_count))
        except OSError:
            log_read_error = 'Could not read audit.log at this time.'
    else:
        log_read_error = 'No audit log file found yet.'

    return render_shell(
        request,
        'drive/admin_logs.html',
        {
            'active_nav': 'admin-logs',
            'line_options': line_options,
            'selected_line_count': line_count,
            'log_lines': log_lines,
            'log_read_error': log_read_error,
            'log_path': str(log_path),
        },
    )


@login_required
def admin_logs_download(request):
    if not request.user.is_staff:
        raise Http404('Page not found.')

    log_path = audit_log_file_path()
    if not log_path.exists() or not log_path.is_file():
        raise Http404('Audit log file not found.')

    audit_event('admin.audit_log_downloaded', request=request, user=request.user, path=str(log_path))
    return FileResponse(log_path.open('rb'), as_attachment=True, filename='audit.log')


def _handle_remove_share(request, subject_user):
    action = request.POST.get('action')
    if action == 'remove_user_share':
        share = get_object_or_404(SharedPath, pk=request.POST.get('share_id'), owner=subject_user)
        audit_event('share.removed', request=request, user=request.user, path=share.relative_path, target=share.target_user.username)
        share.delete()
        messages.success(request, f'Share removed for {share.relative_path}.')
    elif action == 'remove_group_share':
        share = get_object_or_404(GroupSharedPath, pk=request.POST.get('share_id'), owner=subject_user)
        audit_event('share.group_removed', request=request, user=request.user, path=share.relative_path, target=share.target_group.name)
        share.delete()
        messages.success(request, f'Group share removed for {share.relative_path}.')
    elif action == 'remove_public_link':
        link = get_object_or_404(PublicShareLink, pk=request.POST.get('share_id'), owner=subject_user)
        audit_event('share.public_link_removed', request=request, user=request.user, path=link.relative_path)
        link.delete()
        messages.success(request, f'Public link removed for {link.relative_path}.')
    elif action == 'remove_upload_link':
        link = get_object_or_404(UploadShareLink, pk=request.POST.get('share_id'), owner=subject_user)
        audit_event('share.upload_link_removed', request=request, user=request.user, path=link.relative_path)
        link.delete()
        messages.success(request, f'Upload-only link removed for {link.relative_path}.')


def _build_shares_context(subject_user, viewer_user, configured_settings):
    """Build share data for a given user's shares page."""
    now = datetime.now(timezone.utc)

    base_url = (configured_settings.public_share_base_url or '').rstrip('/')

    user_shares = (
        SharedPath.objects.filter(owner=subject_user)
        .select_related('target_user')
        .order_by('relative_path', 'target_user__username')
    )
    group_shares = (
        GroupSharedPath.objects.filter(owner=subject_user)
        .select_related('target_group')
        .order_by('relative_path', 'target_group__name')
    )
    public_links = (
        PublicShareLink.objects.filter(owner=subject_user)
        .order_by('relative_path')
    )
    upload_links = (
        UploadShareLink.objects.filter(owner=subject_user)
        .order_by('relative_path', 'created_at')
    )

    def share_status(expires_at):
        if expires_at is None:
            return 'active', None
        if expires_at <= now:
            return 'expired', expires_at
        return 'active', expires_at

    user_share_rows = []
    for s in user_shares:
        status, exp = share_status(s.expires_at)
        user_share_rows.append({
            'id': s.pk,
            'path': s.relative_path,
            'target': s.target_user.username,
            'permission': s.get_permission_display(),
            'status': status,
            'expires_at': exp,
            'created_at': s.created_at,
        })

    group_share_rows = []
    for s in group_shares:
        status, exp = share_status(s.expires_at)
        group_share_rows.append({
            'id': s.pk,
            'path': s.relative_path,
            'target': s.target_group.name,
            'permission': s.get_permission_display(),
            'status': status,
            'expires_at': exp,
            'created_at': s.created_at,
        })

    public_link_rows = []
    for p in public_links:
        status, exp = share_status(p.expires_at)
        token_url = ''
        if base_url:
            token_url = f'{base_url}/public/{p.token}/'
        else:
            token_url = reverse('drive:public-browse', args=[p.token])
        public_link_rows.append({
            'id': p.pk,
            'path': p.relative_path,
            'token': p.token,
            'url': token_url,
            'status': status,
            'expires_at': exp,
            'created_at': p.created_at,
        })

    upload_link_rows = []
    for u in upload_links:
        status, exp = share_status(u.expires_at)
        token_url = ''
        if base_url:
            token_url = f'{base_url}/upload/{u.token}/'
        else:
            token_url = reverse('drive:public-upload', args=[u.token])
        upload_link_rows.append({
            'id': u.pk,
            'path': u.relative_path,
            'token': u.token,
            'url': token_url,
            'status': status,
            'expires_at': exp,
            'created_at': u.created_at,
            'uploader_email': u.uploader_email,
            'recipient_label': u.recipient_label,
            'uploaded_files_count': u.uploaded_files_count,
            'last_uploaded_at': u.last_uploaded_at,
        })

    return {
        'subject_user': subject_user,
        'is_own': subject_user == viewer_user,
        'user_share_rows': user_share_rows,
        'group_share_rows': group_share_rows,
        'public_link_rows': public_link_rows,
        'upload_link_rows': upload_link_rows,
    }


def public_upload(request, token):
    now = datetime.now(timezone.utc)
    upload_link = UploadShareLink.objects.select_related('owner').filter(token=token).first()
    if not upload_link:
        return render(
            request,
            'drive/public_upload_invalid.html',
            {
                'page_title': 'Upload Link Unavailable',
                'page_description': 'This upload link cannot be verified or is no longer available.',
            },
            status=404,
        )

    if upload_link.expires_at and upload_link.expires_at <= now:
        return render(
            request,
            'drive/public_upload_invalid.html',
            {
                'page_title': 'Upload Link Expired',
                'page_description': 'This upload link has expired and can no longer be used.',
            },
            status=410,
        )

    upload_root = resolve_user_path(upload_link.owner, upload_link.relative_path)
    if not upload_root.exists() or not upload_root.is_dir():
        return render(
            request,
            'drive/public_upload_invalid.html',
            {
                'page_title': 'Upload Link Unavailable',
                'page_description': 'This upload link cannot be verified or is no longer available.',
            },
            status=404,
        )

    if request.method == 'POST':
        uploaded_files = []
        for key in request.FILES.keys():
            if key == 'file' or key == 'folder' or key.startswith('file') or key.startswith('folder'):
                files_for_key = request.FILES.getlist(key)
                hinted_paths = request.POST.getlist(f'upload_path_{key}')
                for index, uploaded_file in enumerate(files_for_key):
                    path_hint = hinted_paths[index] if index < len(hinted_paths) else None
                    uploaded_files.append((uploaded_file, path_hint))

        if not uploaded_files:
            messages.error(request, 'Select at least one file to upload.')
            return redirect('drive:public-upload', token=upload_link.token)

        uploaded_count = 0
        uploaded_bytes = 0
        is_single_upload = len(uploaded_files) == 1

        for uploaded_file, path_hint in uploaded_files:
            try:
                upload_relative_path = safe_upload_relative_path(path_hint or uploaded_file.name)
            except SuspiciousFileOperation:
                if is_single_upload:
                    messages.error(request, 'Invalid file name.')
                else:
                    messages.error(request, f'Skipped invalid file name: {uploaded_file.name}')
                continue

            destination = resolve_within(upload_root, upload_relative_path)
            if destination.exists():
                if is_single_upload:
                    messages.error(request, 'A file with that name already exists.')
                else:
                    messages.error(request, f'{upload_relative_path}: a file with that name already exists.')
                continue

            if destination.parent.exists() and not destination.parent.is_dir():
                if is_single_upload:
                    messages.error(request, 'Parent path is not a folder.')
                else:
                    messages.error(request, f'{upload_relative_path}: parent path is not a folder.')
                continue

            if not has_available_space(upload_link.owner, uploaded_file.size):
                if is_single_upload:
                    messages.error(request, 'Upload would exceed the quota assigned to this storage space.')
                else:
                    messages.error(request, f'{upload_relative_path}: upload would exceed the quota assigned to this storage space.')
                continue

            try:
                save_uploaded_file(uploaded_file, destination)
            except OSError:
                if is_single_upload:
                    messages.error(request, 'Upload failed due to an invalid destination path.')
                else:
                    messages.error(request, f'{upload_relative_path}: upload failed due to an invalid destination path.')
                continue

            uploaded_count += 1
            uploaded_bytes += int(uploaded_file.size or 0)
            if is_single_upload:
                messages.success(request, 'File uploaded.')
            else:
                messages.success(request, f'{upload_relative_path}: uploaded.')

        if uploaded_count:
            used_at = datetime.now(timezone.utc)
            auto_expires_at = used_at + timedelta(minutes=30)
            expires_at = upload_link.expires_at
            if expires_at is None or expires_at > auto_expires_at:
                expires_at = auto_expires_at

            upload_link.uploaded_files_count += uploaded_count
            upload_link.last_uploaded_at = used_at
            upload_link.expires_at = expires_at
            upload_link.save(update_fields=['uploaded_files_count', 'last_uploaded_at', 'expires_at', 'updated_at'])
            audit_event(
                'sharing.upload_link_used',
                request=request,
                owner=upload_link.owner.username,
                token=upload_link.token,
                uploader_email=upload_link.uploader_email,
                recipient=upload_link.recipient_label,
                uploaded_count=uploaded_count,
                uploaded_bytes=uploaded_bytes,
            )

        return redirect('drive:public-upload', token=upload_link.token)

    return render(
        request,
        'drive/public_upload.html',
        {
            'page_title': 'Shrive Secure Upload',
            'page_description': 'Drop files into the box or use the upload button.',
        },
    )


@login_required
def my_shares(request):
    if not initial_setup_complete():
        return redirect('drive:setup')
    if request.method == 'POST':
        _handle_remove_share(request, request.user)
        return redirect('drive:my-shares')
    configured_settings = SystemShareSettings.objects.first() or SystemShareSettings()
    ctx = _build_shares_context(request.user, request.user, configured_settings)
    ctx['active_nav'] = 'my-shares'
    return render_shell(request, 'drive/shares.html', ctx)


@login_required
def user_shares(request, user_id):
    if not request.user.is_staff:
        raise Http404('Page not found.')
    subject_user = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        _handle_remove_share(request, subject_user)
        return redirect('drive:user-shares', user_id=user_id)
    configured_settings = SystemShareSettings.objects.first() or SystemShareSettings()
    ctx = _build_shares_context(subject_user, request.user, configured_settings)
    ctx['active_nav'] = 'admin-users'
    return render_shell(request, 'drive/shares.html', ctx)


@login_required
def own_space(request):
    if not initial_setup_complete():
        return redirect('drive:setup')

    current_path = normalise_relative_path(request.GET.get('path'))
    user_root = get_user_root(request.user)
    current_dir = resolve_user_path(request.user, current_path)
    if current_path and not current_dir.exists():
        raise Http404('Folder not found.')
    if current_dir.exists() and not current_dir.is_dir():
        raise Http404('Folder not found.')

    current_dir.mkdir(parents=True, exist_ok=True)

    if request.method == 'POST':
        if handle_clipboard_actions(
            request,
            acting_user=request.user,
            scope_root=user_root,
            scope_key=f'scope:{request.user.pk}',
            current_dir=current_dir,
            destination_owner=request.user,
            can_paste=True,
        ):
            return redirect(build_url(reverse('drive:space'), path=current_path))

        if handle_write_actions(
            request,
            acting_user=request.user,
            storage_owner=request.user,
            scope_root=user_root,
            current_dir=current_dir,
        ):
            return redirect(build_url(reverse('drive:space'), path=current_path))

    entries = iter_directory(current_dir)
    relative_paths = [entry['path'].relative_to(user_root).as_posix() for entry in entries]
    share_records = active_shares_queryset().filter(
        owner=request.user,
        relative_path__in=relative_paths,
    ).select_related('target_user')
    share_map = {}
    for share in share_records:
        share_map.setdefault(share.relative_path, []).append(share)

    return render_shell(
        request,
        'drive/browser.html',
        {
            'active_nav': 'space',
            'page_title': 'My Drive',
            'page_description': 'Upload into your own storage by default, create folders, and share selected items with other users.',
            'breadcrumbs': make_breadcrumbs('My Drive', reverse('drive:space'), current_path),
            'parent_url': parent_url(reverse('drive:space'), current_path),
            'entries': serialise_entries(
                entries,
                user_root,
                reverse('drive:space'),
                reverse('drive:own-download'),
                share_map,
                scope_key=f'scope:{request.user.pk}',
            ),
            'can_upload': True,
            'can_create_folder': True,
            'can_delete': True,
            'can_paste': True,
            'can_share': True,
            'share_targets': allowed_share_targets_queryset(request.user),
            'share_groups': Group.objects.order_by('name') if request.user.is_superuser else request.user.groups.order_by('name'),
            'permission_choices': SharedPath.Permission.choices,
            'current_folder_path_token': make_path_token(current_path, f'scope:{request.user.pk}'),
            'current_folder_display': current_path or '/',
        },
    )


@login_required
def own_download(request):
    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_user_path(request.user, relative_path)
    response = serve_download(target)
    record_user_transfer(request.user, downloaded_bytes=compute_size(target))
    audit_event('storage.download', request=request, user=request.user, scope='own', path=str(target))
    return response


@login_required
def own_open(request):
    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_user_path(request.user, relative_path)
    if can_edit_text_file(target):
        return render_text_editor(
            request,
            path=target,
            active_nav='space',
            page_title=target.name,
            page_description='Edit this text file directly in your browser.',
            breadcrumbs=make_breadcrumbs('My Drive', reverse('drive:space'), relative_path),
            back_url=parent_url(reverse('drive:space'), relative_path) or reverse('drive:space'),
            can_edit=True,
        )
    return serve_file_inline(target)


@login_required
def own_thumb(request):
    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_user_path(request.user, relative_path)
    return serve_thumbnail(target)


@login_required
def shared_list(request):
    shares = []
    for share in active_shares_queryset().filter(target_user=request.user).select_related('owner'):
        share_root = resolve_user_path(share.owner, share.relative_path)
        if not share_root.exists():
            continue
        shares.append(
            {
                'id': share.id,
                'name': share_root.name,
                'owner': share.owner.username,
                'display_path': share.relative_path or '/',
                'permission': share.get_permission_display(),
                'expires_at': share.expires_at,
                'is_dir': share_root.is_dir(),
                'browse_url': reverse('drive:shared-browse', args=[share.id]),
                'download_url': reverse('drive:shared-download', args=[share.id]),
            }
        )

    for share in active_group_shares_queryset().filter(target_group__in=request.user.groups.all()).select_related('owner', 'target_group'):
        share_root = resolve_user_path(share.owner, share.relative_path)
        if not share_root.exists():
            continue
        shares.append(
            {
                'id': f'group-{share.id}',
                'name': share_root.name,
                'owner': share.owner.username,
                'display_path': share.relative_path or '/',
                'permission': share.get_permission_display(),
                'expires_at': share.expires_at,
                'is_dir': share_root.is_dir(),
                'browse_url': reverse('drive:shared-group-browse', args=[share.id]),
                'download_url': reverse('drive:shared-group-download', args=[share.id]),
            }
        )

    return render_shell(
        request,
        'drive/shared_list.html',
        {
            'active_nav': 'shared',
            'shares': shares,
        },
    )


@login_required
def shared_browse(request, share_id):
    share = get_object_or_404(
        active_shares_queryset().select_related('owner', 'target_user'),
        pk=share_id,
        target_user=request.user,
    )
    shared_root = resolve_user_path(share.owner, share.relative_path)
    if not shared_root.exists():
        messages.error(request, 'That shared item is no longer available.')
        return redirect('drive:shared-list')

    browse_url = reverse('drive:shared-browse', args=[share.id])
    download_url = reverse('drive:shared-download', args=[share.id])
    open_url = reverse('drive:shared-open', args=[share.id])

    if request.method == 'POST' and shared_root.is_file():
        if handle_clipboard_actions(
            request,
            acting_user=request.user,
            scope_root=shared_root.parent,
            scope_key=f'scope:{share.owner.pk}',
            current_dir=shared_root.parent,
            destination_owner=share.owner,
            can_paste=False,
        ):
            return redirect(browse_url)

    if shared_root.is_file():
        entries = [
            {
                'name': shared_root.name,
                'is_dir': False,
                'size': shared_root.stat().st_size,
                'modified_at': datetime.fromtimestamp(shared_root.stat().st_mtime, tz=timezone.utc),
                'scope_path_token': make_path_token(share.relative_path, f'scope:{share.owner.pk}'),
                'owner_path_token': make_path_token(share.relative_path, f'scope:{share.owner.pk}'),
                'scope_relative_path': '',
                'owner_relative_path': share.relative_path,
                'browse_url': None,
                'download_url': download_url,
                'open_url': open_url if can_open_file(shared_root) else None,
                'share_list': [],
                'share_records': [],
            }
        ]
        return render_shell(
            request,
            'drive/browser.html',
            {
                'active_nav': 'shared',
                'page_title': f'Shared by {share.owner.username}',
                'page_description': f'{share.get_permission_display()} access to a single file.',
                'breadcrumbs': [{'label': share.owner.username, 'url': browse_url}],
                'parent_url': None,
                'entries': entries,
                'can_upload': False,
                'can_create_folder': False,
                'can_delete': False,
                'can_paste': False,
                'can_share': False,
                'share_targets': [],
                'permission_choices': SharedPath.Permission.choices,
            },
        )

    current_path = normalise_relative_path(request.GET.get('path'))
    current_dir = resolve_within(shared_root, current_path)
    if current_path and not current_dir.exists():
        raise Http404('Folder not found.')
    if current_dir.exists() and not current_dir.is_dir():
        raise Http404('Folder not found.')

    if request.method == 'POST':
        if handle_clipboard_actions(
            request,
            acting_user=request.user,
            scope_root=shared_root,
            scope_key=f'scope:{share.owner.pk}',
            current_dir=current_dir,
            destination_owner=share.owner,
            can_paste=share.permission == SharedPath.Permission.EDIT,
        ):
            return redirect(build_url(browse_url, path=current_path))

        if share.permission == SharedPath.Permission.EDIT and handle_write_actions(
            request,
            acting_user=request.user,
            storage_owner=share.owner,
            scope_root=shared_root,
            current_dir=current_dir,
        ):
            return redirect(build_url(browse_url, path=current_path))

    return render_shell(
        request,
        'drive/browser.html',
        {
            'active_nav': 'shared',
            'page_title': f'Shared by {share.owner.username}',
            'page_description': f'{share.get_permission_display()} access to {share.relative_path or "/"}.',
            'breadcrumbs': make_breadcrumbs(shared_root.name, browse_url, current_path),
            'parent_url': parent_url(browse_url, current_path),
            'entries': serialise_entries(
                iter_directory(current_dir),
                shared_root,
                browse_url,
                download_url,
                scope_key=f'scope:{share.owner.pk}',
            ),
            'can_upload': share.permission == SharedPath.Permission.EDIT,
            'can_create_folder': share.permission == SharedPath.Permission.EDIT,
            'can_delete': share.permission == SharedPath.Permission.EDIT,
            'can_paste': share.permission == SharedPath.Permission.EDIT,
            'can_share': False,
            'share_targets': [],
            'permission_choices': SharedPath.Permission.choices,
        },
    )


@login_required
def shared_download(request, share_id):
    share = get_object_or_404(active_shares_queryset().select_related('owner'), pk=share_id, target_user=request.user)
    shared_root = resolve_user_path(share.owner, share.relative_path)
    if shared_root.is_file() and not request.GET.get('path'):
        response = serve_download(shared_root)
        record_user_transfer(request.user, downloaded_bytes=compute_size(shared_root))
        audit_event('storage.download', request=request, user=request.user, scope='shared', owner=share.owner.username, path=str(shared_root))
        return response

    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_within(shared_root, relative_path)
    response = serve_download(target)
    record_user_transfer(request.user, downloaded_bytes=compute_size(target))
    audit_event('storage.download', request=request, user=request.user, scope='shared', owner=share.owner.username, path=str(target))
    return response


@login_required
def shared_open(request, share_id):
    share = get_object_or_404(active_shares_queryset().select_related('owner'), pk=share_id, target_user=request.user)
    shared_root = resolve_user_path(share.owner, share.relative_path)
    if shared_root.is_file() and not request.GET.get('path'):
        if can_edit_text_file(shared_root):
            return render_text_editor(
                request,
                path=shared_root,
                active_nav='shared',
                page_title=shared_root.name,
                page_description=f'{share.get_permission_display()} access to a single shared text file.',
                breadcrumbs=[{'label': share.owner.username, 'url': reverse('drive:shared-browse', args=[share.id])}],
                back_url=reverse('drive:shared-list'),
                can_edit=share.permission == SharedPath.Permission.EDIT,
            )
        return serve_file_inline(shared_root)

    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_within(shared_root, relative_path)
    if can_edit_text_file(target):
        browse_url = reverse('drive:shared-browse', args=[share.id])
        return render_text_editor(
            request,
            path=target,
            active_nav='shared',
            page_title=target.name,
            page_description=f'{share.get_permission_display()} access to shared text content.',
            breadcrumbs=make_breadcrumbs(shared_root.name, browse_url, relative_path),
            back_url=parent_url(browse_url, relative_path) or browse_url,
            can_edit=share.permission == SharedPath.Permission.EDIT,
        )
    return serve_file_inline(target)


@login_required
def shared_thumb(request, share_id):
    share = get_object_or_404(active_shares_queryset().select_related('owner'), pk=share_id, target_user=request.user)
    shared_root = resolve_user_path(share.owner, share.relative_path)
    if shared_root.is_file() and not request.GET.get('path'):
        return serve_thumbnail(shared_root)

    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_within(shared_root, relative_path)
    return serve_thumbnail(target)


@login_required
def shared_group_browse(request, share_id):
    share = get_object_or_404(
        active_group_shares_queryset().select_related('owner', 'target_group'),
        pk=share_id,
        target_group__in=request.user.groups.all(),
    )
    shared_root = resolve_user_path(share.owner, share.relative_path)
    if not shared_root.exists():
        messages.error(request, 'That shared item is no longer available.')
        return redirect('drive:shared-list')

    browse_url = reverse('drive:shared-group-browse', args=[share.id])
    download_url = reverse('drive:shared-group-download', args=[share.id])
    open_url = reverse('drive:shared-group-open', args=[share.id])

    if request.method == 'POST' and shared_root.is_file():
        if handle_clipboard_actions(
            request,
            acting_user=request.user,
            scope_root=shared_root.parent,
            scope_key=f'scope:{share.owner.pk}',
            current_dir=shared_root.parent,
            destination_owner=share.owner,
            can_paste=False,
        ):
            return redirect(browse_url)

    if shared_root.is_file():
        entries = [
            {
                'name': shared_root.name,
                'is_dir': False,
                'size': shared_root.stat().st_size,
                'modified_at': datetime.fromtimestamp(shared_root.stat().st_mtime, tz=timezone.utc),
                'scope_path_token': make_path_token(share.relative_path, f'scope:{share.owner.pk}'),
                'owner_path_token': make_path_token(share.relative_path, f'scope:{share.owner.pk}'),
                'scope_relative_path': '',
                'owner_relative_path': share.relative_path,
                'browse_url': None,
                'download_url': download_url,
                'open_url': open_url if can_open_file(shared_root) else None,
                'share_list': [],
                'share_records': [],
            }
        ]
        return render_shell(
            request,
            'drive/browser.html',
            {
                'active_nav': 'shared',
                'page_title': f'Shared by {share.owner.username}',
                'page_description': f'{share.get_permission_display()} access to a single file (group: {share.target_group.name}).',
                'breadcrumbs': [{'label': share.owner.username, 'url': browse_url}],
                'parent_url': None,
                'entries': entries,
                'can_upload': False,
                'can_create_folder': False,
                'can_delete': False,
                'can_paste': False,
                'can_share': False,
                'share_targets': [],
                'share_groups': [],
                'permission_choices': SharedPath.Permission.choices,
            },
        )

    current_path = normalise_relative_path(request.GET.get('path'))
    current_dir = resolve_within(shared_root, current_path)
    if current_path and not current_dir.exists():
        raise Http404('Folder not found.')
    if current_dir.exists() and not current_dir.is_dir():
        raise Http404('Folder not found.')

    if request.method == 'POST':
        if handle_clipboard_actions(
            request,
            acting_user=request.user,
            scope_root=shared_root,
            scope_key=f'scope:{share.owner.pk}',
            current_dir=current_dir,
            destination_owner=share.owner,
            can_paste=share.permission == SharedPath.Permission.EDIT,
        ):
            return redirect(build_url(browse_url, path=current_path))

        if share.permission == SharedPath.Permission.EDIT and handle_write_actions(
            request,
            acting_user=request.user,
            storage_owner=share.owner,
            scope_root=shared_root,
            current_dir=current_dir,
        ):
            return redirect(build_url(browse_url, path=current_path))

    return render_shell(
        request,
        'drive/browser.html',
        {
            'active_nav': 'shared',
            'page_title': f'Shared by {share.owner.username}',
            'page_description': f'{share.get_permission_display()} access to {share.relative_path or "/"} (group: {share.target_group.name}).',
            'breadcrumbs': make_breadcrumbs(shared_root.name, browse_url, current_path),
            'parent_url': parent_url(browse_url, current_path),
            'entries': serialise_entries(
                iter_directory(current_dir),
                shared_root,
                browse_url,
                download_url,
                scope_key=f'scope:{share.owner.pk}',
            ),
            'can_upload': share.permission == SharedPath.Permission.EDIT,
            'can_create_folder': share.permission == SharedPath.Permission.EDIT,
            'can_delete': share.permission == SharedPath.Permission.EDIT,
            'can_paste': share.permission == SharedPath.Permission.EDIT,
            'can_share': False,
            'share_targets': [],
            'share_groups': [],
            'permission_choices': SharedPath.Permission.choices,
        },
    )


@login_required
def shared_group_download(request, share_id):
    share = get_object_or_404(
        active_group_shares_queryset().select_related('owner', 'target_group'),
        pk=share_id,
        target_group__in=request.user.groups.all(),
    )
    shared_root = resolve_user_path(share.owner, share.relative_path)
    if shared_root.is_file() and not request.GET.get('path'):
        response = serve_download(shared_root)
        record_user_transfer(request.user, downloaded_bytes=compute_size(shared_root))
        audit_event(
            'storage.download',
            request=request,
            user=request.user,
            scope='shared_group',
            owner=share.owner.username,
            group=share.target_group.name,
            path=str(shared_root),
        )
        return response

    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_within(shared_root, relative_path)
    response = serve_download(target)
    record_user_transfer(request.user, downloaded_bytes=compute_size(target))
    audit_event(
        'storage.download',
        request=request,
        user=request.user,
        scope='shared_group',
        owner=share.owner.username,
        group=share.target_group.name,
        path=str(target),
    )
    return response


@login_required
def shared_group_open(request, share_id):
    share = get_object_or_404(
        active_group_shares_queryset().select_related('owner', 'target_group'),
        pk=share_id,
        target_group__in=request.user.groups.all(),
    )
    shared_root = resolve_user_path(share.owner, share.relative_path)
    if shared_root.is_file() and not request.GET.get('path'):
        if can_edit_text_file(shared_root):
            return render_text_editor(
                request,
                path=shared_root,
                active_nav='shared',
                page_title=shared_root.name,
                page_description=f'{share.get_permission_display()} access to a single shared text file (group: {share.target_group.name}).',
                breadcrumbs=[{'label': share.owner.username, 'url': reverse('drive:shared-group-browse', args=[share.id])}],
                back_url=reverse('drive:shared-list'),
                can_edit=share.permission == SharedPath.Permission.EDIT,
            )
        return serve_file_inline(shared_root)

    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_within(shared_root, relative_path)
    if can_edit_text_file(target):
        browse_url = reverse('drive:shared-group-browse', args=[share.id])
        return render_text_editor(
            request,
            path=target,
            active_nav='shared',
            page_title=target.name,
            page_description=f'{share.get_permission_display()} access to shared text content (group: {share.target_group.name}).',
            breadcrumbs=make_breadcrumbs(shared_root.name, browse_url, relative_path),
            back_url=parent_url(browse_url, relative_path) or browse_url,
            can_edit=share.permission == SharedPath.Permission.EDIT,
        )
    return serve_file_inline(target)


@login_required
def shared_group_thumb(request, share_id):
    share = get_object_or_404(
        active_group_shares_queryset().select_related('owner', 'target_group'),
        pk=share_id,
        target_group__in=request.user.groups.all(),
    )
    shared_root = resolve_user_path(share.owner, share.relative_path)
    if shared_root.is_file() and not request.GET.get('path'):
        return serve_thumbnail(shared_root)

    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_within(shared_root, relative_path)
    return serve_thumbnail(target)


@login_required
def readonly_list(request):
    roots = [
        {
            'name': root['name'],
            'path': root['path'],
            'browse_url': reverse('drive:readonly-browse', args=[root['slug']]),
            'download_url': reverse('drive:readonly-download', args=[root['slug']]),
        }
        for root in get_readonly_roots(request.user)
    ]
    return render_shell(
        request,
        'drive/readonly_list.html',
        {
            'active_nav': 'readonly',
            'roots': roots,
        },
    )


@login_required
def readonly_browse(request, root_slug):
    try:
        readonly_root = get_readonly_root(root_slug, request.user)
    except KeyError as exc:
        raise Http404('Read only root not found.') from exc
    browse_url = reverse('drive:readonly-browse', args=[root_slug])
    current_path = normalise_relative_path(request.GET.get('path'))
    current_dir = resolve_within(readonly_root['path'], current_path)
    if current_path and not current_dir.exists():
        raise Http404('Folder not found.')
    if current_dir.exists() and not current_dir.is_dir():
        raise Http404('Folder not found.')

    if request.method == 'POST':
        if handle_clipboard_actions(
            request,
            acting_user=request.user,
            scope_root=readonly_root['path'],
            scope_key=f'readonly:{root_slug}',
            current_dir=current_dir,
            destination_owner=None,
            can_paste=False,
        ):
            return redirect(build_url(browse_url, path=current_path))

    return render_shell(
        request,
        'drive/browser.html',
        {
            'active_nav': 'readonly',
            'page_title': readonly_root['name'],
            'page_description': 'Read only access to files elsewhere on the system.',
            'breadcrumbs': make_breadcrumbs(readonly_root['name'], browse_url, current_path),
            'parent_url': parent_url(browse_url, current_path),
            'entries': serialise_entries(
                iter_directory(current_dir),
                readonly_root['path'],
                browse_url,
                reverse('drive:readonly-download', args=[root_slug]),
                scope_key=f'readonly:{root_slug}',
            ),
            'can_upload': False,
            'can_create_folder': False,
            'can_delete': False,
            'can_paste': False,
            'can_share': False,
            'share_targets': [],
            'permission_choices': SharedPath.Permission.choices,
        },
    )


@login_required
def readonly_download(request, root_slug):
    try:
        readonly_root = get_readonly_root(root_slug, request.user)
    except KeyError as exc:
        raise Http404('Read only root not found.') from exc
    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_within(readonly_root['path'], relative_path)
    response = serve_download(target)
    record_user_transfer(request.user, downloaded_bytes=compute_size(target))
    audit_event(
        'storage.download',
        request=request,
        user=request.user,
        scope='readonly',
        root_slug=root_slug,
        path=str(target),
    )
    return response


@login_required
def readonly_open(request, root_slug):
    try:
        readonly_root = get_readonly_root(root_slug, request.user)
    except KeyError as exc:
        raise Http404('Read only root not found.') from exc
    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_within(readonly_root['path'], relative_path)
    if can_edit_text_file(target):
        browse_url = reverse('drive:readonly-browse', args=[root_slug])
        return render_text_editor(
            request,
            path=target,
            active_nav='readonly',
            page_title=target.name,
            page_description='Read only preview of a text file.',
            breadcrumbs=make_breadcrumbs(readonly_root['name'], browse_url, relative_path),
            back_url=parent_url(browse_url, relative_path) or browse_url,
            can_edit=False,
        )
    return serve_file_inline(target)


@login_required
def readonly_thumb(request, root_slug):
    try:
        readonly_root = get_readonly_root(root_slug, request.user)
    except KeyError as exc:
        raise Http404('Read only root not found.') from exc
    relative_path = normalise_relative_path(request.GET.get('path'))
    target = resolve_within(readonly_root['path'], relative_path)
    return serve_thumbnail(target)


def public_browse(request, token):
    public_share = get_object_or_404(active_public_shares_queryset().select_related('owner'), token=token)
    shared_root = resolve_user_path(public_share.owner, public_share.relative_path)
    if not shared_root.exists():
        raise Http404('Shared item not found.')

    browse_url = reverse('drive:public-browse', args=[public_share.token])
    download_url = reverse('drive:public-download', args=[public_share.token])
    open_url = reverse('drive:public-open', args=[public_share.token])

    if shared_root.is_file():
        entries = [
            {
                'name': shared_root.name,
                'is_dir': False,
                'size': shared_root.stat().st_size,
                'modified_at': datetime.fromtimestamp(shared_root.stat().st_mtime, tz=timezone.utc),
                'scope_path_token': '',
                'owner_path_token': '',
                'scope_relative_path': '',
                'owner_relative_path': public_share.relative_path,
                'browse_url': None,
                'download_url': download_url,
                'open_url': open_url if can_open_file(shared_root) else None,
                'share_list': [],
                'share_records': [],
            }
        ]
        return render(
            request,
            'drive/public_browser.html',
            {
                'page_title': 'Shared link',
                'page_description': f'Read-only access shared by {public_share.owner.username}.',
                'breadcrumbs': [{'label': 'Shared item', 'url': browse_url}],
                'parent_url': None,
                'entries': entries,
                'can_download': True,
                'shared_root_entry': None,
                'share_owner': public_share.owner.username,
            },
        )

    current_path = normalise_relative_path(request.GET.get('path'))
    browse_root = request.GET.get('browse') == '1'

    # Landing page: show only the top-level shared folder row, not its contents yet.
    if not current_path and not browse_root:
        shared_root_entry = {
            'name': shared_root.name,
            'is_dir': True,
            'size': None,
            'modified_at': datetime.fromtimestamp(shared_root.stat().st_mtime, tz=timezone.utc),
            'browse_url': build_url(browse_url, browse='1'),
            'download_url': download_url,
        }
        return render(
            request,
            'drive/public_browser.html',
            {
                'page_title': 'Shared link',
                'page_description': f'Read-only access shared by {public_share.owner.username}.',
                'breadcrumbs': [{'label': shared_root.name, 'url': build_url(browse_url, browse='1')}],
                'parent_url': None,
                'entries': [],
                'can_download': True,
                'shared_root_entry': shared_root_entry,
                'share_owner': public_share.owner.username,
            },
        )

    current_dir = resolve_within(shared_root, current_path)
    if current_path and not current_dir.exists():
        raise Http404('Folder not found.')
    if current_dir.exists() and not current_dir.is_dir():
        raise Http404('Folder not found.')

    # When viewing root contents (?browse=1) the parent is the landing page (browse_url).
    if not current_path:
        p_url = browse_url
        crumbs = [{'label': shared_root.name, 'url': build_url(browse_url, browse='1')}]
    else:
        p_url = parent_url(build_url(browse_url, browse='1'), current_path)
        crumbs = make_breadcrumbs(shared_root.name, build_url(browse_url, browse='1'), current_path)

    return render(
        request,
        'drive/public_browser.html',
        {
            'page_title': 'Shared link',
            'page_description': f'Read-only access shared by {public_share.owner.username}.',
            'breadcrumbs': crumbs,
            'parent_url': p_url,
            'entries': serialise_entries(
                iter_directory(current_dir),
                shared_root,
                browse_url,
                download_url,
                scope_key=f'public:{public_share.token}',
            ),
            'can_download': True,
            'shared_root_entry': None,
            'share_owner': public_share.owner.username,
        },
    )


def public_download(request, token):
    public_share = get_object_or_404(active_public_shares_queryset().select_related('owner'), token=token)
    shared_root = resolve_user_path(public_share.owner, public_share.relative_path)
    if not shared_root.exists():
        raise Http404('Shared item not found.')

    if shared_root.is_file() and not request.GET.get('path'):
        target = shared_root
    else:
        relative_path = normalise_relative_path(request.GET.get('path'))
        target = resolve_within(shared_root, relative_path)

    audit_event('sharing.public_download', request=request, owner=public_share.owner.username, token=public_share.token, path=str(target))
    return serve_download(target)


def public_open(request, token):
    public_share = get_object_or_404(active_public_shares_queryset().select_related('owner'), token=token)
    shared_root = resolve_user_path(public_share.owner, public_share.relative_path)
    if not shared_root.exists():
        raise Http404('Shared item not found.')

    if shared_root.is_file() and not request.GET.get('path'):
        target = shared_root
    else:
        relative_path = normalise_relative_path(request.GET.get('path'))
        target = resolve_within(shared_root, relative_path)

    if not can_open_file(target):
        raise Http404('This file type cannot be opened in the browser.')

    audit_event('sharing.public_open', request=request, owner=public_share.owner.username, token=public_share.token, path=str(target))
    return serve_file_inline(target)


def public_thumb(request, token):
    public_share = get_object_or_404(active_public_shares_queryset().select_related('owner'), token=token)
    shared_root = resolve_user_path(public_share.owner, public_share.relative_path)
    if not shared_root.exists():
        raise Http404('Shared item not found.')

    if shared_root.is_file() and not request.GET.get('path'):
        target = shared_root
    else:
        relative_path = normalise_relative_path(request.GET.get('path'))
        target = resolve_within(shared_root, relative_path)

    return serve_thumbnail(target)
