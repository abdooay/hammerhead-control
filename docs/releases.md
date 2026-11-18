# Publishing updates

The public source repository is https://github.com/abdooay/hammerhead-control.
The flat signed APT repository is https://abdooay.github.io/hammerhead-control/apt/.

## Release a new version

1. Make the application changes and update `hammerhead.__version__`.
2. Update `RELEASE_NOTES.md`, including the installer filename.
3. Run `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest discover -s tests -v`.
4. Commit and push to `main`, then create and push the matching `vX.Y.Z` tag.

The release workflow tests the code, builds an architecture-independent `.deb`,
publishes a GitHub Release, signs the APT indexes, and deploys them to GitHub
Pages. Previously released `.deb` files remain available for clients with
cached package lists. Re-running a release verifies that an already published
package is byte-for-byte identical; it never silently replaces that version.
Use a new version for changed package contents.

The workflow can also be dispatched manually **on a release tag**. The tag
must match the version in the source tree. Releases are serialized so deployments
do not overlap. The package and APT source install no background update service;
updates use the system's existing APT tools.

## Archive signing

`packaging/archive-key.asc` is the public key. Its full fingerprint is stored
in `packaging/archive-key.fingerprint`. The private key is stored only in the
repository's encrypted GitHub Actions secret `APT_SIGNING_KEY`. The workflow
imports it into a temporary private GnuPG directory and removes that directory
at the end of the job. Forks and pull-request CI do not receive this key.

APT trusts this key only for the source named in
`/etc/apt/sources.list.d/hammerhead-control.sources`, using `Signed-By` and the
package-owned `/etc/apt/keyrings/hammerhead-control-archive-keyring.gpg`.

GitHub does not expose stored secret values for download. Preserve access to
this repository/secret; if it is lost, publish a replacement key and provide
an explicit client key-migration path. Never commit a private signing key.
To rotate keys, first distribute a keyring containing the new public key in
an update signed by the old key; switch signatures only after clients have
received that update.

## Local builds

Install `python3-pyqt6`, `qt6-wayland`, `dpkg`, `apt-utils`, and `gnupg`.
Then run:

```sh
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) python3 packaging/build_deb.py
```

The result is in `dist/`. Building a `.deb` needs no private key and no root.
Signing an APT repository requires the archive signing key in `GNUPGHOME`:

```sh
python3 packaging/build_repository.py --packages dist --output dist/apt \
  --signing-key "$(cat packaging/archive-key.fingerprint)"
```

The output directory must be new. Do not edit generated index files after signing.
