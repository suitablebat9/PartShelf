#!/usr/bin/env bash
# Run on the Proxmox host. This creates a new container; it never modifies an existing one.
set -euo pipefail
if [[ "$EUID" -ne 0 ]]; then echo 'Run as root on your Proxmox host.'; exit 1; fi
: "${CT_ID:?Set CT_ID to an unused container ID}"
: "${TEMPLATE:?Set TEMPLATE to the downloaded Debian 13 template volume, e.g. local:vztmpl/debian-13-standard_...tar.zst}"
STORAGE="${STORAGE:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
NET="${NET:-ip=dhcp}"
if pct status "$CT_ID" >/dev/null 2>&1; then echo "Container $CT_ID already exists; refusing."; exit 1; fi
pct create "$CT_ID" "$TEMPLATE" --hostname partshelf --unprivileged 1 --cores 2 --memory 1024 --swap 512 --rootfs "${STORAGE}:8" --net0 "name=eth0,bridge=${BRIDGE},${NET}" --onboot 1
pct start "$CT_ID"
echo "Created container $CT_ID. Wait for networking, then run: pct enter $CT_ID"
echo 'Follow docs/PROXMOX.md to install Partshelf inside it.'
