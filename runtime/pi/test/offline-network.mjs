/** Test-only fail-closed guard. Install before the SDK's first dynamic import. */
import assert from 'node:assert/strict';
import {syncBuiltinESMExports} from 'node:module';
import http from 'node:http';
import https from 'node:https';
import http2 from 'node:http2';
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import dgram from 'node:dgram';

export function installNetworkGuard({onAttempt = () => {}} = {}) {
  const attempts = [];
  const block = (name) => function () {
    attempts.push(name);
    onAttempt(name);
    // Never include destinations, request bodies, or credentials in failures.
    throw new Error(`External I/O disabled in Pi tests: ${name}`);
  };
  globalThis.fetch = block('fetch');
  if (globalThis.WebSocket) globalThis.WebSocket = block('WebSocket');
  for (const [name, module, methods] of [
    ['http', http, ['request', 'get']], ['https', https, ['request', 'get']],
    ['http2', http2, ['connect']], ['net', net, ['connect', 'createConnection']],
    ['tls', tls, ['connect']], ['dgram', dgram, ['createSocket']],
  ]) for (const method of methods) module[method] = block(`${name}.${method}`);
  net.Socket.prototype.connect = block('Socket.connect');
  for (const target of [dns, dns.promises, dns.Resolver.prototype, dns.promises.Resolver.prototype]) {
    for (const method of Object.getOwnPropertyNames(target)) {
      if (/^(lookup|resolve|reverse)/.test(method) && typeof target[method] === 'function')
        target[method] = block(`dns.${method}`);
    }
  }
  for (const method of ['send', 'connect']) dgram.Socket.prototype[method] = block(`Datagram.${method}`);
  syncBuiltinESMExports();
  return {attempts, assertNoNetwork:() => assert.deepEqual(attempts, [], 'Pi attempted external I/O')};
}
