"""Hammerhead's 64-byte Razer feature-report protocol. See docs/protocol.md."""

from dataclasses import dataclass
from functools import reduce
import operator


class DeviceError(Exception):
    """A requested operation could not be confirmed by the device."""


class NoResponse(DeviceError):
    pass


class ProtocolError(DeviceError):
    pass


@dataclass(frozen=True)
class Command:
    command_class: int
    command_id: int
    arguments: bytes
    device_type: int = 3


def checksum(report: bytes) -> int:
    return reduce(operator.xor, report[3:62], 0)


def make_report(command: Command, transaction: int) -> bytes:
    if command.device_type not in (0, 3) or not 1 <= transaction <= 31:
        raise ValueError('Invalid device target or transaction counter.')
    if len(command.arguments) > 53:
        raise ValueError('Arguments exceed the feature-report capacity.')
    report = bytearray(64)
    report[0] = 2
    report[2] = (command.device_type << 5) | transaction
    report[6] = len(command.arguments)
    report[7] = command.command_class
    report[8] = command.command_id
    report[9:9 + len(command.arguments)] = command.arguments
    report[62] = checksum(report)
    return bytes(report)


def parse_response(report: bytes, request: bytes) -> bytes | None:
    """Return data only for a complete matching success; None means still waiting."""
    if len(report) != 64:
        raise ProtocolError('The earbuds returned an invalid feature report.')
    # The dongle returns an empty buffer when the wireless control link is absent.
    if not any(report):
        return None
    if report[0] != 2:
        raise ProtocolError('The earbuds returned an invalid feature report.')
    if report[2] != request[2] or report[7:9] != request[7:9]:
        return None
    if report[62] != checksum(report):
        raise ProtocolError('The earbud response failed its checksum.')
    size = int.from_bytes(report[5:7], 'big')
    if size > 53:
        raise ProtocolError('The earbud response has an invalid payload length.')
    status = report[1]
    if status in (0, 1):
        return None
    if status == 4:
        raise NoResponse('The dongle could not reach the earbuds.')
    errors = {3: 'The earbuds rejected the command.', 5: 'This firmware does not support the command.'}
    if status != 2:
        raise DeviceError(errors.get(status, f'The earbuds returned status {status}.'))
    return bytes(report[9:9 + size])
