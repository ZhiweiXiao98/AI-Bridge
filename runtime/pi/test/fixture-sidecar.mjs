/** Test entry point uses the REAL pinned SDK with the in-process fake provider. */
import {main} from '../sidecar.mjs';
import {createPiSession} from '../pi-session.mjs';
import {fakeProvider} from './fake-provider.mjs';
import {installNetworkGuard} from './offline-network.mjs';
// Even a swallowed SDK network error must fail the process-backed contract test.
installNetworkGuard({onAttempt:() => { process.exitCode = 1; }});
await main({sessionFactory:(config, onEvent, callTool) => createPiSession(config, onEvent, callTool, {streamSimple:fakeProvider()})});
