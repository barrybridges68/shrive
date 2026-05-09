# Shrive (Self Hosted Drive)

Shrive is a simple self hosted Django-based drive app for home use. It is not intended to replace services like Google Drive or Dropbox, but it has practical uses at home. It was originally intended for sharing media and photos around the family without big tech getting involved (puts on tinfoil hat!).

Although being a software developer, Django is not my speciallity. So there's a lot of google searches and Co-pilot bits of code in here. I needed a tool for a the job and I didn't want to spend more than a weekend on it. So sorry, not sorry if there's a bug or three in here.

WebDav was added as I wish to back up to this app. This is not tested yet, although I will do soon.

Finially, there is no integration to email or notification services. I'll have think on this as it will be useful especially when sharing links, but out of the scope of what I need right now.

Always happy to hear from others for suggestion or bug reports

This is still early days, so I expect bugs and user flow issues until I get to fully use it myslef.

Note: This is not currently a very mobile friendly application. It's works, but not ideal. I might look into this, but using it on a mobile device is not my main use case.

## Features

- First-run setup page that creates the initial admin username and password.
- Allows for multiple users with Django authentication.
- Per-user storage with quotas (set by Admin).
- Groups for keeping users seperate.
- Usage stats.
- The ability to up load files and folders.
- Selective sharing of files or folders between users.
- Creation of upload and download links for external users.
- Configurable read-only access to other folders on the host system.
- No pracical upload limit apart from your quotas.
- Basic file editing of text based files.
- Simple ToDo app for Admin (if enabled).
- Audit log to see what's blown-up!
- WebDAV access for each user's own storage space.

## Install

1. Clone the repo from with `git clone https://github.com/barrybridges68/shrive.git`
2. Edit the docker-compose.yml and add you domain name to `DJANGO_ALLOWED_HOSTS`. Careful not to add any spaces to it as it gets a touchy about it.
3. You must change the Django secret key `DJANGO_SECRET_KEY`
4. Change the port if required.
5. You can change the mount point for the storage, but I recommend you don't. This is where your uploaded files are stored. Do not edit files within this folder outside of the application or things will get out of sync. Also make sure you access rights to the mount piont are correct. You have been warned!
5. `docker compose up -d --build`
6. Open a browser and behold (Well sort of).

```
services:
  web:
    build:
      context: .
    ports:
      - "8037:8000"
    environment:
      DJANGO_DEBUG: "0"
      DJANGO_ALLOWED_HOSTS: "localhost,127.0.0.1"
      DJANGO_SECRET_KEY: "change-me-before-production"
      FILESHARE_ENABLE_ADMIN_TODO: "0"
      GUNICORN_WORKERS: "3"
      GUNICORN_TIMEOUT: "120"
    volumes:
      - ./data:/app/storage
    restart: unless-stopped

```

## The Todo List

This is an extremely simple ToDo app. I usually add one as the first feature when building an app to keep track of things as I develope it. This may or may not be of use to you, but you're welcome to use it. Just change `FILESHARE_ENABLE_ADMIN_TODO` to `1` and it's enabled.

# First Run

When you run the container for the first time you will be promted for your credentials for the Admin. The email address is currently not used, but maybe later for notifications, so please enter it correctly. It can be changed within the account seetings or for an Admin within the user settings.

Once the Admin is logged in, goto Admin Settings and set any required settings. The base URL needs to set for the external links. So if you domain is for example abc.xyz.com, Set it to this.

Finally, set the time zone for the Admin. This ensures your files have the right time stamps on.



# My Drive Area

## Uploading Files
There are two ways to upload files. Firstly for PC and tablet users you can just drag and drop files or folders into the upload area. Please be aware that when uploading folders it will recursivly upload all files and folders under the select folder. Secondly, clicking (or tapping) on the upload area gives you the options to upload.

## The File Browser

# My Shares

## My Shares
There are 4 types of share
- Shares with people. You can share with anyone within your defined groups. The groups are set by the Admin
- Shares with group. All people within those groups will see this file/folders.
- Public Sharable link. A web link is created, and will point to a web page where someone external from a user of this site can see the files you have selected.
- Finally, although not really a share, you can generate a link to a page where a perosn who is not a user on the site can upload files to. This will be visible only to the creator of the link.

# Shared with me
Simply shows all files shared with you.


## WebDAV API (WebDAV is co-pilot generated code)

Shrive now exposes a WebDAV endpoint at `/dav/`.

- Scope: each authenticated user accesses only their own drive root.
- Auth: WebDAV API key (generated in account settings), via HTTP Basic or Bearer auth.
- Methods: `OPTIONS`, `PROPFIND`, `GET`, `HEAD`, `PUT`, `DELETE`, `MKCOL`, `COPY`, `MOVE`.

Examples:

```bash
# List root metadata
curl -u anyname:YOUR_API_KEY -X PROPFIND -H "Depth: 1" http://YOUR_URL:YOUR_PORT/dav/

# Upload/replace a file
curl -u anyname:YOUR_API_KEY -T ./notes.txt http://YOUR_URL:YOUR_PORT/dav/notes.txt

# Create a folder
curl -u anyname:YOUR_API_KEY -X MKCOL http://YOUR_URL:YOUR_PORT/dav/projects
```

# Disclamer, warning, what ever you want to call it.

This project may delete your files. It is your responcability to maintain your files safely. Keep a backup, don't allow access to files you don't want shared, and gernerally don't be a dick with valuable data. I take no responcabilty for this application in any way. Use it at your own risk. That said, it you use it and find it useful, enjoy.

# Licence
Free to use, but no part of this work can be used for commercial purposes.
