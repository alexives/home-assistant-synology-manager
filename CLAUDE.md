# Synology Manager Home Assistant Integration

## What this is

A Home Assistant custom integration for managing packages on Synology NAS devices - update entities for DSM firmware, installed packages, and Docker containers, plus switch entities for package and Docker compose project control.

## Architecture

- `synology_client.py` - Wrapper around the `synology-api` (N4S4) library. Uses the library's `SysInfo`, `Package`, and `Docker` classes for read operations. Makes raw API calls via `request_data()` for write operations not covered by the library (trigger DSM upgrade, pull Docker image, recreate container, trigger security scan, start/stop compose projects). All methods are synchronous (`requests`-based).
- `coordinator.py` - `DataUpdateCoordinator` that polls all four data sources (DSM, packages, containers, projects) every 6 hours. Calls `synology_client` methods via `hass.async_add_executor_job` since the API is sync. Per-source error isolation: if one source fails, others still update.
- `update.py` - Four `UpdateEntity` subclasses: `SynologyDSMUpdateEntity`, `SynologyPackageUpdateEntity`, `SynologyProjectUpdateEntity` (one per compose project, all its containers combined), `SynologyContainerUpdateEntity` (standalone containers only). All support `INSTALL`. Package install auto-triggers a Security Advisor scan.
- `switch.py` - `SynologyPackageSwitchEntity` (packages DSM can start/stop) and `SynologyProjectSwitchEntity` (Docker compose projects). On/off maps to start/stop.
- `entity.py` - `SynologyManagerEntity` base class (attaches to the NAS device) plus device registry helpers: NAS device registration, compose-project child devices, stale child-device cleanup.
- `button.py` - `SynologySecurityScanButtonEntity`, a button that triggers a Security Advisor scan on demand (same path package upgrades use).
- `config_flow.py` - UI config flow collecting host, port, credentials, SSL settings. Validates by attempting a login. Includes reauth support.
- `__init__.py` - Entry setup: creates client, connects, creates coordinator, registers the NAS device, removes stale child devices, forwards to button, switch, and update platforms. `async_remove_config_entry_device` lets the UI delete a child device whose item is gone.

## Key details

- The `synology-api` library is sync (uses `requests`). Every call goes through `hass.async_add_executor_job`.
- Session handling: `synology-api` keeps **one** session as a class-level `BaseApi.shared_session`, reused by `SysInfo`/`Package`/`Docker`. `connect()` clears it first so each connect (and every HA reload) re-authenticates instead of resurrecting a stale SID. A single `client.reconnect()` (used by all coordinator reads and Docker write paths) refreshes everything when a session goes stale. Because the session is process-global, **true multi-NAS is unsound at the library level** - separate config entries share one session. Known limitation.
- Package upgrade flow: DSM needs the SPK downloaded first. `upgrade_package()` sends raw `SYNO.Core.Package.Installation` requests with **method `upgrade`**: download (with url/checksum) → poll `get_dowload_package_status()` → `check_installation()` (resolve volume) → quick-upgrade request (`blqinst: true`, `installrunpackage: true`, no url). Both request shapes mirror Package Center's `PkgManApp.js` (`_onRequestDownload` / `_onRequestQuickInstall`), verified live against DSM 7.3.2. Don't use the library's `download_package`/`install_package` (they hardcode method `install`, which DSM 7.3.2 rejects with reserved error 120 - shown as "Preserve for other purpose" - for an already-installed package) nor its bare `upgrade` method (error 4501 "system busy" for system packages). `_installation_request()` sends both write requests as **raw POSTs with the `X-SYNO-TOKEN` header and every payload value JSON-encoded** - the library's transport can't make the fresh-install request at all (its GET trips method `install`'s stricter validation, error 120 on `checksum`; its POST never attaches the token, error 119; Python bools serialize to "True"/"False", which DSM rejects with 120 reason "type" on `install` while method `upgrade` happens to tolerate them - all verified live) - and logs/re-raises with the step name plus DSM's error payload (`errors.name`/`reason`), which the library drops. Package install also triggers a Security Advisor scan via `SYNO.Core.SecurityScan.Operation` `start` to clear Security Advisor warnings. The `start` call needs `items='"ALL"'` (a JSON-encoded string, exactly what the DSM Security Advisor "Scan" button sends - `doScan` in `synosecurityscan.js`, fetchable from the NAS at `/webman/modules/SecurityScan/synosecurityscan.js` with the `id` session cookie). Gotchas, all verified against a live DSM 7 NAS: the earlier `SYNO.Core.SecurityScan.Status` `system_scan` does **not** exist (error 103, so the scan never ran) - the status method the UI actually polls is `system_get` (returns `sysStatus`/`sysProgress`/`lastScanTime`); `start` *without* `items` returns error 1300; and a stale SID fails with error 119, so `trigger_security_scan` retries once on a fresh session and raises on final failure (the post-upgrade caller treats it as best-effort; the button surfaces it). A manual scan button is also exposed via `button.py`.
- Package upgrade dependencies: before the upgrade, `_installation_check()` mirrors the wizard's `SYNO.Core.Package.Installation` `check` v2 with the installable record's `deppkgs`/`depsers` etc. **String params must be JSON-encoded** (bare strings fail with error 120 reason "type" - same gotcha as SecurityScan's `items`) **and the `X-SYNO-TOKEN` header is required** (without it, error 119 even on a fresh SID). The check goes out raw because the library drops error payloads, and the payload is the point: error **4526** carries `errors.uninstall_packages`, the dependency packages Package Center's wizard fresh-installs first (verified live: Contacts 1.0.11 requires `Node.js_v22`). `upgrade_package()` installs those with **method `install`** (correct for a not-yet-installed package) before running the upgrade.
- Third-party packages (Package Center sources such as SynoCommunity): `SYNO.Core.Package.Server` `list` returns **only** Synology packages with `blloadothers: false` (what the library's `list_installable()` sends) and **only** third-party packages (`source: "others"`) with `blloadothers: true`, so `_installable_map()` merges both, Synology entries first. They are usually unsigned, and DSM silently ignores the quick-upgrade request for them (download finishes, version never changes - verified live). `_run_package_operation()` therefore sends third-party packages down Package Center's wizard path (`_onRequestInstall`): `SYNO.Core.Package.Installation.Download` `check` (gives `filename` and `codesign_error`, e.g. 4532 "unknown publisher"), then one `SYNO.Entry.Request` compound of `check` v2 + `upgrade` with `path`/`volume_path`/`force: true` and `check_codesign: false` when there is a codesign error - what Package Center sends after the user clicks "Agree". The update dialog shows a "Community package" notice for these.
- Outdated dependencies: a catalog `deppkgs` constraint on an *installed* package that is too old (e.g. `synokernel-cdrom` 2.0 needs `synocli-kernel >= 2.0`) is not something `upgrade_package()` fixes - DSM refuses that upgrade with 4501. `get_packages()` flags it as `unmet_dependencies`; the entity drops `INSTALL`, puts the reason in `release_summary`, and its release notes link to the dependency's update entity via `/config/updates?more-info-entity-id=<entity_id>` (the frontend opens the more-info dialog from that param). The release notes, not `release_summary`, carry the link: the frontend hides `release_summary` when the entity supports release notes.
- DSM upgrade / reboot window, all observed live during the 7.3.2 → 7.4.1 upgrade: once `SYNO.Core.Upgrade` `start` is accepted, DSM tears down its web stack - for ~4 min every API call *including login* returns error **499** ("system not ready" in DSM's login JS; **498** = "system upgrading"), then the NAS drops off the network entirely for the reboot (~5 min), then services come back but **Container Manager sits in `starting` for ~2 more min** answering with misleading error codes, and some packages can linger in status `upgrading`. The library has no table entry for 498/499 and dies with `KeyError` while formatting its own exception. Client behavior: `_err_detail()` translates 498/499 into "the NAS is not ready"; `upgrade_dsm()` treats a dropped connection (confirmed by a 30s login probe - a healthy NAS still reporting the update as pending means the start never landed) or 498/499 on the final `start` as success; the DSM entity skips the immediate coordinator refresh (a failed refresh would mark all entities unavailable for the full 6h interval) and schedules one 25 min out; Docker writes gate on the Container Manager package reporting `running`. Synology's guidance: the whole update can take up to 20 minutes - the DSM entity posts a persistent notification saying so.
- Error surfacing: every entity write action goes through `actions.run_action`, which logs the full traceback at ERROR, creates a persistent notification with a clickable link to `/config/logs?filter=synology_manager` (the frontend pre-fills the search box from the `filter` param), and raises `HomeAssistantError` so the popup carries the real cause. Client-side best-effort failures log at WARNING with `_err_detail()` (never a bare `str(err)` - library exceptions can stringify to `""`).
- Update entities override `version_is_newer` to compare the build suffix (`X.Y.Z-BUILD`); HA's default (AwesomeVersion) ignores it, so build-only bumps like `1.5.2-1831` → `1.5.2-1832` would otherwise show as "Up-to-date".
- Devices: one NAS device per config entry (identifier = entry id; model/serial from `SYNO.DSM.Info` `getinfo`, `sw_version` kept in step with the DSM source by a coordinator listener). Each compose project is a **child device** (HA 2026.9+ `ChildDeviceInfo` with `parent_device_id`, not the older `via_device`) keyed `<entry_id>_project_<project name>`, holding the project switch and project update entity; everything else sits on the NAS device. Child devices reference the NAS device by device id, so `__init__` registers it before forwarding platforms. Stale child devices are removed at setup, before entities load (so no live entity needs re-adding if the item comes back), and only when every source behind that kind succeeded: the coordinator records `failed_sources`, `get_projects()` raises instead of returning `[]` on failure, and no Container Manager (`client.has_docker` false, e.g. still starting after a reboot) counts the Docker sources as failed. An empty list must never read as "everything was deleted". Look devices up with `async_get_device_by_identifier` / `async_get_child_device_by_identifier`; HA 2026.10 raises on the old `async_get_device`.
- Container update detection: compares `downloaded_images().id` (local image on disk) with container `ImageID` (image the container was created from). No remote registry polling.
- Container update for compose projects = stop + build + start via `SYNO.Docker.Project`. For ghcr.io/lscr.io images, pull is skipped (user manages pulls via Synology Task Scheduler). For Docker Hub images, `pull_start` is attempted first, then Docker session is reconnected before rebuild.

## Running tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Unit tests (tests/integration needs synology_api and a live NAS; skip it locally)
mise exec -- python -m pytest tests/ -v --ignore=tests/integration

# Lint
mise exec -- ruff check custom_components/ tests/
mise exec -- ruff format --check custom_components/ tests/
```

## Local dev environment

The `ha-dev` container comes from this repo's `docker-compose.dev.yml` (its compose labels point here; the sibling duo repo that used to manage it is no longer checked out). It mounts this repo's `custom_components/` into the `ha-config` volume, so edits appear immediately:

```bash
docker start ha-dev     # existing container; don't recreate it, the config lives in the volume
# HA at http://localhost:8123
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

Each discrete change goes through its own pull request - that PR is the system of record for *what* changed and *why*, so put the full description and rationale there.

1. Branch per change (e.g. `fix/...`, `feat/...`).
2. Open a PR with a complete description. Run tests + lint first.
3. Merge the PR (`gh pr merge`). Don't push functional changes straight to `main`.

Exception: trivial non-functional changes (docs, comments) may be committed directly to `main`.

## Releasing a set of changes

A release bundles one or more merged PRs.

1. Bump `version` in `custom_components/synology_manager/manifest.json`
2. Bump `version` in `pyproject.toml`
3. `gh release create v<version> --target main` - this creates the tag. Group the
   notes under these category headings (omit any with no entries), one short bullet
   per PR with its `(#N)` link; the detail lives in the PRs:
   - `## ⚠️ Breaking Changes`
   - `## 🆕 Enhancements`
   - `## ✅ Bug Fixes`
   - `## ⚓ Code Quality`
   - `## 📝 Documentation`
   - `## 📦 Dependencies`
   - `## 🧹 Housekeeping`

## Conventions

- Python 3.14+, async/await for HA code, sync for synology-api wrapper
- Tests use `pytest-homeassistant-custom-component` with mocked synology-api classes
- `ConfigEntryAuthFailed` for auth errors (triggers HA reauth flow), `ConfigEntryNotReady` for connection errors (triggers retry)
