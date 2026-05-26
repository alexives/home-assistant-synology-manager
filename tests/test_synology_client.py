"""Tests for the Synology API client wrapper."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.synology_upgrades.synology_client import (
    SynologyAuthenticationError,
    SynologyClient,
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
    @patch("custom_components.synology_upgrades.synology_client.Package")
    @patch("custom_components.synology_upgrades.synology_client.DockerApi")
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
            host="nas.local",
            port=5001,
            username="admin",
            password="secret",
            secure=True,
            verify_ssl=False,
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
        assert ha.installed_version == "2024.1"
        assert ha.image == "ghcr.io/home-assistant/home-assistant:2024.1"

    @patch("custom_components.synology_upgrades.synology_client.SysInfo")
    @patch("custom_components.synology_upgrades.synology_client.Package")
    @patch("custom_components.synology_upgrades.synology_client.DockerApi")
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
