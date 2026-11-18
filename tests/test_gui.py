import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from hammerhead.device import DeviceError
from hammerhead import gui


class FakeController:
    def __init__(self):
        self.muted = False
        self.noise = 'off'
        self.fail = False
        self.calls = []

    def status(self):
        return {'connected': True, 'accessible': True, 'detail': 'Test transport',
                'noise_mode': self.noise, 'mic_muted': self.muted, 'capabilities': ['noise', 'source', 'mic']}

    def set_noise_mode(self, mode):
        self.calls.append(mode)
        time.sleep(.03)
        if self.fail:
            raise DeviceError('Device rejected change')
        self.noise = mode
        return self.status()

    def set_mic_mute(self, mode):
        self.calls.append(mode)
        time.sleep(.03)
        if self.fail:
            raise DeviceError('Device rejected mute')
        self.muted = mode == 'mute'
        return self.status()

    def set_source(self, source):
        self.calls.append(source)
        return self.status()


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def wait_for(self, predicate):
        end = time.monotonic() + 3
        while not predicate() and time.monotonic() < end:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def setUp(self):
        self.controller = FakeController()
        self.patch = patch.object(gui, 'Controller', return_value=self.controller)
        self.patch.start()
        self.window = gui.ControlWindow()
        self.window.show()
        self.wait_for(lambda: self.window._status['connected'])
        self.window._poll.stop()

    def tearDown(self):
        self.window.close()
        self.wait_for(lambda: self.window._thread_stopped)
        self.window.deleteLater()
        self.patch.stop()

    def test_unsupported_pairing_is_not_actionable(self):
        self.assertFalse(self.window.pairing_button.isEnabled())
        self.assertFalse(self.window.pairing_action.isEnabled())
        self.assertTrue(self.window._noise_buttons['off'].isChecked())

    def test_selection_waits_for_device_and_serializes_requests(self):
        self.window._noise_buttons['ambient'].click()
        self.assertTrue(self.window._noise_buttons['off'].isChecked())
        self.window.request('noise', 'anc')
        self.wait_for(lambda: not self.window._busy)
        self.assertTrue(self.window._noise_buttons['ambient'].isChecked())
        self.assertEqual(self.controller.calls, ['ambient'])

    def test_device_failure_never_becomes_success(self):
        self.controller.fail = True
        self.window._noise_buttons['anc'].click()
        self.wait_for(lambda: not self.window._busy)
        self.assertIn('Device rejected change', self.window.error_label.text())
        self.assertFalse(any(button.isChecked() for button in self.window._noise_buttons.values()))

    def test_mic_window_and_tray_wait_for_device_readback(self):
        self.window.mic_button.click()
        self.assertEqual(self.window.mic_label.text(), 'Microphone: Unmuted')
        self.assertFalse(self.window.mic_button.isEnabled())
        self.wait_for(lambda: not self.window._busy)
        self.assertEqual(self.window.mic_label.text(), 'Microphone: Muted')
        self.assertEqual(self.window.mic_button.text(), 'Unmute microphone')
        self.window.mic_action.trigger()
        self.wait_for(lambda: not self.window._busy)
        self.assertEqual(self.controller.calls, ['mute', 'unmute'])
        self.assertEqual(self.window.mic_label.text(), 'Microphone: Unmuted')

    def test_mic_failure_clears_state_and_disables_controls(self):
        self.controller.fail = True
        self.window.mic_button.click()
        self.wait_for(lambda: not self.window._busy)
        self.assertEqual(self.window.mic_label.text(), 'Microphone: Unknown')
        self.assertFalse(self.window.mic_button.isEnabled())
        self.assertFalse(self.window.mic_action.isEnabled())
        self.assertIn('Device rejected mute', self.window.error_label.text())

    def test_refresh_reflects_external_mute_gesture(self):
        self.controller.muted = True
        self.window.request('status')
        self.wait_for(lambda: not self.window._busy)
        self.assertEqual(self.window.mic_label.text(), 'Microphone: Muted')
        self.assertEqual(self.window.mic_action.text(), 'Unmute microphone')

    def test_source_button_uses_toggle(self):
        self.window.source_button.click()
        self.wait_for(lambda: not self.window._busy)
        self.assertEqual(self.controller.calls, ['toggle'])


if __name__ == '__main__':
    unittest.main()
