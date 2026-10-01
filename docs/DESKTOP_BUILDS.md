# Desktop build verification (Windows and macOS)

`.github/workflows/desktop-build.yml` builds the **remote client** on standard
GitHub-hosted `windows-latest` (x64), `macos-latest` (ARM64), and
`macos-15-intel` (x64) runners. It never selects larger
or paid runner labels, publishes a release, signs with a certificate, or notarizes.
Billing still depends on GitHub's account/repository plan and policy.

The entry point is `boot_remote.py`, not the Python-subprocess launcher
`start_client.py`. The dependency set is separate from server/mobile requirements
and uses PySide6, matching the current UI. A Python 3.12 environment on the target
OS can run:

```sh
python -m pip install -r requirements-desktop-build.txt
python -m unittest discover -s tests/public_ci -p test_desktop_packaging.py -v
python tools/desktop/build.py
python tools/desktop/smoke.py
```

Windows output: `build/desktop/dist/AI-Bridge-Remote/AI-Bridge-Remote.exe`.
macOS output: `build/desktop/dist/AI-Bridge-Remote.app`. Each is native to the
runner's reported architecture, not a universal binary. Keep the whole directory
or app bundle. macOS PyInstaller may apply the required ad-hoc signature; there
is no developer signing identity, trusted signature or notarization.

## Public distribution gate

**CI uploads only the build inventory, not the executable or app bundle.** A build
success is not release approval. Before adding binary upload/release steps, review
the exact bundled Qt libraries/plugins and every dependency: retain full notices
and license texts, satisfy corresponding-source obligations, and verify/document
replacement and relinking of LGPL libraries. `build/desktop/dependency-notices/`
collects the installed distributions' actual license/notice/SBOM files plus
metadata for this review; `review/desktop-inventory.json` lists versions and every
built file's SHA-256. These are inputs to review, not a complete compliance claim.
See [Qt obligations](https://www.qt.io/development/open-source-lgpl-obligations)
and [PyInstaller's license](https://pyinstaller.org/en/stable/license.html).

## Native Qt scope checks

A small QtGui analysis hook omits the unused PDF image plugin and virtual-keyboard
plugin before PyInstaller resolves their native dependencies. After building,
`desktop-inventory.json` is checked for VirtualKeyboard, Pdf, Qml and Quick library,
framework and plugin names. Any remaining instance fails the build. This validates
the actual output rather than assuming Python-module exclusions remove native
libraries. It does not replace the distribution-license gate above.

## Scope and privacy

Only the project's `LICENSE` is copied as repository data; code is discovered
through Python imports. No recursive copy of repository data is used. The build
excludes `assets/`, vendored `lib/`, docs, browser drivers/profiles, databases,
user configs, logs, credentials, plugins and server/mobile tooling. The current
UI keeps text buttons when decorative icons are absent; no unverified artwork is
redistributed. Default layouts/settings come from the code.

This is a login/startup-tested **remote-client build**, not full desktop feature
parity. It requires a separately configured reachable server. Local RAG, local
Docker execution, browser automation, source-code hot updates and local pytest
execution are not bundled. Build verification does not test authenticated server
flows, remote execution, external plugins, or native interactive UI behavior.

The frozen app writes its configuration and logs under `%LOCALAPPDATA%/AI-Bridge`
on Windows or `~/Library/Application Support/AI-Bridge` on macOS, never into the
installed bundle. `AI_BRIDGE_CLIENT_HOME` can select a separate writable state
directory. The smoke test uses a fresh temporary directory and does not log in or
contact a server. For updates, rebuild and replace the complete bundle.
