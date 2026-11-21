# FileBee Telegram Bot

A Render-ready Telegram bot project using **Pyrogram + TgCrypto**, SQLite and a live Flask dashboard. It has automatic user/admin command menus, per-user link collections, FileBee URL capture, download buttons, admin tools, and an optional streaming upload adapter.

## Important FileBee.live integration note

The target domain is **https://filebee.live/**. Its publicly accessible page currently renders as a JavaScript application, and this build could not verify a public upload API, authentication contract, folder API, provider-side expiry controls, or a 4GB per-file limit. The project deliberately does **not** invent API URLs or field names.

As supplied, the project runs in **FileBee link mode**:

1. A user opens FileBee from `/start` or `/upload`.
2. The user uploads their file on the FileBee website.
3. The user sends the resulting HTTPS `filebee.live` or `*.filebee.live` share link to the bot.
4. The bot saves the URL in that Telegram user's collection and replies with a Download button.

The bot does not claim that a Telegram attachment has been uploaded to FileBee unless a real API endpoint has been configured and returned a valid FileBee URL.

### Optional streaming upload adapter

`filebee.py` contains a generic streaming multipart adapter, disabled by default. If FileBee provides an official API, set its real endpoint and response contract in Render environment variables. The adapter streams MTProto chunks and does not save the entire media file to Render disk. It expects a multipart form upload using the configured file field and a JSON response containing a FileBee share URL.

This generic adapter is an integration hook, **not a claim that FileBee.live currently supports this API shape**. You must use the exact parameters from FileBee's official documentation before enabling it.

## Features

- Pyrogram MTProto client with TgCrypto acceleration.
- Telegram media handling for documents, photos, videos, audio, voice, animations, video notes and stickers.
- Per-user local collection named with the Telegram numeric user ID.
- User join/collection creation date and optional bot-side tracking expiry.
- FileBee share-link capture from messages and `/download URL`.
- Download buttons for saved FileBee URLs.
- `/myfiles`, `/folder`, `/status`, `/id`, `/help`, `/upload`.
- Admin commands `/admin`, `/stats`, `/users`, `/setexpiry`, `/ban`, `/unban`, `/broadcast`, `/filebeecheck`.
- User and admin commands registered automatically with Telegram.
- Live dashboard with bot state, uptime, users, saved links, counts and server time.
- Render health endpoint `/health` and persistent SQLite disk support.
- Streaming multipart adapter hook for a future confirmed FileBee API.

## User commands

| Command | Description |
|---|---|
| `/start` | Create the bot-side user collection |
| `/upload` | Show FileBee upload instructions |
| `/myfiles` | Show the latest saved links |
| `/folder` | Show user ID, collection creation time and tracking expiry |
| `/download URL` | Generate a FileBee download button |
| `/status` | Show bot status and uptime |
| `/id` | Show Telegram user ID |
| `/help` | Show command help |

Users can also send a FileBee share URL as a normal text message; the bot saves it automatically.

## Admin commands

Configure `ADMIN_IDS` as comma-separated Telegram numeric user IDs.

| Command | Description |
|---|---|
| `/admin` | Admin overview |
| `/stats` | Usage statistics |
| `/users` | Recent users |
| `/setexpiry USER_ID DAYS` | Set bot-side link tracking expiry (`0` disables) |
| `/ban USER_ID` | Ban a user |
| `/unban USER_ID` | Unban a user |
| `/broadcast TEXT` | Send an announcement |
| `/filebeecheck` | Show current FileBee integration mode |

**Expiry clarification:** the bot can show the creation date and its own link-index expiry date. It cannot set, read, or enforce FileBee's remote file expiry without a documented FileBee API. `/setexpiry` changes only the bot-side tracking record; it does not delete FileBee-hosted content.

## Local installation

Python 3.11 is recommended.

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
```

Fill in `API_ID`, `API_HASH`, `BOT_TOKEN`, and `ADMIN_IDS` in `.env`, then run:

```bash
python bot.py
```

## Render deployment

1. Push this folder to a GitHub repository.
2. Create a Render **Web Service** from the repository using the included `render.yaml` / Dockerfile.
3. Add `API_ID`, `API_HASH`, `BOT_TOKEN`, `ADMIN_IDS`, and a strong `DASHBOARD_PASSWORD` in Render Environment.
4. Keep `DATABASE_PATH=/var/data/bot.db`; the Blueprint defines a persistent disk mounted at `/var/data`.
5. Deploy. Open `https://YOUR-SERVICE.onrender.com/` for the dashboard and `/health` for the liveness check.

A paid always-on Render plan is needed for continuous operation; free instances may spin down.

## Environment variables

| Variable | Required | Purpose |
|---|---:|---|
| `API_ID` | Yes | Telegram API ID from my.telegram.org |
| `API_HASH` | Yes | Telegram API hash |
| `BOT_TOKEN` | Yes | Token from BotFather |
| `ADMIN_IDS` | Recommended | Comma-separated Telegram admin IDs |
| `FILEBEE_WEBSITE` | No | Defaults to `https://filebee.live` |
| `FILEBEE_UPLOAD_URL` | No | Official FileBee upload endpoint; leave blank until verified |
| `FILEBEE_API_TOKEN` | No | API token if FileBee's documented endpoint requires one |
| `FILEBEE_AUTH_HEADER` | No | Defaults to `Authorization` |
| `FILEBEE_AUTH_PREFIX` | No | Defaults to `Bearer ` |
| `FILEBEE_FILE_FIELD` | No | Multipart file field; default `file` |
| `FILEBEE_RESPONSE_URL_FIELD` | No | JSON path to returned share URL, e.g. `data.share_url` |
| `FILEBEE_UPLOAD_TIMEOUT` | No | Upload timeout seconds; default 3600 |
| `MAX_FILE_GB` | No | Bot guard (1–4); does not override Telegram or FileBee limits |
| `LINK_RECORD_TTL_DAYS` | No | Bot-side index expiry; `0` means no expiry |
| `DATABASE_PATH` | No | SQLite path; use `/var/data/bot.db` on Render |
| `PORT` | No | Dashboard port; Render supplies it |
| `DASHBOARD_USER` | No | Dashboard Basic Auth username |
| `DASHBOARD_PASSWORD` | Recommended | Dashboard Basic Auth password |
| `BOT_NAME` | No | Display name |

## 4GB transfer note

`MAX_FILE_GB=4` is only a local guard. It is not proof that Telegram or FileBee accepts a 4GB file. End-to-end 4GB transfer requires all of the following: Telegram account/session can access the source file at that size, FileBee officially accepts the file size, its endpoint supports streamed/chunked multipart uploads, sufficient provider quota exists, and the Render instance has enough network/runtime allowance. Verify those limits with the respective providers before production use.

## Security notes

- Never commit `.env`, Telegram session files, bot tokens or provider API credentials.
- Use HTTPS URLs only; the link collector only accepts FileBee.live hostnames and subdomains.
- Set a strong dashboard password and keep the Render disk private.
- Only store/share files you own or are authorized to distribute.
