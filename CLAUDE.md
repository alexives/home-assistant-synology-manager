# Synology Manager Home Assistant Integration

## What this is

A Home Assistant custom integration for Synology NAS devices — update entities for DSM firmware, installed packages, and Docker containers (with install support), plus switch entities for Docker compose project control.

## Architecture

- `synology_client.py` — Wrapper around the `synology-api` (N4S4) library. Uses the library's `SysInfo`, `Package`, and `Docker` classes for read operations. Makes raw API calls via `request_data()` for write operations not covered by the library (trigger DSM upgrade, pull Docker image, recreate container, trigger security scan, start/stop compose projects). All methods are synchronous (`requests`-based).
- `coordinator.py` — `DataUpdateCoordinator` that polls all four data sources (DSM, packages, containers, projects) every 6 hours. Calls `synology_client` methods via `hass.async_add_executor_job` since the API is sync. Per-source error isolation: if one source fails, others still update.
- `update.py` — Three `UpdateEntity` subclasses: `SynologyDSMUpdateEntity`, `SynologyPackageUpdateEntity`, `SynologyContainerUpdateEntity`. All support `INSTALL`. Package install auto-triggers a Security Advisor scan.
- `switch.py` — `SynologyProjectSwitchEntity` for Docker compose projects. On/off maps to start/stop.
- `button.py` — `SynologySecurityScanButtonEntity`, a button that triggers a Security Advisor scan on demand (same path package upgrades use).
- `config_flow.py` — UI config flow collecting host, port, credentials, SSL settings. Validates by attempting a login. Includes reauth support.
- `__init__.py` — Entry setup: creates client, connects, creates coordinator, forwards to button, switch, and update platforms.

## Key details

- The `synology-api` library is sync (uses `requests`). Every call goes through `hass.async_add_executor_job`.
- Session handling: `synology-api` keeps **one** session as a class-level `BaseApi.shared_session`, reused by `SysInfo`/`Package`/`Docker`. `connect()` clears it first so each connect (and every HA reload) re-authenticates instead of resurrecting a stale SID. A single `client.reconnect()` (used by all coordinator reads and Docker write paths) refreshes everything when a session goes stale. Because the session is process-global, **true multi-NAS is unsound at the library level** — separate config entries share one session. Known limitation.
- Package upgrade flow: DSM needs the SPK downloaded first. `upgrade_package()` does `download_package()` → poll `get_dowload_package_status()` → `check_installation_from_download()` (resolve file path) → `install_package(force=True)` (compound check+install). The library's bare `upgrade` method returns error 4501 ("system busy") for system packages, so don't use it. Package install also triggers a Security Advisor scan via `SYNO.Core.SecurityScan.Operation` `start` to clear Security Advisor warnings. (The earlier `SYNO.Core.SecurityScan.Status` `system_scan` does **not** exist on DSM 7 — it returns error 103, so the scan never ran. `start` is the only trigger DSM exposes; it returns error 1300 when nothing has changed since the last scan, which `trigger_security_scan` logs at WARNING rather than swallowing. A manual scan button is also exposed via `button.py`.)
- Update entities override `version_is_newer` to compare the build suffix (`X.Y.Z-BUILD`); HA's default (AwesomeVersion) ignores it, so build-only bumps like `1.5.2-1831` → `1.5.2-1832` would otherwise show as "Up-to-date".
- Container update detection: compares `downloaded_images().id` (local image on disk) with container `ImageID` (image the container was created from). No remote registry polling.
- Container update for compose projects = stop + build + start via `SYNO.Docker.Project`. For ghcr.io/lscr.io images, pull is skipped (user manages pulls via Synology Task Scheduler). For Docker Hub images, `pull_start` is attempted first, then Docker session is reconnected before rebuild.

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

The `ha-dev` container is managed from the **sibling duo repo's** compose, not this repo's — it mounts several repos' `custom_components/` into one HA instance, so using this repo's compose would create a separate volume and lose the existing config:

```bash
docker compose -f ../home_assistant_gitlab_duo/docker-compose.dev.yml up -d
# HA at http://localhost:8123
# custom_components/synology_manager is live-mounted, so edits appear immediately.
docker restart ha-dev   # reload after code changes
```

### Validating against a real NAS

The integration's client is sync and importable on its own, so you can exercise it against a live NAS by running a standalone script inside the container (read the config entry under `/config/.storage/` for connection params):

```bash
docker exec -i ha-dev python - <<'PY'
import sys; sys.path.insert(0, "/config/custom_components/synology_manager")
import synology_client as sc
client = sc.SynologyClient(host=..., port=..., username=..., password=..., secure=True, verify_ssl=False)
client.connect()
print(client.get_packages())
PY
```

This is how to reproduce session-expiry, package-detection, and upgrade bugs against the real device without driving HA's event loop.

## File layout

```
custom_components/synology_manager/   # The integration
tests/                                # Unit tests (HA test framework)
docker-compose.dev.yml                # Local HA dev instance
```

## Making a change

Each discrete change goes through its own pull request — that PR is the system of record for *what* changed and *why*, so put the full description and rationale there.

1. Branch per change (e.g. `fix/...`, `feat/...`).
2. Open a PR with a complete description. Run tests + lint first.
3. Merge the PR (`gh pr merge`). Don't push functional changes straight to `main`.

Exception: trivial non-functional changes (docs, comments) may be committed directly to `main`.

## Releasing a set of changes

A release bundles one or more merged PRs.

1. Bump `version` in `custom_components/synology_manager/manifest.json`
2. Bump `version` in `pyproject.toml`
3. `gh release create v<version> --target main` — release notes are a **one-sentence summary of each PR** in the release, nothing more (the detail lives in the PRs). This creates the tag.

## Conventions

- Python 3.14+, async/await for HA code, sync for synology-api wrapper
- Tests use `pytest-homeassistant-custom-component` with mocked synology-api classes
- `ConfigEntryAuthFailed` for auth errors (triggers HA reauth flow), `ConfigEntryNotReady` for connection errors (triggers retry)
