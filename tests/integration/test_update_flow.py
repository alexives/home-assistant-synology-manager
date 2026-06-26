#!/usr/bin/env python3
"""Integration test for Synology container update and switch flow.

Run with: uvx --with synology-api --with requests python3 tests/integration/test_update_flow.py

Requires .env at repo root with: SYN_HOST, SYN_USER, SYN_PW, HA_LOCAL_URL, HA_LOCAL_TOKEN
Requires 'testing' compose project running on NAS with alexives/synology-test:latest
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import requests
from synology_api.docker_api import Docker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INTEGRATION_DIR = Path(__file__).resolve().parent
IMAGE = "alexives/synology-test:latest"
PROJECT_NAME = "testing"
CONTAINER_NAME = "synology-test-app"
UPDATE_ENTITY = "update.rio_grande_testing"
SWITCH_ENTITY = "switch.rio_grande_testing"


def load_env() -> dict[str, str]:
    env = {}
    env_file = REPO_ROOT / ".env"
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip()
    return env


class HAClient:
    def __init__(self, url: str, token: str):
        self.base = f"http://{url}"
        self.headers = {"Authorization": f"Bearer {token}"}

    def get_state(self, entity_id: str) -> dict:
        r = requests.get(f"{self.base}/api/states/{entity_id}", headers=self.headers)
        r.raise_for_status()
        return r.json()

    def call_service(self, domain: str, service: str, entity_id: str) -> None:
        r = requests.post(
            f"{self.base}/api/services/{domain}/{service}",
            headers=self.headers,
            json={"entity_id": entity_id},
        )
        r.raise_for_status()

    def refresh_coordinator(self) -> None:
        self.call_service("homeassistant", "update_entity", UPDATE_ENTITY)


class NASClient:
    def __init__(self, host: str, port: str, user: str, pw: str):
        self.docker = Docker(
            ip_address=host,
            port=port,
            username=user,
            password=pw,
            secure=True,
            cert_verify=False,
            dsm_version=7,
            debug=False,
        )

    def _find_container(self) -> dict | None:
        for ctr in self.docker.containers().get("data", {}).get("containers", []):
            labels = ctr.get("Labels", {})
            if labels.get("com.docker.compose.project") == PROJECT_NAME:
                return ctr
        return None

    def get_container_image_id(self) -> str | None:
        ctr = self._find_container()
        return ctr.get("ImageID", "") if ctr else None

    def get_container_status(self) -> str | None:
        ctr = self._find_container()
        return ctr.get("status", "") if ctr else None

    def is_image_upgradable(self) -> bool:
        for img in self.docker.downloaded_images().get("data", {}).get("images", []):
            if "synology-test" in img.get("repository", ""):
                for tag in img.get("tags", []):
                    if tag == "latest":
                        return bool(img.get("upgradable", False))
        return False

    def get_downloaded_image_id(self) -> str | None:
        for img in self.docker.downloaded_images().get("data", {}).get("images", []):
            if "synology-test" in img.get("repository", ""):
                for tag in img.get("tags", []):
                    if tag == "latest":
                        return img.get("id", "")
        return None

    def pull_image(self) -> None:
        result = self.docker.request_data(
            "SYNO.Docker.Image",
            "entry.cgi",
            req_param={
                "method": "pull_start",
                "version": 1,
                "repository": "alexives/synology-test",
                "tag": "latest",
            },
        )
        task_id = result.get("data", {}).get("task_id", "")
        if not task_id:
            raise RuntimeError(f"pull_start returned no task_id: {result}")
        for _ in range(60):
            status = self.docker.request_data(
                "SYNO.Docker.Image",
                "entry.cgi",
                req_param={"method": "pull_status", "version": 1, "task_id": task_id},
            )
            if status.get("data", {}).get("finished"):
                return
            time.sleep(1)
        raise RuntimeError("Image pull timed out")


def push_new_image() -> str:
    """Build and push a new image, return the local image ID."""
    result = subprocess.run(
        ["bash", str(INTEGRATION_DIR / "push-update.sh")],
        capture_output=True,
        text=True,
        check=True,
    )
    print(result.stdout)
    # Get the local image ID
    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{.Id}}", IMAGE],
        capture_output=True,
        text=True,
        check=True,
    )
    return inspect.stdout.strip()


def wait_for(description: str, check, timeout: int = 120, interval: int = 3):
    """Poll until check() returns truthy, or timeout."""
    print(f"  Waiting for {description}...", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = check()
        if result:
            print(" OK")
            return result
        print(".", end="", flush=True)
        time.sleep(interval)
    print(" TIMEOUT")
    raise TimeoutError(f"Timed out waiting for {description}")


def report(label: str):
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")


def check_preconditions(ha: HAClient, nas: NASClient):
    report("PRECONDITION CHECK")

    state = ha.get_state(UPDATE_ENTITY)
    print(f"  Update entity state: {state['state']}")
    print(f"  Installed: {state['attributes'].get('installed_version')}")
    print(f"  Latest:    {state['attributes'].get('latest_version')}")

    state = ha.get_state(SWITCH_ENTITY)
    print(f"  Switch entity state: {state['state']}")

    ctr_status = nas.get_container_status()
    print(f"  Container status:    {ctr_status}")

    if ctr_status != "running":
        raise RuntimeError(f"Container not running: {ctr_status}")
    print("  All preconditions met.")


def test_update_image_on_disk(ha: HAClient, nas: NASClient):
    """Scenario 1: New image already pulled to NAS, trigger update via HA."""
    report("SCENARIO 1: Update with image already on disk")

    # Ensure we have a pending update
    image_before = push_new_image()
    print(f"  Pushed new image: {image_before[:20]}...")
    nas.pull_image()
    print("  Pulled image to NAS")

    ctr_id_before = nas.get_container_image_id()
    disk_id = nas.get_downloaded_image_id()
    print(f"  Container ImageID: ...{ctr_id_before[-12:]}")
    print(f"  On-disk ImageID:   ...{disk_id[-12:]}")
    assert ctr_id_before != disk_id, "Expected mismatch before update"

    # Refresh coordinator so HA sees the update
    ha.refresh_coordinator()
    time.sleep(2)

    state = ha.get_state(UPDATE_ENTITY)
    print(f"  HA update state: {state['state']}")
    assert state["state"] == "on", f"Expected update available, got {state['state']}"

    # Trigger update
    print("  Triggering update via HA...")
    ha.call_service("update", "install", UPDATE_ENTITY)

    # Wait for container to be rebuilt with new image
    def container_updated():
        ctr_id = nas.get_container_image_id()
        return ctr_id and ctr_id == disk_id

    wait_for("container rebuild", container_updated, timeout=120)

    # Verify HA reflects the update
    ha.refresh_coordinator()
    time.sleep(2)
    state = ha.get_state(UPDATE_ENTITY)
    print(f"  HA update state after: {state['state']}")
    print(f"  Installed: {state['attributes'].get('installed_version')}")
    assert state["state"] == "off", f"Expected no update pending, got {state['state']}"

    print("  PASSED")


def test_update_pulls_newer_image(ha: HAClient, nas: NASClient):
    """Scenario 2: Pull triggers a newer image during rebuild."""
    report("SCENARIO 2: Update pulls newer image during rebuild")

    # Push and pull an image so HA sees an update
    push_new_image()
    nas.pull_image()
    print("  Pulled first image to NAS")

    ctr_id_before = nas.get_container_image_id()
    disk_id_before = nas.get_downloaded_image_id()
    print(f"  Container ImageID: ...{ctr_id_before[-12:]}")
    print(f"  On-disk ImageID:   ...{disk_id_before[-12:]}")
    assert ctr_id_before != disk_id_before, "Expected mismatch before update"

    # Push another new image to Docker Hub (don't pull).
    # When update triggers, it pulls this newer version during rebuild.
    push_new_image()
    print("  Pushed second image (not pulled)")

    ha.refresh_coordinator()
    time.sleep(2)

    state = ha.get_state(UPDATE_ENTITY)
    print(f"  HA update state: {state['state']}")
    assert state["state"] == "on", f"Expected update available, got {state['state']}"

    print("  Triggering update via HA (will pull newest + rebuild)...")
    ha.call_service("update", "install", UPDATE_ENTITY)

    # Wait for container to be rebuilt
    def container_changed():
        ctr_id = nas.get_container_image_id()
        return ctr_id and ctr_id != ctr_id_before

    wait_for("container rebuild with new image", container_changed, timeout=180)

    new_ctr_id = nas.get_container_image_id()
    new_disk_id = nas.get_downloaded_image_id()
    print(f"  Container ImageID after:  ...{new_ctr_id[-12:]}")
    print(f"  On-disk ImageID after:    ...{new_disk_id[-12:]}")
    assert new_ctr_id == new_disk_id, "Container should match on-disk image after update"
    if new_ctr_id == disk_id_before:
        print("  NOTE: Pull returned cached image (Docker Hub CDN lag)")
    else:
        print("  Pull fetched a newer image than was on disk")

    print("  PASSED")


def test_upgradable_flag_prep(nas: NASClient):
    """Scenario 3 prep: Push a new image so the registry has a newer version."""
    report("SCENARIO 3 PREP: Push image for upgradable flag test")

    push_new_image()
    print("  Pushed new image to Docker Hub (not pulling to NAS)")

    ctr_id = nas.get_container_image_id()
    disk_id = nas.get_downloaded_image_id()
    print(f"  Container ImageID: ...{ctr_id[-12:]}")
    print(f"  On-disk ImageID:   ...{disk_id[-12:]}")
    assert ctr_id == disk_id, "Expected no local mismatch"

    if nas.is_image_upgradable():
        print("  Upgradable flag already set - ready to verify")
    else:
        print("  Upgradable flag not set yet")
        print("  ACTION REQUIRED: In Container Manager, check for updates on")
        print("  the synology-test image, then run scenario 3 verify.")

    print("  PREP DONE")


def test_upgradable_flag_verify(ha: HAClient, nas: NASClient):
    """Scenario 3 verify: Confirm HA detects update via upgradable flag and installs."""
    report("SCENARIO 3 VERIFY: Update detected via upgradable flag")

    ctr_id_before = nas.get_container_image_id()
    disk_id_before = nas.get_downloaded_image_id()
    print(f"  Container ImageID: ...{ctr_id_before[-12:]}")
    print(f"  On-disk ImageID:   ...{disk_id_before[-12:]}")

    assert nas.is_image_upgradable(), "Expected upgradable flag to be True"
    print("  Upgradable flag is True")

    ha.refresh_coordinator()
    time.sleep(2)

    state = ha.get_state(UPDATE_ENTITY)
    print(f"  HA update state: {state['state']}")
    assert state["state"] == "on", f"Expected update available, got {state['state']}"

    print("  Triggering update via HA (will pull + rebuild)...")
    ha.call_service("update", "install", UPDATE_ENTITY)

    def container_changed():
        ctr_id = nas.get_container_image_id()
        return ctr_id and ctr_id != ctr_id_before

    wait_for("container rebuild with new image", container_changed, timeout=180)

    new_ctr_id = nas.get_container_image_id()
    new_disk_id = nas.get_downloaded_image_id()
    print(f"  Container ImageID after:  ...{new_ctr_id[-12:]}")
    print(f"  On-disk ImageID after:    ...{new_disk_id[-12:]}")
    assert new_ctr_id == new_disk_id, "Container should match on-disk image after update"

    print("  PASSED")


def test_switch_stop_start(ha: HAClient, nas: NASClient):
    """Scenario 4: Stop and start the project via switch."""
    report("SCENARIO 4: Stop and start via switch")

    # Verify running
    status = nas.get_container_status()
    print(f"  Container status: {status}")
    assert status == "running", f"Expected running, got {status}"

    state = ha.get_state(SWITCH_ENTITY)
    print(f"  Switch state: {state['state']}")
    assert state["state"] == "on"

    # Stop
    print("  Turning off switch...")
    ha.call_service("switch", "turn_off", SWITCH_ENTITY)

    def container_stopped():
        s = nas.get_container_status()
        return s and s != "running"

    wait_for("container stopped", container_stopped, timeout=30)
    print(f"  Container status: {nas.get_container_status()}")

    ha.refresh_coordinator()
    time.sleep(2)
    state = ha.get_state(SWITCH_ENTITY)
    print(f"  Switch state after stop: {state['state']}")
    assert state["state"] == "off", f"Expected off, got {state['state']}"

    # Start
    print("  Turning on switch...")
    ha.call_service("switch", "turn_on", SWITCH_ENTITY)

    def container_running():
        return nas.get_container_status() == "running"

    wait_for("container running", container_running, timeout=30)
    print(f"  Container status: {nas.get_container_status()}")

    ha.refresh_coordinator()
    time.sleep(2)
    state = ha.get_state(SWITCH_ENTITY)
    print(f"  Switch state after start: {state['state']}")
    assert state["state"] == "on", f"Expected on, got {state['state']}"

    print("  PASSED")


def _run_tests(tests, ha, nas):
    passed = 0
    failed = 0
    errors: list[str] = []
    for name, func, args in tests:
        try:
            func(*args)
            passed += 1
        except Exception as e:
            failed += 1
            errors.append(f"{name}: {e}")
            print(f"  FAILED: {e}")
    return passed, failed, errors


def main():
    env = load_env()
    syn_host = env["SYN_HOST"]
    host, _, port = syn_host.partition(":")

    ha = HAClient(env["HA_LOCAL_URL"], env["HA_LOCAL_TOKEN"])
    nas = NASClient(host, port, env["SYN_USER"], env["SYN_PW"])

    check_preconditions(ha, nas)

    passed, failed, errors = _run_tests(
        [
            ("scenario_1", test_update_image_on_disk, (ha, nas)),
            ("scenario_2", test_update_pulls_newer_image, (ha, nas)),
            ("scenario_3_prep", test_upgradable_flag_prep, (nas,)),
            ("scenario_4", test_switch_stop_start, (ha, nas)),
        ],
        ha,
        nas,
    )

    report("RESULTS")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    for err in errors:
        print(f"  - {err}")

    if failed:
        sys.exit(1)

    print("\n  Scenario 3 verify must be run separately after triggering")
    print("  a registry check in Container Manager:")
    print("    python3 tests/integration/test_update_flow.py --verify-upgradable")


def main_verify_upgradable():
    env = load_env()
    syn_host = env["SYN_HOST"]
    host, _, port = syn_host.partition(":")

    ha = HAClient(env["HA_LOCAL_URL"], env["HA_LOCAL_TOKEN"])
    nas = NASClient(host, port, env["SYN_USER"], env["SYN_PW"])

    try:
        test_upgradable_flag_verify(ha, nas)
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if "--verify-upgradable" in sys.argv:
        main_verify_upgradable()
    else:
        main()
