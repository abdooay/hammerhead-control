#!/usr/bin/python3
"""Create a signed, flat APT repository from released Debian packages."""
import argparse
import gzip
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def build(packages, output, fingerprint):
    output.mkdir(parents=True, exist_ok=False)
    pool = output / 'pool'
    pool.mkdir()
    candidates = sorted(packages.glob('hammerhead-control_*_all.deb'))
    if not candidates:
        raise ValueError('No Hammerhead packages were provided.')
    for package in candidates:
        name = subprocess.check_output(['dpkg-deb', '-f', str(package), 'Package'], text=True).strip()
        architecture = subprocess.check_output(['dpkg-deb', '-f', str(package), 'Architecture'], text=True).strip()
        version = subprocess.check_output(['dpkg-deb', '-f', str(package), 'Version'], text=True).strip()
        if name != 'hammerhead-control' or architecture != 'all' or package.name != f'{name}_{version}_all.deb':
            raise ValueError(f'Unexpected package identity: {package.name}')
        shutil.copyfile(package, pool / package.name)
    index = subprocess.check_output(['apt-ftparchive', 'packages', 'pool'], cwd=output)
    (output / 'Packages').write_bytes(index)
    (output / 'Packages.gz').write_bytes(gzip.compress(index, mtime=0))
    release = subprocess.check_output([
        'apt-ftparchive', '-o', 'APT::FTPArchive::Release::Origin=Hammerhead Control',
        '-o', 'APT::FTPArchive::Release::Label=Hammerhead Control',
        '-o', 'APT::FTPArchive::Release::Description=Hammerhead Control stable packages',
        'release', '.',
    ], cwd=output)
    (output / 'Release').write_bytes(release)
    command = ['gpg', '--batch', '--yes', '--local-user', fingerprint, '--digest-algo', 'SHA256']
    subprocess.run(command + ['--clearsign', '--output', str(output / 'InRelease'), str(output / 'Release')], check=True)
    subprocess.run(command + ['--armor', '--detach-sign', '--output', str(output / 'Release.gpg'), str(output / 'Release')], check=True)
    public = ROOT / 'packaging/archive-key.asc'
    shutil.copyfile(public, output / 'archive-key.asc')
    subprocess.run(['gpg', '--batch', '--verify', str(output / 'InRelease')], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--signing-key', required=True)
    args = parser.parse_args()
    expected = (ROOT / 'packaging/archive-key.fingerprint').read_text().strip()
    if args.signing_key != expected:
        parser.error('The signing key must match the public key bundled in the package.')
    build(args.packages.resolve(), args.output.resolve(), args.signing_key)
