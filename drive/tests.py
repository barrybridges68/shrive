from pathlib import Path
import io
import re
from datetime import timedelta
from tempfile import TemporaryDirectory
import zipfile

from django.contrib.auth.models import Group, User
from django.core import signing
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import AdminTodoItem, GroupSharedPath, SharedPath, SystemShareSettings, UploadShareLink, UserReadonlyShare, UserStorageProfile, UserTransferStats
from .storage import get_readonly_roots, get_user_root, iter_directory


class FileShareTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.override = override_settings(
            FILESHARE_STORAGE_ROOT=Path(self.temp_dir.name) / 'storage',
            FILESHARE_READONLY_ROOTS=[{'name': 'Readonly', 'path': self.temp_dir.name}],
            FILESHARE_DEFAULT_QUOTA_BYTES=1024,
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
            DEFAULT_FROM_EMAIL='noreply@fileshare.local',
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

    def test_home_redirects_to_setup_before_admin_exists(self):
        response = self.client.get('/')
        self.assertRedirects(response, '/setup/')

    def test_setup_creates_initial_admin(self):
        response = self.client.post(
            '/setup/',
            {
                'username': 'admin',
                'email': 'admin@example.com',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
        )

        self.assertRedirects(response, '/space/')
        self.assertTrue(User.objects.filter(username='admin', is_superuser=True).exists())

    def test_new_users_receive_random_github_style_avatar_url(self):
        user = User.objects.create_user(username='avatar-user', password='StrongPass123!')
        profile = UserStorageProfile.objects.get(user=user)

        self.assertTrue(profile.avatar_url.startswith('https://api.dicebear.com/9.x/identicon/svg?seed='))

    def test_shared_item_appears_for_target_user(self):
        owner = User.objects.create_user(username='owner', password='StrongPass123!')
        target_user = User.objects.create_user(username='target', password='StrongPass123!')
        root = get_user_root(owner)
        shared_file = root / 'report.txt'
        shared_file.write_text('shared data', encoding='utf-8')
        SharedPath.objects.create(
            owner=owner,
            target_user=target_user,
            relative_path='report.txt',
            permission=SharedPath.Permission.VIEW,
        )

        self.client.force_login(target_user)
        response = self.client.get('/shared/')

        self.assertContains(response, 'report.txt')
        self.assertContains(response, 'View only')

    def test_share_action_can_set_expiry_duration(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        owner = User.objects.create_user(username='owner', password='StrongPass123!')
        target_user = User.objects.create_user(username='target', password='StrongPass123!')
        team = Group.objects.create(name='Team A')
        owner.groups.add(team)
        target_user.groups.add(team)
        shared_file = get_user_root(owner) / 'report.txt'
        shared_file.write_text('shared data', encoding='utf-8')

        self.client.force_login(owner)
        response = self.client.get('/space/')
        self.assertEqual(response.status_code, 200)

        page_content = response.content.decode()
        token_match = re.search(r'data-path-token="([^"]+)"', page_content)
        self.assertIsNotNone(token_match)

        post_response = self.client.post(
            '/space/',
            {
                'action': 'share',
                'path_token': token_match.group(1),
                'target_user': target_user.id,
                'permission': SharedPath.Permission.VIEW,
                'expires_in_hours': '24',
            },
            follow=True,
        )

        self.assertContains(post_response, 'Item shared.')
        share = SharedPath.objects.get(owner=owner, target_user=target_user, relative_path='report.txt')
        self.assertIsNotNone(share.expires_at)
        self.assertGreater(share.expires_at, timezone.now())

    def test_share_targets_are_limited_to_users_in_same_groups(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        owner = User.objects.create_user(username='owner', password='StrongPass123!')
        allowed_user = User.objects.create_user(username='allowed', password='StrongPass123!')
        blocked_user = User.objects.create_user(username='blocked', password='StrongPass123!')
        team = Group.objects.create(name='Team A')
        owner.groups.add(team)
        allowed_user.groups.add(team)

        shared_file = get_user_root(owner) / 'report.txt'
        shared_file.write_text('shared data', encoding='utf-8')

        self.client.force_login(owner)
        response = self.client.get('/space/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'allowed')
        self.assertNotContains(response, 'blocked')

        page_content = response.content.decode()
        token_match = re.search(r'data-path-token="([^"]+)"', page_content)
        self.assertIsNotNone(token_match)

        post_response = self.client.post(
            '/space/',
            {
                'action': 'share',
                'path_token': token_match.group(1),
                'target_user': blocked_user.id,
                'permission': SharedPath.Permission.VIEW,
            },
            follow=True,
        )

        self.assertContains(post_response, 'Select a valid choice.')
        self.assertFalse(
            SharedPath.objects.filter(owner=owner, target_user=blocked_user, relative_path='report.txt').exists()
        )

    def test_superuser_sees_share_targets_without_group_membership(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        target_user = User.objects.create_user(username='target-user', password='StrongPass123!')
        Group.objects.create(name='Ops')
        (get_user_root(admin_user) / 'admin-share.txt').write_text('data', encoding='utf-8')

        self.client.force_login(admin_user)
        response = self.client.get('/space/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'target-user')
        self.assertContains(response, 'Ops')

    def test_share_action_can_share_with_group(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        owner = User.objects.create_user(username='owner-group', password='StrongPass123!')
        member = User.objects.create_user(username='member-group', password='StrongPass123!')
        team = Group.objects.create(name='Team Share')
        owner.groups.add(team)
        member.groups.add(team)

        shared_file = get_user_root(owner) / 'group-report.txt'
        shared_file.write_text('shared data', encoding='utf-8')

        self.client.force_login(owner)
        response = self.client.get('/space/')
        self.assertEqual(response.status_code, 200)

        page_content = response.content.decode()
        token_match = re.search(r'data-path-token="([^"]+)"', page_content)
        self.assertIsNotNone(token_match)

        post_response = self.client.post(
            '/space/',
            {
                'action': 'share',
                'path_token': token_match.group(1),
                'target_group': team.id,
                'permission': SharedPath.Permission.VIEW,
            },
            follow=True,
        )

        self.assertContains(post_response, 'Item shared.')
        self.assertTrue(
            GroupSharedPath.objects.filter(owner=owner, target_group=team, relative_path='group-report.txt').exists()
        )

    def test_group_shared_item_appears_for_group_member(self):
        owner = User.objects.create_user(username='owner-gsl', password='StrongPass123!')
        member = User.objects.create_user(username='member-gsl', password='StrongPass123!')
        outsider = User.objects.create_user(username='outsider-gsl', password='StrongPass123!')
        team = Group.objects.create(name='Team Visible')
        owner.groups.add(team)
        member.groups.add(team)

        shared_file = get_user_root(owner) / 'group-visible.txt'
        shared_file.write_text('shared data', encoding='utf-8')
        GroupSharedPath.objects.create(
            owner=owner,
            target_group=team,
            relative_path='group-visible.txt',
            permission=SharedPath.Permission.VIEW,
        )

        self.client.force_login(member)
        member_response = self.client.get('/shared/')
        self.assertContains(member_response, 'group-visible.txt')

        self.client.force_login(outsider)
        outsider_response = self.client.get('/shared/')
        self.assertNotContains(outsider_response, 'group-visible.txt')

    def test_shared_with_me_sidebar_count_includes_direct_and_group_shares(self):
        User.objects.create_superuser(username='admin-count', email='admin-count@example.com', password='StrongPass123!')
        direct_owner = User.objects.create_user(username='direct-owner', password='StrongPass123!')
        group_owner = User.objects.create_user(username='group-owner', password='StrongPass123!')
        member = User.objects.create_user(username='member-count', password='StrongPass123!')
        team = Group.objects.create(name='Count Team')
        group_owner.groups.add(team)
        member.groups.add(team)

        direct_file = get_user_root(direct_owner) / 'direct-count.txt'
        direct_file.write_text('direct', encoding='utf-8')
        SharedPath.objects.create(
            owner=direct_owner,
            target_user=member,
            relative_path='direct-count.txt',
            permission=SharedPath.Permission.VIEW,
        )

        group_file = get_user_root(group_owner) / 'group-count.txt'
        group_file.write_text('group', encoding='utf-8')
        GroupSharedPath.objects.create(
            owner=group_owner,
            target_group=team,
            relative_path='group-count.txt',
            permission=SharedPath.Permission.VIEW,
        )

        self.client.force_login(member)
        response = self.client.get('/space/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '>Shared with me')
        self.assertContains(response, '>2<')

    def test_expired_share_is_hidden_from_shared_list(self):
        owner = User.objects.create_user(username='owner', password='StrongPass123!')
        target_user = User.objects.create_user(username='target', password='StrongPass123!')
        shared_file = get_user_root(owner) / 'expired-report.txt'
        shared_file.write_text('shared data', encoding='utf-8')
        SharedPath.objects.create(
            owner=owner,
            target_user=target_user,
            relative_path='expired-report.txt',
            permission=SharedPath.Permission.VIEW,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        self.client.force_login(target_user)
        response = self.client.get('/shared/')

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'expired-report.txt')

    def test_expired_share_cannot_be_opened(self):
        owner = User.objects.create_user(username='owner', password='StrongPass123!')
        target_user = User.objects.create_user(username='target', password='StrongPass123!')
        shared_file = get_user_root(owner) / 'expired-open.txt'
        shared_file.write_text('shared data', encoding='utf-8')
        share = SharedPath.objects.create(
            owner=owner,
            target_user=target_user,
            relative_path='expired-open.txt',
            permission=SharedPath.Permission.VIEW,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        self.client.force_login(target_user)
        response = self.client.get(f'/shared/{share.id}/')

        self.assertEqual(response.status_code, 404)

    def test_create_upload_only_link_requires_email_and_recipient(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        owner = User.objects.create_user(username='owner-upload-link', password='StrongPass123!')
        folder = get_user_root(owner) / 'dropbox'
        folder.mkdir(parents=True, exist_ok=True)

        self.client.force_login(owner)
        response = self.client.get('/space/?path=dropbox')
        self.assertEqual(response.status_code, 200)

        page_content = response.content.decode()
        token_match = re.search(r'id="create-upload-link-path-token"\s+value="([^"]+)"', page_content)
        self.assertIsNotNone(token_match)

        post_response = self.client.post(
            '/space/',
            {
                'action': 'create_upload_link',
                'path_token': token_match.group(1),
                'uploader_email': '',
            },
            follow=True,
        )

        self.assertContains(post_response, 'Uploader email is required.')
        self.assertEqual(UploadShareLink.objects.count(), 0)

    def test_upload_only_link_hides_metadata_and_accepts_upload(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        owner = User.objects.create_user(username='owner-upload-link-2', password='StrongPass123!')
        folder = get_user_root(owner) / 'incoming'
        folder.mkdir(parents=True, exist_ok=True)

        self.client.force_login(owner)
        response = self.client.get('/space/?path=incoming')
        self.assertEqual(response.status_code, 200)

        page_content = response.content.decode()
        token_match = re.search(r'id="create-upload-link-path-token"\s+value="([^"]+)"', page_content)
        self.assertIsNotNone(token_match)

        uploader_email = 'uploader@example.com'
        recipient_label = 'Finance Team'
        create_response = self.client.post(
            '/space/',
            {
                'action': 'create_upload_link',
                'path_token': token_match.group(1),
                'uploader_email': uploader_email,
            },
            follow=True,
        )

        self.assertContains(create_response, 'Upload-only link:')
        upload_link = UploadShareLink.objects.get(owner=owner, relative_path='incoming')
        upload_url = f'/upload/{upload_link.token}/'

        self.assertNotIn(uploader_email, upload_url)
        self.assertNotIn('Finance', upload_url)

        public_page = self.client.get(upload_url)
        self.assertEqual(public_page.status_code, 200)
        self.assertNotContains(public_page, uploader_email)
        self.assertNotContains(public_page, recipient_label)

        upload_response = self.client.post(
            upload_url,
            {
                'action': 'upload',
                'file': SimpleUploadedFile('invoice.txt', b'new invoice'),
            },
            follow=True,
        )

        self.assertContains(upload_response, 'File uploaded.')
        self.assertTrue((folder / 'invoice.txt').exists())
        upload_link.refresh_from_db()
        self.assertEqual(upload_link.uploaded_files_count, 1)
        self.assertIsNotNone(upload_link.last_uploaded_at)

    def test_upload_only_link_invalid_token_shows_error_page(self):
        response = self.client.get('/upload/not-a-valid-token/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Upload Link Unavailable', status_code=404)
        self.assertContains(response, 'cannot be verified', status_code=404)

    def test_create_upload_only_link_accepts_expiry_duration(self):
        User.objects.create_superuser(username='admin-expiry', email='admin-expiry@example.com', password='StrongPass123!')
        owner = User.objects.create_user(username='owner-upload-expiry', password='StrongPass123!')
        folder = get_user_root(owner) / 'dropbox'
        folder.mkdir(parents=True, exist_ok=True)

        self.client.force_login(owner)
        response = self.client.get('/space/?path=dropbox')
        self.assertEqual(response.status_code, 200)

        page_content = response.content.decode()
        token_match = re.search(r'id="create-upload-link-path-token"\s+value="([^"]+)"', page_content)
        self.assertIsNotNone(token_match)

        self.client.post(
            '/space/',
            {
                'action': 'create_upload_link',
                'path_token': token_match.group(1),
                'uploader_email': 'uploader-expiry@example.com',
                'expires_in_hours': '1',
            },
            follow=True,
        )

        upload_link = UploadShareLink.objects.get(owner=owner, relative_path='dropbox')
        self.assertIsNotNone(upload_link.expires_at)
        self.assertGreater(upload_link.expires_at, timezone.now() + timedelta(minutes=55))

    def test_upload_only_link_expires_30_minutes_after_use(self):
        User.objects.create_superuser(username='admin-upload-auto-expire', email='admin-upload-auto-expire@example.com', password='StrongPass123!')
        owner = User.objects.create_user(username='owner-upload-auto-expire', password='StrongPass123!')
        folder = get_user_root(owner) / 'incoming'
        folder.mkdir(parents=True, exist_ok=True)

        upload_link = UploadShareLink.objects.create(
            owner=owner,
            relative_path='incoming',
            token='tokenuploadexpires123',
            uploader_email='uploader@example.com',
            recipient_label=owner.username,
            expires_at=timezone.now() + timedelta(days=1),
        )

        upload_response = self.client.post(
            f'/upload/{upload_link.token}/',
            {
                'action': 'upload',
                'file': SimpleUploadedFile('invoice.txt', b'new invoice'),
            },
            follow=True,
        )

        self.assertContains(upload_response, 'File uploaded.')

        upload_link.refresh_from_db()
        self.assertIsNotNone(upload_link.expires_at)
        expected_expiry = timezone.now() + timedelta(minutes=30)
        self.assertLess(abs((upload_link.expires_at - expected_expiry).total_seconds()), 120)

    def test_quota_blocks_large_upload(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='quota-user', password='StrongPass123!')
        profile = UserStorageProfile.objects.get(user=user)
        profile.quota_bytes = 1
        profile.save(update_fields=['quota_bytes'])

        self.client.force_login(user)
        response = self.client.post(
            '/space/',
            {
                'action': 'upload',
                'file': SimpleUploadedFile('large.txt', b'12345'),
            },
            follow=True,
        )

        self.assertContains(response, 'Upload would exceed the quota assigned to this storage space.')

    def test_folder_upload_creates_nested_directories(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='folder-user', password='StrongPass123!')
        self.client.force_login(user)

        response = self.client.post(
            '/space/',
            {
                'action': 'upload',
                'file0': SimpleUploadedFile('readme.txt', b'folder upload content'),
                'upload_path_file0': 'project/docs/readme.txt',
            },
            follow=True,
        )

        self.assertContains(response, 'File uploaded.')
        user_root = get_user_root(user)
        self.assertTrue((user_root / 'project' / 'docs' / 'readme.txt').exists())

    def test_folder_upload_with_single_field_preserves_subfolders(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='folder-user-2', password='StrongPass123!')
        self.client.force_login(user)

        response = self.client.post(
            '/space/',
            {
                'action': 'upload',
                'folder': [
                    SimpleUploadedFile('doc-a.txt', b'a'),
                    SimpleUploadedFile('doc-b.txt', b'b'),
                ],
                'upload_path_folder': [
                    'project/docs/doc-a.txt',
                    'project/docs/sub/doc-b.txt',
                ],
            },
            follow=True,
        )

        self.assertContains(response, 'project/docs/doc-a.txt: uploaded.')
        self.assertContains(response, 'project/docs/sub/doc-b.txt: uploaded.')
        user_root = get_user_root(user)
        self.assertTrue((user_root / 'project' / 'docs' / 'doc-a.txt').exists())
        self.assertTrue((user_root / 'project' / 'docs' / 'sub' / 'doc-b.txt').exists())

    def test_can_create_folder_with_create_folder_action(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='new-folder-user', password='StrongPass123!')
        self.client.force_login(user)

        response = self.client.post('/space/', {'action': 'create_folder', 'name': 'notes'}, follow=True)

        self.assertContains(response, 'Folder created.')
        self.assertTrue((get_user_root(user) / 'notes').is_dir())

    def test_can_create_text_file_with_default_txt_extension(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='new-text-user', password='StrongPass123!')
        self.client.force_login(user)

        response = self.client.post('/space/', {'action': 'create_text_file', 'name': 'draft'}, follow=True)

        self.assertContains(response, 'Text file created.')
        created_file = get_user_root(user) / 'draft.txt'
        self.assertTrue(created_file.is_file())
        self.assertEqual(created_file.read_text(encoding='utf-8'), '')

    def test_directory_listing_calculates_folder_size(self):
        user = User.objects.create_user(username='size-user', password='StrongPass123!')
        user_root = get_user_root(user)
        folder = user_root / 'project'
        (folder / 'docs').mkdir(parents=True, exist_ok=True)
        (folder / 'docs' / 'readme.txt').write_bytes(b'12345')
        (folder / 'docs' / 'notes.txt').write_bytes(b'678')

        entries = iter_directory(user_root)
        project_entry = next(entry for entry in entries if entry['name'] == 'project')

        self.assertTrue(project_entry['is_dir'])
        self.assertEqual(project_entry['size'], 8)

    def test_folder_can_be_downloaded_as_zip(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='zip-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        folder = user_root / 'project'
        (folder / 'docs').mkdir(parents=True, exist_ok=True)
        (folder / 'docs' / 'readme.txt').write_text('zip me', encoding='utf-8')

        response = self.client.get('/space/download/?path=project')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type'), 'application/zip')
        archive_bytes = b''.join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            self.assertIn('docs/readme.txt', archive.namelist())

    def test_upload_and_download_update_transfer_stats(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='transfer-user', password='StrongPass123!')
        self.client.force_login(user)

        upload_response = self.client.post(
            '/space/',
            {
                'action': 'upload',
                'file': SimpleUploadedFile('hello.txt', b'hello world'),
            },
            follow=True,
        )
        self.assertContains(upload_response, 'File uploaded.')

        download_response = self.client.get('/space/download/?path=hello.txt')
        self.assertEqual(download_response.status_code, 200)

        stats = UserTransferStats.objects.get(user=user)
        self.assertEqual(stats.uploaded_bytes, len(b'hello world'))
        self.assertEqual(stats.downloaded_bytes, len(b'hello world'))
        self.assertIsNotNone(stats.last_upload_at)
        self.assertIsNotNone(stats.last_download_at)

    def test_delete_rejects_tampered_path_token(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='token-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        target = user_root / 'keep.txt'
        target.write_text('safe', encoding='utf-8')

        response = self.client.get('/space/')
        self.assertEqual(response.status_code, 200)
        page_content = response.content.decode()
        match = re.search(r'data-path-token="([^"]+)"', page_content)
        self.assertIsNotNone(match)
        tampered_token = f"{match.group(1)}x"

        delete_response = self.client.post(
            '/space/',
            {
                'action': 'delete',
                'path_token': tampered_token,
            },
            follow=True,
        )

        self.assertContains(delete_response, 'That request could not be validated.')
        self.assertTrue(target.exists())

    def test_bulk_delete_removes_multiple_items(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='bulk-delete-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        (user_root / 'one.txt').write_text('one', encoding='utf-8')
        (user_root / 'two.txt').write_text('two', encoding='utf-8')

        scope = f'scope:{user.pk}'
        token_one = signing.dumps({'path': 'one.txt', 'scope': scope}, salt='drive.path-token')
        token_two = signing.dumps({'path': 'two.txt', 'scope': scope}, salt='drive.path-token')

        response = self.client.post(
            '/space/',
            {
                'action': 'bulk_delete',
                'path_tokens': [token_one, token_two],
            },
            follow=True,
        )

        self.assertContains(response, '2 item(s) deleted.')
        self.assertFalse((user_root / 'one.txt').exists())
        self.assertFalse((user_root / 'two.txt').exists())

    def test_bulk_share_grants_multiple_items(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        owner = User.objects.create_user(username='bulk-share-owner', password='StrongPass123!')
        target_user = User.objects.create_user(username='bulk-share-target', password='StrongPass123!')
        team = Group.objects.create(name='Bulk share team')
        owner.groups.add(team)
        target_user.groups.add(team)
        self.client.force_login(owner)
        owner_root = get_user_root(owner)
        (owner_root / 'alpha.txt').write_text('alpha', encoding='utf-8')
        (owner_root / 'beta.txt').write_text('beta', encoding='utf-8')

        scope = f'scope:{owner.pk}'
        token_alpha = signing.dumps({'path': 'alpha.txt', 'scope': scope}, salt='drive.path-token')
        token_beta = signing.dumps({'path': 'beta.txt', 'scope': scope}, salt='drive.path-token')

        response = self.client.post(
            '/space/',
            {
                'action': 'bulk_share',
                'path_tokens': [token_alpha, token_beta],
                'target_user': target_user.id,
                'permission': SharedPath.Permission.VIEW,
            },
            follow=True,
        )

        self.assertContains(response, '2 item(s) shared.')
        self.assertTrue(
            SharedPath.objects.filter(owner=owner, target_user=target_user, relative_path='alpha.txt').exists()
        )
        self.assertTrue(
            SharedPath.objects.filter(owner=owner, target_user=target_user, relative_path='beta.txt').exists()
        )

    def test_text_file_opens_in_editor_page(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='inline-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        (user_root / 'note.txt').write_text('hello inline', encoding='utf-8')

        response = self.client.get('/space/open/?path=note.txt')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Save changes')
        self.assertContains(response, 'hello inline')

    def test_text_file_can_be_saved_from_editor_page(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='editor-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        file_path = user_root / 'note.txt'
        file_path.write_text('old value', encoding='utf-8')

        response = self.client.post(
            '/space/open/?path=note.txt',
            {'content': 'new value'},
            follow=True,
        )

        self.assertContains(response, 'File saved.')
        self.assertEqual(file_path.read_text(encoding='utf-8'), 'new value')

    def test_python_file_opens_in_editor_page(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='python-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        (user_root / 'script.py').write_text('print("hello")\n', encoding='utf-8')

        response = self.client.get('/space/open/?path=script.py')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Save changes')
        self.assertContains(response, 'print(&quot;hello&quot;)')

    def test_markdown_file_opens_in_editor_page(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='markdown-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        (user_root / 'README.md').write_text('# heading\n', encoding='utf-8')

        response = self.client.get('/space/open/?path=README.md')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Save changes')
        self.assertContains(response, '# heading')

    @override_settings(FILESHARE_TEXT_EDITOR_EXTENSIONS=['.txt', '.note'])
    def test_custom_editor_extension_from_settings_opens_in_editor_page(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='custom-editor-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        (user_root / 'journal.note').write_text('configured editor type', encoding='utf-8')

        response = self.client.get('/space/open/?path=journal.note')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Save changes')
        self.assertContains(response, 'configured editor type')

    def test_shared_view_only_text_file_opens_readonly_editor(self):
        owner = User.objects.create_user(username='owner', password='StrongPass123!')
        target_user = User.objects.create_user(username='target', password='StrongPass123!')
        shared_file = get_user_root(owner) / 'report.txt'
        shared_file.write_text('shared text', encoding='utf-8')
        share = SharedPath.objects.create(
            owner=owner,
            target_user=target_user,
            relative_path='report.txt',
            permission=SharedPath.Permission.VIEW,
        )
        self.client.force_login(target_user)

        response = self.client.get(f'/shared/{share.id}/open/')

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Save changes')
        self.assertContains(response, 'shared text')

    def test_unknown_file_type_cannot_be_opened_inline(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='inline-user-2', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        (user_root / 'binary.bin').write_bytes(b'\x00\x01\x02')

        response = self.client.get('/space/open/?path=binary.bin')

        self.assertEqual(response.status_code, 404)

    def test_video_file_type_can_be_opened_inline(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='video-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        (user_root / 'clip.mp4').write_bytes(b'\x00\x00\x00\x18ftypmp42')

        response = self.client.get('/space/open/?path=clip.mp4')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type').split(';')[0], 'video/mp4')

    def test_audio_file_type_can_be_opened_inline(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='audio-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)
        (user_root / 'clip.mp3').write_bytes(b'ID3\x04\x00\x00\x00\x00\x00\x21')

        response = self.client.get('/space/open/?path=clip.mp3')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type').split(';')[0], 'audio/mpeg')

    def test_image_thumbnail_endpoint_returns_png(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user = User.objects.create_user(username='thumb-user', password='StrongPass123!')
        self.client.force_login(user)
        user_root = get_user_root(user)

        from PIL import Image

        image_path = user_root / 'photo.jpg'
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new('RGB', (240, 120), color=(10, 120, 200))
        image.save(image_path, format='JPEG')

        response = self.client.get('/space/thumb/?path=photo.jpg')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type'), 'image/png')

    def test_readonly_root_page_is_available(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        self.client.force_login(admin_user)

        response = self.client.get('/readonly/')

        self.assertContains(response, 'Readonly')

    def test_admin_users_page_can_create_user_with_quota(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        self.client.force_login(admin_user)

        response = self.client.post(
            '/users/',
            {
                'action': 'create_user',
                'username': 'new-user',
                'email': 'new-user@example.com',
                'quota_gib': '2.5',
                'is_staff': '1',
            },
            follow=True,
        )

        self.assertContains(response, 'Temporary password:')
        created_user = User.objects.get(username='new-user')
        profile = UserStorageProfile.objects.get(user=created_user)
        self.assertEqual(profile.quota_bytes, int(2.5 * (1024 ** 3)))
        self.assertTrue(created_user.is_staff)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('new-user@example.com', mail.outbox[0].to)
        self.assertIn('Temporary password:', response.content.decode())

    def test_admin_users_page_can_update_quota(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        target_user = User.objects.create_user(username='member', password='StrongPass123!')
        self.client.force_login(admin_user)

        response = self.client.post(
            '/users/',
            {
                'action': 'set_quota',
                'user_id': target_user.id,
                'quota_gib': '3.0',
            },
            follow=True,
        )

        self.assertContains(response, 'Quota updated for')
        target_user.refresh_from_db()
        profile = UserStorageProfile.objects.get(user=target_user)
        self.assertEqual(profile.quota_bytes, int(3.0 * (1024 ** 3)))

    def test_admin_users_page_can_update_user_from_edit_action(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        target_user = User.objects.create_user(username='member', email='old@example.com', password='StrongPass123!')
        readonly_root = Path(self.temp_dir.name) / 'member-readonly'
        readonly_root.mkdir(parents=True, exist_ok=True)
        UserReadonlyShare.objects.create(user=target_user, name='old-share', path=self.temp_dir.name)
        self.client.force_login(admin_user)

        response = self.client.post(
            '/users/',
            {
                'action': 'update_user',
                'user_id': target_user.id,
                'email': 'updated@example.com',
                'quota_gib': '4.0',
                'is_staff': '1',
                'readonly_storage_roots': str(readonly_root),
            },
            follow=True,
        )

        self.assertContains(response, 'User &quot;member&quot; updated.')
        target_user.refresh_from_db()
        profile = UserStorageProfile.objects.get(user=target_user)
        self.assertEqual(target_user.email, 'updated@example.com')
        self.assertTrue(target_user.is_staff)
        self.assertEqual(profile.quota_bytes, int(4.0 * (1024 ** 3)))
        readonly_paths = list(UserReadonlyShare.objects.filter(user=target_user).values_list('path', flat=True))
        self.assertEqual(readonly_paths, [str(readonly_root.resolve())])

    def test_admin_users_page_cannot_delete_superuser(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        second_admin = User.objects.create_superuser(username='second-admin', email='second@example.com', password='StrongPass123!')
        self.client.force_login(admin_user)

        response = self.client.post(
            '/users/',
            {
                'action': 'delete_user',
                'user_id': second_admin.id,
            },
            follow=True,
        )

        self.assertContains(response, 'Superuser accounts cannot be removed from this page.')
        self.assertTrue(User.objects.filter(pk=second_admin.pk).exists())

    def test_admin_users_page_is_accessible_to_staff(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        staff_user = User.objects.create_user(username='staff-user', password='StrongPass123!', is_staff=True)
        self.client.force_login(staff_user)

        response = self.client.get('/users/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'User management')

    def test_admin_users_alias_route_is_available(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        self.client.force_login(admin_user)

        response = self.client.get('/admin/users/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'User management')

    def test_admin_stats_page_is_accessible_to_staff(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        staff_user = User.objects.create_user(username='staff-user', password='StrongPass123!', is_staff=True)
        self.client.force_login(staff_user)

        response = self.client.get('/users/stats/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin stats')

    def test_admin_stats_page_displays_transfer_and_last_login_values(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        member = User.objects.create_user(username='member', email='member@example.com', password='StrongPass123!')
        User.objects.filter(pk=member.pk).update(last_login=timezone.now())
        stats = UserTransferStats.objects.get(user=member)
        stats.uploaded_bytes = 1234
        stats.downloaded_bytes = 2345
        stats.last_upload_at = timezone.now()
        stats.last_download_at = timezone.now()
        stats.save()

        self.client.force_login(admin_user)
        response = self.client.get('/users/stats/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'member')
        self.assertContains(response, 'member@example.com')
        page_content = response.content.decode()
        self.assertIn('1.2', page_content)
        self.assertIn('2.3', page_content)

    def test_admin_stats_alias_route_is_available(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        self.client.force_login(admin_user)

        response = self.client.get('/admin/users/stats/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin stats')

    def test_admin_todo_page_is_accessible_to_staff(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        self.client.force_login(admin_user)

        response = self.client.get('/users/todo/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin todo')

    @override_settings(FILESHARE_ENABLE_ADMIN_TODO=False)
    def test_admin_todo_page_is_hidden_and_inaccessible_when_disabled(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        self.client.force_login(admin_user)

        todo_response = self.client.get('/users/todo/')
        self.assertEqual(todo_response.status_code, 404)

        space_response = self.client.get('/space/')
        self.assertEqual(space_response.status_code, 200)
        self.assertNotContains(space_response, '>Admin todo')

    def test_admin_todo_items_are_shared_across_staff_users(self):
        first_staff = User.objects.create_user(username='staff-one', password='StrongPass123!', is_staff=True)
        second_staff = User.objects.create_user(username='staff-two', password='StrongPass123!', is_staff=True)
        AdminTodoItem.objects.create(title='Rotate backups', description='Nightly runbook', owner=first_staff)
        self.client.force_login(second_staff)

        response = self.client.get('/users/todo/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rotate backups')
        self.assertContains(response, 'staff-one')
        self.assertContains(response, 'Nightly runbook')

    def test_admin_todo_count_is_shown_in_staff_sidebar(self):
        staff_user = User.objects.create_user(username='staff-count', password='StrongPass123!', is_staff=True)
        AdminTodoItem.objects.create(title='Task one', owner=staff_user)
        AdminTodoItem.objects.create(title='Task two', owner=staff_user)
        self.client.force_login(staff_user)

        response = self.client.get('/users/todo/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '>Admin todo')
        self.assertContains(response, '>2<')

    def test_staff_can_create_edit_and_delete_admin_todo_item(self):
        staff_user = User.objects.create_user(username='staff', password='StrongPass123!', is_staff=True)
        other_staff = User.objects.create_user(username='staff-2', password='StrongPass123!', is_staff=True)
        self.client.force_login(staff_user)

        create_response = self.client.post(
            '/users/todo/',
            {
                'action': 'create_todo',
                'title': 'Review storage alerts',
                'description': 'Initial investigation notes',
                'priority': str(AdminTodoItem.Priority.HIGH),
                'status': AdminTodoItem.Status.PAUSED,
            },
            follow=True,
        )

        self.assertContains(create_response, 'Todo item created.')
        todo_item = AdminTodoItem.objects.get(title='Review storage alerts')
        self.assertEqual(todo_item.owner, staff_user)
        self.assertEqual(todo_item.description, 'Initial investigation notes')
        self.assertEqual(todo_item.status, AdminTodoItem.Status.PAUSED)

        update_response = self.client.post(
            '/users/todo/',
            {
                'action': 'update_todo',
                'todo_id': todo_item.id,
                'title': 'Review storage alerts now',
                'description': 'Blocked by vendor response',
                'priority': str(AdminTodoItem.Priority.URGENT),
                'owner_id': str(other_staff.id),
                'status': AdminTodoItem.Status.BLOCKED,
            },
            follow=True,
        )

        self.assertContains(update_response, 'Todo item updated.')
        todo_item.refresh_from_db()
        self.assertEqual(todo_item.title, 'Review storage alerts now')
        self.assertEqual(todo_item.description, 'Blocked by vendor response')
        self.assertEqual(todo_item.priority, AdminTodoItem.Priority.URGENT)
        self.assertEqual(todo_item.status, AdminTodoItem.Status.BLOCKED)
        self.assertEqual(todo_item.owner, other_staff)

        delete_response = self.client.post(
            '/users/todo/',
            {
                'action': 'delete_todo',
                'todo_id': todo_item.id,
            },
            follow=True,
        )

        self.assertContains(delete_response, 'Todo item deleted.')
        self.assertFalse(AdminTodoItem.objects.filter(pk=todo_item.pk).exists())

    def test_admin_users_page_can_update_share_roots(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        readonly_root = Path(self.temp_dir.name) / 'readonly-root'
        readonly_root_2 = Path(self.temp_dir.name) / 'readonly-root-2'
        readonly_root.mkdir(parents=True, exist_ok=True)
        readonly_root_2.mkdir(parents=True, exist_ok=True)
        user_root = Path(self.temp_dir.name) / 'user-root'
        self.client.force_login(admin_user)

        response = self.client.post(
            '/users/',
            {
                'action': 'set_share_roots',
                'user_storage_root': str(user_root),
                'readonly_storage_roots': f'{readonly_root}\n{readonly_root_2}',
            },
            follow=True,
        )

        self.assertContains(response, 'Share roots updated.')
        configured = SystemShareSettings.get_solo()
        self.assertEqual(configured.user_storage_root, str(user_root.resolve()))
        self.assertEqual(
            configured.readonly_storage_root,
            f'{readonly_root.resolve()}\n{readonly_root_2.resolve()}',
        )
        self.assertTrue(get_user_root(admin_user).is_relative_to(user_root.resolve()))
        roots = get_readonly_roots()
        self.assertEqual(len(roots), 2)
        self.assertEqual(roots[0]['path'], readonly_root.resolve())
        self.assertEqual(roots[1]['path'], readonly_root_2.resolve())

    def test_admin_can_configure_user_specific_readonly_roots_during_user_creation(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        readonly_root = Path(self.temp_dir.name) / 'user-specific-readonly'
        readonly_root.mkdir(parents=True, exist_ok=True)
        (readonly_root / 'guide.txt').write_text('hello', encoding='utf-8')
        self.client.force_login(admin_user)

        response = self.client.post(
            '/users/',
            {
                'action': 'create_user',
                'username': 'readonly-member',
                'email': '',
                'quota_gib': '1.0',
                'readonly_storage_roots': str(readonly_root),
            },
            follow=True,
        )

        self.assertContains(response, 'Configured 1 user-specific read-only share root(s)')

        created_user = User.objects.get(username='readonly-member')
        self.client.force_login(created_user)
        readonly_page = self.client.get('/readonly/')

        self.assertEqual(readonly_page.status_code, 200)
        self.assertContains(readonly_page, 'user-specific-readonly')

    def test_admin_can_create_groups_and_assign_user_membership(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        managed_user = User.objects.create_user(username='group-member', password='StrongPass123!')
        alpha = Group.objects.create(name='Alpha')
        self.client.force_login(admin_user)

        create_group_response = self.client.post(
            '/users/',
            {
                'action': 'create_group',
                'name': 'Beta',
            },
            follow=True,
        )

        self.assertContains(create_group_response, 'Group &quot;Beta&quot; created.')
        beta = Group.objects.get(name='Beta')

        update_response = self.client.post(
            '/users/',
            {
                'action': 'update_user',
                'user_id': str(managed_user.id),
                'email': '',
                'quota_gib': '1.0',
                'readonly_storage_roots': '',
                'groups': [str(alpha.id), str(beta.id)],
            },
            follow=True,
        )

        self.assertContains(update_response, 'User &quot;group-member&quot; updated.')
        managed_user.refresh_from_db()
        self.assertEqual(
            set(managed_user.groups.values_list('name', flat=True)),
            {'Alpha', 'Beta'},
        )

    def test_admin_can_delete_group(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        group = Group.objects.create(name='Disposable')
        self.client.force_login(admin_user)

        response = self.client.post(
            '/users/',
            {
                'action': 'delete_group',
                'group_id': str(group.id),
            },
            follow=True,
        )

        self.assertContains(response, 'Group &quot;Disposable&quot; deleted.')
        self.assertFalse(Group.objects.filter(name='Disposable').exists())

    def test_admin_can_reset_user_password_from_user_list(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        target_user = User.objects.create_user(username='reset-member', password='OldPass123!')
        self.client.force_login(admin_user)

        response = self.client.post(
            '/users/',
            {
                'action': 'reset_user_password',
                'user_id': str(target_user.id),
            },
            follow=True,
        )

        self.assertContains(response, 'Password reset for &quot;reset-member&quot;. Temporary password: ')
        target_user.refresh_from_db()
        self.assertFalse(target_user.check_password('OldPass123!'))

        page_content = response.content.decode()
        match = re.search(r'Password reset for &quot;reset-member&quot;\. Temporary password: ([A-Za-z0-9]+)', page_content)
        self.assertIsNotNone(match)
        self.assertTrue(target_user.check_password(match.group(1)))

    def test_user_specific_readonly_roots_are_not_visible_to_other_users(self):
        owner = User.objects.create_user(username='owner-user', password='StrongPass123!')
        other = User.objects.create_user(username='other-user', password='StrongPass123!')
        root = Path(self.temp_dir.name) / 'private-readonly'
        root.mkdir(parents=True, exist_ok=True)

        from .models import UserReadonlyShare

        UserReadonlyShare.objects.create(user=owner, name='private-readonly', path=str(root.resolve()))

        self.client.force_login(other)
        response = self.client.get('/readonly/')

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'private-readonly')

    def test_admin_users_page_can_set_zero_readonly_roots_and_hide_nav(self):
        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        user_root = Path(self.temp_dir.name) / 'user-root-empty'
        self.client.force_login(admin_user)

        response = self.client.post(
            '/users/',
            {
                'action': 'set_share_roots',
                'user_storage_root': str(user_root),
                'readonly_storage_roots': '',
            },
            follow=True,
        )

        self.assertContains(response, 'Share roots updated.')
        self.assertEqual(get_readonly_roots(), [])

        space_response = self.client.get('/space/')
        self.assertNotContains(space_response, 'Read only libraries')

    def test_non_admin_account_page_can_change_password(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        standard_user = User.objects.create_user(username='standard', password='OldPass123!')
        self.client.force_login(standard_user)

        response = self.client.post(
            '/account/',
            {
                'old_password': 'OldPass123!',
                'new_password1': 'NewPass123!Strong',
                'new_password2': 'NewPass123!Strong',
            },
            follow=True,
        )

        self.assertContains(response, 'Your password has been updated.')
        standard_user.refresh_from_db()
        self.assertTrue(standard_user.check_password('NewPass123!Strong'))

    def test_non_admin_account_page_shows_stats_above_password_card(self):
        User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!')
        standard_user = User.objects.create_user(username='standard', password='OldPass123!')
        user_root = get_user_root(standard_user)
        (user_root / 'usage.txt').write_bytes(b'12345')
        stats = UserTransferStats.objects.get(user=standard_user)
        stats.uploaded_bytes = 2048
        stats.downloaded_bytes = 1024
        stats.last_upload_at = timezone.now()
        stats.last_download_at = timezone.now()
        stats.save()
        self.client.force_login(standard_user)

        response = self.client.get('/account/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'My stats')
        self.assertContains(response, 'Storage usage')
        self.assertContains(response, 'Uploaded total')
        self.assertContains(response, 'Downloaded total')
        page_content = response.content.decode()
        self.assertLess(page_content.index('My stats'), page_content.index('My password'))

    def test_staff_changes_password_from_users_and_settings_page(self):
        staff_user = User.objects.create_user(username='staff', password='OldPass123!', is_staff=True)
        self.client.force_login(staff_user)

        response = self.client.post(
            '/users/',
            {
                'action': 'change_password',
                'old_password': 'OldPass123!',
                'new_password1': 'NewStaffPass123!Strong',
                'new_password2': 'NewStaffPass123!Strong',
            },
            follow=True,
        )

        self.assertContains(response, 'Your password has been updated.')
        staff_user.refresh_from_db()
        self.assertTrue(staff_user.check_password('NewStaffPass123!Strong'))

    def test_staff_user_redirected_from_account_page(self):
        staff_user = User.objects.create_user(username='staff', password='StrongPass123!', is_staff=True)
        self.client.force_login(staff_user)

        response = self.client.get('/account/')

        self.assertRedirects(response, '/users/')

    def test_deleting_user_removes_storage_files_and_folders(self):
        user = User.objects.create_user(username='cleanup-user', password='StrongPass123!')
        user_root = get_user_root(user)
        nested_dir = user_root / 'nested'
        nested_dir.mkdir(parents=True, exist_ok=True)
        (nested_dir / 'file.txt').write_text('cleanup me', encoding='utf-8')

        self.assertTrue((nested_dir / 'file.txt').exists())

        user.delete()

        self.assertFalse(user_root.exists())

