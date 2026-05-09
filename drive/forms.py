from django import forms
from django.contrib.auth.models import Group, User
from django.utils.text import slugify
from django.utils import timezone
from zoneinfo import available_timezones
from decimal import Decimal
from datetime import timedelta
from urllib.parse import urlparse

from .models import AdminTodoItem, SharedPath
from .storage import normalise_relative_path


def allowed_share_targets_queryset(owner):
    if not owner or not owner.is_authenticated:
        return User.objects.none()

    if owner.is_superuser:
        return User.objects.filter(is_active=True).exclude(pk=owner.pk).order_by("username")

    owner_groups = owner.groups.all()
    if not owner_groups.exists():
        return User.objects.none()

    return (
        User.objects.filter(is_active=True, groups__in=owner_groups)
        .exclude(pk=owner.pk)
        .distinct()
        .order_by("username")
    )


class InitialSetupForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if not username:
            raise forms.ValidationError("Username is required.")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("That username is already in use.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned_data


class FolderCreateForm(forms.Form):
    name = forms.CharField(max_length=255)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name or name in {".", ".."}:
            raise forms.ValidationError("Enter a valid folder name.")
        if "/" in name or "\\" in name:
            raise forms.ValidationError("Folder names cannot contain path separators.")
        return name


class UploadForm(forms.Form):
    file = forms.FileField()


class ShareGrantForm(forms.Form):
    EXPIRY_CHOICES = [
        ('', 'No expiry'),
        ('1', '1 hour'),
        ('24', '24 hours'),
        ('168', '7 days'),
        ('720', '30 days'),
    ]

    relative_path = forms.CharField(widget=forms.HiddenInput)
    target_user = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    target_group = forms.ModelChoiceField(queryset=Group.objects.none(), required=False)
    permission = forms.ChoiceField(choices=SharedPath.Permission.choices)
    expires_in_hours = forms.ChoiceField(choices=EXPIRY_CHOICES, required=False)
    expires_at = forms.DateTimeField(
        required=False,
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )

    def __init__(self, owner, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.fields["target_user"].queryset = allowed_share_targets_queryset(owner)
        self.fields["target_user"].label_from_instance = lambda user: user.username
        if owner and owner.is_authenticated and owner.is_superuser:
            self.fields["target_group"].queryset = Group.objects.order_by("name")
        else:
            self.fields["target_group"].queryset = owner.groups.order_by("name") if owner and owner.is_authenticated else Group.objects.none()
        self.fields["target_group"].label_from_instance = lambda group: group.name

    def clean_relative_path(self):
        relative_path = normalise_relative_path(self.cleaned_data["relative_path"])
        if not relative_path:
            raise forms.ValidationError("Select a file or folder to share.")
        return relative_path

    def clean(self):
        cleaned_data = super().clean()
        target_user = cleaned_data.get('target_user')
        target_group = cleaned_data.get('target_group')

        if target_user and target_group:
            self.add_error('target_group', 'Choose either a user or a group, not both.')
            return cleaned_data
        if not target_user and not target_group:
            self.add_error('target_user', 'Select a user or a group to share with.')
            return cleaned_data

        expires_in_hours = (cleaned_data.get('expires_in_hours') or '').strip()
        expires_at = cleaned_data.get('expires_at')

        if expires_in_hours and expires_at:
            self.add_error('expires_at', 'Choose either a duration or a specific expiry time, not both.')
            return cleaned_data

        resolved_expiry = None
        if expires_in_hours:
            resolved_expiry = timezone.now() + timedelta(hours=int(expires_in_hours))
        elif expires_at:
            if timezone.is_naive(expires_at):
                resolved_expiry = timezone.make_aware(expires_at, timezone.get_current_timezone())
            else:
                resolved_expiry = expires_at

        if resolved_expiry and resolved_expiry <= timezone.now():
            self.add_error('expires_at', 'Expiry must be in the future.')
            return cleaned_data

        cleaned_data['resolved_expires_at'] = resolved_expiry
        return cleaned_data


class AdminUserCreateForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    quota_gib = forms.DecimalField(min_value=Decimal("0.1"), max_digits=10, decimal_places=2, label="Quota (GiB)")
    is_staff = forms.BooleanField(required=False, initial=False)
    readonly_storage_roots = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="User-specific read-only share roots",
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if not username:
            raise forms.ValidationError("Username is required.")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("That username is already in use.")
        return username

    def clean_email(self):
        return self.cleaned_data["email"].strip()

    def clean_quota_gib(self):
        quota_gib = self.cleaned_data["quota_gib"]
        if quota_gib <= 0:
            raise forms.ValidationError("Quota must be greater than zero.")
        return quota_gib

    def clean_readonly_storage_roots(self):
        raw_value = (self.cleaned_data.get("readonly_storage_roots") or "")
        lines = [line.strip() for line in raw_value.splitlines() if line.strip()]
        return "\n".join(lines)

    @property
    def quota_bytes(self) -> int:
        return int(self.cleaned_data["quota_gib"] * (1024 ** 3))


class AdminQuotaUpdateForm(forms.Form):
    user_id = forms.IntegerField(min_value=1)
    quota_gib = forms.DecimalField(min_value=Decimal("0.1"), max_digits=10, decimal_places=2, label="Quota (GiB)")

    def clean_quota_gib(self):
        quota_gib = self.cleaned_data["quota_gib"]
        if quota_gib <= 0:
            raise forms.ValidationError("Quota must be greater than zero.")
        return quota_gib

    @property
    def quota_bytes(self) -> int:
        return int(self.cleaned_data["quota_gib"] * (1024 ** 3))


class AdminShareRootSettingsForm(forms.Form):
    PUBLIC_SHARE_LIFETIME_CHOICES = [
        ('day', '1 day'),
        ('week', '1 week'),
        ('month', '1 month'),
        ('never', 'Never expire'),
    ]

    readonly_storage_roots = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        label="Read-only share roots",
        help_text="One absolute path per line.",
        required=False,
    )
    public_share_base_url = forms.URLField(
        max_length=500,
        required=False,
        label='Public share base URL',
        help_text='Optional. Example: https://files.example.com',
    )
    public_share_link_lifetime = forms.ChoiceField(
        choices=PUBLIC_SHARE_LIFETIME_CHOICES,
        required=True,
        label='Public share link lifetime',
        initial='never',
    )
    timezone_name = forms.ChoiceField(
        choices=(),
        required=True,
        label='System timezone',
        initial='UTC',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        timezone_choices = sorted((tz, tz) for tz in available_timezones())
        self.fields['timezone_name'].choices = timezone_choices

    def clean_readonly_storage_roots(self):
        raw_value = (self.cleaned_data.get("readonly_storage_roots") or "")
        lines = [line.strip() for line in raw_value.splitlines() if line.strip()]
        return "\n".join(lines)

    def clean_public_share_base_url(self):
        value = (self.cleaned_data.get('public_share_base_url') or '').strip().rstrip('/')
        if not value:
            return ''

        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise forms.ValidationError('Enter a valid absolute URL using http or https.')
        return value

    def clean_public_share_link_lifetime(self):
        value = (self.cleaned_data.get('public_share_link_lifetime') or 'never').strip().lower()
        valid_values = {choice[0] for choice in self.PUBLIC_SHARE_LIFETIME_CHOICES}
        if value not in valid_values:
            raise forms.ValidationError('Select a valid lifetime option.')
        return value

    def clean_timezone_name(self):
        value = (self.cleaned_data.get('timezone_name') or '').strip()
        valid_values = {choice[0] for choice in self.fields['timezone_name'].choices}
        if value not in valid_values:
            raise forms.ValidationError('Select a valid timezone.')
        return value


class AdminGroupCreateForm(forms.Form):
    name = forms.CharField(max_length=150)

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Group name is required.")
        if Group.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("That group already exists.")
        return name


class AdminGroupRenameForm(forms.Form):
    group_id = forms.IntegerField(min_value=1)
    name = forms.CharField(max_length=150)

    def clean_name(self):
        return (self.cleaned_data.get('name') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        group_id = cleaned_data.get('group_id')
        name = cleaned_data.get('name')

        if not name:
            self.add_error('name', 'Group name is required.')
            return cleaned_data

        if not group_id:
            return cleaned_data

        if Group.objects.filter(name__iexact=name).exclude(pk=group_id).exists():
            self.add_error('name', 'That group already exists.')
        return cleaned_data


class AdminTodoItemForm(forms.ModelForm):
    class Meta:
        model = AdminTodoItem
        fields = ['title', 'description', 'priority', 'status']
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Add a todo item'}),
            'description': forms.Textarea(attrs={'rows': 8, 'class': 'form-control'}),
            'priority': forms.Select(),
            'status': forms.Select(),
        }

    def clean_title(self):
        title = (self.cleaned_data.get('title') or '').strip()
        if not title:
            raise forms.ValidationError('Todo item title is required.')
        return title

    def clean_description(self):
        return (self.cleaned_data.get('description') or '').strip()
