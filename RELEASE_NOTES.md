Adds hardware microphone mute and unmute to the KDE window and system tray, with device readback before displaying success. Gesture changes are reflected on the next status refresh.

Keyboard shortcuts can use `hammerhead-control --mic mute`, `--mic unmute`, or `--mic toggle`. JSON status includes `mic_muted`.

Mute and unmute were verified by readback on the connected Hammerhead V3 HyperSpeed, including GUI and tray actions. The original microphone state was restored after testing.

Update with `sudo apt update && sudo apt install --only-upgrade hammerhead-control`, then restart the app.

For a new installation, download `hammerhead-control_0.1.2_all.deb` and run `sudo apt install ./hammerhead-control_0.1.2_all.deb`.

Controls require the HyperSpeed connection. Bluetooth pairing still requires the earbud gesture.
