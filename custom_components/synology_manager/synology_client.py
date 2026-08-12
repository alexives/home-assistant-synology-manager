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


# DSM sends these codes without any error payload on package endpoints;
# keep them readable (the library's table had entries for them).
_DSM_ERROR_HINTS = {
    101: "no parameter of API, method or version",
    119: "invalid session / SID not found",
    120: "invalid parameter",
}


class SynologyAuthenticationError(Exception):
    """Raised when authentication fails."""


class SynologyConnectionError(Exception):
    """Raised when the NAS is unreachable."""


def _iter_exc_chain(err: BaseException):
    """Yield err and every exception it was raised from, cycle-safe."""
    seen: set[int] = set()
    cur: BaseException | None = err
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ or cur.__context__


def _nas_not_ready_code(err: BaseException) -> int | None:
    """Return 498/499 when the exception chain says DSM itself is not ready.

    While booting or applying a system update, DSM answers every API call -
    login included - with error 499 ("system not ready" in DSM's own login
    JS) or 498 ("system upgrading"). The library has no table entry for
    either code and dies with a KeyError while formatting its message, so
    check both the ``error_code`` attribute and bare KeyError shapes.
    """
    for exc in _iter_exc_chain(err):
        code = getattr(exc, "error_code", None)
        if code is None and isinstance(exc, KeyError) and exc.args:
            code = exc.args[0]
        if code in (498, 499):
            return code
    return None


def _connection_dropped(err: BaseException) -> bool:
    """True when the exception chain says the connection died mid-request.

    ChunkedEncodingError covers DSM's web stack closing a response cleanly
    mid-body during upgrade teardown (requests wraps the underlying
    IncompleteRead in it rather than in a ConnectionError).
    """
    import requests

    dropped = (
        requests.exceptions.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
        ConnectionError,
    )
    return any(isinstance(exc, dropped) for exc in _iter_exc_chain(err))


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


def _err_detail(err: Exception) -> str:
    """Extract a diagnosable message from any exception.

    synology-api exceptions can stringify to "" (the text lives in
    ``error_message``) and map reserved DSM error codes (112-149) to the
    placeholder "Preserve for other purpose", so include the numeric code.
    DSM 498/499 (unknown to the library, which dies with a bare KeyError)
    mean the NAS itself is booting or applying an update - say so instead
    of surfacing "499".
    """
    not_ready = _nas_not_ready_code(err)
    if not_ready is not None:
        return (
            f"DSM error {not_ready}: the NAS is not ready (starting up or "
            "applying a system update); it should recover on its own"
        )
    detail = getattr(err, "error_message", None) or str(err) or type(err).__name__
    code = getattr(err, "error_code", None)
    if code is not None:
        detail = f"DSM error {code}: {detail}"
    return detail


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
    """Return True if candidate is a newer version than installed.

    Synology versions are ``X.Y.Z-BUILD``. The build suffix is significant -
    updates often bump only the build (e.g. ``1.5.2-1831`` -> ``1.5.2-1832``) -
    so compare it when the leading version is equal.
    """
    if not candidate or candidate == installed:
        return False
    try:
        cand_ver = Version(candidate.split("-")[0])
        inst_ver = Version(installed.split("-")[0])
    except InvalidVersion:
        return candidate != installed
    if cand_ver != inst_ver:
        return cand_ver > inst_ver
    cand_build = candidate.split("-", 1)[1] if "-" in candidate else ""
    inst_build = installed.split("-", 1)[1] if "-" in installed else ""
    try:
        return int(cand_build) > int(inst_build)
    except ValueError:
        return cand_build > inst_build


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

    @staticmethod
    def _clear_shared_session() -> None:
        """Drop the library's class-level session so the next constructor re-authenticates.

        synology-api caches one session on ``BaseApi.shared_session`` and reuses
        it for every API class. Without clearing it, reconstructing a wrapper (on
        reconnect or HA reload) resurrects the stale SID instead of logging in.
        """
        try:
            from synology_api.base_api import BaseApi

            BaseApi.shared_session = None
        except Exception:
            _LOGGER.debug("Could not clear shared session", exc_info=True)

    def connect(self) -> None:
        """Authenticate and create API instances.

        Clears any cached session first so each connect mints a fresh login.
        Raises SynologyAuthenticationError on bad credentials.
        Raises SynologyConnectionError if NAS is unreachable.
        """
        self._clear_shared_session()
        kwargs = self._api_kwargs()
        try:
            self._sysinfo = SysInfo(**kwargs)
            self._package = Package(**kwargs)
        except Exception as err:
            if _nas_not_ready_code(err) is not None:
                raise SynologyConnectionError(_err_detail(err)) from err
            err_str = str(err).lower()
            if "login" in err_str or "auth" in err_str or "credential" in err_str:
                raise SynologyAuthenticationError(str(err)) from err
            raise SynologyConnectionError(str(err)) from err

        try:
            self._docker = DockerApi(**kwargs)
        except Exception as err:
            _LOGGER.warning(
                "Docker/Container Manager not available on this NAS: %s", _err_detail(err)
            )
            self._docker = None

    def get_dsm_update(self) -> DsmUpdateInfo:
        """Check for DSM firmware updates.

        On DSM 7 the upgrade check nests its payload under ``data.update``
        (e.g. ``{"update": {"available": true, "version": "DSM 7.3.2-86009
        Update 4", ...}}``) and does not include the installed version, which
        comes from a separate SYNO.DSM.Info getinfo call (``version_string``).
        """
        info = self._sysinfo.sys_upgrade_check()
        update = info.get("data", {}).get("update", {})
        available = update.get("available", False)
        dsm_info = self._sysinfo.request_data(
            "SYNO.DSM.Info",
            "entry.cgi",
            req_param={"method": "getinfo", "version": 2},
        )
        installed = dsm_info.get("data", {}).get("version_string", "")
        return DsmUpdateInfo(
            installed_version=installed,
            latest_version=update.get("version", None) if available else None,
            update_available=available,
            release_notes=update.get("release_note", None),
        )

    def _get_package_status(self) -> dict[str, dict[str, Any]]:
        """Fetch per-package status and startable flags via compound API.

        Returns a dict keyed by package ID with 'status' and 'startable' values.
        """
        try:
            result = self._compound_request(
                "SYNO.Core.Package",
                "list",
                2,
                self._sysinfo.session,
                params={"additional": ["status", "startable"]},
            )
            return {
                pkg["id"]: pkg.get("additional", {})
                for pkg in result.get("packages", [])
                if isinstance(pkg, dict) and pkg.get("id")
            }
        except Exception as err:
            _LOGGER.warning(
                "Package status fetch failed, running/stopped state unavailable: %s",
                _err_detail(err),
                exc_info=True,
            )
            return {}

    def get_packages(self) -> list[PackageInfo]:
        """List all installed packages with update status."""
        installed = self._sysinfo.installed_package_list()
        installed_data = installed.get("data", {}).get("packages", [])

        installable = self._package.list_installable()
        installable_data = installable.get("data", {}).get("packages", [])
        installable_map = {pkg["id"]: pkg for pkg in installable_data if isinstance(pkg, dict)}

        status_map = self._get_package_status()

        packages = []
        for pkg in installed_data:
            if not isinstance(pkg, dict):
                continue
            pkg_id = pkg.get("id", "")
            installed_ver = pkg.get("version", "")
            installable_pkg = installable_map.get(pkg_id, {})
            latest_ver = installable_pkg.get("version", "") if installable_pkg else None
            update_available = _is_newer(latest_ver, installed_ver) if latest_ver else False

            pkg_status = status_map.get(pkg_id, {})
            if pkg_status.get("startable"):
                is_running = pkg_status.get("status") == "running"
            else:
                is_running = None

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
        except Exception as err:
            _LOGGER.warning(
                "downloaded_images failed, container update detection degraded: %s",
                _err_detail(err),
                exc_info=True,
            )

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
        except Exception as err:
            _LOGGER.warning(
                "list_projects failed, no project entities this cycle: %s",
                _err_detail(err),
                exc_info=True,
            )
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
            self.reconnect()
            return getattr(self._docker, method_name)(*args, **kwargs)

    def _compound_request(
        self, api: str, method: str, version: int, session, params: dict | None = None
    ) -> dict:
        """Send a request via the SYNO.Entry.Request compound API wrapper.

        APIs with requestFormat=JSON only work through this wrapper,
        not via direct GET/POST.
        """
        import requests as req_lib

        inner: dict[str, Any] = {"api": api, "method": method, "version": version}
        if params:
            inner.update(params)

        scheme = "https" if self._secure else "http"
        url = f"{scheme}://{self._host}:{self._port}/webapi/entry.cgi"
        form = {
            "api": "SYNO.Entry.Request",
            "method": "request",
            "version": 1,
            "compound": json.dumps([inner]),
            "_sid": session._sid,
        }
        resp = req_lib.post(
            url,
            data=form,
            verify=self._verify_ssl,
            headers={"X-SYNO-TOKEN": session._syno_token},
        )
        resp.raise_for_status()
        outer = resp.json()
        result = outer.get("data", {}).get("result", [{}])[0]
        if not result.get("success"):
            raise RuntimeError(f"{api} {method} failed: {result}")
        return result.get("data", {})

    def _compound_project_request(self, method: str, params: dict | None = None) -> dict:
        """Send a SYNO.Docker.Project request via the compound API."""
        return self._compound_request(
            "SYNO.Docker.Project", method, 1, self._docker.session, params
        )

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
        self._wait_for_container_manager()
        try:
            self._compound_project_request("start", {"id": project_id})
        except Exception as err:
            _LOGGER.warning(
                "Project start via SYNO.Docker.Project failed (%s), "
                "falling back to container-level start",
                _err_detail(err),
            )
            self._container_fallback(project_id, "start")

    def stop_project(self, project_id: str) -> None:
        """Stop a compose project."""
        self._wait_for_container_manager()
        try:
            self._compound_project_request("stop", {"id": project_id})
        except Exception as err:
            _LOGGER.warning(
                "Project stop via SYNO.Docker.Project failed (%s), "
                "falling back to container-level stop",
                _err_detail(err),
            )
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
        """Download the pending DSM update, then trigger the install.

        Mirrors what DSM's own Update & Restore UI sends (captured from
        admin_center.js on DSM 7.3.2): start the download via
        SYNO.Core.Upgrade.Server.Download (target "update"), poll its
        progress until "finished", then fire SYNO.Core.Upgrade start with
        force=true and type "server". The install reboots the NAS. These
        write methods reject GET (error 101), so they go out as POST.

        Reconnects first: the coordinator only polls every 6 hours, so the
        shared SID is often stale by the time the user clicks Install.
        """
        import time

        self.reconnect()
        self._sysinfo.request_data(
            "SYNO.Core.Upgrade.Server.Download",
            "entry.cgi",
            req_param={
                "method": "start",
                "version": 2,
                "target": "update",
                "need_auto_smallupdate": True,
            },
            method="post",
        )

        for _ in range(240):
            progress = self._sysinfo.request_data(
                "SYNO.Core.Upgrade.Server.Download",
                "entry.cgi",
                req_param={"method": "progress", "version": 2, "need_download_target": True},
            )
            status = progress.get("data", {}).get("status", "")
            if status == "finished":
                break
            if status in ("failed", "stopped"):
                raise RuntimeError(f"DSM update download {status}")
            time.sleep(5)
        else:
            raise RuntimeError("DSM update download did not finish within timeout")

        try:
            self._sysinfo.request_data(
                "SYNO.Core.Upgrade",
                "entry.cgi",
                req_param={"method": "start", "version": 1, "force": True, "type": "server"},
                method="post",
            )
        except Exception as err:
            # Once DSM accepts the start it tears down its web stack, so a
            # dropped connection or 498/499 here means the upgrade is running
            # (verified live: 7.3.2 -> 7.4.1 applied while this call "failed").
            # A bare connection drop could also be a network blip that ate the
            # POST, so confirm the NAS actually went dark before calling it done.
            confirmed = _nas_not_ready_code(err) is not None or (
                _connection_dropped(err) and self._nas_went_dark()
            )
            if confirmed:
                _LOGGER.info(
                    "DSM upgrade started; the NAS is applying the update and will reboot (%s)",
                    _err_detail(err),
                )
                return
            raise

    def _nas_went_dark(self) -> bool:
        """Distinguish upgrade teardown from a network blip after a dropped POST.

        Give DSM a moment to enter its pre-upgrade state, then probe with a
        fresh login: an unreachable or not-ready NAS confirms the upgrade is
        running, while a healthy NAS that still reports the update as pending
        means the start request never landed.
        """
        import time

        time.sleep(30)
        try:
            self.reconnect()
            dsm = self.get_dsm_update()
        except Exception:
            return True
        return not dsm.update_available

    def _raw_entry_post(
        self,
        api: str,
        version: int | str,
        method: str,
        payload: dict[str, Any],
        timeout: tuple[int, int] = (10, 60),
    ) -> dict:
        """POST to entry.cgi with X-SYNO-TOKEN, JSON-encoding every payload value.

        The library's transport can't make some of these requests, all
        verified live: its GET trips method ``install``'s stricter validation
        (error 120), its POST never attaches X-SYNO-TOKEN (error 119 even on
        a fresh SID), and Python bools serialize to "True"/"False", which DSM
        rejects with 120 reason "type" - DSM's own UI JSON-stringifies every
        non-string param. Returns the parsed response without raising on
        success=false: some callers need the error payload the library drops.
        """
        import requests as req_lib

        session = self._package.session
        form: dict[str, Any] = {
            "api": api,
            "version": str(version),
            "method": method,
            "_sid": session._sid,
        }
        for key, value in payload.items():
            form[key] = json.dumps(value)
        scheme = "https" if self._secure else "http"
        resp = req_lib.post(
            f"{scheme}://{self._host}:{self._port}/webapi/entry.cgi",
            data=form,
            verify=self._verify_ssl,
            headers={"X-SYNO-TOKEN": session._syno_token},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _installation_request(self, package_id: str, step: str, params: dict) -> dict:
        """Send a ``SYNO.Core.Package.Installation`` write, surfacing DSM errors.

        Raw responses keep the error payload the library drops -
        ``errors.name``/``reason`` say which param DSM disliked, and
        reserved-range codes keep their number.
        """
        payload = dict(params)
        method = payload.pop("method", "")
        version = payload.pop("version", 1)
        try:
            # Generous read timeout: DSM applies quick install/upgrade
            # requests synchronously enough that responses can take a while.
            result = self._raw_entry_post(
                "SYNO.Core.Package.Installation",
                version,
                method,
                payload,
                timeout=(10, 600),
            )
        except Exception as err:
            detail = _err_detail(err)
            _LOGGER.warning("Package %s %s failed: %s", package_id, step, detail)
            raise RuntimeError(f"Package {package_id} {step} failed: {detail}") from err
        if not result.get("success"):
            error = result.get("error", {})
            code = error.get("code")
            detail_body = error.get("errors") or _DSM_ERROR_HINTS.get(code, "no detail")
            detail = f"DSM error {code}: {detail_body}"
            _LOGGER.warning("Package %s %s failed: %s", package_id, step, detail)
            raise RuntimeError(f"Package {package_id} {step} failed: {detail}")
        return result

    def _installable_map(self) -> dict[str, dict]:
        """Fetch the installable feed once, keyed by package id."""
        response = self._package.list_installable()
        packages = response.get("data", {}).get("packages", [])
        return {p.get("id"): p for p in packages if isinstance(p, dict)}

    def _installation_check(self, pkg_info: dict) -> dict:
        """Mirror Package Center's pre-upgrade check, keeping the error payload.

        ``SYNO.Core.Package.Installation`` ``check`` v2 answers error 4526
        whose ``errors.uninstall_packages`` lists the dependency packages the
        wizard would install first (verified live: Contacts 1.0.11 requires
        Node.js_v22), so success=false is an expected answer here.
        """
        payload: dict[str, Any] = {
            "id": pkg_info.get("id", ""),
            "ver": pkg_info.get("version", ""),
            "blupgrade": True,
        }
        for key in ("deppkgs", "depsers", "conflictpkgs", "breakpkgs", "replacepkgs"):
            value = pkg_info.get(key)
            if value is not None:
                payload[key] = value
        return self._raw_entry_post("SYNO.Core.Package.Installation", 2, "check", payload)

    def _missing_dependencies(self, pkg_info: dict) -> list[str]:
        """Dependency packages that must be installed before this upgrade.

        Best-effort: if the check itself fails, proceed and let the upgrade
        surface its own error. DSM sends ``uninstall_packages`` as a dict of
        missing package ids, or "" when nothing is missing - tolerate any
        shape, since empty collections arrive as "" in this payload.
        """
        try:
            result = self._installation_check(pkg_info)
        except Exception as err:
            _LOGGER.warning(
                "Pre-upgrade dependency check for %s failed, proceeding without it: %s",
                pkg_info.get("id"),
                _err_detail(err),
            )
            return []
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        errors_payload = error.get("errors")
        missing = (
            errors_payload.get("uninstall_packages") if isinstance(errors_payload, dict) else None
        )
        if isinstance(missing, (dict, list)) and missing:
            return list(missing)
        if not result.get("success") and error.get("code") != 4526:
            # 4526 is the expected "wizard info" answer; anything else means
            # the check itself misfired - don't let best-effort hide it.
            _LOGGER.warning(
                "Pre-upgrade dependency check for %s returned DSM error %s, proceeding without it",
                pkg_info.get("id"),
                error.get("code"),
            )
        return []

    def _run_package_operation(self, package_id: str, pkg_info: dict, method: str) -> None:
        """Download an SPK then apply it via Package Center's quick request.

        ``method`` is ``upgrade`` for installed packages and ``install`` for
        new ones (dependencies) - the same split Package Center makes.
        """
        import time

        target_ver = pkg_info.get("version", "")
        is_syno = pkg_info.get("source") == "syno"
        beta = bool(pkg_info.get("beta", False))

        # Step 1: download the SPK to the NAS; this returns a task id.
        download = self._installation_request(
            package_id,
            "download",
            {
                "method": method,
                "version": 1,
                "operation": method,
                "name": package_id,
                "url": pkg_info.get("link", ""),
                "checksum": pkg_info.get("md5", ""),
                "filesize": pkg_info.get("size", 0),
                "type": pkg_info.get("type", 0),
                "blqinst": False,
                "is_syno": is_syno,
                "beta": beta,
            },
        )
        task_id = download.get("data", {}).get("taskid", "")
        if not task_id:
            raise RuntimeError(
                f"Package {package_id} download did not return a task id: {download}"
            )

        # Step 2: wait for the download to finish.
        for _ in range(120):
            status = self._package.get_dowload_package_status(task_id)
            if status.get("data", {}).get("finished"):
                break
            time.sleep(2)
        else:
            raise RuntimeError(f"Package {package_id} download did not finish within timeout")

        # Step 3: resolve the target volume.
        volume_path = (
            self._package.check_installation(package_id).get("data", {}).get("volume_path", "")
        )

        # Step 4: apply the downloaded package via the quick install/upgrade request.
        self._installation_request(
            package_id,
            "install",
            {
                "method": method,
                "version": 1,
                "name": package_id,
                "blqinst": True,
                "volume_path": volume_path,
                "is_syno": is_syno,
                "beta": beta,
                "installrunpackage": True,
            },
        )

        # Step 5: confirm the installed version reaches the target.
        for _ in range(120):
            installed = self._sysinfo.installed_package_list()
            for pkg in installed.get("data", {}).get("packages", []):
                if pkg.get("id") == package_id and pkg.get("version") == target_ver:
                    return
            time.sleep(2)

        if method == "install":
            # A dependency that never confirms would be blindly re-downloaded
            # and re-installed by the caller's retry loop; fail it instead.
            raise RuntimeError(f"Package {package_id} install did not complete within timeout")
        _LOGGER.warning("Package %s %s did not complete within timeout", package_id, method)

    def upgrade_package(self, package_id: str) -> None:
        """Upgrade a package via the DSM download-then-upgrade flow.

        Both write requests use method ``upgrade``: DSM 7.3.2 rejects method
        ``install`` for an already-installed package with reserved error 120.
        The requests mirror what Package Center's ``_onRequestDownload`` and
        ``_onRequestQuickInstall`` send (captured from PkgManApp.js).

        Missing dependency packages are fresh-installed first, exactly like
        Package Center's wizard (verified live: Contacts 1.0.11 requires
        Node.js_v22; DSM answers the pre-upgrade check with error 4526 until
        it is installed).

        Reconnects first: the shared SID is often stale by the time the user
        clicks Install (the coordinator only polls every 6 hours).
        """
        self.reconnect()
        feed = self._installable_map()
        pkg_info = feed.get(package_id)
        if pkg_info is None:
            raise RuntimeError(f"Package {package_id} not found in installable list")
        _LOGGER.debug("Upgrading package %s to %s", package_id, pkg_info.get("version", ""))

        # The raise must come from a re-check, never right after an install -
        # installing on the final round and then failing would report an
        # upgrade that may have just become viable.
        for attempt in range(3):
            missing = self._missing_dependencies(pkg_info)
            if not missing:
                break
            if attempt == 2:
                raise RuntimeError(
                    f"Package {package_id} still has unmet dependencies after installing {missing}"
                )
            for dep_id in missing:
                dep_info = feed.get(dep_id)
                if dep_info is None:
                    raise RuntimeError(
                        f"Dependency {dep_id} of {package_id} not found in installable list"
                    )
                _LOGGER.info("Package %s requires %s; installing it first", package_id, dep_id)
                self._run_package_operation(dep_id, dep_info, "install")

        self._run_package_operation(package_id, pkg_info, "upgrade")

    def trigger_security_scan(self) -> None:
        """Trigger a Security Advisor scan.

        Uses ``SYNO.Core.SecurityScan.Operation`` ``start`` with
        ``items='"ALL"'`` (a JSON-encoded string) - exactly what the DSM
        Security Advisor "Scan" button sends (``doScan`` in
        ``synosecurityscan.js``). Both pieces matter:

        - The previously used ``SYNO.Core.SecurityScan.Status`` ``system_scan``
          does not exist on DSM 7 (returns error 103), so the scan never ran.
          (The status method the UI polls is ``system_get``.)
        - ``start`` without the ``items`` parameter returns error 1300.

        The shared SID is usually stale by the time the button is pressed
        (the coordinator only polls every 6 hours) and DSM then rejects the
        call with error 119, so retry once on a fresh session. Raises on
        final failure so callers can surface it; the post-upgrade caller
        treats it as best-effort instead.
        """

        def _start() -> None:
            self._sysinfo.request_data(
                "SYNO.Core.SecurityScan.Operation",
                "entry.cgi",
                req_param={"method": "start", "version": 1, "items": '"ALL"'},
            )

        try:
            _start()
        except Exception as first_err:
            _LOGGER.debug(
                "Security scan start failed (%s), reconnecting and retrying",
                _err_detail(first_err),
            )
            self.reconnect()
            try:
                _start()
            except Exception as err:
                detail = _err_detail(err)
                _LOGGER.warning("Security scan start failed after reconnect: %s", detail)
                raise RuntimeError(f"Security scan start failed: {detail}") from err

    def reconnect(self) -> None:
        """Re-authenticate and rebuild every API wrapper (best-effort).

        One shared session backs SysInfo, Package, and Docker, so a single
        reconnect refreshes all read and write paths. Best-effort: failures are
        logged and the caller retries the operation against the new session.
        """
        try:
            self.connect()
        except Exception:
            _LOGGER.warning("Reconnect failed", exc_info=True)

    def _wait_for_container_manager(self, attempts: int = 36) -> None:
        """Block until the Container Manager package reports running.

        After a reboot (e.g. a DSM update) the package sits in "starting" for
        minutes while its API answers with misleading error codes, so gate
        Docker writes on it. An empty status map means the fetch itself failed
        (the API may be flapping in that same window) - keep polling rather
        than proceeding blind. A populated map with no Container Manager (or
        legacy Docker) entry means it isn't installed; proceed and let the
        Docker call report its own error.
        """
        import time

        last_status: str | None = None
        for attempt in range(attempts):
            status_map = self._get_package_status()
            if status_map:
                entry = status_map.get("ContainerManager")
                if entry is None:
                    entry = status_map.get("Docker")
                if entry is None:
                    return
                last_status = entry.get("status")
                if last_status == "running":
                    return
                if last_status in ("stop", "stopped", "broken"):
                    raise RuntimeError(
                        f"Container Manager is {last_status}; start it in Package "
                        "Center before managing containers"
                    )
                _LOGGER.debug("Container Manager is %s, waiting", last_status)
            else:
                _LOGGER.debug("Container Manager status unavailable, retrying")
            if attempt < attempts - 1:
                time.sleep(5)
        raise RuntimeError(
            "Could not confirm Container Manager is ready (last status: "
            f"{last_status or 'unknown'}); try again in a few minutes"
        )

    def update_container(self, container_name: str, image: str) -> None:
        """Rebuild a container's compose project with the latest image on disk."""
        self.reconnect()
        self._wait_for_container_manager()
        repo = image.split(":")[0] if ":" in image else image
        tag = image.split(":")[-1] if ":" in image else "latest"

        if not repo.startswith(("ghcr.io/", "lscr.io/")):
            self._pull_image(repo, tag)
            self.reconnect()

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
        self.reconnect()
        self._wait_for_container_manager()
        for image in images:
            repo = image.split(":")[0] if ":" in image else image
            tag = image.split(":")[-1] if ":" in image else "latest"
            if not repo.startswith(("ghcr.io/", "lscr.io/")):
                self._pull_image(repo, tag)
                self.reconnect()
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
        except Exception as err:
            _LOGGER.warning(
                "pull_start failed for %s:%s (%s), rebuilding with the image already on disk",
                repo,
                tag,
                _err_detail(err),
            )
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
            except Exception as err:
                # WARNING here would fire every 2s for the whole poll window;
                # the loop-exhaustion warning below is the visible signal.
                _LOGGER.debug("pull_status poll failed for %s:%s: %s", repo, tag, _err_detail(err))
            time.sleep(2)

        _LOGGER.warning(
            "Image pull for %s:%s did not report finished within timeout, "
            "proceeding with rebuild anyway",
            repo,
            tag,
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
