# FileShare

A Django file-sharing project with a Google Drive-style workflow and a Bootstrap dashboard shell based on the template from `/home/barry/Documents/Projects/musk-design-web`.

## What it supports

- Multiple users with Django authentication.
- Per-user private storage by default.
- Selective sharing of files or folders across users with `view` or `edit` access.
- Per-user quota enforcement managed by the system administrator.
- First-run setup page that creates the initial admin username and password.
- Configurable read-only access to other folders on the host system.
- Configurable root storage folder inside the project settings.
- No application-level upload size cap in Django.

## Key settings

Edit `config/settings.py` and review:

- `FILESHARE_STORAGE_ROOT`: root folder used for user-owned storage.
- `FILESHARE_READONLY_ROOTS`: list of read-only external folders to expose in the UI.
- `FILESHARE_DEFAULT_QUOTA_BYTES`: default storage allocation for new users.

Example:

```python
FILESHARE_STORAGE_ROOT = BASE_DIR / 'storage'
FILESHARE_READONLY_ROOTS = [
    {'name': 'Reference Docs', 'path': '/srv/reference'},
]
FILESHARE_DEFAULT_QUOTA_BYTES = 10 * 1024 * 1024 * 1024
```

## Run it

```bash
cd /home/barry/Documents/Projects/FileShare
source .venv/bin/activate
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

## Docker

Build and run with Docker Compose:

```bash
docker compose up --build
```

The container starts with Gunicorn, runs migrations automatically, collects static files, and stores runtime data in a persistent Docker volume mounted at `/data`.

Open `http://127.0.0.1:8000/`.

## Admin workflow

1. On first launch, visit `/` and create the initial admin account.
2. Open `/admin/` with that account.
3. Create additional users in Django admin.
4. Set or adjust each user quota in `User storage profiles`.

## Requirement check

1. Multiple users with login and access rights: implemented with Django auth, admin roles, and per-share permissions.
2. Sharing across users when selected: implemented with share actions on files and folders.
3. Upload to a user’s own space by default with no app-level file size limit: implemented.
4. Variable for storage root and variable for read-only external paths: implemented in settings.
5. Per-user space limit set by system admin: implemented through `UserStorageProfile` in admin.
6. First use sets admin username and password: implemented at `/setup/` and redirected from `/` until complete.
7. Use the Bootstrap template in `/home/barry/Documents/Projects/musk-design-web/`: implemented by reusing copied theme assets and layout patterns.
8. Create the project in `/home/barry/Documents/Projects/FileShare`: implemented.
9. Standard file manager look and feel: implemented with sidebar navigation, folder/file listing, breadcrumbs, and action toolbar.
10. Rechecked all requirements: covered above.

## Notes

- Django is configured with `DATA_UPLOAD_MAX_MEMORY_SIZE = None`, so the app does not impose its own request-size cap. A reverse proxy or web server in front of Django may still need separate tuning.
- Shared `edit` access allows uploads, folder creation, and deletion inside the shared folder.
