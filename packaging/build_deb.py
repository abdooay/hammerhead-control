#!/usr/bin/python3
"""Build the architecture-independent Debian package without root privileges."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def build(output):
    version = runpy.run_path(str(ROOT / 'hammerhead/__init__.py'))['__version__']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a three-part numeric release version.')
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'hammerhead-control_{version}_all.deb'
    epoch = int(os.environ.get('SOURCE_DATE_EPOCH', str(int((ROOT / 'hammerhead/__init__.py').stat().st_mtime))))
    with tempfile.TemporaryDirectory(prefix='hammerhead-deb-') as temporary:
        stage = Path(temporary)

        def copy(source, destination, mode=0o644):
            path = stage / destination
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, path)
            path.chmod(mode)

        for source in sorted((ROOT / 'hammerhead').glob('*.py')):
            copy(source, f'usr/share/hammerhead-control/hammerhead/{source.name}')
        copy('assets/hammerhead-control.svg', 'usr/share/hammerhead-control/assets/hammerhead-control.svg')
        copy('assets/hammerhead-control.svg', 'usr/share/icons/hicolor/scalable/apps/hammerhead-control.svg')
        copy('packaging/launcher', 'usr/bin/hammerhead-control', 0o755)
        copy('system/70-hammerhead-control.rules', 'usr/lib/udev/rules.d/70-hammerhead-control.rules')
        copy('packaging/hammerhead-control.sources', 'etc/apt/sources.list.d/hammerhead-control.sources')
        copy('packaging/copyright', 'usr/share/doc/hammerhead-control/copyright')
        for source in ['README.md', 'docs/protocol.md', 'docs/releases.md', 'docs/screenshot.png']:
            copy(source, f'usr/share/doc/hammerhead-control/{source}')
        desktop = stage / 'usr/share/applications/hammerhead-control.desktop'
        desktop.parent.mkdir(parents=True)
        desktop.write_text((ROOT / 'assets/hammerhead-control.desktop.in').read_text().replace('"@ROOT@/run.sh"', '/usr/bin/hammerhead-control'))
        key = stage / 'usr/share/keyrings/hammerhead-control-archive-keyring.gpg'
        key.parent.mkdir(parents=True)
        key.write_bytes(subprocess.check_output(['gpg', '--batch', '--dearmor'], input=(ROOT / 'packaging/archive-key.asc').read_bytes()))
        metadata = stage / 'DEBIAN'
        metadata.mkdir()
        installed_size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()) // 1024 + 1
        (metadata / 'control').write_text(f'''Package: hammerhead-control
Version: {version}
Architecture: all
Section: sound
Priority: optional
Maintainer: AbdElrahman <1643109+abdooay@users.noreply.github.com>
Depends: python3 (>= 3.10), python3-pyqt6 (>= 6.4), udev
Recommends: qt6-wayland
Installed-Size: {installed_size}
Homepage: https://github.com/abdooay/hammerhead-control
Description: KDE controls for Razer Hammerhead V3 HyperSpeed earbuds
 Native Qt controls for ANC, ambient listening and source switching.
 Includes a system tray and a signed APT update source.
''')
        (metadata / 'conffiles').write_text('/etc/apt/sources.list.d/hammerhead-control.sources\n')
        for script in ['postinst', 'postrm']:
            copy(f'packaging/{script}', f'DEBIAN/{script}', 0o755)
        sums = []
        for path in sorted(stage.rglob('*')):
            if path.is_file() and 'DEBIAN' not in path.relative_to(stage).parts:
                sums.append(f'{hashlib.md5(path.read_bytes()).hexdigest()}  {path.relative_to(stage)}')
        (metadata / 'md5sums').write_text('\n'.join(sums) + '\n')
        # Consistent ownership, modes and timestamps make release builds repeatable.
        for path in stage.rglob('*'):
            if path.is_dir():
                path.chmod(0o755)
            elif not path.stat().st_mode & 0o111:
                path.chmod(0o644)
            os.utime(path, (epoch, epoch))
        stage.chmod(0o755)
        os.utime(stage, (epoch, epoch))
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(stage), str(target)], check=True,
                       env=dict(os.environ, SOURCE_DATE_EPOCH=str(epoch)))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    print(build(args.output.resolve()))
