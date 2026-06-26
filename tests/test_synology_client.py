"""Tests for the Synology API client wrapper."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.synology_manager.synology_client import (
    SynologyAuthenticationError,
    SynologyClient,
)


class TestClientConstruction:
    """Tests for client creation and authentication."""

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
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

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_connect_with_otp(self, mock_docker, mock_package, mock_sysinfo):
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

    @patch("custom_components.synology_manager.synology_client.SysInfo")
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


class TestDsmUpdate:
    """Tests for DSM update checking."""

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
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
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        result = client.get_dsm_update()

        assert result.installed_version == "7.2.1-69057"
        assert result.latest_version == "7.2.2-72806"
        assert result.update_available is True
        assert result.release_notes == "Bug fixes and improvements"

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
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
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        result = client.get_dsm_update()

        assert result.installed_version == "7.2.2-72806"
        assert result.latest_version is None
        assert result.update_available is False


class TestPackages:
    """Tests for package listing."""

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
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
                    {
                        "id": "HyperBackup",
                        "version": "4.1.1-3740",
                        "changelog": "<h4>Bug fixes</h4>",
                    },
                    {"id": "SynologyDrive", "version": "3.5.0"},
                ]
            },
            "success": True,
        }
        mock_package.return_value = mock_pkg

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client._get_package_status = MagicMock(return_value={})
        packages = client.get_packages()

        assert len(packages) == 2
        hyper = next(p for p in packages if p.package_id == "HyperBackup")
        assert hyper.update_available is True
        assert hyper.latest_version == "4.1.1-3740"
        assert hyper.changelog == "<h4>Bug fixes</h4>"

        drive = next(p for p in packages if p.package_id == "SynologyDrive")
        assert drive.update_available is False
        assert drive.latest_version == "3.5.0"
        assert drive.changelog is None

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_get_packages_is_running(self, mock_docker, mock_package, mock_sysinfo):
        """Test that is_running is derived from compound API status for startable packages."""
        mock_sys = MagicMock()
        mock_sys.installed_package_list.return_value = {
            "data": {
                "packages": [
                    {"id": "ContainerManager", "name": "Container Manager", "version": "3.1.0"},
                    {"id": "LogCenter", "name": "Log Center", "version": "1.4.0"},
                    {"id": "CodecPack", "name": "Codec Pack", "version": "2.0.0"},
                ]
            },
            "success": True,
        }
        mock_sysinfo.return_value = mock_sys

        mock_pkg = MagicMock()
        mock_pkg.list_installable.return_value = {"data": {"packages": []}, "success": True}
        mock_package.return_value = mock_pkg

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client._get_package_status = MagicMock(
            return_value={
                "ContainerManager": {"status": "running", "startable": True},
                "LogCenter": {"status": "stopped", "startable": True},
                "CodecPack": {"status": "running", "startable": False},
            }
        )
        packages = client.get_packages()

        cm = next(p for p in packages if p.package_id == "ContainerManager")
        assert cm.is_running is True

        log = next(p for p in packages if p.package_id == "LogCenter")
        assert log.is_running is False

        codec = next(p for p in packages if p.package_id == "CodecPack")
        assert codec.is_running is None

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_start_stop_package(self, mock_docker, mock_package, mock_sysinfo):
        """Test start_package and stop_package call the correct API."""
        mock_pkg = MagicMock()
        mock_pkg.core_list = {
            "SYNO.Core.Package.Control": {"path": "entry.cgi", "minVersion": 1},
        }
        mock_package.return_value = mock_pkg

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()

        client.start_package("ContainerManager")
        start_call = mock_pkg.request_data.call_args_list[-1]
        assert start_call.kwargs["req_param"]["method"] == "start"
        assert start_call.kwargs["req_param"]["id"] == "ContainerManager"

        client.stop_package("LogCenter")
        stop_call = mock_pkg.request_data.call_args_list[-1]
        assert stop_call.kwargs["req_param"]["method"] == "stop"
        assert stop_call.kwargs["req_param"]["id"] == "LogCenter"


class TestContainers:
    """Tests for container listing."""

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_get_containers(self, mock_docker, mock_package, mock_sysinfo):
        """Test listing containers with update detection from downloaded_images."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "homeassistant",
                        "image": "ghcr.io/home-assistant/home-assistant:2024.1",
                        "status": "running",
                        "ImageID": "sha256:aaa111aaa111",
                        "Labels": {
                            "com.docker.compose.project": "ha",
                            "com.docker.compose.service": "homeassistant",
                        },
                    },
                    {
                        "name": "mosquitto",
                        "image": "eclipse-mosquitto:2.0",
                        "status": "running",
                        "ImageID": "sha256:bbb222bbb222",
                        "Labels": {
                            "com.docker.compose.project": "mqtt",
                            "com.docker.compose.service": "mosquitto",
                        },
                    },
                ]
            },
            "success": True,
        }
        mock_docker_inst.downloaded_images.return_value = {
            "data": {
                "images": [
                    {
                        "repository": "ghcr.io/home-assistant/home-assistant",
                        "tags": ["2024.1"],
                        "upgradable": False,
                        "id": "sha256:ccc333ccc333",
                    },
                    {
                        "repository": "eclipse-mosquitto",
                        "tags": ["2.0"],
                        "upgradable": False,
                        "id": "sha256:bbb222bbb222",
                    },
                ]
            },
            "success": True,
        }
        mock_docker.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        containers = client.get_containers()

        assert len(containers) == 2
        ha = next(c for c in containers if c.name == "homeassistant")
        assert ha.display_name == "Ha"
        assert ha.image == "ghcr.io/home-assistant/home-assistant:2024.1"
        assert ha.update_available is True
        assert ha.installed_version == "2024.1 (aaa111aaa111)"
        assert ha.latest_version == "2024.1 (ccc333ccc333)"

        mosquitto = next(c for c in containers if c.name == "mosquitto")
        assert mosquitto.display_name == "Mqtt"
        assert mosquitto.update_available is False
        assert mosquitto.installed_version == "2.0"
        assert mosquitto.latest_version == "2.0"

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_get_containers_no_docker(self, mock_docker, mock_package, mock_sysinfo):
        """Test that containers returns empty when Docker is not installed."""
        mock_docker.side_effect = Exception("Docker not installed")

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        containers = client.get_containers()

        assert containers == []

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_multi_container_compose_project(self, mock_docker, mock_package, mock_sysinfo):
        """Test that multi-container projects get per-service display names."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "rallly-rallly-1",
                        "image": "lukevella/rallly:3.12.1",
                        "status": "running",
                        "ImageID": "sha256:aaa111",
                        "Labels": {
                            "com.docker.compose.project": "rallly",
                            "com.docker.compose.service": "rallly",
                        },
                    },
                    {
                        "name": "rallly-rallly_db-1",
                        "image": "postgres:14.2",
                        "status": "running",
                        "ImageID": "sha256:bbb222",
                        "Labels": {
                            "com.docker.compose.project": "rallly",
                            "com.docker.compose.service": "rallly_db",
                        },
                    },
                ]
            },
            "success": True,
        }
        mock_docker_inst.downloaded_images.return_value = {
            "data": {
                "images": [
                    {
                        "repository": "lukevella/rallly",
                        "tags": ["3.12.1"],
                        "upgradable": False,
                        "id": "sha256:aaa111",
                    },
                    {
                        "repository": "postgres",
                        "tags": ["14.2"],
                        "upgradable": False,
                        "id": "sha256:bbb222",
                    },
                ]
            },
            "success": True,
        }
        mock_docker.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        containers = client.get_containers()

        assert len(containers) == 2
        rallly_app = next(c for c in containers if c.name == "rallly-rallly-1")
        rallly_db = next(c for c in containers if c.name == "rallly-rallly_db-1")
        assert rallly_app.display_name == "Rallly - Rallly"
        assert rallly_db.display_name == "Rallly - Rallly Db"

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_single_container_project_uses_project_name(
        self, mock_docker, mock_package, mock_sysinfo
    ):
        """Test that single-container projects use the project name as display name."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "mealie-mealie-1",
                        "image": "ghcr.io/mealie-recipes/mealie:v2.6.0",
                        "status": "running",
                        "ImageID": "sha256:abc123",
                        "Labels": {
                            "com.docker.compose.project": "mealie",
                            "com.docker.compose.service": "mealie",
                        },
                    },
                ]
            },
            "success": True,
        }
        mock_docker_inst.downloaded_images.return_value = {
            "data": {
                "images": [
                    {
                        "repository": "ghcr.io/mealie-recipes/mealie",
                        "tags": ["v2.6.0"],
                        "upgradable": False,
                        "id": "sha256:abc123",
                    },
                ]
            },
            "success": True,
        }
        mock_docker.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        containers = client.get_containers()

        assert len(containers) == 1
        assert containers[0].display_name == "Mealie"

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_skips_stopped_and_sha256_containers(self, mock_docker, mock_package, mock_sysinfo):
        """Test that stopped containers and sha256 images are excluded."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "running-app",
                        "image": "nginx:latest",
                        "status": "running",
                        "ImageID": "sha256:aaa",
                        "Labels": {},
                    },
                    {
                        "name": "stopped-app",
                        "image": "nginx:latest",
                        "status": "stopped",
                        "ImageID": "sha256:bbb",
                        "Labels": {},
                    },
                    {
                        "name": "sha256-app",
                        "image": "sha256:deadbeef",
                        "status": "running",
                        "ImageID": "sha256:ccc",
                        "Labels": {},
                    },
                ]
            },
            "success": True,
        }
        mock_docker_inst.downloaded_images.return_value = {
            "data": {"images": []},
            "success": True,
        }
        mock_docker.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        containers = client.get_containers()

        assert len(containers) == 1
        assert containers[0].name == "running-app"

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_update_detected_via_upgradable_flag(self, mock_docker, mock_package, mock_sysinfo):
        """Test that the upgradable flag from downloaded_images triggers update."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "app",
                        "image": "nginx:1.25",
                        "status": "running",
                        "ImageID": "sha256:same",
                        "Labels": {},
                    },
                ]
            },
            "success": True,
        }
        mock_docker_inst.downloaded_images.return_value = {
            "data": {
                "images": [
                    {
                        "repository": "nginx",
                        "tags": ["1.25"],
                        "upgradable": True,
                        "id": "sha256:same",
                    },
                ]
            },
            "success": True,
        }
        mock_docker.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        containers = client.get_containers()

        assert containers[0].update_available is True

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_update_detected_via_image_id_mismatch(self, mock_docker, mock_package, mock_sysinfo):
        """Test that ImageID mismatch between container and downloaded image triggers update."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "app",
                        "image": "nginx:1.25",
                        "status": "running",
                        "ImageID": "sha256:old_image_id",
                        "Labels": {},
                    },
                ]
            },
            "success": True,
        }
        mock_docker_inst.downloaded_images.return_value = {
            "data": {
                "images": [
                    {
                        "repository": "nginx",
                        "tags": ["1.25"],
                        "upgradable": False,
                        "id": "sha256:new_image_id",
                    },
                ]
            },
            "success": True,
        }
        mock_docker.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        containers = client.get_containers()

        assert containers[0].update_available is True
        assert "old_image_id" in containers[0].installed_version
        assert "new_image_id" in containers[0].latest_version

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_downloaded_images_failure_does_not_crash(
        self, mock_docker, mock_package, mock_sysinfo
    ):
        """Test that failure to fetch downloaded_images still returns containers."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "app",
                        "image": "nginx:1.25",
                        "status": "running",
                        "ImageID": "sha256:aaa",
                        "Labels": {},
                    },
                ]
            },
            "success": True,
        }
        mock_docker_inst.downloaded_images.side_effect = Exception("API error")
        mock_docker.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        containers = client.get_containers()

        assert len(containers) == 1
        assert containers[0].update_available is False


class TestProjects:
    """Tests for compose project listing."""

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_get_projects(self, mock_docker, mock_package, mock_sysinfo):
        """Test parsing SYNO.Docker.Project list response."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.list_projects.return_value = {
            "data": {
                "uuid-mealie-001": {
                    "name": "mealie",
                    "status": "RUNNING",
                    "share_path": "/docker/mealie",
                    "is_package": False,
                    "enable_service_portal": False,
                    "containerIds": ["8f04919d76d1"],
                },
                "uuid-rallly-002": {
                    "name": "rallly",
                    "status": "RUNNING",
                    "share_path": "/docker/portainer-ce/compose/38",
                    "is_package": False,
                    "enable_service_portal": False,
                },
            },
            "success": True,
        }
        mock_docker.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        projects = client.get_projects()

        assert len(projects) == 2
        mealie = next(p for p in projects if p.name == "mealie")
        assert mealie.project_id == "uuid-mealie-001"
        assert mealie.display_name == "Mealie"
        assert mealie.status == "RUNNING"

        rallly = next(p for p in projects if p.name == "rallly")
        assert rallly.project_id == "uuid-rallly-002"
        assert rallly.status == "RUNNING"

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_get_projects_no_docker(self, mock_docker, mock_package, mock_sysinfo):
        """Test that projects returns empty when Docker is not installed."""
        mock_docker.side_effect = Exception("Docker not installed")

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        assert client.get_projects() == []

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_get_projects_api_failure(self, mock_docker, mock_package, mock_sysinfo):
        """Test that list_projects failure returns empty list."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.list_projects.side_effect = Exception("API error 1202")
        mock_docker.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        assert client.get_projects() == []


class TestDockerWriteOperations:
    """Tests for Docker write operations (start/stop/update)."""

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_docker_write_retries_on_stale_session(
        self, mock_docker_cls, mock_package, mock_sysinfo
    ):
        """Test that _docker_write reconnects and retries on failure."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.stop_project.side_effect = Exception("stale session")
        mock_docker_cls.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()

        fresh_docker = MagicMock()
        fresh_docker.stop_project.return_value = {"success": True}

        def fake_reconnect():
            client._docker = fresh_docker

        client.reconnect = fake_reconnect
        result = client._docker_write("stop_project", "uuid-123")

        assert result == {"success": True}

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_stop_project_uses_compound_api(self, mock_docker_cls, mock_package, mock_sysinfo):
        """Test that stop_project uses the compound API."""
        mock_docker_cls.return_value = MagicMock()
        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client._compound_project_request = MagicMock()

        client.stop_project("uuid-mealie")

        client._compound_project_request.assert_called_once_with("stop", {"id": "uuid-mealie"})

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_stop_project_falls_back_to_containers(
        self, mock_docker_cls, mock_package, mock_sysinfo
    ):
        """Test that stop_project falls back to stopping individual containers."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "mealie-mealie-1",
                        "image": "ghcr.io/mealie-recipes/mealie:v2.6.0",
                        "status": "running",
                        "Labels": {
                            "com.docker.compose.project": "mealie",
                        },
                    },
                ]
            },
        }
        mock_docker_inst.list_projects.return_value = {
            "data": {
                "uuid-mealie": {"name": "mealie", "status": "RUNNING"},
            },
        }
        mock_docker_cls.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client._compound_project_request = MagicMock(side_effect=RuntimeError("compound failed"))

        client.stop_project("uuid-mealie")

        mock_docker_inst.stop_container.assert_called_once_with("mealie-mealie-1")

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_start_project_uses_compound_api(self, mock_docker_cls, mock_package, mock_sysinfo):
        """Test that start_project uses the compound API."""
        mock_docker_cls.return_value = MagicMock()
        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client._compound_project_request = MagicMock()

        client.start_project("uuid-rallly")

        client._compound_project_request.assert_called_once_with("start", {"id": "uuid-rallly"})

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_start_project_falls_back_to_containers(
        self, mock_docker_cls, mock_package, mock_sysinfo
    ):
        """Test that start_project falls back to starting individual containers."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "rallly-rallly-1",
                        "status": "stopped",
                        "Labels": {"com.docker.compose.project": "rallly"},
                    },
                    {
                        "name": "rallly-rallly_db-1",
                        "status": "stopped",
                        "Labels": {"com.docker.compose.project": "rallly"},
                    },
                ]
            },
        }
        mock_docker_inst.list_projects.return_value = {
            "data": {"uuid-rallly": {"name": "rallly", "status": "STOPPED"}},
        }
        mock_docker_cls.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client._compound_project_request = MagicMock(side_effect=RuntimeError("compound failed"))

        client.start_project("uuid-rallly")

        assert mock_docker_inst.start_container.call_count == 2
        mock_docker_inst.start_container.assert_any_call("rallly-rallly-1")
        mock_docker_inst.start_container.assert_any_call("rallly-rallly_db-1")

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_get_project_containers(self, mock_docker_cls, mock_package, mock_sysinfo):
        """Test filtering containers by compose project label."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "rallly-rallly-1",
                        "Labels": {"com.docker.compose.project": "rallly"},
                    },
                    {
                        "name": "rallly-rallly_db-1",
                        "Labels": {"com.docker.compose.project": "rallly"},
                    },
                    {
                        "name": "mealie-mealie-1",
                        "Labels": {"com.docker.compose.project": "mealie"},
                    },
                    {
                        "name": "standalone",
                        "Labels": {},
                    },
                ]
            },
        }
        mock_docker_cls.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()

        result = client._get_project_containers("rallly")
        assert result == ["rallly-rallly-1", "rallly-rallly_db-1"]

        result = client._get_project_containers("mealie")
        assert result == ["mealie-mealie-1"]

        result = client._get_project_containers("nonexistent")
        assert result == []

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_find_project_for_container(self, mock_docker_cls, mock_package, mock_sysinfo):
        """Test looking up compose project UUID from container name."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "rallly-rallly-1",
                        "Labels": {"com.docker.compose.project": "rallly"},
                    },
                    {
                        "name": "standalone-app",
                        "Labels": {},
                    },
                ]
            },
        }
        mock_docker_inst.list_projects.return_value = {
            "data": {
                "uuid-rallly-002": {"name": "rallly", "status": "RUNNING"},
            },
        }
        mock_docker_cls.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()

        assert client._find_project_for_container("rallly-rallly-1") == "uuid-rallly-002"
        assert client._find_project_for_container("standalone-app") is None
        assert client._find_project_for_container("nonexistent") is None

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_update_container_calls_build_project(
        self, mock_docker_cls, mock_package, mock_sysinfo
    ):
        """Test that updating a compose container calls build_project."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "mealie-mealie-1",
                        "Labels": {"com.docker.compose.project": "mealie"},
                    },
                ]
            },
        }
        mock_docker_inst.list_projects.return_value = {
            "data": {"uuid-mealie": {"name": "mealie", "status": "RUNNING"}},
        }
        mock_docker_cls.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client.reconnect = lambda: None

        client._build_project = MagicMock()
        client.update_container("mealie-mealie-1", "ghcr.io/mealie-recipes/mealie:v2.6.0")

        client._build_project.assert_called_once_with("uuid-mealie")

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_update_standalone_container(self, mock_docker_cls, mock_package, mock_sysinfo):
        """Test updating a standalone container (stop, delete, create)."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "standalone-app",
                        "Labels": {},
                    },
                ]
            },
        }
        mock_docker_cls.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client.reconnect = lambda: None

        client.update_container("standalone-app", "ghcr.io/org/app:1.0")

        mock_docker_inst.stop_container.assert_called_once_with("standalone-app")
        container_calls = [
            c
            for c in mock_docker_inst.request_data.call_args_list
            if c.args[0] == "SYNO.Docker.Container"
        ]
        assert len(container_calls) == 2
        assert container_calls[0].kwargs["req_param"]["method"] == "delete"
        assert container_calls[1].kwargs["req_param"]["method"] == "create"
        assert container_calls[1].kwargs["req_param"]["image"] == "ghcr.io/org/app:1.0"

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_update_container_pulls_dockerhub_image(
        self, mock_docker_cls, mock_package, mock_sysinfo
    ):
        """Test that Docker Hub images get pulled before rebuild."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "rallly-rallly-1",
                        "Labels": {"com.docker.compose.project": "rallly"},
                    },
                ]
            },
        }
        mock_docker_inst.list_projects.return_value = {
            "data": {"uuid-rallly": {"name": "rallly", "status": "RUNNING"}},
        }
        mock_docker_inst.request_data.return_value = {
            "data": {"task_id": "pull-task-1", "finished": True},
        }
        mock_docker_cls.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client.reconnect = lambda: None
        client._build_project = MagicMock()

        client.update_container("rallly-rallly-1", "lukevella/rallly:3.12.1")

        pull_call = mock_docker_inst.request_data.call_args_list[0]
        assert pull_call.kwargs["req_param"]["method"] == "pull_start"
        assert pull_call.kwargs["req_param"]["repository"] == "lukevella/rallly"
        assert pull_call.kwargs["req_param"]["tag"] == "3.12.1"

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_update_container_skips_pull_for_ghcr(
        self, mock_docker_cls, mock_package, mock_sysinfo
    ):
        """Test that ghcr.io images skip the pull step."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "mealie-mealie-1",
                        "Labels": {"com.docker.compose.project": "mealie"},
                    },
                ]
            },
        }
        mock_docker_inst.list_projects.return_value = {
            "data": {"uuid-mealie": {"name": "mealie", "status": "RUNNING"}},
        }
        mock_docker_cls.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client.reconnect = lambda: None
        client._build_project = MagicMock()

        client.update_container("mealie-mealie-1", "ghcr.io/mealie-recipes/mealie:v2.6.0")

        for call in mock_docker_inst.request_data.call_args_list:
            assert call.kwargs.get("req_param", {}).get("method") != "pull_start"

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_update_container_skips_pull_for_lscr(
        self, mock_docker_cls, mock_package, mock_sysinfo
    ):
        """Test that lscr.io images skip the pull step."""
        mock_docker_inst = MagicMock()
        mock_docker_inst.containers.return_value = {
            "data": {
                "containers": [
                    {
                        "name": "app",
                        "Labels": {"com.docker.compose.project": "app"},
                    },
                ]
            },
        }
        mock_docker_inst.list_projects.return_value = {
            "data": {"uuid-app": {"name": "app", "status": "RUNNING"}},
        }
        mock_docker_cls.return_value = mock_docker_inst

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        client.reconnect = lambda: None
        client._build_project = MagicMock()

        client.update_container("app", "lscr.io/linuxserver/plex:latest")

        for call in mock_docker_inst.request_data.call_args_list:
            assert call.kwargs.get("req_param", {}).get("method") != "pull_start"


class TestDisplayNameHelpers:
    """Tests for the display name helper functions."""

    def test_prettify(self):
        from custom_components.synology_manager.synology_client import _prettify

        assert _prettify("my-container") == "My Container"
        assert _prettify("my_container") == "My Container"
        assert _prettify("rallly") == "Rallly"

    def test_container_display_name_no_project(self):
        from custom_components.synology_manager.synology_client import _container_display_name

        result = _container_display_name("standalone-app", "", "", {})
        assert result == "Standalone App"

    def test_container_display_name_single_container_project(self):
        from custom_components.synology_manager.synology_client import _container_display_name

        result = _container_display_name("mealie-mealie-1", "mealie", "mealie", {"mealie": 1})
        assert result == "Mealie"

    def test_container_display_name_multi_container_project(self):
        from custom_components.synology_manager.synology_client import _container_display_name

        result = _container_display_name("rallly-rallly-1", "rallly", "rallly", {"rallly": 2})
        assert result == "Rallly - Rallly"

        result = _container_display_name("rallly-rallly_db-1", "rallly", "rallly_db", {"rallly": 2})
        assert result == "Rallly - Rallly Db"

    def test_is_newer(self):
        from custom_components.synology_manager.synology_client import _is_newer

        assert _is_newer("4.1.1-3740", "4.1.0-3735") is True
        assert _is_newer("4.1.0-3735", "4.1.0-3735") is False
        assert _is_newer("4.0.0", "4.1.0") is False
        assert _is_newer("", "4.1.0") is False
        assert _is_newer("unknown-v2", "unknown-v1") is True
        # Same version, newer build number (Synology bumps the suffix after the dash)
        assert _is_newer("1.5.2-1832", "1.5.2-1831") is True
        assert _is_newer("1.5.2-1831", "1.5.2-1832") is False


class TestPackageUpgrade:
    """Tests for the package upgrade flow."""

    def _make_client(self, mock_package_cls, mock_sysinfo_cls, target="1.5.2-1832"):
        pkg = MagicMock()
        pkg.list_installable.return_value = {
            "data": {
                "packages": [
                    {
                        "id": "HybridShare",
                        "version": target,
                        "link": "https://example.com/hs.spk",
                        "md5": "deadbeef",
                        "size": 12345,
                    }
                ]
            }
        }
        pkg.download_package.return_value = {
            "data": {"taskid": "@SYNOPKG_DOWNLOAD_HybridShare", "progress": 0.0}
        }
        pkg.get_dowload_package_status.return_value = {"data": {"finished": True, "progress": 1.0}}
        pkg.check_installation_from_download.return_value = {
            "data": {"filename": "/volume1/@tmp/synopkg/download.xxx/@SYNOPKG_DOWNLOAD_HybridShare"}
        }
        pkg.check_installation.return_value = {"data": {"volume_path": ""}}
        pkg.install_package.return_value = {"data": {"has_fail": False}, "success": True}
        mock_package_cls.return_value = pkg

        sysinfo = MagicMock()
        sysinfo.installed_package_list.return_value = {
            "data": {"packages": [{"id": "HybridShare", "version": target}]}
        }
        mock_sysinfo_cls.return_value = sysinfo

        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
        )
        client.connect()
        return client, pkg, sysinfo

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_upgrade_downloads_then_installs_with_force(
        self, mock_docker, mock_package_cls, mock_sysinfo_cls
    ):
        """Upgrade must download the SPK, then install the downloaded file with force."""
        client, pkg, _ = self._make_client(mock_package_cls, mock_sysinfo_cls)

        client.upgrade_package("HybridShare")

        # Step 1: download using the installable link/checksum/size
        pkg.download_package.assert_called_once_with(
            "https://example.com/hs.spk", "HybridShare", "deadbeef", 12345
        )
        # Step 2: poll the download status with the returned task id
        pkg.get_dowload_package_status.assert_called_with("@SYNOPKG_DOWNLOAD_HybridShare")
        # Step 3: resolve the downloaded file via the task id
        pkg.check_installation_from_download.assert_called_with("@SYNOPKG_DOWNLOAD_HybridShare")
        # Step 4: install the downloaded file with force (the bare `upgrade` method
        # returns error 4501 for system packages)
        pkg.install_package.assert_called_once()
        args, kwargs = pkg.install_package.call_args
        assert args[0] == "HybridShare"
        assert args[2] == "/volume1/@tmp/synopkg/download.xxx/@SYNOPKG_DOWNLOAD_HybridShare"
        assert kwargs.get("force") is True

    @patch("custom_components.synology_manager.synology_client.SysInfo")
    @patch("custom_components.synology_manager.synology_client.Package")
    @patch("custom_components.synology_manager.synology_client.DockerApi")
    def test_upgrade_raises_when_no_download_task(
        self, mock_docker, mock_package_cls, mock_sysinfo_cls
    ):
        """If the download step returns no task id, fail loudly instead of silently."""
        client, pkg, _ = self._make_client(mock_package_cls, mock_sysinfo_cls)
        pkg.download_package.return_value = {"data": {}}

        with pytest.raises(RuntimeError):
            client.upgrade_package("HybridShare")
        pkg.install_package.assert_not_called()


class TestTriggerSecurityScan:
    """Tests for the Security Advisor scan trigger."""

    def _make_client(self):
        client = SynologyClient(
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
        )
        client._sysinfo = MagicMock()
        return client

    def test_trigger_uses_securityscan_operation_start(self):
        """The trigger must call SYNO.Core.SecurityScan.Operation 'start'.

        The old SYNO.Core.SecurityScan.Status 'system_scan' method does not
        exist on DSM 7 (error 103), so the scan never actually ran.
        """
        client = self._make_client()

        client.trigger_security_scan()

        client._sysinfo.request_data.assert_called_once()
        args, kwargs = client._sysinfo.request_data.call_args
        assert args[0] == "SYNO.Core.SecurityScan.Operation"
        req_param = kwargs.get("req_param", args[2] if len(args) > 2 else {})
        assert req_param["method"] == "start"

    def test_trigger_logs_failure_instead_of_silently_swallowing(self, caplog):
        """A failed scan trigger must be surfaced in the logs, not hidden."""
        import logging

        client = self._make_client()
        client._sysinfo.request_data.side_effect = RuntimeError("Core Error: 1300")

        with caplog.at_level(logging.WARNING):
            client.trigger_security_scan()  # must not raise

        assert any("1300" in r.message or "scan" in r.message.lower() for r in caplog.records)
