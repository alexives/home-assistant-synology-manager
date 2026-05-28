"""Synology API client wrapper."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from packaging.version import InvalidVersion, Version

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
    changelog: str | None
    is_running: bool | None


@dataclass
class ContainerInfo:
    """Docker container information."""

    name: str
    display_name: str
    image: str
    installed_version: str
    latest_version: str | None
    update_available: bool
    status: str
    project_name: str = ""


@dataclass
class ProjectInfo:
    """Docker compose project information."""

    project_id: str
    name: str
    display_name: str
    status: str


@dataclass
class ProjectUpdateInfo:
    """Update information for a compose project (aggregated across containers)."""

    project_name: str
    display_name: str
    project_id: str | None
    containers: list[ContainerInfo]
    update_available: bool
    images: list[str]


def _prettify(name: str) -> str:
    """Convert a container/project name to a human-readable title."""
    return name.replace("-", " ").replace("_", " ").title()


def _container_display_name(
    container_name: str,
    project: str,
    service: str,
    project_counts: dict[str, int],
) -> str:
    """Build a display name from compose project and service labels."""
    if not project:
        return _prettify(container_name)
    if project_counts.get(project, 1) == 1:
        return _prettify(project)
    return f"{_prettify(project)} - {_prettify(service or container_name)}"


def _is_newer(candidate: str, installed: str) -> bool:
    """Return True if candidate is a newer version than installed."""
    if not candidate or candidate == installed:
        return False
    try:
        return Version(candidate.split("-")[0]) > Version(installed.split("-")[0])
    except InvalidVersion:
        return candidate != installed


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
        installable_map = {pkg["id"]: pkg for pkg in installable_data if isinstance(pkg, dict)}

        packages = []
        for pkg in installed_data:
            if not isinstance(pkg, dict):
                continue
            pkg_id = pkg.get("id", "")
            installed_ver = pkg.get("version", "")
            installable_pkg = installable_map.get(pkg_id, {})
            latest_ver = installable_pkg.get("version", "") if installable_pkg else None
            update_available = _is_newer(latest_ver, installed_ver) if latest_ver else False

            additional = pkg.get("additional", {})
            is_running = additional.get("status") == "running" if "status" in additional else None

            packages.append(
                PackageInfo(
                    package_id=pkg_id,
                    display_name=pkg.get("name", pkg_id),
                    installed_version=installed_ver,
                    latest_version=latest_ver if update_available else installed_ver,
                    update_available=update_available,
                    changelog=installable_pkg.get("changelog") if installable_pkg else None,
                    is_running=is_running,
                )
            )
        return packages

    def get_containers(self) -> list[ContainerInfo]:
        """List all Docker containers with update status."""
        if self._docker is None:
            return []

        result = self._docker.containers()
        data = result.get("data", {}).get("containers", [])

        image_info: dict[str, dict[str, str]] = {}
        try:
            images = self._docker.downloaded_images()
            img_data = images.get("data", {}).get("images", [])
            for img in img_data:
                if not isinstance(img, dict):
                    continue
                repo = img.get("repository", "")
                image_id = img.get("id", "")
                for tag in img.get("tags", []):
                    if tag == "<none>":
                        continue
                    image_info[f"{repo}:{tag}"] = {
                        "upgradable": img.get("upgradable", False),
                        "image_id": image_id,
                    }
        except Exception:
            _LOGGER.debug("downloaded_images failed", exc_info=True)

        project_counts: dict[str, int] = {}
        parsed: list[tuple[dict, str, str]] = []
        for ctr in data:
            if not isinstance(ctr, dict):
                continue
            if ctr.get("status", "") != "running":
                continue
            image = ctr.get("image", "")
            if image.startswith("sha256:"):
                continue
            labels = ctr.get("Labels", {})
            project = labels.get("com.docker.compose.project", "")
            service = labels.get("com.docker.compose.service", "")
            if project:
                project_counts[project] = project_counts.get(project, 0) + 1
            parsed.append((ctr, project, service))

        containers = []
        for ctr, project, service in parsed:
            image = ctr.get("image", "")
            repo = image.split(":")[0] if ":" in image else image
            tag = image.split(":")[-1] if ":" in image else "latest"
            image_key = f"{repo}:{tag}"
            info = image_info.get(image_key, {})
            update_available = bool(info.get("upgradable"))

            if not update_available:
                local_image_id = info.get("image_id", "")
                container_image_id = ctr.get("ImageID", "")
                if local_image_id and container_image_id and local_image_id != container_image_id:
                    update_available = True

            if update_available:
                local_short = ctr.get("ImageID", "")[-12:]
                local_image_id = info.get("image_id", "")
                container_image_id = ctr.get("ImageID", "")
                installed_version = f"{tag} ({local_short})" if local_short else tag
                if local_image_id and local_image_id != container_image_id:
                    latest_version = f"{tag} ({local_image_id[-12:]})"
                else:
                    latest_version = f"{tag} (update available)"
            else:
                installed_version = tag
                latest_version = tag

            display_name = _container_display_name(
                ctr.get("name", ""), project, service, project_counts
            )

            containers.append(
                ContainerInfo(
                    name=ctr.get("name", ""),
                    display_name=display_name,
                    image=image,
                    installed_version=installed_version,
                    latest_version=latest_version,
                    update_available=update_available,
                    status=ctr.get("status", "unknown"),
                    project_name=project,
                )
            )
        return containers

    @staticmethod
    def group_container_updates(
        containers: list[ContainerInfo], projects: list[ProjectInfo]
    ) -> tuple[list[ProjectUpdateInfo], list[ContainerInfo]]:
        """Group containers into project-level updates and standalone containers.

        Returns (project_updates, standalone_containers).
        """
        project_id_by_name = {p.name: p.project_id for p in projects}

        grouped: dict[str, list[ContainerInfo]] = {}
        standalone: list[ContainerInfo] = []

        for ctr in containers:
            if ctr.project_name:
                grouped.setdefault(ctr.project_name, []).append(ctr)
            else:
                standalone.append(ctr)

        project_updates = []
        for proj_name, ctrs in grouped.items():
            project_updates.append(
                ProjectUpdateInfo(
                    project_name=proj_name,
                    display_name=_prettify(proj_name),
                    project_id=project_id_by_name.get(proj_name),
                    containers=ctrs,
                    update_available=any(c.update_available for c in ctrs),
                    images=[c.image for c in ctrs],
                )
            )

        return project_updates, standalone

    def get_projects(self) -> list[ProjectInfo]:
        """List all Docker compose projects."""
        if self._docker is None:
            return []

        try:
            result = self._docker.list_projects()
        except Exception:
            _LOGGER.debug("list_projects failed", exc_info=True)
            return []

        projects = []
        for pid, proj in result.get("data", {}).items():
            if not isinstance(proj, dict):
                continue
            name = proj.get("name", "")
            status = proj.get("status", "unknown")
            projects.append(
                ProjectInfo(
                    project_id=pid,
                    name=name,
                    display_name=_prettify(name),
                    status=status,
                )
            )
        return projects

    def _docker_write(self, method_name: str, *args, **kwargs):
        """Execute a Docker write operation, reconnecting on stale session."""
        try:
            return getattr(self._docker, method_name)(*args, **kwargs)
        except Exception:
            _LOGGER.debug("Docker %s failed, reconnecting and retrying", method_name, exc_info=True)
            self._reconnect_docker()
            return getattr(self._docker, method_name)(*args, **kwargs)

    def _compound_project_request(self, method: str, params: dict | None = None) -> dict:
        """Send a SYNO.Docker.Project request via the compound API wrapper.

        The Project API has requestFormat=JSON and only works through
        SYNO.Entry.Request, not via direct GET/POST.
        """
        import requests as req_lib

        inner = {"api": "SYNO.Docker.Project", "method": method, "version": 1}
        if params:
            inner.update(params)

        scheme = "https" if self._secure else "http"
        url = f"{scheme}://{self._host}:{self._port}/webapi/entry.cgi"
        form = {
            "api": "SYNO.Entry.Request",
            "method": "request",
            "version": 1,
            "compound": json.dumps([inner]),
            "_sid": self._docker.session._sid,
        }
        resp = req_lib.post(
            url,
            data=form,
            verify=self._verify_ssl,
            headers={"X-SYNO-TOKEN": self._docker.session._syno_token},
        )
        resp.raise_for_status()
        outer = resp.json()
        result = outer.get("data", {}).get("result", [{}])[0]
        if not result.get("success"):
            raise RuntimeError(f"SYNO.Docker.Project {method} failed: {result}")
        return result.get("data", {})

    def _build_project(self, project_id: str) -> dict:
        """Rebuild a compose project (pull new images, recreate containers).

        Calls build twice: the first recreates containers with new images but
        Synology may assign hash-prefixed names. The second normalizes names
        back to those declared in the compose file.
        """
        result = self._compound_project_request("build", {"id": project_id})
        try:
            self._compound_project_request("build", {"id": project_id})
        except Exception:
            _LOGGER.debug("Second build (name normalization) failed", exc_info=True)
        return result

    def _get_project_containers(self, project_name: str) -> list[str]:
        """Get container names belonging to a compose project."""
        result = self._docker.containers()
        names = []
        for ctr in result.get("data", {}).get("containers", []):
            if not isinstance(ctr, dict):
                continue
            labels = ctr.get("Labels", {})
            if labels.get("com.docker.compose.project", "") == project_name:
                names.append(ctr.get("name", ""))
        return [n for n in names if n]

    def _get_project_name(self, project_id: str) -> str | None:
        """Resolve project UUID to project name."""
        result = self._docker.list_projects()
        proj = result.get("data", {}).get(project_id)
        if proj:
            return proj.get("name")
        return None

    def _container_fallback(self, project_id: str, action: str) -> None:
        """Start/stop individual containers when the project API fails."""
        name = self._get_project_name(project_id)
        if not name:
            raise RuntimeError(f"Project {project_id} not found")
        func = self._docker.start_container if action == "start" else self._docker.stop_container
        for ctr in self._get_project_containers(name):
            func(ctr)

    def start_project(self, project_id: str) -> None:
        """Start a compose project."""
        try:
            self._compound_project_request("start", {"id": project_id})
        except Exception:
            _LOGGER.debug("Compound start_project failed, falling back to container-level start")
            self._container_fallback(project_id, "start")

    def stop_project(self, project_id: str) -> None:
        """Stop a compose project."""
        try:
            self._compound_project_request("stop", {"id": project_id})
        except Exception:
            _LOGGER.debug("Compound stop_project failed, falling back to container-level stop")
            self._container_fallback(project_id, "stop")

    def start_package(self, package_id: str) -> None:
        """Start a package."""
        api_name = "SYNO.Core.Package.Control"
        info = self._package.core_list[api_name]
        self._package.request_data(
            api_name,
            info["path"],
            req_param={"method": "start", "version": info["minVersion"], "id": package_id},
        )

    def stop_package(self, package_id: str) -> None:
        """Stop a package."""
        api_name = "SYNO.Core.Package.Control"
        info = self._package.core_list[api_name]
        self._package.request_data(
            api_name,
            info["path"],
            req_param={"method": "stop", "version": info["minVersion"], "id": package_id},
        )

    def upgrade_dsm(self) -> None:
        """Trigger DSM firmware download and install."""
        self._sysinfo.request_data(
            "SYNO.Core.Upgrade.Server",
            "entry.cgi",
            req_param={"method": "download", "version": 2},
        )

    def upgrade_package(self, package_id: str) -> None:
        """Trigger a package upgrade via SYNO.Core.Package.Installation."""
        import time

        response = self._package.list_installable()
        installable = response.get("data", {}).get("packages", [])
        pkg_info = next((p for p in installable if p.get("id") == package_id), None)
        if pkg_info is None:
            raise RuntimeError(f"Package {package_id} not found in installable list")

        _LOGGER.debug("Upgrading package %s to %s", package_id, pkg_info.get("version", ""))
        response = self._package.request_data(
            "SYNO.Core.Package.Installation",
            "entry.cgi",
            req_param={
                "method": "install",
                "version": 1,
                "operation": "upgrade",
                "type": 0,
                "blqinst": False,
                "url": pkg_info.get("link", ""),
                "name": package_id,
                "checksum": pkg_info.get("md5", ""),
                "filesize": pkg_info.get("size", 0),
            },
        )
        target_ver = pkg_info.get("version", "")

        for _ in range(120):
            installed = self._sysinfo.installed_package_list()
            for pkg in installed.get("data", {}).get("packages", []):
                if pkg.get("id") == package_id and pkg.get("version") == target_ver:
                    return
            time.sleep(2)

        _LOGGER.warning("Package %s upgrade did not complete within timeout", package_id)

    def trigger_security_scan(self) -> None:
        """Trigger a Security Advisor scan (best-effort)."""
        try:
            self._sysinfo.request_data(
                "SYNO.Core.SecurityScan.Status",
                "entry.cgi",
                req_param={"method": "system_scan", "version": 1},
            )
        except Exception:
            _LOGGER.debug("Security scan trigger failed", exc_info=True)

    def _reconnect_docker(self) -> None:
        """Re-create the Docker API session (e.g. after a failed pull invalidates it)."""
        from synology_api.base_api import BaseApi

        try:
            BaseApi.shared_session = None
            self._docker = DockerApi(**self._api_kwargs())
        except Exception:
            _LOGGER.warning("Docker reconnect failed", exc_info=True)

    def update_container(self, container_name: str, image: str) -> None:
        """Rebuild a container's compose project with the latest image on disk."""
        self._reconnect_docker()
        repo = image.split(":")[0] if ":" in image else image
        tag = image.split(":")[-1] if ":" in image else "latest"

        if not repo.startswith(("ghcr.io/", "lscr.io/")):
            self._pull_image(repo, tag)
            self._reconnect_docker()

        project_id = self._find_project_for_container(container_name)
        if project_id:
            self._build_project(project_id)
        else:
            self._docker.stop_container(container_name)
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

    def update_project(self, project_id: str, images: list[str]) -> None:
        """Pull images that need it, then rebuild the compose project."""
        self._reconnect_docker()
        for image in images:
            repo = image.split(":")[0] if ":" in image else image
            tag = image.split(":")[-1] if ":" in image else "latest"
            if not repo.startswith(("ghcr.io/", "lscr.io/")):
                self._pull_image(repo, tag)
                self._reconnect_docker()
        self._build_project(project_id)

    def _pull_image(self, repo: str, tag: str) -> None:
        """Best-effort image pull via Synology API. Proceeds to rebuild even on failure."""
        import time

        try:
            result = self._docker.request_data(
                "SYNO.Docker.Image",
                "entry.cgi",
                req_param={
                    "method": "pull_start",
                    "version": 1,
                    "repository": repo,
                    "tag": tag,
                },
            )
        except Exception:
            _LOGGER.debug("pull_start failed for %s:%s, image may already be on disk", repo, tag)
            return

        task_id = result.get("data", {}).get("task_id", "")
        if not task_id:
            return

        for _ in range(300):
            try:
                status = self._docker.request_data(
                    "SYNO.Docker.Image",
                    "entry.cgi",
                    req_param={
                        "method": "pull_status",
                        "version": 1,
                        "task_id": task_id,
                    },
                )
                if status.get("data", {}).get("finished"):
                    return
            except Exception:
                pass
            time.sleep(2)

        _LOGGER.debug(
            "Image pull status tracking failed for %s:%s, proceeding with rebuild", repo, tag
        )

    def _find_project_for_container(self, container_name: str) -> str | None:
        """Look up the compose project ID for a container."""
        result = self._docker.containers()
        for ctr in result.get("data", {}).get("containers", []):
            if not isinstance(ctr, dict) or ctr.get("name") != container_name:
                continue
            project_name = ctr.get("Labels", {}).get("com.docker.compose.project", "")
            if not project_name:
                return None
            projects = self._docker.list_projects()
            for pid, proj in projects.get("data", {}).items():
                if proj.get("name") == project_name:
                    return pid
            return None
        return None
