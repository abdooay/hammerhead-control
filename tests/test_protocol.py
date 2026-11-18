import unittest
from unittest.mock import patch
from contextlib import contextmanager
from hammerhead.protocol import Command, DeviceError, NoResponse, ProtocolError, checksum, make_report, parse_response
from hammerhead.device import Controller, GET_NOISE, GET_CONNECTION, SWITCH_SOURCE, read_noise

# Captured from this user's 1532:0a61 device; independent of packet construction.
ANC_OFF_REPLY = bytes.fromhex('02026100000003188601000a' + '00' * 50 + '9600')


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.request = make_report(GET_NOISE, 1)

    def test_captured_request_and_reply(self):
        self.assertEqual(self.request.hex(), '02006100000001188601' + '00' * 52 + '9e00')
        self.assertEqual(parse_response(ANC_OFF_REPLY, self.request), b'\x01\x00\x0a')

    def test_connection_targets_dongle(self):
        request = make_report(GET_CONNECTION, 1)
        self.assertEqual(request[2], 1)
        self.assertEqual(request[6:10], bytes([1, 0x18, 0x9a, 1]))

    def test_stale_reply_is_not_success(self):
        stale = bytearray(ANC_OFF_REPLY)
        stale[2] = 0x62
        self.assertIsNone(parse_response(stale, self.request))
        stale[2] = 0x61
        stale[8] = 0x92
        self.assertIsNone(parse_response(stale, self.request))

    def test_corrupt_reply_rejected(self):
        corrupt = bytearray(ANC_OFF_REPLY)
        corrupt[10] = 80
        with self.assertRaises(ProtocolError):
            parse_response(corrupt, self.request)

    def test_short_reply_rejected(self):
        with self.assertRaises(ProtocolError):
            parse_response(ANC_OFF_REPLY[:12], self.request)

    def test_empty_dongle_reply_is_not_success(self):
        self.assertIsNone(parse_response(bytes(64), self.request))

    def test_invalid_length_rejected(self):
        data = bytearray(ANC_OFF_REPLY)
        data[6] = 54
        data[62] = checksum(data)
        with self.assertRaises(ProtocolError):
            parse_response(data, self.request)

    def test_pending_and_error_responses(self):
        for status in (0, 1, 3, 4, 5):
            with self.subTest(status=status):
                data = bytearray(ANC_OFF_REPLY)
                data[1] = status
                if status in (0, 1):
                    self.assertIsNone(parse_response(data, self.request))
                else:
                    with self.assertRaises(NoResponse if status == 4 else DeviceError):
                        parse_response(data, self.request)

    def test_invalid_transactions_and_argument_overflow(self):
        for counter in (0, 32):
            with self.assertRaises(ValueError):
                make_report(GET_NOISE, counter)
        with self.assertRaises(ValueError):
            make_report(Command(0x18, 6, bytes(54)), 1)


class FakeTransport:
    def __init__(self, mode=0, confirm=True):
        self.mode = mode
        self.confirm = confirm
        self.commands = []

    def exchange(self, command):
        self.commands.append(command)
        if command == GET_NOISE:
            return bytes([1, self.mode, 7])
        if command == GET_CONNECTION:
            return bytes([1, 3, 0])
        if command.command_class == 0x18 and command.command_id == 6:
            if self.confirm:
                self.mode = command.arguments[1]
            return command.arguments
        if command == SWITCH_SOURCE:
            return b''
        raise AssertionError(f'Unexpected command: {command}')


class ControllerTests(unittest.TestCase):
    def setup_controller(self, transport):
        controller = Controller()
        @contextmanager
        def device():
            yield transport
        controller._device = device
        return controller

    def test_mode_preserves_level_and_requires_readback(self):
        transport = FakeTransport()
        status = self.setup_controller(transport).set_noise_mode('ambient')
        self.assertEqual(status['noise_mode'], 'ambient')
        self.assertEqual(transport.commands[1], Command(0x18, 6, bytes([1, 80, 7])))
        self.assertEqual(transport.commands[2], GET_NOISE)

    def test_does_not_claim_unconfirmed_mode(self):
        with self.assertRaisesRegex(DeviceError, 'did not confirm'):
            self.setup_controller(FakeTransport(confirm=False)).set_noise_mode('anc')

    def test_same_mode_does_not_write(self):
        transport = FakeTransport()
        self.setup_controller(transport).set_noise_mode('off')
        self.assertFalse(any(command.command_id == 6 for command in transport.commands))

    def test_only_exact_model_source_toggle_sent(self):
        transport = FakeTransport()
        controller = self.setup_controller(transport)
        controller.set_source('toggle')
        self.assertEqual(transport.commands[0], SWITCH_SOURCE)
        with self.assertRaises(DeviceError):
            controller.set_source('bluetooth')

    def test_pairing_never_sends_unverified_command(self):
        transport = FakeTransport()
        with self.assertRaises(DeviceError):
            self.setup_controller(transport).start_pairing()
        self.assertEqual(transport.commands, [])

    def test_unknown_device_state_fails(self):
        transport = FakeTransport(mode=99)
        with self.assertRaises(ProtocolError):
            read_noise(transport)

    @patch('hammerhead.device.find_device', return_value=None)
    def test_no_dongle_disables_controls(self, _):
        status = Controller().status()
        self.assertFalse(status['connected'])
        self.assertEqual(status['capabilities'], [])


if __name__ == '__main__':
    unittest.main()
