# Synology Manager Home Assistant Integration

## What this is

A Home Assistant custom integration for Synology NAS devices — update entities for DSM firmware, installed packages, and Docker containers (with install support), plus switch entities for Docker compose project control.

## Architecture

- `synology_client.py` — Wrapper around the `synology-api` (N4S4) library. Uses the library's `SysInfo`, `Package`, and `Docker` classes for read operations. Makes raw API calls via `request_data()` for write operations not covered by the library (trigger DSM upgrade, pull Docker image, recreate container, trigger security scan, start/stop compose projects). All methods are synchronous (`requests`-based).
- `coordinator.py` — `DataUpdateCoordinator` that polls all four data sources (DSM, packages, containers, projects) every 6 hours. Calls `synology_client` methods via `hass.async_add_executor_job` since the API is sync. Per-source error isolation: if one source fails, others still update.
- `update.py` — Three `UpdateEntity` subclasses: `SynologyDSMUpdateEntity`, `SynologyPackageUpdateEntity`, `SynologyContainerUpdateEntity`. All support `INSTALL`. Package install auto-triggers a Security Advisor scan.
- `switch.py` — `SynologyProjectSwitchEntity` for Docker compose projects. On/off maps to start/stop.
- `config_flow.py` — UI config flow collecting host, port, credentials, SSL settings. Validates by attempting a login. Includes reauth support.
- `__init__.py` — Entry setup: creates client, connects, creates coordinator, forwards to update and switch platforms.

## Key details

- The `synology-api` library is sync (uses `requests`). Every call goes through `hass.async_add_executor_job`.
- `BaseApi` classes share a class-level session. Multi-NAS support works via separate config entries, each with their own client instance.
- Container update detection: compares `downloaded_images().id` (local image on disk) with container `ImageID` (image the container was created from). No remote registry polling.
- Container update for compose projects = stop + build + start via `SYNO.Docker.Project`. For ghcr.io/lscr.io images, pull is skipped (user manages pulls via Synology Task Scheduler). For Docker Hub images, `pull_start` is attempted first, then Docker session is reconnected before rebuild.
- Package install automatically triggers `SYNO.Core.SecurityScan.Status` method `system_scan` to clear Security Advisor warnings.

## Running tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Unit tests
python3 -m pytest tests/ -v

# Lint
uvx ruff check custom_components/ tests/
uvx ruff format --check custom_components/ tests/
```

## Local dev environment

```bash
docker compose -f docker-compose.dev.yml up -d
# HA available at http://localhost:8123
# custom_components/ is volume-mounted — restart container after code changes
docker restart ha-dev
```

## File layout

```
custom_components/synology_manager/   # The integration
tests/                                # Unit tests (HA test framework)
docker-compose.dev.yml                # Local HA dev instance
```

## Releasing

Version must be updated in two places, then tagged:

1. Bump `version` in `custom_components/synology_manager/manifest.json`
2. Bump `version` in `pyproject.toml`
3. Commit, then tag: `git tag v<version> && git push origin v<version>`

## Conventions

- Python 3.13+, async/await for HA code, sync for synology-api wrapper
- Tests use `pytest-homeassistant-custom-component` with mocked synology-api classes
- `ConfigEntryAuthFailed` for auth errors (triggers HA reauth flow), `ConfigEntryNotReady` for connection errors (triggers retry)
