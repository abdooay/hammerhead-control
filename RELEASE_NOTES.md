Debian packaging update: keep the APT source and its signing key together when the application is removed. `apt purge` removes both.

Existing users can update with `sudo apt update && sudo apt install --only-upgrade hammerhead-control`.

For a new installation, download `hammerhead-control_0.1.1_all.deb` and run `sudo apt install ./hammerhead-control_0.1.1_all.deb`.

ANC, ambient, off, source switching, and tray controls are unchanged. Bluetooth pairing still requires the earbud gesture.
