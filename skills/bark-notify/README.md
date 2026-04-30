# 🔔 bark-notify

An [Amp](https://ampcode.com) / [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that sends [Bark](https://github.com/Finb/Bark) push notifications to your iPhone.

Bark is a free, open-source iOS app that lets you receive custom push notifications via a simple HTTP API, powered by Apple APNs.

**Zero external dependencies** — uses only Python 3 stdlib.

## Features

- 📱 **Full Bark API** — title, subtitle, body, Markdown, sound, icon, image, group, URL, copy, badge, and more
- 🔕 **Interruption levels** — active, timeSensitive, passive, critical (rings through Do Not Disturb)
- 📞 **Call mode** — repeat ringtone for 30 seconds
- 🔐 **AES encryption** — end-to-end encrypted push (AES-128/192/256, CBC/ECB/GCM)
- 🤖 **Agent integration** — task completion mode with auto-detected project names
- ⚡ **One-command setup** — paste your Bark URL and go
- 🔒 **Secure by default** — `.env` is git-ignored, `.env.example` is the template

## Quick Start

### 1. Prerequisites

- Python 3.6+
- [Bark iOS app](https://apps.apple.com/app/bark-custom-notifications/id1403753865) installed with notifications enabled
- A Bark server (the [official public server](https://api.day.app) works out of the box, or [self-host](https://github.com/Finb/bark-server))

### 2. Install the Skill

```bash
npx skills add backtomyfuture/bark-notify
```

### 3. Setup

Open the Bark iOS app, copy the example URL, then run:

```bash
python3 scripts/setup.py "https://api.day.app/YOUR_KEY/test"
```

This parses your URL and creates the `.env` config file. Works with any format:

```
https://api.day.app/abcdefg/test              → Official server
https://bark.example.com/abcdefg/             → Self-hosted
https://example.com:8080/abcdefg/test push    → Custom port
```

### 4. Test

```bash
python3 scripts/send_bark_notification.py --title "Hello" --body "It works!" --sound chime
```

## Usage

### Task Completion (for AI agents)

```bash
python3 scripts/send_bark_notification.py \
  --task-title "Fix auth bug" \
  --status success \
  --summary "Patched JWT validation in middleware"
```

### Direct Push

```bash
python3 scripts/send_bark_notification.py \
  --title "Deploy" \
  --body "v2.0 is live" \
  --sound birdsong \
  --group deploys \
  --level timeSensitive \
  --url "https://dashboard.example.com"
```

### More Examples

```bash
# Critical alert (overrides Silent / DND)
python3 scripts/send_bark_notification.py \
  --title "🔥 Alert" --body "Server down" --level critical --call

# With image
python3 scripts/send_bark_notification.py \
  --title "Screenshot" --body "New design" --image "https://i.imgur.com/xxx.png"

# Encrypted push
python3 scripts/send_bark_notification.py \
  --title "Secret" --body "Classified" --encrypt

# Dry run
python3 scripts/send_bark_notification.py \
  --title "Test" --body "Preview" --dry-run
```

## Configuration

All config lives in `.env` (not environment variables):

| Key | Required | Description |
|-----|----------|-------------|
| `BARK_KEY` | ✅ | Your device key from the Bark app |
| `BARK_BASE_URL` | ✅ | Bark server URL |
| `BARK_MACHINE_NAME` | — | Device name in task notifications |
| `BARK_ENCRYPT_ALGORITHM` | — | `AES128` / `AES192` / `AES256` |
| `BARK_ENCRYPT_MODE` | — | `CBC` / `ECB` / `GCM` |
| `BARK_ENCRYPT_KEY` | — | Encryption key |
| `BARK_ENCRYPT_IV` | — | Initialization vector |

## All CLI Flags

| Flag | Description |
|------|-------------|
| `--title` | Notification title |
| `--subtitle` | Notification subtitle |
| `--body` | Notification body |
| `--markdown` | Body as Markdown (replaces `--body`) |
| `--sound` | Sound name (`alarm`, `chime`, `birdsong`, ...) |
| `--icon` | Custom icon URL (iOS 15+) |
| `--image` | Image URL |
| `--group` | Notification group |
| `--url` | URL on tap |
| `--copy` | Text to copy on long-press |
| `--auto-copy` | Auto-copy content |
| `--level` | `active` / `timeSensitive` / `passive` / `critical` |
| `--volume` | Critical alert volume (0–10) |
| `--badge` | App badge number |
| `--call` | Repeat ringtone 30s |
| `--is-archive` | Force save to history |
| `--action` | `alert` or `none` |
| `--notify-id` | Notification ID (update/delete) |
| `--delete` | Delete by `--notify-id` |
| `--encrypt` | Encrypt payload |
| `--dry-run` | Preview without sending |
| `--setup` | Run interactive setup |

## How It Works

```
Agent / Script
    │
    ▼
send_bark_notification.py  ──reads──▶  .env (BARK_KEY, BARK_BASE_URL)
    │
    ▼  POST JSON
Bark Server (self-hosted or api.day.app)
    │
    ▼  APNs
iPhone (Bark app)
```

## License

[MIT](LICENSE)

## Credits

- [Bark](https://github.com/Finb/Bark) by Finb — the iOS app
- [bark-server](https://github.com/Finb/bark-server) — the server component
