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

Send push notifications to iPhone via [Bark](https://github.com/Finb/Bark). Zero external dependencies (Python 3 stdlib only).

## Quick Usage

### 1. Task Completion (Agent Workflows)
Send structured notifications when an AI agent task finishes:
```bash
python3 scripts/send_bark_notification.py \
  --task-title "Fix auth bug" \
  --status success \
  --summary "Patched JWT validation in middleware"
```
- **`--status` options**: `success` (✅), `failed` (❌), `partial` (⚠️), `blocked` (🚫), `info` (ℹ️), `warning` (⚠️).
- Auto-detects device name from `.env` and project name from `AGENTS.md` (or override with `--project-name`).

### 2. Direct Push Notification
Send arbitrary notifications with full parameter control:
```bash
python3 scripts/send_bark_notification.py \
  --title "Deploy Complete" \
  --body "v2.1.0 deployed to production" \
  --sound birdsong \
  --group deploys \
  --level timeSensitive \
  --url "https://dashboard.example.com"
```

## Parameter Reference

| Flag | Bark Param | Description |
|------|------------|-------------|
| `--title` | `title` | Notification title (larger font) |
| `--subtitle` | `subtitle` | Notification subtitle |
| `--body` | `body` | Notification body text |
| `--markdown` | `markdown` | Body as Markdown (replaces `--body`) |
| `--sound` | `sound` | Notification ringtone name |
| `--group` | `group` | Group name in iOS notification center |
| `--icon` | `icon` | Custom icon URL (iOS 15+, cached locally) |
| `--image` | `image` | Image URL displayed in notification |
| `--url` | `url` | URL or URL scheme to open on tap |
| `--copy` | `copy` | Text to copy on long-press |
| `--auto-copy` | `autoCopy` | Automatically copy text to clipboard (iOS ≤ 14.5) |
| `--level` | `level` | `active` (default), `timeSensitive`, `passive`, `critical` |
| `--volume` | `volume` | Volume for critical alerts (`0`–`10`) |
| `--badge` | `badge` | App icon badge count |
| `--call` | `call` | Repeat ringtone for 30s |
| `--is-archive` | `isArchive` | Force archive into Bark history |
| `--action` | `action` | Action on tap (`alert` or `none`) |
| `--notify-id` | `id` | Unique ID for updating or deleting notifications |
| `--delete` | `delete` | Delete notification specified by `--notify-id` |
| `--encrypt` | — | Encrypt payload with AES (requires `.env` encryption config) |
| `--dry-run` | — | Preview request without sending (keys are redacted) |

### Interruption Levels (`--level`)

| Level | Behavior |
|-------|----------|
| `active` | Default: wakes screen immediately |
| `timeSensitive` | Breaks through iOS Focus Modes |
| `passive` | Silent: enters notification center without screen wake |
| `critical` | Overrides Mute & Do Not Disturb switches, always rings |

### Common Sounds (`--sound`)
`alarm`, `anticipate`, `bell`, `birdsong`, `bloom`, `calypso`, `chime`, `electronic`, `fanfare`, `glass`, `gotosleep`, `healthnotification`, `horn`, `mailsent`, `minuet`, `paymentsuccess`, `silence`, `telegraph`, `update`.

## Configuration & Fallback Hierarchy

Configuration is automatically resolved in order:
1. Local `.env` in skill directory (`<skill_dir>/.env`)
2. Global `.env` in user home (`~/.agents/skills/bark-notify/.env`)
3. Environment variables (`BARK_KEY`, `BARK_BASE_URL`, `BARK_MACHINE_NAME`)

### Quick Setup

To configure or update settings non-interactively:
```bash
python3 scripts/setup.py "https://your-bark-server/YOUR_KEY/" --force
```

### Configuration Keys (`.env`)

| Key | Required | Description |
|-----|:--------:|-------------|
| `BARK_KEY` | ✅ | Device key from the Bark iOS app |
| `BARK_BASE_URL` | ✅ | Bark server base URL (default: `https://api.day.app`) |
| `BARK_MACHINE_NAME` | — | Machine/device label shown in task pushes |
| `BARK_ENCRYPT_ALGORITHM` | — | `AES128` / `AES192` / `AES256` |
| `BARK_ENCRYPT_MODE` | — | `CBC` / `ECB` / `GCM` (default: `CBC`) |
| `BARK_ENCRYPT_KEY` | — | Secret encryption key matching algorithm length |
| `BARK_ENCRYPT_IV` | — | Initialization vector (16 bytes for CBC, 12 for GCM) |
