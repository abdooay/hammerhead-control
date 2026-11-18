"""Direct HID controls, scoped to Hammerhead V3 HyperSpeed interface 3."""

from contextlib import contextmanager
from pathlib import Path
import fcntl
import os
import secrets
import time

from .protocol import Command, DeviceError, NoResponse, ProtocolError, make_report, parse_response


NOISE_VALUES = {'off': 0, 'anc': 1, 'ambient': 0x50}
GET_NOISE = Command(0x18, 0x86, bytes([1]))
GET_CONNECTION = Command(0x18, 0x9a, bytes([1]), device_type=0)
SWITCH_SOURCE = Command(0x18, 0x1d, b'')


def find_device(sysfs=Path('/sys/class/hidraw')) -> Path | None:
    matches = []
    for entry in sysfs.glob('hidraw*'):
        try:
            device = (entry / 'device').resolve()
            values = dict(line.split('=', 1) for line in (device / 'uevent').read_text().splitlines() if '=' in line)
            if (values.get('HID_ID') == '0003:00001532:00000A61'
                    and (device.parent / 'bInterfaceNumber').read_text().strip() == '03'):
                matches.append(Path('/dev') / entry.name)
        except (FileNotFoundError, PermissionError):
            continue
    if len(matches) > 1:
        raise DeviceError('More than one Hammerhead dongle is connected. Connect only one.')
    return matches[0] if matches else None


@contextmanager
def device_lock():
    runtime = Path(f'/run/user/{os.getuid()}')
    path = runtime / 'hammerhead-control-device.lock'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DeviceError('Another Hammerhead operation is in progress. Try again.') from error
        yield
    finally:
        os.close(fd)


class HidTransport:
    def __init__(self, path):
        self.path = path
        self.fd = None
        self.counter = secrets.randbelow(31)

    def __enter__(self):
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        except PermissionError as error:
            raise DeviceError('Device access is needed. Install the supplied udev rule.') from error
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    def exchange(self, command):
        self.counter = self.counter % 31 + 1
        request = make_report(command, self.counter)
        # Linux hidraw HIDIOCSFEATURE/HIDIOCGFEATURE include the report ID.
        ioctl_base = (3 << 30) | (64 << 16) | (ord('H') << 8)
        size = fcntl.ioctl(self.fd, ioctl_base | 0x06, bytearray(request), True)
        if size != 64:
            raise ProtocolError('The dongle did not accept the complete command.')
        deadline = time.monotonic() + 1.5
        time.sleep(0.1)
        while time.monotonic() < deadline:
            response = bytearray(64)
            response[0] = 2
            size = fcntl.ioctl(self.fd, ioctl_base | 0x07, response, True)
            if size == 0:
                time.sleep(0.05)
                continue
            data = parse_response(bytes(response[:size]), request)
            if data is not None:
                return data
            time.sleep(0.05)
        raise NoResponse('The earbuds did not respond in time. Check that they are in HyperSpeed mode.')


def read_noise(transport):
    data = transport.exchange(GET_NOISE)
    if len(data) != 3 or data[0] != 1 or data[1] not in NOISE_VALUES.values():
        raise ProtocolError('The earbuds returned an unrecognized listening mode.')
    return next(name for name, value in NOISE_VALUES.items() if value == data[1]), data[2]


def read_connection(transport):
    data = transport.exchange(GET_CONNECTION)
    if len(data) != 3 or data[0] != 1 or data[1] > 3 or data[2] > 3:
        raise ProtocolError('The earbuds returned an unrecognized connection status.')
    return data[1], data[2]


def ready_status(noise_mode, wireless, bluetooth):
    return {'connected': True, 'accessible': True, 'detail': 'Connected through the HyperSpeed dongle.',
            'noise_mode': noise_mode, 'wireless_earbuds': wireless, 'bluetooth_earbuds': bluetooth,
            'capabilities': ['noise', 'source']}


class Controller:
    @contextmanager
    def _device(self):
        try:
            with device_lock():
                path = find_device()
                if path is None:
                    raise DeviceError('Connect the Hammerhead V3 HyperSpeed dongle.')
                with HidTransport(path) as transport:
                    yield transport
        except OSError as error:
            raise DeviceError(f'Unable to access the earbuds: {error.strerror}') from error

    def status(self):
        base = {'connected': False, 'accessible': False, 'noise_mode': None, 'capabilities': []}
        path = find_device()
        if path is None:
            return {**base, 'detail': 'Connect the Hammerhead V3 HyperSpeed dongle.'}
        if not os.access(path, os.R_OK | os.W_OK):
            return {**base, 'connected': True, 'detail': 'Device access is needed. Install the supplied udev rule.'}
        try:
            with self._device() as transport:
                noise, _ = read_noise(transport)
                wireless, bluetooth = read_connection(transport)
                return ready_status(noise, wireless, bluetooth)
        except NoResponse:
            return {**base, 'accessible': True, 'detail': 'Dongle detected. Wake the earbuds and switch them to HyperSpeed mode.'}

    def set_noise_mode(self, mode):
        if mode not in NOISE_VALUES:
            raise DeviceError(f'Unknown listening mode: {mode}')
        with self._device() as transport:
            current, level = read_noise(transport)
            if current != mode:
                transport.exchange(Command(0x18, 0x06, bytes([1, NOISE_VALUES[mode], level])))
            actual, _ = read_noise(transport)
            if actual != mode:
                raise DeviceError('The earbuds did not confirm the requested listening mode.')
            wireless, bluetooth = read_connection(transport)
            return ready_status(actual, wireless, bluetooth)

    def set_source(self, source):
        if source != 'toggle':
            raise DeviceError('This model supports toggling the audio source, not selecting a source directly.')
        with self._device() as transport:
            transport.exchange(SWITCH_SOURCE)
            try:
                wireless, bluetooth = read_connection(transport)
                noise, _ = read_noise(transport)
                status = ready_status(noise, wireless, bluetooth)
                status['detail'] = 'The earbuds acknowledged the audio-source switch.'
                return status
            except NoResponse:
                return {'connected': False, 'accessible': True, 'noise_mode': None,
                        'capabilities': [], 'detail': 'The source command was acknowledged, but the wireless control link is unavailable. Triple-tap an earbud to return to HyperSpeed.'}

    def start_pairing(self):
        raise DeviceError('Bluetooth pairing from the computer is not supported. Triple-tap an earbud and hold the last tap for 3 seconds.')
