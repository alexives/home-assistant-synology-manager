# Synology Upgrades - Home Assistant Custom Integration

## Overview

A HACS-installable Home Assistant custom integration that provides `update` entities for Synology NAS devices, covering DSM firmware upgrades, installed package upgrades, and Container Manager container updates. All entities support triggering installs from HA.

## Scope

Three categories of update entities from a single integration:

1. **DSM Firmware** - one entity per NAS showing installed vs. available DSM version, with install support (triggers firmware download + apply; NAS reboots)
2. **Installed Packages** - one persistent entity per installed Synology package (e.g., Hyper Backup, Synology Drive Server). Shows current vs. available version; install triggers the package update. Automatically triggers a Security Advisor scan after each successful package install.
3. **Containers** - one persistent entity per Docker/Container Manager container. Uses Synology's built-in update check to determine if a newer image exists. Install pulls the new image, stops the container, recreates it with the new image (preserving volumes/network/environment), and starts it.

## Architecture

### Single Coordinator Pattern

One `DataUpdateCoordinator` polls all three data sources every 6 hours. Each source (DSM, packages, containers) is fetched independently within `_async_update_data` - if one fails, the others still update and the failed source retains its last-known data with a warning logged.

### API Library

Uses the `synology-api` library (N4S4) for all Synology API interactions. This library provides wrappers for authentication, Docker/Container Manager APIs, and core system APIs.

### Configuration

UI-based config flow (no YAML). One config entry per NAS device. Users add the integration multiple times for multiple NAS devices.

Config flow collects:
- **Host/IP** - NAS address
- **Port** - default 5001 (HTTPS)
- **Username** - must be an admin account
- **Password**
- **Use HTTPS** - default on
- **Verify SSL** - default off (most NAS use self-signed certs)
- **OTP code** - additional step if 2FA is enabled

Credentials are validated during config flow by attempting a login. Stored in HA's config entry (encrypted at rest).

## Data Model

The coordinator returns this structure on each refresh:

```python
{
    "dsm": {
        "installed_version": "7.2.1-69057",
        "latest_version": "7.2.2-72806",
        "update_available": True,
        "release_notes": "...",
    },
    "packages": {
        "Hyper Backup": {
            "installed_version": "4.1.0-3735",
            "latest_version": "4.1.1-3740",
            "update_available": True,
        },
        "Synology Drive Server": {
            "installed_version": "3.5.0-26085",
            "latest_version": "3.5.0-26085",
            "update_available": False,
        },
        # one entry per installed package (all packages, not just those with updates)
    },
    "containers": {
        "homeassistant": {
            "image": "ghcr.io/home-assistant/home-assistant:2024.1",
            "installed_version": "2024.1",
            "latest_version": "2024.2",
            "update_available": True,
            "container_id": "abc123",
            "status": "running",
        },
        # one entry per container
    },
}
```

## Entity Design

All entities extend `UpdateEntity` with `UpdateEntityFeature.INSTALL`.

### SynologyDSMUpdateEntity

- **Count**: One per NAS
- **Entity ID**: `update.{nas_name}_dsm`
- **Title**: "DSM"
- **Properties**: `installed_version`, `latest_version` from coordinator's `dsm` data
- **install()**: Calls `SYNO.Core.Upgrade.Server` to download firmware and apply. Sets `in_progress = True`. NAS reboots - entity becomes unavailable during reboot and recovers when NAS comes back.
- **release_notes()**: Returns notes from API if available

### SynologyPackageUpdateEntity

- **Count**: One per installed package (persistent, even when up to date)
- **Entity ID**: `update.{nas_name}_{package_name}`
- **Title**: Package display name (e.g., "Hyper Backup")
- **Properties**: `installed_version`, `latest_version` from coordinator's `packages` data
- **install()**: Triggers package update via Synology Package API. Sets `in_progress = True`. After successful install, automatically triggers a Security Advisor scan via `SYNO.Core.SecurityScan`.
- Newly installed packages appear at next coordinator refresh. Removed packages become unavailable.

### SynologyContainerUpdateEntity

- **Count**: One per container (persistent)
- **Entity ID**: `update.{nas_name}_{container_name}`
- **Title**: Container name
- **Properties**: `installed_version` = current image tag, `latest_version` from Synology's built-in update check
- **install()**: Sequence: pull new image → stop container → recreate with new image (preserving volumes, network, environment) → start container. Sets `in_progress = True` through the process.
- Newly created containers appear at next coordinator refresh. Removed containers become unavailable.

## Session Management

- Config flow validates credentials on setup
- Coordinator reuses authenticated session across refreshes
- Re-authenticates automatically if session expires
- Admin privileges required for update checks and install triggers

## File Structure

Follows the same repo conventions as `home_assistant_gitlab_duo`:

```
synology_upgrades_component/          # repository root
├── .gitignore
├── .gitlab-ci.yml                    # CI: ruff-lint + unit-tests
├── CLAUDE.md                         # Project documentation for Claude Code
├── README.md
├── pyproject.toml                    # setuptools, ruff, pytest config
├── hacs.json                         # HACS metadata
├── docker-compose.dev.yml            # Local HA dev instance
├── custom_components/
│   └── synology_upgrades/
│       ├── __init__.py               # async_setup_entry, creates API client + coordinator
│       ├── manifest.json             # domain, requirements, codeowners, iot_class
│       ├── config_flow.py            # UI config flow with credential validation + 2FA
│       ├── coordinator.py            # DataUpdateCoordinator - polls DSM, packages, containers
│       ├── update.py                 # Three UpdateEntity subclasses
│       ├── const.py                  # Domain name, defaults, API constants
│       ├── strings.json              # Config flow UI strings
│       ├── translations/
│       │   └── en.json               # English translations
│       └── brand/
│           ├── icon.png              # Synology icon for HA
│           └── logo.png
├── tests/                            # Unit tests (pytest-homeassistant-custom-component)
│   ├── conftest.py
│   ├── test_config_flow.py
│   ├── test_coordinator.py
│   └── test_update.py
└── tests_integration/                # Live tests against a real NAS
    ├── conftest.py
    └── pytest.ini
```

### pyproject.toml

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["custom_components*"]

[project]
name = "home-assistant-synology-upgrades"
version = "0.1.0"
description = "Home Assistant integration for Synology NAS upgrade management"
requires-python = ">=3.13"

[project.optional-dependencies]
dev = [
    "pytest-homeassistant-custom-component>=0.13.333",
]
integration-test = []

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B", "SIM", "RUF"]
ignore = ["E501"]

[tool.ruff.lint.isort]
known-first-party = ["custom_components.synology_upgrades"]
```

### manifest.json

```json
{
    "domain": "synology_upgrades",
    "name": "Synology Upgrades",
    "version": "0.1.0",
    "config_flow": true,
    "codeowners": ["@aives"],
    "iot_class": "local_polling",
    "requirements": ["synology-api>=0.9.0"]
}
```

### hacs.json

```json
{
    "name": "Synology Upgrades",
    "homeassistant": "2025.7.0",
    "render_readme": true
}
```

## Synology APIs Used

| Purpose | API | Method |
|---|---|---|
| DSM update check | `SYNO.Core.Upgrade.Server` | `check` |
| DSM firmware download + apply | `SYNO.Core.Upgrade.Server` | `download`, apply |
| List installed packages | `SYNO.Core.Package` | `list` |
| Check package updates | `SYNO.Core.Package.Server` | check for updates |
| Install package update | `SYNO.Core.Package.Installation` | install/update |
| List containers | `SYNO.Docker.Container` | `list`, `get` |
| Check container image updates | `SYNO.Docker.Image` | check (built-in) |
| Pull container image | `SYNO.Docker.Image` | `pull` |
| Stop/start container | `SYNO.Docker.Container` | `stop`, `start` |
| Recreate container | `SYNO.Docker.Container` | delete + create (re-applying original config: volumes, network, env) |
| Security scan trigger | `SYNO.Core.SecurityScan` | `start` |

## Polling & Performance

- Single coordinator polls every 6 hours
- All three sources fetched per refresh with per-source error isolation
- Minimal NAS load - 6-hour interval is well under any rate limit concerns
- Coordinator refresh can be triggered manually via HA's "Update entity" refresh button

## Key Decisions

- **Persistent entities**: All packages and containers always have an entity, even when up to date (shows "Up to date" in HA UI)
- **No confirmation dialogs**: HA's update entity doesn't support them; users trigger installs knowingly
- **Container recreate on install**: Preserves volumes, network config, and environment variables
- **Auto security scan**: Only after package installs, not DSM or container updates
- **Entity disable**: Users can disable any entity via HA's built-in entity settings to hide unwanted updates
