"""Launch the GUI, or perform one device operation for a desktop shortcut."""
import argparse
import json
import sys
from . import __version__


def main():
    parser = argparse.ArgumentParser(description='Hammerhead Control — KDE earbud controls', allow_abbrev=False)
    parser.add_argument('--version', action='version', version=f'Hammerhead Control {__version__}')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--status', action='store_true', help='print device status as JSON')
    actions.add_argument('--noise', choices=['anc', 'ambient', 'off'], help='set noise control mode')
    actions.add_argument('--mic', choices=['mute', 'unmute', 'toggle'], help='control the earbud microphone hardware mute')
    actions.add_argument('--switch-source', action='store_true', help='toggle Bluetooth / HyperSpeed (may disconnect computer controls)')
    actions.add_argument('--pair', action='store_true', help='enter Bluetooth pairing, if supported')
    args = parser.parse_args()
    if args.status or args.noise or args.mic or args.switch_source or args.pair:
        from .device import Controller, DeviceError
        controller = Controller()
        try:
            if args.noise:
                result = controller.set_noise_mode(args.noise)
            elif args.mic:
                result = controller.set_mic_mute(args.mic)
            elif args.switch_source:
                result = controller.set_source('toggle')
            elif args.pair:
                result = controller.start_pairing()
            else:
                result = controller.status()
            print(json.dumps(result, indent=2))
            return 0
        except DeviceError as error:
            print(str(error), file=sys.stderr)
            return 1
    try:
        from .gui import run_gui
    except ModuleNotFoundError as error:
        if error.name == 'PyQt6':
            print('Qt bindings are missing. Install the python3-pyqt6 system package.', file=sys.stderr)
            return 1
        raise
    return run_gui()


if __name__ == '__main__':
    raise SystemExit(main())
