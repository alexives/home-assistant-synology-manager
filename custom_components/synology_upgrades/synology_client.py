"""Synology API client wrapper."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

try:
    from synology_api.core_package import Package
    from synology_api.core_sys_info import SysInfo
    from synology_api.docker_api import Docker as DockerApi
except ImportError:
    SysInfo = None  # type: ignore[assignment,misc]
    Package = None  # type: ignore[assignment,misc]
    DockerApi = None  # type: ignore[assignment,misc]


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
            pkg["id"]: pkg.get("version", "") for pkg in installable_data if isinstance(pkg, dict)
        }

        packages = []
        for pkg in installed_data:
            if not isinstance(pkg, dict):
                continue
            pkg_id = pkg.get("id", "")
            installed_ver = pkg.get("version", "")
            latest_ver = installable_map.get(pkg_id)
            update_available = bool(latest_ver and latest_ver != installed_ver)

            packages.append(
                PackageInfo(
                    package_id=pkg_id,
                    display_name=pkg.get("name", pkg_id),
                    installed_version=installed_ver,
                    latest_version=latest_ver if update_available else installed_ver,
                    update_available=update_available,
                )
            )
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
            containers.append(
                ContainerInfo(
                    name=ctr.get("name", ""),
                    image=image,
                    installed_version=tag,
                    latest_version=tag,
                    update_available=False,
                    status=ctr.get("status", "unknown"),
                )
            )
        return containers

    def upgrade_dsm(self) -> None:
        """Trigger DSM firmware download and install."""
        self._sysinfo.request_data(
            "SYNO.Core.Upgrade.Server",
            "entry.cgi",
            req_param={"method": "download", "version": 2},
        )

    def upgrade_package(self, package_id: str) -> None:
        """Trigger a package upgrade.

        Calling download_package for an already-installed package
        auto-triggers the upgrade on the NAS. We just need to download
        and wait for completion.
        """
        import time

        response = self._package.list_installable()
        installable = response.get("data", {}).get("packages", [])
        pkg_info = next((p for p in installable if p.get("id") == package_id), None)
        if pkg_info is None:
            raise RuntimeError(f"Package {package_id} not found in installable list")

        _LOGGER.debug("Upgrading package %s from %s", package_id, pkg_info.get("link", ""))
        response = self._package.download_package(
            url=pkg_info.get("link", ""),
            package_id=package_id,
            checksum=pkg_info.get("md5", ""),
            filesize=pkg_info.get("size", 0),
        )
        task_id = response.get("data", {}).get("taskid", "")

        for _ in range(300):
            status = self._package.get_dowload_package_status(task_id=task_id)
            data = status.get("data", {})
            if data.get("finished") and not data.get("installing"):
                break
            time.sleep(1)

    def trigger_security_scan(self) -> None:
        """Trigger a Security Advisor scan."""
        self._sysinfo.request_data(
            "SYNO.Core.SecurityScan.Status",
            "entry.cgi",
            req_param={"method": "system_scan", "version": 1},
        )

    def update_container(self, container_name: str, image: str) -> None:
        """Pull new image and recreate container."""
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
