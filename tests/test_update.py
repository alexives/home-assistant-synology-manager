"""Tests for Synology Manager update entities."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.update import UpdateEntityFeature

from custom_components.synology_manager.synology_client import (
    ContainerInfo,
    DsmUpdateInfo,
    PackageInfo,
    ProjectUpdateInfo,
)
from custom_components.synology_manager.update import (
    SynologyContainerUpdateEntity,
    SynologyDSMUpdateEntity,
    SynologyPackageUpdateEntity,
    SynologyProjectUpdateEntity,
    _container_release_notes,
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
                changelog="<h4>Bug fixes</h4>",
                is_running=True,
            ),
            PackageInfo(
                package_id="SynologyDrive",
                display_name="Synology Drive Server",
                installed_version="3.5.0",
                latest_version="3.5.0",
                update_available=False,
                changelog=None,
                is_running=True,
            ),
        ],
        "project_updates": [],
        "standalone_containers": [
            ContainerInfo(
                name="homeassistant",
                display_name="Homeassistant",
                image="ghcr.io/home-assistant/home-assistant:2024.1",
                installed_version="2024.1",
                latest_version="2024.1",
                update_available=False,
                status="running",
            ),
        ],
        "containers": [],
    }
    coordinator.client = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.entry_id = "test_entry_id"
    coordinator.server_name = "Test Nas"
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

    def test_build_only_bump_shows_update_available(self, mock_coordinator):
        """A build-suffix-only bump (1.5.2-1831 -> -1832) must register as an update.

        HA core's default version_is_newer (AwesomeVersion) treats these as equal
        and renders "Up-to-date", so the entity must override it with Synology's
        build-aware comparison.
        """
        mock_coordinator.data["packages"].append(
            PackageInfo(
                package_id="HybridShare",
                display_name="Hybrid Share",
                installed_version="1.5.2-1831",
                latest_version="1.5.2-1832",
                update_available=True,
                changelog=None,
                is_running=True,
            )
        )
        entity = SynologyPackageUpdateEntity(mock_coordinator, "HybridShare")

        assert entity.version_is_newer("1.5.2-1832", "1.5.2-1831") is True
        assert entity.state == "on"

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
    """Tests for the standalone container update entity."""

    def test_properties(self, mock_coordinator):
        """Test container entity properties."""
        entity = SynologyContainerUpdateEntity(mock_coordinator, "homeassistant")

        assert entity.installed_version == "2024.1"
        assert entity.title == "Homeassistant"
        assert UpdateEntityFeature.INSTALL in entity.supported_features

    @pytest.mark.asyncio
    async def test_install(self, mock_coordinator):
        """Test triggering container update."""
        entity = SynologyContainerUpdateEntity(mock_coordinator, "homeassistant")
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_install(version=None, backup=None)

        entity.hass.async_add_executor_job.assert_called_once_with(
            mock_coordinator.client.update_container,
            "homeassistant",
            "ghcr.io/home-assistant/home-assistant:2024.1",
        )

    def test_unique_id_uses_container_name(self, mock_coordinator):
        """Test that unique_id is based on container name."""
        entity = SynologyContainerUpdateEntity(mock_coordinator, "homeassistant")
        assert entity.unique_id == "test_entry_id_ctr_homeassistant"

    def test_missing_container_returns_none(self, mock_coordinator):
        """Test properties when container disappears from data."""
        entity = SynologyContainerUpdateEntity(mock_coordinator, "deleted-container")
        assert entity.installed_version is None
        assert entity.latest_version is None
        assert entity.title == "deleted-container"
        assert entity.name == "Test Nas deleted-container"

    @pytest.mark.asyncio
    async def test_install_noop_when_container_missing(self, mock_coordinator):
        """Test that install does nothing if container is gone."""
        entity = SynologyContainerUpdateEntity(mock_coordinator, "deleted-container")
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_install(version=None, backup=None)

        entity.hass.async_add_executor_job.assert_not_called()


class TestProjectUpdateEntity:
    """Tests for the compose project update entity."""

    @pytest.fixture
    def project_coordinator(self, mock_coordinator):
        """Coordinator with project_updates data."""
        mock_coordinator.data["project_updates"] = [
            ProjectUpdateInfo(
                project_name="rallly",
                display_name="Rallly",
                project_id="uuid-rallly-002",
                containers=[
                    ContainerInfo(
                        name="rallly-rallly-1",
                        display_name="Rallly - Rallly",
                        image="lukevella/rallly:3.12.1",
                        installed_version="3.12.1 (aaa111)",
                        latest_version="3.12.1 (bbb222)",
                        update_available=True,
                        status="running",
                        project_name="rallly",
                    ),
                    ContainerInfo(
                        name="rallly-rallly_db-1",
                        display_name="Rallly - Rallly Db",
                        image="postgres:14.2",
                        installed_version="14.2",
                        latest_version="14.2",
                        update_available=False,
                        status="running",
                        project_name="rallly",
                    ),
                ],
                update_available=True,
                images=["lukevella/rallly:3.12.1", "postgres:14.2"],
            ),
            ProjectUpdateInfo(
                project_name="mealie",
                display_name="Mealie",
                project_id="uuid-mealie-001",
                containers=[
                    ContainerInfo(
                        name="mealie-mealie-1",
                        display_name="Mealie",
                        image="ghcr.io/mealie-recipes/mealie:v2.6.0",
                        installed_version="v2.6.0",
                        latest_version="v2.6.0",
                        update_available=False,
                        status="running",
                        project_name="mealie",
                    ),
                ],
                update_available=False,
                images=["ghcr.io/mealie-recipes/mealie:v2.6.0"],
            ),
        ]
        return mock_coordinator

    def test_name_and_title(self, project_coordinator):
        entity = SynologyProjectUpdateEntity(project_coordinator, "rallly")
        assert entity.name == "Test Nas Rallly"
        assert entity.title == "Rallly"

    def test_unique_id_uses_project_name(self, project_coordinator):
        entity = SynologyProjectUpdateEntity(project_coordinator, "rallly")
        assert entity.unique_id == "test_entry_id_proj_update_rallly"

    def test_installed_version_combines_containers(self, project_coordinator):
        entity = SynologyProjectUpdateEntity(project_coordinator, "rallly")
        assert entity.installed_version == "3.12.1 (aaa111), 14.2"

    def test_latest_version_combines_containers(self, project_coordinator):
        entity = SynologyProjectUpdateEntity(project_coordinator, "rallly")
        assert entity.latest_version == "3.12.1 (bbb222), 14.2"

    def test_no_update_when_all_containers_current(self, project_coordinator):
        entity = SynologyProjectUpdateEntity(project_coordinator, "mealie")
        assert entity.installed_version == entity.latest_version

    def test_update_available_when_any_container_has_update(self, project_coordinator):
        """installed != latest signals update in HA."""
        entity = SynologyProjectUpdateEntity(project_coordinator, "rallly")
        assert entity.installed_version != entity.latest_version

    @pytest.mark.asyncio
    async def test_install_calls_update_project(self, project_coordinator):
        entity = SynologyProjectUpdateEntity(project_coordinator, "rallly")
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_install(version=None, backup=None)

        entity.hass.async_add_executor_job.assert_called_once_with(
            project_coordinator.client.update_project,
            "uuid-rallly-002",
            ["lukevella/rallly:3.12.1", "postgres:14.2"],
        )

    @pytest.mark.asyncio
    async def test_install_noop_when_no_project_id(self, project_coordinator):
        project_coordinator.data["project_updates"][0].project_id = None
        entity = SynologyProjectUpdateEntity(project_coordinator, "rallly")
        entity.hass = MagicMock()
        entity.hass.async_add_executor_job = AsyncMock()

        await entity.async_install(version=None, backup=None)

        entity.hass.async_add_executor_job.assert_not_called()

    def test_missing_project_returns_none(self, project_coordinator):
        entity = SynologyProjectUpdateEntity(project_coordinator, "nonexistent")
        assert entity.installed_version is None
        assert entity.latest_version is None

    @pytest.mark.asyncio
    async def test_release_notes_lists_all_containers(self, project_coordinator):
        entity = SynologyProjectUpdateEntity(project_coordinator, "rallly")
        notes = await entity.async_release_notes()
        assert "Rallly - Rallly" in notes
        assert "Rallly - Rallly Db" in notes
        assert "lukevella/rallly" in notes
        assert "postgres" in notes


class TestGroupContainerUpdates:
    """Tests for the static grouping method."""

    def test_groups_by_project_name(self):
        from custom_components.synology_manager.synology_client import (
            ProjectInfo,
            SynologyClient,
        )

        containers = [
            ContainerInfo(
                name="rallly-rallly-1",
                display_name="Rallly - Rallly",
                image="lukevella/rallly:3.12.1",
                installed_version="3.12.1",
                latest_version="3.12.1",
                update_available=False,
                status="running",
                project_name="rallly",
            ),
            ContainerInfo(
                name="rallly-rallly_db-1",
                display_name="Rallly - Rallly Db",
                image="postgres:14.2",
                installed_version="14.2",
                latest_version="14.2",
                update_available=False,
                status="running",
                project_name="rallly",
            ),
            ContainerInfo(
                name="standalone-nginx",
                display_name="Standalone Nginx",
                image="nginx:1.25",
                installed_version="1.25",
                latest_version="1.25",
                update_available=False,
                status="running",
                project_name="",
            ),
        ]
        projects = [
            ProjectInfo(
                project_id="uuid-rallly", name="rallly", display_name="Rallly", status="RUNNING"
            ),
        ]

        project_updates, standalone = SynologyClient.group_container_updates(containers, projects)

        assert len(project_updates) == 1
        assert project_updates[0].project_name == "rallly"
        assert project_updates[0].project_id == "uuid-rallly"
        assert len(project_updates[0].containers) == 2

        assert len(standalone) == 1
        assert standalone[0].name == "standalone-nginx"

    def test_update_available_when_any_container_updated(self):
        from custom_components.synology_manager.synology_client import (
            ProjectInfo,
            SynologyClient,
        )

        containers = [
            ContainerInfo(
                name="app-1",
                display_name="App",
                image="app:1.0",
                installed_version="1.0 (old)",
                latest_version="1.0 (new)",
                update_available=True,
                status="running",
                project_name="myapp",
            ),
            ContainerInfo(
                name="db-1",
                display_name="Db",
                image="postgres:14",
                installed_version="14",
                latest_version="14",
                update_available=False,
                status="running",
                project_name="myapp",
            ),
        ]
        projects = [
            ProjectInfo(project_id="uuid-1", name="myapp", display_name="Myapp", status="RUNNING"),
        ]

        project_updates, _ = SynologyClient.group_container_updates(containers, projects)

        assert project_updates[0].update_available is True

    def test_no_update_when_all_current(self):
        from custom_components.synology_manager.synology_client import (
            ProjectInfo,
            SynologyClient,
        )

        containers = [
            ContainerInfo(
                name="app-1",
                display_name="App",
                image="app:1.0",
                installed_version="1.0",
                latest_version="1.0",
                update_available=False,
                status="running",
                project_name="myapp",
            ),
        ]
        projects = [
            ProjectInfo(project_id="uuid-1", name="myapp", display_name="Myapp", status="RUNNING"),
        ]

        project_updates, _ = SynologyClient.group_container_updates(containers, projects)

        assert project_updates[0].update_available is False

    def test_project_without_matching_project_info(self):
        """Containers with a project label but no matching project entry."""
        from custom_components.synology_manager.synology_client import SynologyClient

        containers = [
            ContainerInfo(
                name="orphan-1",
                display_name="Orphan",
                image="app:1.0",
                installed_version="1.0",
                latest_version="1.0",
                update_available=False,
                status="running",
                project_name="orphan",
            ),
        ]

        project_updates, standalone = SynologyClient.group_container_updates(containers, [])

        assert len(project_updates) == 1
        assert project_updates[0].project_id is None
        assert len(standalone) == 0


class TestContainerReleaseNotes:
    """Tests for container release notes URL generation."""

    def test_ghcr_image(self):
        result = _container_release_notes("ghcr.io/mealie-recipes/mealie:v2.6.0")
        assert "github.com/mealie-recipes/mealie/releases" in result
        assert "GitHub" in result

    def test_lscr_image(self):
        result = _container_release_notes("lscr.io/linuxserver/plex:latest")
        assert "hub.docker.com/r/linuxserver/plex" in result
        assert "Docker Hub" in result

    def test_dockerhub_namespaced_image(self):
        result = _container_release_notes("lukevella/rallly:3.12.1")
        assert "hub.docker.com/r/lukevella/rallly" in result

    def test_dockerhub_official_image(self):
        result = _container_release_notes("postgres:14.2")
        assert "hub.docker.com/_/postgres" in result

    def test_image_without_tag(self):
        result = _container_release_notes("nginx")
        assert "hub.docker.com/_/nginx" in result
