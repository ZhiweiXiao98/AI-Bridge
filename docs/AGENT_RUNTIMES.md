# Optional agent runtimes

New API conversations can use the Pi runtime or the existing Legacy runtime.
Browser conversations and existing Legacy sessions keep their original path.
The Pi integration is experimental. Codex, Claude Agent and remote adapters are
visible extension points, not implemented integrations.

## Install the source runtime

Use Python 3.12 for the application. Pi additionally requires Node 22.19.0 or
newer. From `runtime/pi`, run `npm ci --ignore-scripts` to install the exact
SDK dependency selected in `package-lock.json`. The sidecar currently pins
`@earendil-works/pi-coding-agent` to `0.99.1`. Do not copy `node_modules` into
source control, and do not upgrade the SDK without running its contract tests.

Configure your own provider API key through the application. Provider usage
may incur charges. The sidecar keeps the active credential overlay in memory;
new literal echoes of that key are filtered before session persistence. This
does not retroactively scrub historical files or all encoded secret variants.
Do not share session files without reviewing them.

Pi owns model iteration, retries, compaction and native JSONL history. AI Bridge
owns Python Skills and Docker execution. Each requested tool execution is sent
through the host approval boundary. The sidecar disables automatic project
extension, Skills and AGENTS discovery and does not enable Pi's built-in host
tools. Cancel and approval controls are bound to an authenticated account,
device and request. Browser/Legacy behavior remains separately implemented.

Desktop candidate packages are clients; install the optional Node runtime on
the server that runs the agent. A desktop client package alone does not install
Node, Pi dependencies, Chrome, Docker, local models or a running server.

## Offline validation

- `python -m unittest discover -s tests/public_ci -v`
- `python -m pip install -r requirements-ci.txt`
- `python -m pytest tests --disable-socket --allow-unix-socket`
- From `runtime/pi`: `npm run check && npm test`

The GitHub workflow splits regular Python and offscreen Qt tests and runs Pi
contracts in a dedicated Node job. The ordinary Python job may skip the three
SDK-dependent subprocess tests; the dedicated Pi job installs the SDK and
runs those tests. Real-provider, real Docker, model-download, slow and benchmark
tests require explicit opt-in and are not evidence of a production deployment.
The checked-in source migration does not include a new mobile/PWA client.

## Third-party licensing

The repository's MIT license covers its own code, not all dependencies.
Pi is installed from its upstream package with its dependency license notices.
The pinned Pi SDK is MIT-licensed, copyright Mario Zechner; see its
[upstream license](https://github.com/earendil-works/pi/blob/main/LICENSE).
No SDK implementation or node_modules tree is vendored in this repository.
PySide6/Qt and other dependencies retain their own licenses; consult their
installed package notices and upstream terms before distributing binaries.
A successful build is not a license-clearance or signed release. Follow
`DESKTOP_BUILDS.md` for the separate binary-distribution gate when available.
