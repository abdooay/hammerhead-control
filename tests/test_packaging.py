import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class PackageTests(unittest.TestCase):
    def test_package_is_reproducible_and_contains_only_deliverables(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            environment = dict(os.environ, SOURCE_DATE_EPOCH='1794996000')
            command = ['/usr/bin/python3', str(ROOT / 'packaging/build_deb.py'), '--output', str(output)]
            subprocess.run(command, check=True, env=environment, stdout=subprocess.DEVNULL)
            package = next(output.glob('*.deb'))
            first = hashlib.sha256(package.read_bytes()).hexdigest()
            subprocess.run(command, check=True, env=environment, stdout=subprocess.DEVNULL)
            self.assertEqual(hashlib.sha256(package.read_bytes()).hexdigest(), first)
            contents = subprocess.check_output(['dpkg-deb', '-c', str(package)], text=True)
            for excluded in ('Agent/', '__pycache__', '/home/', 'private', 'middleware.js', 'tests/'):
                self.assertNotIn(excluded, contents)
            for expected in ('usr/bin/hammerhead-control', 'usr/lib/udev/rules.d/70-hammerhead-control.rules',
                             'etc/apt/keyrings/hammerhead-control-archive-keyring.gpg',
                             'etc/apt/sources.list.d/hammerhead-control.sources'):
                self.assertIn(expected, contents)
            self.assertEqual(subprocess.check_output(['dpkg-deb', '-f', str(package), 'Architecture'], text=True).strip(), 'all')
            extracted = output / 'extracted'
            subprocess.run(['dpkg-deb', '-x', str(package), str(extracted)], check=True)
            metadata = output / 'metadata'
            subprocess.run(['dpkg-deb', '-e', str(package), str(metadata)], check=True)
            conffiles = (metadata / 'conffiles').read_text().splitlines()
            self.assertIn('/etc/apt/sources.list.d/hammerhead-control.sources', conffiles)
            self.assertIn('/etc/apt/keyrings/hammerhead-control-archive-keyring.gpg', conffiles)
            source = (extracted / 'etc/apt/sources.list.d/hammerhead-control.sources').read_text()
            self.assertIn('https://abdooay.github.io/hammerhead-control/apt/', source)
            self.assertIn('Signed-By: /etc/apt/keyrings/hammerhead-control-archive-keyring.gpg', source)
            self.assertNotIn('Trusted:', source)
            desktop = extracted / 'usr/share/applications/hammerhead-control.desktop'
            subprocess.run(['desktop-file-validate', str(desktop)], check=True)
            self.assertIn('Exec=/usr/bin/hammerhead-control', desktop.read_text())
            version = subprocess.check_output(['/usr/bin/python3', '-m', 'hammerhead', '--version'],
                                              cwd=extracted / 'usr/share/hammerhead-control', text=True)
            self.assertIn('Hammerhead Control', version)

    def test_public_archive_key_matches_pinned_fingerprint(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.check_output(['gpg', '--homedir', home, '--batch', '--with-colons',
                                              '--show-keys', str(ROOT / 'packaging/archive-key.asc')], text=True)
        fingerprint = next(line.split(':')[9] for line in result.splitlines() if line.startswith('fpr:'))
        self.assertEqual(fingerprint, (ROOT / 'packaging/archive-key.fingerprint').read_text().strip())
        self.assertNotIn('PRIVATE', (ROOT / 'packaging/archive-key.asc').read_text())


if __name__ == '__main__':
    unittest.main()
