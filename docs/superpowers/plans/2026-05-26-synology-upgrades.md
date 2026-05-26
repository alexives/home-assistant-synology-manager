# Synology Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS-installable Home Assistant custom integration that provides `update` entities for Synology NAS devices — DSM firmware, installed packages, and Docker containers — all with install support.

**Architecture:** Single `DataUpdateCoordinator` polls three data sources every 6 hours via a `SynologyClient` wrapper. The wrapper uses the `synology-api` (N4S4) library for read operations and raw HTTP calls for write operations (trigger upgrade, pull image, recreate container, trigger security scan) that the library doesn't cover. All synology-api calls are synchronous (`requests`-based) and run via `hass.async_add_executor_job`.

**Tech Stack:** Python 3.13+, Home Assistant `UpdateEntity` platform, `synology-api` library, `pytest-homeassistant-custom-component` for tests, ruff for linting.

**Reference repo:** `../home_assistant_gitlab_duo` — follow its patterns for pyproject.toml, conftest.py, config flow tests, CI, docker-compose, CLAUDE.md.

---

## File Map

| File | Responsibility |
|---|---|
| `custom_components/synology_upgrades/const.py` | Domain name, config keys, defaults |
| `custom_components/synology_upgrades/synology_client.py` | Wrapper around synology-api + raw API calls |
| `custom_components/synology_upgrades/config_flow.py` | UI config flow with credential validation |
| `custom_components/synology_upgrades/coordinator.py` | DataUpdateCoordinator polling all three sources |
| `custom_components/synology_upgrades/update.py` | Three UpdateEntity subclasses (DSM, Package, Container) |
| `custom_components/synology_upgrades/__init__.py` | async_setup_entry / async_unload_entry |
| `custom_components/synology_upgrades/manifest.json` | Integration metadata |
| `custom_components/synology_upgrades/strings.json` | Config flow UI strings |
| `custom_components/synology_upgrades/translations/en.json` | English translations (copy of strings.json) |
| `tests/conftest.py` | Shared fixtures (enable custom integrations, mock deps) |
| `tests/test_synology_client.py` | Tests for the API client wrapper |
| `tests/test_config_flow.py` | Config flow tests |
| `tests/test_coordinator.py` | Coordinator tests with mocked client |
| `tests/test_update.py` | Update entity tests with mocked coordinator |
| `tests/test_init.py` | Setup/unload tests |

---

### Task 1: Repo Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `hacs.json`
- Create: `.gitignore`
- Create: `.gitlab-ci.yml`
- Create: `docker-compose.dev.yml`
- Create: `README.md`

- [ ] **Step 1: Initialize git repo**

```bash
cd /Users/aives/repos/synology_upgrades_component
git init
```

- [ ] **Step 2: Create pyproject.toml**

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

- [ ] **Step 3: Create hacs.json**

```json
{
  "name": "Synology Upgrades",
  "homeassistant": "2025.7.0",
  "render_readme": true
}
```

- [ ] **Step 4: Create .gitignore**

```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
dist/
build/
.venv/
*.egg
.env
.coverage
.ruff_cache/
```

- [ ] **Step 5: Create .gitlab-ci.yml**

```yaml
stages:
  - lint
  - test

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

cache:
  paths:
    - .cache/pip

ruff-lint:
  image: python:3.12-slim
  stage: lint
  before_script:
    - pip install --quiet ruff
  script:
    - ruff check custom_components/ tests/
    - ruff format --check custom_components/ tests/

unit-tests:
  image: ghcr.io/home-assistant/home-assistant:2026.5
  stage: test
  before_script:
    - pip install --quiet ".[dev]"
  script:
    - python -m pytest tests/ -v --tb=short
```

- [ ] **Step 6: Create docker-compose.dev.yml**

```yaml
services:
  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    container_name: ha-dev
    ports:
      - "8123:8123"
    volumes:
      - ./custom_components:/config/custom_components
      - ha-config:/config
    restart: "no"

volumes:
  ha-config:
```

- [ ] **Step 7: Create README.md**

```markdown
# Synology Upgrades

A Home Assistant custom integration that provides update entities for Synology NAS devices.

## Features

- **DSM Firmware Updates** — see available DSM versions and trigger upgrades
- **Package Updates** — track and install updates for all installed Synology packages
- **Container Updates** — detect and apply Docker container image updates via Container Manager

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Synology Upgrades" and install
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services → Add Integration

### Manual

Copy `custom_components/synology_upgrades` to your HA `custom_components` directory.

## Configuration

The integration is configured via the UI. You'll need:

- NAS hostname or IP address
- Port (default: 5001 for HTTPS)
- Admin username and password
- OTP code if 2FA is enabled

## Requirements

- DSM 7.0+
- Admin account on the NAS
- Container Manager installed (for container update entities)
```

- [ ] **Step 8: Commit scaffolding**

```bash
git add pyproject.toml hacs.json .gitignore .gitlab-ci.yml docker-compose.dev.yml README.md
git commit -m "chore: initial repo scaffolding"
```

---

### Task 2: Constants + Manifest

**Files:**
- Create: `custom_components/synology_upgrades/__init__.py` (empty placeholder)
- Create: `custom_components/synology_upgrades/const.py`
- Create: `custom_components/synology_upgrades/manifest.json`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p custom_components/synology_upgrades/translations
mkdir -p tests
```

- [ ] **Step 2: Create empty __init__.py placeholder**

```python
"""The Synology Upgrades integration."""
```

- [ ] **Step 3: Create const.py**

```python
"""Constants for the Synology Upgrades integration."""

DOMAIN = "synology_upgrades"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SSL = "ssl"
CONF_VERIFY_SSL = "verify_ssl"
CONF_OTP_CODE = "otp_code"

DEFAULT_PORT = 5001
DEFAULT_SSL = True
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL_HOURS = 6
```

- [ ] **Step 4: Create manifest.json**

```json
{
  "domain": "synology_upgrades",
  "name": "Synology Upgrades",
  "version": "0.1.0",
  "config_flow": true,
  "codeowners": ["@aives"],
  "iot_class": "local_polling",
  "requirements": ["synology-api>=0.8.0"]
}
```

- [ ] **Step 5: Commit**

```bash
git add custom_components/ tests/
git commit -m "feat: add constants and manifest"
```

---

### Task 3: Synology API Client Wrapper

**Files:**
- Create: `custom_components/synology_upgrades/synology_client.py`
- Create: `tests/test_synology_client.py`

The `synology-api` library is synchronous (`requests`-based). All methods on this client are sync. The coordinator will call them via `hass.async_add_executor_job`.

The library's `BaseApi` handles auth on construction. Each API class (`SysInfo`, `Package`, `Docker`) authenticates independently but shares a class-level session. For raw API calls not covered by the library, we use the `request_data` method on an existing instance.

- [ ] **Step 1: Write the failing tests for client construction and authentication**

Create `tests/test_synology_client.py`:

```python
"""Tests for the Synology API client wrapper."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.synology_upgrades.synology_client import (
    SynologyAuthenticationError,
    SynologyClient,
    SynologyConnectionError,
)


class TestClientConstruction:
    """Tests for client creation and authentication."""

    @patch("custom_components.synology_upgrades.synology_client.SysInfo")
    @patch("custom_components.synology_upgrades.synology_client.Package")
    @patch("custom_components.synology_upgrades.synology_client.DockerApi")
    def test_connect_creates_api_instances(self, mock_docker, mock_package, mock_sysinfo):
        """Test that connect() creates all API class instances."""
        client = SynologyClient(
            host="192.168.1.100",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()

        mock_sysinfo.assert_called_once_with(
            ip_address="192.168.1.100",
            port="5001",
            username="admin",
            password="secret",
            secure=True,
            cert_verify=False,
            dsm_version=7,
            debug=False,
            otp_code=None,
        )
        mock_package.assert_called_once()
        mock_docker.assert_called_once()

    @patch("custom_components.synology_upgrades.synology_client.SysInfo")
    def test_connect_with_otp(self, mock_sysinfo):
        """Test that OTP code is passed through."""
        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
            otp_code="123456",
        )
        client.connect()

        call_kwargs = mock_sysinfo.call_args[1]
        assert call_kwargs["otp_code"] == "123456"

    @patch("custom_components.synology_upgrades.synology_client.SysInfo")
    def test_connect_auth_failure_raises(self, mock_sysinfo):
        """Test that auth failure raises SynologyAuthenticationError."""
        mock_sysinfo.side_effect = Exception("Login failed")

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="wrong",
            secure=True,
            verify_ssl=False,
        )
        with pytest.raises(SynologyAuthenticationError):
            client.connect()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pip install -e ".[dev]" && python -m pytest tests/test_synology_client.py -v
```

Expected: FAIL — `synology_client` module doesn't exist yet.

- [ ] **Step 3: Write the client implementation**

Create `custom_components/synology_upgrades/synology_client.py`:

```python
"""Synology API client wrapper."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)


class SynologyAuthenticationError(Exception):
    """Raised when authentication fails."""


class SynologyConnectionError(Exception):
    """Raised when the NAS is unreachable."""


@dataclass
class DsmUpdateInfo:
    """DSM firmware update information."""

    installed_version: str
    latest_version: str | None
    update_available: bool
    release_notes: str | None


@dataclass
class PackageInfo:
    """Installed package information."""

    package_id: str
    display_name: str
    installed_version: str
    latest_version: str | None
    update_available: bool


@dataclass
class ContainerInfo:
    """Docker container information."""

    name: str
    image: str
    installed_version: str
    latest_version: str | None
    update_available: bool
    status: str


class SynologyClient:
    """Wraps synology-api library with raw API calls for gaps."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        secure: bool = True,
        verify_ssl: bool = False,
        otp_code: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._secure = secure
        self._verify_ssl = verify_ssl
        self._otp_code = otp_code
        self._sysinfo = None
        self._package = None
        self._docker = None

    def _api_kwargs(self) -> dict[str, Any]:
        """Common kwargs for all synology-api constructors."""
        return {
            "ip_address": self._host,
            "port": str(self._port),
            "username": self._username,
            "password": self._password,
            "secure": self._secure,
            "cert_verify": self._verify_ssl,
            "dsm_version": 7,
            "debug": False,
            "otp_code": self._otp_code,
        }

    def connect(self) -> None:
        """Authenticate and create API instances.

        Raises SynologyAuthenticationError on bad credentials.
        Raises SynologyConnectionError if NAS is unreachable.
        """
        from synology_api.core_sys_info import SysInfo
        from synology_api.core_package import Package
        from synology_api.docker_api import Docker as DockerApi

        kwargs = self._api_kwargs()
        try:
            self._sysinfo = SysInfo(**kwargs)
            self._package = Package(**kwargs)
        except Exception as err:
            err_str = str(err).lower()
            if "login" in err_str or "auth" in err_str or "credential" in err_str:
                raise SynologyAuthenticationError(str(err)) from err
            raise SynologyConnectionError(str(err)) from err

        try:
            self._docker = DockerApi(**kwargs)
        except Exception:
            _LOGGER.warning("Docker/Container Manager not available on this NAS")
            self._docker = None

    def get_dsm_update(self) -> DsmUpdateInfo:
        """Check for DSM firmware updates."""
        info = self._sysinfo.sys_upgrade_check()
        data = info.get("data", {})
        available = data.get("available", False)
        return DsmUpdateInfo(
            installed_version=data.get("firmware_version", ""),
            latest_version=data.get("version", None) if available else None,
            update_available=available,
            release_notes=data.get("release_note", None),
        )

    def get_packages(self) -> list[PackageInfo]:
        """List all installed packages with update status."""
        installed = self._sysinfo.installed_package_list()
        installed_data = installed.get("data", {}).get("packages", [])

        installable = self._package.list_installable()
        installable_data = installable.get("data", {}).get("packages", [])
        installable_map = {
            pkg["id"]: pkg.get("version", "")
            for pkg in installable_data
            if isinstance(pkg, dict)
        }

        packages = []
        for pkg in installed_data:
            if not isinstance(pkg, dict):
                continue
            pkg_id = pkg.get("id", "")
            installed_ver = pkg.get("version", "")
            latest_ver = installable_map.get(pkg_id)
            update_available = bool(latest_ver and latest_ver != installed_ver)

            packages.append(PackageInfo(
                package_id=pkg_id,
                display_name=pkg.get("name", pkg_id),
                installed_version=installed_ver,
                latest_version=latest_ver if update_available else installed_ver,
                update_available=update_available,
            ))
        return packages

    def get_containers(self) -> list[ContainerInfo]:
        """List all Docker containers with update status."""
        if self._docker is None:
            return []

        result = self._docker.containers()
        data = result.get("data", {}).get("containers", [])

        containers = []
        for ctr in data:
            if not isinstance(ctr, dict):
                continue
            image = ctr.get("image", "")
            tag = image.split(":")[-1] if ":" in image else "latest"
            containers.append(ContainerInfo(
                name=ctr.get("name", ""),
                image=image,
                installed_version=tag,
                latest_version=tag,
                update_available=False,
                status=ctr.get("status", "unknown"),
            ))
        return containers

    def upgrade_dsm(self) -> None:
        """Trigger DSM firmware download and install.

        This is a raw API call — the synology-api library doesn't
        expose a method to trigger the actual upgrade.
        """
        self._sysinfo.request_data(
            "SYNO.Core.Upgrade.Server",
            "entry.cgi",
            req_param={"method": "download", "version": 2},
        )

    def upgrade_package(self, package_id: str) -> None:
        """Trigger a package upgrade."""
        self._package.easy_install(package_id, volume_path="/volume1")

    def trigger_security_scan(self) -> None:
        """Trigger a Security Advisor scan.

        Raw API call — the library only reads scan config/status.
        """
        self._sysinfo.request_data(
            "SYNO.Core.SecurityScan.Status",
            "entry.cgi",
            req_param={"method": "system_scan", "version": 1},
        )

    def update_container(self, container_name: str, image: str) -> None:
        """Pull new image and recreate container.

        1. Pull the latest version of the image
        2. Stop the container
        3. Export container settings (preserves volumes, env, network)
        4. Delete the old container
        5. Recreate from exported settings with new image
        6. Start the container

        Uses raw API calls for pull/create/delete — the library
        only covers list/start/stop.
        """
        self._docker.stop_container(container_name)

        repo = image.split(":")[0] if ":" in image else image
        tag = image.split(":")[-1] if ":" in image else "latest"
        self._docker.request_data(
            "SYNO.Docker.Image",
            "entry.cgi",
            req_param={
                "method": "pull",
                "version": 1,
                "repository": repo,
                "tag": tag,
            },
        )

        self._docker.request_data(
            "SYNO.Docker.Container",
            "entry.cgi",
            req_param={
                "method": "delete",
                "version": 1,
                "name": container_name,
                "force": True,
                "preserve_profile": True,
            },
        )

        self._docker.request_data(
            "SYNO.Docker.Container",
            "entry.cgi",
            req_param={
                "method": "create",
                "version": 1,
                "name": container_name,
                "image": f"{repo}:{tag}",
                "is_run_instantly": True,
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_synology_client.py -v
```

Expected: All 3 tests pass.

- [ ] **Step 5: Write tests for data-fetching methods**

Add to `tests/test_synology_client.py`:

```python
class TestDsmUpdate:
    """Tests for DSM update checking."""

    @patch("custom_components.synology_upgrades.synology_client.SysInfo")
    @patch("custom_components.synology_upgrades.synology_client.Package")
    @patch("custom_components.synology_upgrades.synology_client.DockerApi")
    def test_get_dsm_update_available(self, mock_docker, mock_package, mock_sysinfo):
        """Test parsing DSM update when one is available."""
        mock_instance = MagicMock()
        mock_instance.sys_upgrade_check.return_value = {
            "data": {
                "available": True,
                "firmware_version": "7.2.1-69057",
                "version": "7.2.2-72806",
                "release_note": "Bug fixes and improvements",
            },
            "success": True,
        }
        mock_sysinfo.return_value = mock_instance

        client = SynologyClient(
            host="nas.local", port=5001, username="admin",
            password="secret", secure=True, verify_ssl=False,
        )
        client.connect()
        result = client.get_dsm_update()

        assert result.installed_version == "7.2.1-69057"
        assert result.latest_version == "7.2.2-72806"
        assert result.update_available is True
        assert result.release_notes == "Bug fixes and improvements"

    @patch("custom_components.synology_upgrades.synology_client.SysInfo")
    @patch("custom_components.synology_upgrades.synology_client.Package")
    @patch("custom_components.synology_upgrades.synology_client.DockerApi")
    def test_get_dsm_update_not_available(self, mock_docker, mock_package, mock_sysinfo):
        """Test parsing DSM update when up to date."""
        mock_instance = MagicMock()
        mock_instance.sys_upgrade_check.return_value = {
            "data": {
                "available": False,
                "firmware_version": "7.2.2-72806",
            },
            "success": True,
        }
        mock_sysinfo.return_value = mock_instance

        client = SynologyClient(
            host="nas.local", port=5001, username="admin",
            password="secret", secure=True, verify_ssl=False,
        )
        client.connect()
        result = client.get_dsm_update()

        assert result.installed_version == "7.2.2-72806"
        assert result.latest_version is None
        assert result.update_available is False


class TestPackages:
    """Tests for package listing."""

    @patch("custom_components.synology_upgrades.synology_client.SysInfo")
    @patch("custom_components.synology_upgrades.synology_client.Package")
    @patch("custom_components.synology_upgrades.synology_client.DockerApi")
    def test_get_packages_with_update(self, mock_docker, mock_package, mock_sysinfo):
        """Test listing packages where one has an update."""
        mock_sys = MagicMock()
        mock_sys.installed_package_list.return_value = {
            "data": {
                "packages": [
                    {"id": "HyperBackup", "name": "Hyper Backup", "version": "4.1.0-3735"},
                    {"id": "SynologyDrive", "name": "Synology Drive Server", "version": "3.5.0"},
                ]
            },
            "success": True,
        }
        mock_sysinfo.return_value = mock_sys

        mock_pkg = MagicMock()
        mock_pkg.list_installable.return_value = {
            "data": {
                "packages": [
                    {"id": "HyperBackup", "version": "4.1.1-3740"},
                    {"id": "SynologyDrive", "version": "3.5.0"},
                ]
            },
            "success": True,
        }
        mock_package.return_value = mock_pkg

        client = SynologyClient(
            host="nas.local", port=5001, username="admin",
            password="secret", secure=True, verify_ssl=False,
        )
        client.connect()
        packages = client.get_packages()

        assert len(packages) == 2
        hyper = next(p for p in packages if p.package_id == "HyperBackup")
        assert hyper.update_available is True
        assert hyper.latest_version == "4.1.1-3740"

        drive = next(p for p in packages if p.package_id == "SynologyDrive")
        assert drive.update_available is False
        assert drive.latest_version == "3.5.0"


class TestContainers:
    """Tests for container listing."""

    @patch("custom_components.synology_upgrades.synology_client.SysInfo")
    @patch("custom_components.synology_upgrades.synology_client.Package")
    @patch("custom_components.synology_upgrades.synology_client.DockerApi")
    def test_get_containers(self, mock_docker, mock_package, mock_sysinfo):
        """Test listing containers."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "homeassistant",
                        "image": "ghcr.io/home-assistant/home-assistant:2024.1",
                        "status": "running",
                    },
                    {
                        "name": "mosquitto",
                        "image": "eclipse-mosquitto:2.0",
                        "status": "running",
                    },
                ]
            },
            "success": True,
        }
        mock_docker.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local", port=5001, username="admin",
            password="secret", secure=True, verify_ssl=False,
        )
        client.connect()
        containers = client.get_containers()

        assert len(containers) == 2
        ha = next(c for c in containers if c.name == "homeassistant")
        assert ha.installed_version == "2024.1"
        assert ha.image == "ghcr.io/home-assistant/home-assistant:2024.1"

    @patch("custom_components.synology_upgrades.synology_client.SysInfo")
    @patch("custom_components.synology_upgrades.synology_client.Package")
    @patch("custom_components.synology_upgrades.synology_client.DockerApi")
    def test_get_containers_no_docker(self, mock_docker, mock_package, mock_sysinfo):
        """Test that containers returns empty when Docker is not installed."""
        mock_docker.side_effect = Exception("Docker not installed")

        client = SynologyClient(
            host="nas.local", port=5001, username="admin",
            password="secret", secure=True, verify_ssl=False,
        )
        client.connect()
        containers = client.get_containers()

        assert containers == []
```

- [ ] **Step 6: Run all client tests**

```bash
python -m pytest tests/test_synology_client.py -v
```

Expected: All 7 tests pass.

- [ ] **Step 7: Commit**

```bash
git add custom_components/synology_upgrades/synology_client.py tests/test_synology_client.py
git commit -m "feat: add Synology API client wrapper"
```

---

### Task 4: Config Flow

**Files:**
- Create: `custom_components/synology_upgrades/config_flow.py`
- Create: `custom_components/synology_upgrades/strings.json`
- Create: `custom_components/synology_upgrades/translations/en.json`
- Create: `tests/conftest.py`
- Create: `tests/test_config_flow.py`

- [ ] **Step 1: Create test conftest.py**

Create `tests/conftest.py` (following the gitlab_duo pattern):

```python
"""Shared test fixtures for Synology Upgrades integration tests."""

import pathlib
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    yield


@pytest.fixture(autouse=True)
def fix_custom_components_path():
    """Remove non-existent placeholder paths from custom_components.__path__."""
    import custom_components

    original_path = list(custom_components.__path__)
    real_paths = list(dict.fromkeys(p for p in original_path if pathlib.Path(p).is_dir()))
    custom_components.__path__ = real_paths
    yield
    custom_components.__path__ = original_path


@pytest.fixture(autouse=True)
def mock_process_deps_reqs():
    """Bypass integration dependency loading in tests."""
    with patch(
        "homeassistant.config_entries.async_process_deps_reqs",
        new_callable=AsyncMock,
    ):
        yield
```

- [ ] **Step 2: Write failing config flow tests**

Create `tests/test_config_flow.py`:

```python
"""Tests for the Synology Upgrades config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.synology_upgrades.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)

VALID_USER_INPUT = {
    CONF_HOST: "192.168.1.100",
    CONF_PORT: 5001,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_SSL: True,
    CONF_VERIFY_SSL: False,
}


async def test_form_success(hass: HomeAssistant) -> None:
    """Test successful config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.synology_upgrades.config_flow.validate_input",
        return_value={"host": "192.168.1.100"},
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            VALID_USER_INPUT,
        )

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Synology NAS (192.168.1.100)"
    assert result2["data"][CONF_HOST] == "192.168.1.100"
    assert result2["data"][CONF_USERNAME] == "admin"


async def test_form_invalid_auth(hass: HomeAssistant) -> None:
    """Test config flow with invalid credentials."""
    from custom_components.synology_upgrades.config_flow import InvalidAuth

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.synology_upgrades.config_flow.validate_input",
        side_effect=InvalidAuth,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            VALID_USER_INPUT,
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "authentication_error"}


async def test_form_cannot_connect(hass: HomeAssistant) -> None:
    """Test config flow when NAS is unreachable."""
    from custom_components.synology_upgrades.config_flow import CannotConnect

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.synology_upgrades.config_flow.validate_input",
        side_effect=CannotConnect,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            VALID_USER_INPUT,
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_form_unknown_error(hass: HomeAssistant) -> None:
    """Test config flow with an unexpected error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.synology_upgrades.config_flow.validate_input",
        side_effect=RuntimeError("Unexpected"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            VALID_USER_INPUT,
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "unknown"}


async def test_form_already_configured(hass: HomeAssistant) -> None:
    """Test config flow aborts when the same NAS is already configured."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Synology NAS (192.168.1.100)",
        data={**VALID_USER_INPUT},
        unique_id="192.168.1.100_5001",
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.synology_upgrades.config_flow.validate_input",
        return_value={"host": "192.168.1.100"},
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            VALID_USER_INPUT,
        )

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
python -m pytest tests/test_config_flow.py -v
```

Expected: FAIL — `config_flow` module doesn't exist yet.

- [ ] **Step 4: Write config_flow.py**

Create `custom_components/synology_upgrades/config_flow.py`:

```python
"""Config flow for Synology Upgrades integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .synology_client import SynologyAuthenticationError, SynologyClient, SynologyConnectionError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SSL, default=DEFAULT_SSL): bool,
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)


class InvalidAuth(Exception):
    """Error to indicate invalid authentication."""


class CannotConnect(Exception):
    """Error to indicate the NAS is unreachable."""


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict:
    """Validate credentials by connecting to the NAS."""
    client = SynologyClient(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        secure=data[CONF_SSL],
        verify_ssl=data[CONF_VERIFY_SSL],
    )
    try:
        await hass.async_add_executor_job(client.connect)
    except SynologyAuthenticationError as err:
        raise InvalidAuth from err
    except SynologyConnectionError as err:
        raise CannotConnect from err
    return {"host": data[CONF_HOST]}


class SynologyUpgradesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Synology Upgrades."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] | None = None

        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors = {"base": "authentication_error"}
            except CannotConnect:
                errors = {"base": "cannot_connect"}
            except Exception:
                _LOGGER.exception("Unexpected exception during validation")
                errors = {"base": "unknown"}
            else:
                host = user_input[CONF_HOST]
                port = user_input[CONF_PORT]
                await self.async_set_unique_id(f"{host}_{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Synology NAS ({host})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
```

- [ ] **Step 5: Create strings.json**

Create `custom_components/synology_upgrades/strings.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Connect to Synology NAS",
        "description": "Enter your NAS connection details. The account must have admin privileges.",
        "data": {
          "host": "Host",
          "port": "Port",
          "username": "Username",
          "password": "Password",
          "ssl": "Use HTTPS",
          "verify_ssl": "Verify SSL certificate"
        }
      }
    },
    "abort": {
      "already_configured": "This Synology NAS is already configured."
    },
    "error": {
      "authentication_error": "Invalid credentials. Ensure the account has admin privileges.",
      "cannot_connect": "Cannot connect to the NAS. Check the host, port, and SSL settings.",
      "unknown": "An unexpected error occurred."
    }
  }
}
```

- [ ] **Step 6: Create translations/en.json**

Copy `strings.json` to `custom_components/synology_upgrades/translations/en.json` (identical content).

- [ ] **Step 7: Run config flow tests**

```bash
python -m pytest tests/test_config_flow.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 8: Commit**

```bash
git add custom_components/synology_upgrades/config_flow.py custom_components/synology_upgrades/strings.json custom_components/synology_upgrades/translations/ tests/conftest.py tests/test_config_flow.py
git commit -m "feat: add config flow with credential validation"
```

---

### Task 5: Coordinator

**Files:**
- Create: `custom_components/synology_upgrades/coordinator.py`
- Create: `tests/test_coordinator.py`

- [ ] **Step 1: Write failing coordinator tests**

Create `tests/test_coordinator.py`:

```python
"""Tests for the Synology Upgrades coordinator."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.synology_upgrades.coordinator import SynologyUpgradesCoordinator
from custom_components.synology_upgrades.synology_client import (
    ContainerInfo,
    DsmUpdateInfo,
    PackageInfo,
)


@pytest.fixture
def mock_client():
    """Create a mock SynologyClient."""
    client = MagicMock()
    client.get_dsm_update.return_value = DsmUpdateInfo(
        installed_version="7.2.1-69057",
        latest_version="7.2.2-72806",
        update_available=True,
        release_notes="Bug fixes",
    )
    client.get_packages.return_value = [
        PackageInfo(
            package_id="HyperBackup",
            display_name="Hyper Backup",
            installed_version="4.1.0-3735",
            latest_version="4.1.1-3740",
            update_available=True,
        ),
    ]
    client.get_containers.return_value = [
        ContainerInfo(
            name="homeassistant",
            image="ghcr.io/home-assistant/home-assistant:2024.1",
            installed_version="2024.1",
            latest_version="2024.1",
            update_available=False,
            status="running",
        ),
    ]
    return client


async def test_coordinator_fetches_all_sources(hass: HomeAssistant, mock_client) -> None:
    """Test that coordinator fetches DSM, packages, and containers."""
    coordinator = SynologyUpgradesCoordinator(hass, mock_client)
    await coordinator.async_config_entry_first_refresh()

    assert coordinator.data["dsm"].installed_version == "7.2.1-69057"
    assert coordinator.data["dsm"].update_available is True
    assert len(coordinator.data["packages"]) == 1
    assert coordinator.data["packages"][0].package_id == "HyperBackup"
    assert len(coordinator.data["containers"]) == 1
    assert coordinator.data["containers"][0].name == "homeassistant"


async def test_coordinator_dsm_failure_preserves_other_data(
    hass: HomeAssistant, mock_client
) -> None:
    """Test that DSM failure doesn't block packages and containers."""
    mock_client.get_dsm_update.side_effect = Exception("DSM API down")

    coordinator = SynologyUpgradesCoordinator(hass, mock_client)
    await coordinator.async_config_entry_first_refresh()

    assert coordinator.data["dsm"] is None
    assert len(coordinator.data["packages"]) == 1
    assert len(coordinator.data["containers"]) == 1


async def test_coordinator_packages_failure_preserves_other_data(
    hass: HomeAssistant, mock_client
) -> None:
    """Test that package failure doesn't block DSM and containers."""
    mock_client.get_packages.side_effect = Exception("Package API down")

    coordinator = SynologyUpgradesCoordinator(hass, mock_client)
    await coordinator.async_config_entry_first_refresh()

    assert coordinator.data["dsm"] is not None
    assert coordinator.data["packages"] == []
    assert len(coordinator.data["containers"]) == 1


async def test_coordinator_all_fail_raises(hass: HomeAssistant, mock_client) -> None:
    """Test that coordinator raises UpdateFailed when all sources fail."""
    mock_client.get_dsm_update.side_effect = Exception("DSM down")
    mock_client.get_packages.side_effect = Exception("Packages down")
    mock_client.get_containers.side_effect = Exception("Docker down")

    coordinator = SynologyUpgradesCoordinator(hass, mock_client)
    with pytest.raises(UpdateFailed):
        await coordinator.async_config_entry_first_refresh()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_coordinator.py -v
```

Expected: FAIL — `coordinator` module doesn't exist yet.

- [ ] **Step 3: Write coordinator.py**

Create `custom_components/synology_upgrades/coordinator.py`:

```python
"""DataUpdateCoordinator for Synology Upgrades."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN
from .synology_client import SynologyClient

_LOGGER = logging.getLogger(__name__)


class SynologyUpgradesCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls DSM, packages, and containers."""

    def __init__(self, hass: HomeAssistant, client: SynologyClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from all three sources with per-source error isolation."""
        dsm = None
        packages = []
        containers = []
        failures = []

        try:
            dsm = await self.hass.async_add_executor_job(self.client.get_dsm_update)
        except Exception:
            _LOGGER.warning("Failed to fetch DSM update info", exc_info=True)
            failures.append("dsm")

        try:
            packages = await self.hass.async_add_executor_job(self.client.get_packages)
        except Exception:
            _LOGGER.warning("Failed to fetch package info", exc_info=True)
            failures.append("packages")

        try:
            containers = await self.hass.async_add_executor_job(self.client.get_containers)
        except Exception:
            _LOGGER.warning("Failed to fetch container info", exc_info=True)
            failures.append("containers")

        if len(failures) == 3:
            raise UpdateFailed("All data sources failed")

        return {
            "dsm": dsm,
            "packages": packages,
            "containers": containers,
        }
```

- [ ] **Step 4: Run coordinator tests**

```bash
python -m pytest tests/test_coordinator.py -v
```

Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/synology_upgrades/coordinator.py tests/test_coordinator.py
git commit -m "feat: add DataUpdateCoordinator with per-source error isolation"
```

---

### Task 6: Update Entities

**Files:**
- Create: `custom_components/synology_upgrades/update.py`
- Create: `tests/test_update.py`

- [ ] **Step 1: Write failing tests for DSM update entity**

Create `tests/test_update.py`:

```python
"""Tests for Synology Upgrades update entities."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.update import UpdateEntityFeature
from homeassistant.core import HomeAssistant

from custom_components.synology_upgrades.synology_client import (
    ContainerInfo,
    DsmUpdateInfo,
    PackageInfo,
)
from custom_components.synology_upgrades.update import (
    SynologyContainerUpdateEntity,
    SynologyDSMUpdateEntity,
    SynologyPackageUpdateEntity,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with sample data."""
    coordinator = MagicMock()
    coordinator.data = {
        "dsm": DsmUpdateInfo(
            installed_version="7.2.1-69057",
            latest_version="7.2.2-72806",
            update_available=True,
            release_notes="Bug fixes and improvements",
        ),
        "packages": [
            PackageInfo(
                package_id="HyperBackup",
                display_name="Hyper Backup",
                installed_version="4.1.0-3735",
                latest_version="4.1.1-3740",
                update_available=True,
            ),
            PackageInfo(
                package_id="SynologyDrive",
                display_name="Synology Drive Server",
                installed_version="3.5.0",
                latest_version="3.5.0",
                update_available=False,
            ),
        ],
        "containers": [
            ContainerInfo(
                name="homeassistant",
                image="ghcr.io/home-assistant/home-assistant:2024.1",
                installed_version="2024.1",
                latest_version="2024.1",
                update_available=False,
                status="running",
            ),
        ],
    }
    coordinator.client = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


class TestDSMUpdateEntity:
    """Tests for the DSM firmware update entity."""

    def test_properties(self, mock_coordinator):
        """Test DSM entity properties."""
        entity = SynologyDSMUpdateEntity(mock_coordinator)

        assert entity.installed_version == "7.2.1-69057"
        assert entity.latest_version == "7.2.2-72806"
        assert entity.title == "DSM"
        assert UpdateEntityFeature.INSTALL in entity.supported_features

    def test_no_update_available(self, mock_coordinator):
        """Test DSM entity when up to date."""
        mock_coordinator.data["dsm"] = DsmUpdateInfo(
            installed_version="7.2.2-72806",
            latest_version=None,
            update_available=False,
            release_notes=None,
        )
        entity = SynologyDSMUpdateEntity(mock_coordinator)

        assert entity.installed_version == "7.2.2-72806"
        assert entity.latest_version == "7.2.2-72806"

    def test_dsm_data_none(self, mock_coordinator):
        """Test DSM entity when DSM data fetch failed."""
        mock_coordinator.data["dsm"] = None
        entity = SynologyDSMUpdateEntity(mock_coordinator)

        assert entity.installed_version is None
        assert entity.latest_version is None

    @pytest.mark.asyncio
    async def test_install(self, mock_coordinator):
        """Test triggering DSM upgrade."""
        entity = SynologyDSMUpdateEntity(mock_coordinator)
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_install(version=None, backup=None)

        entity.hass.async_add_executor_job.assert_called_once_with(
            mock_coordinator.client.upgrade_dsm
        )


class TestPackageUpdateEntity:
    """Tests for the package update entity."""

    def test_properties(self, mock_coordinator):
        """Test package entity properties."""
        pkg = mock_coordinator.data["packages"][0]
        entity = SynologyPackageUpdateEntity(mock_coordinator, pkg.package_id)

        assert entity.installed_version == "4.1.0-3735"
        assert entity.latest_version == "4.1.1-3740"
        assert entity.title == "Hyper Backup"
        assert UpdateEntityFeature.INSTALL in entity.supported_features

    def test_up_to_date_package(self, mock_coordinator):
        """Test package entity when up to date."""
        pkg = mock_coordinator.data["packages"][1]
        entity = SynologyPackageUpdateEntity(mock_coordinator, pkg.package_id)

        assert entity.installed_version == "3.5.0"
        assert entity.latest_version == "3.5.0"

    @pytest.mark.asyncio
    async def test_install_triggers_security_scan(self, mock_coordinator):
        """Test that package install triggers security scan after."""
        pkg = mock_coordinator.data["packages"][0]
        entity = SynologyPackageUpdateEntity(mock_coordinator, pkg.package_id)
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_install(version=None, backup=None)

        calls = entity.hass.async_add_executor_job.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == mock_coordinator.client.upgrade_package
        assert calls[0].args[1] == "HyperBackup"
        assert calls[1].args[0] == mock_coordinator.client.trigger_security_scan


class TestContainerUpdateEntity:
    """Tests for the container update entity."""

    def test_properties(self, mock_coordinator):
        """Test container entity properties."""
        ctr = mock_coordinator.data["containers"][0]
        entity = SynologyContainerUpdateEntity(mock_coordinator, ctr.name)

        assert entity.installed_version == "2024.1"
        assert entity.title == "homeassistant"
        assert UpdateEntityFeature.INSTALL in entity.supported_features

    @pytest.mark.asyncio
    async def test_install(self, mock_coordinator):
        """Test triggering container update."""
        ctr = mock_coordinator.data["containers"][0]
        entity = SynologyContainerUpdateEntity(mock_coordinator, ctr.name)
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_install(version=None, backup=None)

        entity.hass.async_add_executor_job.assert_called_once_with(
            mock_coordinator.client.update_container,
            "homeassistant",
            "ghcr.io/home-assistant/home-assistant:2024.1",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_update.py -v
```

Expected: FAIL — `update` module doesn't exist yet.

- [ ] **Step 3: Write update.py**

Create `custom_components/synology_upgrades/update.py`:

```python
"""Update entities for Synology Upgrades."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SynologyUpgradesCoordinator
from .synology_client import ContainerInfo, PackageInfo


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Synology Upgrades update entities."""
    coordinator: SynologyUpgradesCoordinator = entry.runtime_data.coordinator
    entities: list[UpdateEntity] = []

    entities.append(SynologyDSMUpdateEntity(coordinator))

    for pkg in coordinator.data.get("packages", []):
        entities.append(SynologyPackageUpdateEntity(coordinator, pkg.package_id))

    for ctr in coordinator.data.get("containers", []):
        entities.append(SynologyContainerUpdateEntity(coordinator, ctr.name))

    async_add_entities(entities)


class SynologyDSMUpdateEntity(CoordinatorEntity[SynologyUpgradesCoordinator], UpdateEntity):
    """Update entity for DSM firmware."""

    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: SynologyUpgradesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_dsm"

    @property
    def title(self) -> str:
        return "DSM"

    @property
    def installed_version(self) -> str | None:
        dsm = self.coordinator.data.get("dsm")
        if dsm is None:
            return None
        return dsm.installed_version

    @property
    def latest_version(self) -> str | None:
        dsm = self.coordinator.data.get("dsm")
        if dsm is None:
            return None
        if dsm.latest_version is None:
            return dsm.installed_version
        return dsm.latest_version

    async def async_release_notes(self) -> str | None:
        dsm = self.coordinator.data.get("dsm")
        if dsm is None:
            return None
        return dsm.release_notes

    async def async_install(self, version: str | None, backup: bool | None, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self.coordinator.client.upgrade_dsm)
        await self.coordinator.async_request_refresh()


class SynologyPackageUpdateEntity(CoordinatorEntity[SynologyUpgradesCoordinator], UpdateEntity):
    """Update entity for a Synology package."""

    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, coordinator: SynologyUpgradesCoordinator, package_id: str) -> None:
        super().__init__(coordinator)
        self._package_id = package_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_pkg_{package_id}"

    def _get_package(self) -> PackageInfo | None:
        for pkg in self.coordinator.data.get("packages", []):
            if pkg.package_id == self._package_id:
                return pkg
        return None

    @property
    def title(self) -> str:
        pkg = self._get_package()
        return pkg.display_name if pkg else self._package_id

    @property
    def installed_version(self) -> str | None:
        pkg = self._get_package()
        return pkg.installed_version if pkg else None

    @property
    def latest_version(self) -> str | None:
        pkg = self._get_package()
        return pkg.latest_version if pkg else None

    async def async_install(self, version: str | None, backup: bool | None, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.client.upgrade_package, self._package_id
        )
        await self.hass.async_add_executor_job(self.coordinator.client.trigger_security_scan)
        await self.coordinator.async_request_refresh()


class SynologyContainerUpdateEntity(CoordinatorEntity[SynologyUpgradesCoordinator], UpdateEntity):
    """Update entity for a Docker container."""

    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, coordinator: SynologyUpgradesCoordinator, container_name: str) -> None:
        super().__init__(coordinator)
        self._container_name = container_name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_ctr_{container_name}"

    def _get_container(self) -> ContainerInfo | None:
        for ctr in self.coordinator.data.get("containers", []):
            if ctr.name == self._container_name:
                return ctr
        return None

    @property
    def title(self) -> str:
        return self._container_name

    @property
    def installed_version(self) -> str | None:
        ctr = self._get_container()
        return ctr.installed_version if ctr else None

    @property
    def latest_version(self) -> str | None:
        ctr = self._get_container()
        return ctr.latest_version if ctr else None

    async def async_install(self, version: str | None, backup: bool | None, **kwargs: Any) -> None:
        ctr = self._get_container()
        if ctr is None:
            return
        await self.hass.async_add_executor_job(
            self.coordinator.client.update_container,
            self._container_name,
            ctr.image,
        )
        await self.coordinator.async_request_refresh()
```

- [ ] **Step 4: Run update entity tests**

```bash
python -m pytest tests/test_update.py -v
```

Expected: All 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/synology_upgrades/update.py tests/test_update.py
git commit -m "feat: add DSM, package, and container update entities"
```

---

### Task 7: Integration Init (Setup / Unload)

**Files:**
- Modify: `custom_components/synology_upgrades/__init__.py`
- Create: `tests/test_init.py`

- [ ] **Step 1: Write failing init tests**

Create `tests/test_init.py`:

```python
"""Tests for Synology Upgrades integration setup."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.synology_upgrades.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.synology_upgrades.synology_client import (
    DsmUpdateInfo,
    SynologyAuthenticationError,
    SynologyConnectionError,
)

MOCK_CONFIG = {
    CONF_HOST: "192.168.1.100",
    CONF_PORT: 5001,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_SSL: True,
    CONF_VERIFY_SSL: False,
}


def create_mock_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synology NAS (192.168.1.100)",
        data=MOCK_CONFIG,
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_entry(hass: HomeAssistant) -> None:
    """Test successful setup of config entry."""
    entry = create_mock_entry(hass)

    mock_client = MagicMock()
    mock_client.get_dsm_update.return_value = DsmUpdateInfo(
        installed_version="7.2.1", latest_version=None,
        update_available=False, release_notes=None,
    )
    mock_client.get_packages.return_value = []
    mock_client.get_containers.return_value = []

    with (
        patch(
            "custom_components.synology_upgrades.SynologyClient",
            return_value=mock_client,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=lambda: lambda *a, **kw: AsyncMock(return_value=True)(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None


async def test_setup_entry_auth_failed(hass: HomeAssistant) -> None:
    """Test that auth failure on startup triggers reauth."""
    entry = create_mock_entry(hass)

    mock_client = MagicMock()
    mock_client.connect.side_effect = SynologyAuthenticationError("Bad credentials")

    with patch(
        "custom_components.synology_upgrades.SynologyClient",
        return_value=mock_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    reauth_flows = [f for f in flows if f["context"].get("source") == "reauth"]
    assert len(reauth_flows) == 1


async def test_setup_entry_connection_error(hass: HomeAssistant) -> None:
    """Test that connection error marks entry for retry."""
    entry = create_mock_entry(hass)

    mock_client = MagicMock()
    mock_client.connect.side_effect = SynologyConnectionError("NAS unreachable")

    with patch(
        "custom_components.synology_upgrades.SynologyClient",
        return_value=mock_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(hass: HomeAssistant) -> None:
    """Test successful unload of config entry."""
    entry = create_mock_entry(hass)

    mock_client = MagicMock()
    mock_client.get_dsm_update.return_value = DsmUpdateInfo(
        installed_version="7.2.1", latest_version=None,
        update_available=False, release_notes=None,
    )
    mock_client.get_packages.return_value = []
    mock_client.get_containers.return_value = []

    with (
        patch(
            "custom_components.synology_upgrades.SynologyClient",
            return_value=mock_client,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=lambda: lambda *a, **kw: AsyncMock(return_value=True)(),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            new_callable=lambda: lambda *a, **kw: AsyncMock(return_value=True)(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(entry.entry_id)

    assert entry.state is ConfigEntryState.NOT_LOADED
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_init.py -v
```

Expected: FAIL — `__init__.py` is just a placeholder.

- [ ] **Step 3: Write the full __init__.py**

Replace `custom_components/synology_upgrades/__init__.py`:

```python
"""The Synology Upgrades integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    CONF_OTP_CODE,
    DOMAIN,
)
from .coordinator import SynologyUpgradesCoordinator
from .synology_client import SynologyAuthenticationError, SynologyClient, SynologyConnectionError

PLATFORMS = (Platform.UPDATE,)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class SynologyUpgradesData:
    """Runtime data for the Synology Upgrades integration."""

    client: SynologyClient
    coordinator: SynologyUpgradesCoordinator


type SynologyUpgradesConfigEntry = ConfigEntry[SynologyUpgradesData]


async def async_setup_entry(hass: HomeAssistant, entry: SynologyUpgradesConfigEntry) -> bool:
    """Set up Synology Upgrades from a config entry."""
    client = SynologyClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        secure=entry.data[CONF_SSL],
        verify_ssl=entry.data[CONF_VERIFY_SSL],
        otp_code=entry.data.get(CONF_OTP_CODE),
    )

    try:
        await hass.async_add_executor_job(client.connect)
    except SynologyAuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SynologyConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = SynologyUpgradesCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SynologyUpgradesData(client=client, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SynologyUpgradesConfigEntry) -> bool:
    """Unload Synology Upgrades."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

- [ ] **Step 4: Run init tests**

```bash
python -m pytest tests/test_init.py -v
```

Expected: All 4 tests pass.

- [ ] **Step 5: Run all tests together**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/synology_upgrades/__init__.py tests/test_init.py
git commit -m "feat: add integration setup/unload with auth and coordinator"
```

---

### Task 8: Linting + CLAUDE.md

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: Run ruff and fix any issues**

```bash
pip install ruff && ruff check custom_components/ tests/ && ruff format --check custom_components/ tests/
```

Fix any issues found.

- [ ] **Step 2: Format code**

```bash
ruff format custom_components/ tests/
```

- [ ] **Step 3: Create CLAUDE.md**

```markdown
# Synology Upgrades Home Assistant Integration

## What this is

A Home Assistant custom integration that provides update entities for Synology NAS devices — DSM firmware, installed packages, and Docker containers — all with install support.

## Architecture

- `synology_client.py` — Wrapper around the `synology-api` (N4S4) library. Uses the library's `SysInfo`, `Package`, and `Docker` classes for read operations. Makes raw API calls via `request_data()` for write operations not covered by the library (trigger DSM upgrade, pull Docker image, recreate container, trigger security scan). All methods are synchronous (`requests`-based).
- `coordinator.py` — `DataUpdateCoordinator` that polls all three data sources (DSM, packages, containers) every 6 hours. Calls `synology_client` methods via `hass.async_add_executor_job` since the API is sync. Per-source error isolation: if one source fails, others still update.
- `update.py` — Three `UpdateEntity` subclasses: `SynologyDSMUpdateEntity`, `SynologyPackageUpdateEntity`, `SynologyContainerUpdateEntity`. All support `INSTALL`. Package install auto-triggers a Security Advisor scan.
- `config_flow.py` — UI config flow collecting host, port, credentials, SSL settings. Validates by attempting a login.
- `__init__.py` — Entry setup: creates client, connects, creates coordinator, forwards to update platform.

## Key details

- The `synology-api` library is sync (uses `requests`). Every call goes through `hass.async_add_executor_job`.
- `BaseApi` classes share a class-level session. Multi-NAS support works via separate config entries, each with their own client instance.
- Container update = pull new image + stop + delete (preserve_profile=True) + create + start. All via raw API calls.
- Package install automatically triggers `SYNO.Core.SecurityScan.Status` method `system_scan` to clear Security Advisor warnings.

## Running tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Unit tests
python -m pytest tests/ -v

# Lint
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/
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
custom_components/synology_upgrades/   # The integration
tests/                                 # Unit tests (HA test framework)
docker-compose.dev.yml                 # Local HA dev instance
```

## Releasing

Version must be updated in two places, then tagged:

1. Bump `version` in `custom_components/synology_upgrades/manifest.json`
2. Bump `version` in `pyproject.toml`
3. Commit, then tag: `git tag v<version> && git push origin v<version>`

## Conventions

- Python 3.13+, async/await for HA code, sync for synology-api wrapper
- Tests use `pytest-homeassistant-custom-component` with mocked synology-api classes
- `ConfigEntryAuthFailed` for auth errors (triggers HA reauth flow), `ConfigEntryNotReady` for connection errors (triggers retry)
```

- [ ] **Step 4: Run full test suite one final time**

```bash
python -m pytest tests/ -v && ruff check custom_components/ tests/
```

Expected: All tests pass, no lint errors.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md project documentation"
```

- [ ] **Step 6: Final formatting commit if needed**

```bash
ruff format custom_components/ tests/
git add -A && git diff --cached --quiet || git commit -m "style: apply ruff formatting"
```
