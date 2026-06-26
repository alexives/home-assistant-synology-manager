# Synology Manager

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alexives&repository=home-assistant-synology-manager&category=integration)

A Home Assistant custom integration for managing packages on Synology NAS devices — update entities for DSM firmware, installed packages, and Docker containers, plus switch entities for Docker compose project control.

> [!NOTE]
> This integration was almost entirely AI-coded (Claude). It has automated tests and works against a real NAS, but it has not had a thorough line-by-line human review. Use at your own risk, review it before trusting it on your system, and please report any issues.

## Features

- **DSM Firmware Updates** — see available DSM versions and trigger upgrades
- **Package Updates** — track and install updates for all installed Synology packages
- **Container Updates** — detect and apply Docker container image updates via Container Manager, with support for compose projects grouped as single entities
- **Compose Project Switches** — start and stop Docker compose projects from Home Assistant
- **Security Advisor Scan** — a button to trigger a Security Advisor scan on demand (also run automatically after a package upgrade)

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alexives&repository=home-assistant-synology-manager&category=integration)

Or manually add as a custom repository:

1. Open HACS in Home Assistant
2. Click the three dots menu → Custom repositories
3. Add `https://github.com/alexives/home-assistant-synology-manager` with category "Integration"
4. Search for "Synology Manager" and install
5. Restart Home Assistant
6. Add the integration via Settings → Devices & Services → Add Integration

### Manual

Copy `custom_components/synology_manager` to your HA `custom_components` directory.

## Configuration

The integration is configured via the UI. You'll need:

- NAS hostname or IP address
- Port (default: 5001 for HTTPS)
- Admin username and password
- OTP code if 2FA is enabled

## Container image pulls (ghcr.io / lscr.io)

During a container update this integration pulls **Docker Hub** images automatically,
then rebuilds the compose project. It does **not** pull `ghcr.io` / `lscr.io` images
itself (those registries often need auth or hit rate limits, and pulls are better
managed on the NAS) — for those it just rebuilds from whatever image is already on
disk, so a newer one only gets applied if it has already been pulled. Set up two
**Synology Task Scheduler** tasks (Control Panel → Task Scheduler → Create → Scheduled
Task → User-defined script, run as `root`, e.g. daily) to keep those images current:

**Pull task** — pull the latest image for every running compose-project container on
those registries:

```sh
docker ps --filter "label=com.docker.compose.project" --format '{{.Image}}' | grep -E '^(ghcr\.io|lscr\.io)/' | sort -u | xargs -I{} docker pull {}
```

**Cleanup task** — keep the 4 newest images per repository and remove older ones
(prevents disk filling up with superseded images):

```sh
docker images --format '{{.Repository}} {{.ID}} {{.CreatedAt}}' | grep -E '^(ghcr\.io|lscr\.io)/' | sort -k1,1 -k3,3r | awk '{count[$1]++; if (count[$1] > 4) print $2}' | xargs -r docker rmi 2>/dev/null
```

Schedule the pull task before the cleanup task.

## Requirements

- DSM 7.0+
- Admin account on the NAS
- Container Manager installed (for container update and switch entities)
