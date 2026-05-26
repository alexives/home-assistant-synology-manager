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
