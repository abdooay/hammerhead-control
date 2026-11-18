#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this helper through pkexec to enable device access.' >&2
    exit 1
fi
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -o root -g root -m 0644 "$script_dir/70-hammerhead-control.rules" /etc/udev/rules.d/70-hammerhead-control.rules
udevadm control --reload-rules
for node in /sys/class/hidraw/*; do
    [ -f "$node/device/uevent" ] || continue
    if grep -q '^HID_ID=0003:00001532:00000A61$' "$node/device/uevent"; then
        udevadm trigger --action=change "$node"
    fi
done
udevadm settle --timeout=5
