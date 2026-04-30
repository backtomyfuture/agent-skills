---
name: bark-notify
description: >-
  Send Bark (day.app) push notifications to iPhone. Use when an agent run finishes,
  a task completes, or whenever the user needs to be notified. Also use for sending
  custom push notifications with advanced features like custom sounds, icons, images,
  groups, critical alerts, time-sensitive notifications, Markdown content, click-to-copy,
  URL jumps, badge updates, repeated ringtones (call mode), and AES-encrypted push.
  Trigger on: "notify me", "send a push", "bark", "push notification", "alert me",
  "提醒我", "推送通知", or any task completion notification.
---

# Bark Notify

Send [Bark](https://github.com/Finb/Bark) push notifications to your iPhone.
Bark is a free, open-source iOS push tool based on Apple APNs — battery-friendly,
reliable, and private. Zero external Python dependencies.

## Quick Start

### 1. Install the Bark iOS App

Download [Bark](https://apps.apple.com/app/bark-custom-notifications/id1403753865)
from the App Store and allow notifications.

### 2. Run Setup

Open the Bark app, copy the example URL (looks like
`https://api.day.app/YOUR_KEY/test`), then run:

```bash
python3 ~/.agents/skills/bark-notify/scripts/setup.py "PASTE_YOUR_BARK_URL_HERE"
```

The setup script automatically parses the URL to extract your server address and
device key, then writes the `.env` config file. It works with any Bark URL format —
official server, self-hosted, custom port, etc.

Alternatively, copy and edit manually:

```bash
cp ~/.agents/skills/bark-notify/.env.example ~/.agents/skills/bark-notify/.env
# Then edit .env with your BARK_KEY and BARK_BASE_URL
```

### 3. Test It

```bash
python3 ~/.agents/skills/bark-notify/scripts/send_bark_notification.py \
  --title "Hello" --body "Bark is ready!" --sound chime
```

If your iPhone buzzes, you're all set.

## Configuration (.env)

The `.env` file lives in the skill directory. All config is read from it (not
from shell environment variables), so each skill installation is self-contained.

| Key | Required | Description |
|-----|----------|-------------|
| `BARK_KEY` | ✅ | Device key from the Bark app |
| `BARK_BASE_URL` | ✅ | Bark server URL (no trailing slash) |
| `BARK_MACHINE_NAME` | — | Device name shown in task notifications |
| `BARK_ENCRYPT_ALGORITHM` | — | `AES128` / `AES192` / `AES256` |
| `BARK_ENCRYPT_MODE` | — | `CBC` / `ECB` / `GCM` (default: CBC) |
| `BARK_ENCRYPT_KEY` | — | Encryption key (must match algorithm length) |
| `BARK_ENCRYPT_IV` | — | IV (16 bytes for CBC, 12 for GCM, N/A for ECB) |

If `.env` is missing or `BARK_KEY` is empty, the script prints a guided setup
prompt instead of failing silently.

## Usage

Two modes: **task completion** (for agent workflows) and **direct API** (for
any custom push).

### Mode 1 — Task Completion

Designed for AI agent task-done notifications. Generates a structured message
with device name, project, status emoji, and summary.

```bash
python3 scripts/send_bark_notification.py \
  --task-title "Fix login bug" \
  --status success \
  --summary "Fixed null pointer in auth middleware"
```

Status values: `success` ✅ · `failed` ❌ · `partial` ⚠️ · `blocked` 🚫 ·
`info` ℹ️ · `warning` ⚠️

The `--project-name` flag overrides auto-detection. Otherwise, the script walks
up the directory tree looking for `AGENTS.md` to extract the project name from
YAML frontmatter (`project_name:`) or plain text (`Project Name: ...` /
`项目名称：...`), falling back to the folder name.

### Mode 2 — Direct Bark API

Send any notification with full Bark parameter control:

```bash
python3 scripts/send_bark_notification.py \
  --title "Deploy Complete" \
  --body "v2.1.0 deployed to production" \
  --sound birdsong \
  --group deploys \
  --icon "https://example.com/rocket.png" \
  --url "https://dashboard.example.com" \
  --level timeSensitive
```

## Bark API Parameters

Every official Bark parameter is supported as a CLI flag:

| Flag | Bark Param | Description |
|------|-----------|-------------|
| `--title` | `title` | Notification title (larger font) |
| `--subtitle` | `subtitle` | Notification subtitle |
| `--body` | `body` | Notification body text |
| `--markdown` | `markdown` | Body as Markdown (replaces `--body`) |
| `--sound` | `sound` | Notification sound name |
| `--icon` | `icon` | Custom icon URL (iOS 15+, cached on device) |
| `--image` | `image` | Image URL displayed in the notification |
| `--group` | `group` | Group name for notification center |
| `--url` | `url` | URL to open on tap (URL Scheme / Universal Link) |
| `--copy` | `copy` | Text to copy on long-press |
| `--auto-copy` | `autoCopy` | Auto-copy content (iOS ≤ 14.5) |
| `--level` | `level` | Interruption level (see below) |
| `--volume` | `volume` | Critical alert volume, 0–10 |
| `--badge` | `badge` | App icon badge number |
| `--call` | `call` | Repeat ringtone for 30 seconds |
| `--is-archive` | `isArchive` | Force save to notification history |
| `--action` | `action` | `alert` = popup on tap; `none` = do nothing |
| `--notify-id` | `id` | Notification ID (for update/delete) |
| `--delete` | `delete` | Delete notification by `--notify-id` |
| `--encrypt` | — | Encrypt payload (requires .env encryption config) |
| `--dry-run` | — | Print the request without sending |

### Interruption Levels

| Level | Behavior |
|-------|----------|
| `active` | Default — lights up screen immediately |
| `timeSensitive` | Breaks through Focus Mode |
| `passive` | Silent — notification list only, no screen wake |
| `critical` | Overrides Silent and Do Not Disturb, always plays sound |

### Available Sounds

Built-in: `alarm` · `anticipate` · `bell` · `birdsong` · `bloom` · `calypso` ·
`chime` · `choo` · `descent` · `electronic` · `fanfare` · `glass` ·
`gotosleep` · `healthnotification` · `horn` · `ladder` · `mailsent` ·
`minuet` · `multiwayinvitation` · `newmail` · `newsflash` · `noir` ·
`paymentsuccess` · `shake` · `sherwoodforest` · `silence` · `spell` ·
`suspense` · `telegraph` · `tiptoes` · `typewriters` · `update`

You can also add custom `.caf` ringtone files to the Bark app.

## Encryption

Bark supports AES end-to-end encryption — the server and Apple APNs never see
plaintext content.

1. Open Bark iOS app → Settings → Encryption, configure algorithm/key/IV
2. Set matching `BARK_ENCRYPT_*` values in `.env`
3. Add `--encrypt` when sending

| Algorithm | Key Length | Supported Modes |
|-----------|-----------|-----------------|
| AES128 | 16 bytes | CBC, ECB, GCM |
| AES192 | 24 bytes | CBC, ECB, GCM |
| AES256 | 32 bytes | CBC, ECB, GCM |

The script tries PyCryptodome first, then falls back to the `openssl` CLI
(available by default on macOS and most Linux). No pip install needed.

## Examples

```bash
SCRIPT=~/.agents/skills/bark-notify/scripts/send_bark_notification.py

# Simple notification
python3 $SCRIPT --title "Hello" --body "World"

# Critical alert that rings even in silent mode
python3 $SCRIPT --title "🔥 Server Down" --body "prod-1 unreachable" \
  --level critical --sound alarm --call

# Notification with image and click-to-open URL
python3 $SCRIPT --title "PR Merged" --body "#142 merged to main" \
  --image "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png" \
  --url "https://github.com/org/repo/pull/142" --group github

# Markdown content
python3 $SCRIPT --title "Report" \
  --markdown "## Summary\n- Users: **1,234**\n- Revenue: \$56K"

# Update an existing notification
python3 $SCRIPT --title "Build" --body "Building..." --notify-id build-1
python3 $SCRIPT --title "Build" --body "Build complete ✅" --notify-id build-1

# Delete a notification
python3 $SCRIPT --notify-id build-1 --delete --title " " --body " "

# Encrypted push
python3 $SCRIPT --title "Secret" --body "Classified info" --encrypt

# Dry run (print without sending)
python3 $SCRIPT --title "Test" --body "Preview" --dry-run
```

## File Structure

```
bark-notify/
├── SKILL.md              # This file — skill instructions
├── .env.example          # Config template (safe to commit)
├── .env                  # Your actual config (git-ignored)
├── .gitignore
├── LICENSE               # MIT
└── scripts/
    ├── setup.py          # Interactive setup from Bark URL
    └── send_bark_notification.py  # Main notification sender
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Configuration Required" | Run `python3 scripts/setup.py "YOUR_URL"` |
| "BARK_KEY is empty" | Edit `.env` and fill in `BARK_KEY` |
| HTTP 400 | Check that `BARK_KEY` is correct |
| SSL errors | Your server may need `--timeout 30` for slow TLS handshakes |
| Encryption fails | Ensure key length matches algorithm, and PyCryptodome or `openssl` is available |
| No notification received | Check iOS notification permissions for Bark |
