# Shrive (Self Hosted Drive)

A simple self hosted Django based file-sharing project or home use. It is not intended to be a replacement for services like Google Drive or Drop Box, but it has it's uses at home. Was orginally intended for sharing media, photos etc around the family without big tech getting involved.

## What it supports

- Allows for multiple users with Django authentication.
- Per-user private storage by default.
- Selective sharing of files or folders across users with `view` or `edit` access.
- Per-user quota enforcement managed by the system administrator.
- First-run setup page that creates the initial admin username and password.
- Configurable read-only access to other folders on the host system.
- Configurable root storage folder inside the project settings.
- No application-level upload size cap in Django.
- Basic file editing of text based files

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

## Notes

- Django is configured with `DATA_UPLOAD_MAX_MEMORY_SIZE = None`, so the app does not impose its own request-size cap. A reverse proxy or web server in front of Django may still need separate tuning.
- Shared `edit` access allows uploads, folder creation, and deletion inside the shared folder.

# Disclamer, warning, what ever you want to call it.

This project may delete your files. It is your responcability to maintain your files safely. Keep a backup, don't allow access to files you don't want shared, and gernerally don't be a dick with valuable data. I take no responcabilty for this application in any way. Use it at your own risk. That said, it you use it and find it useful, enjoy.

# Licence
Free to use, but no part of this work can be used for commercial purposes.
