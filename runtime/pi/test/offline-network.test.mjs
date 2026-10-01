import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import {installNetworkGuard} from './offline-network.mjs';

test('offline guard rejects fetch and standard HTTP, socket, TLS, and DNS paths',()=>{
  const guard=installNetworkGuard();
  for (const attempt of [
    ()=>fetch('https://example.invalid'), ()=>http.get('http://example.invalid'),
    ()=>https.request('https://example.invalid'), ()=>net.connect(443,'example.invalid'),
    ()=>new net.Socket().connect(443,'example.invalid'), ()=>tls.connect(443,'example.invalid'),
    ()=>dns.lookup('example.invalid',()=>{}), ()=>dns.promises.lookup('example.invalid'),
    ()=>new dns.Resolver().resolve4('example.invalid',()=>{}),
    ()=>new dns.promises.Resolver().resolve4('example.invalid'),
  ]) assert.throws(attempt,/External I\/O disabled/);
  assert.equal(guard.attempts.length,10);
  assert.throws(guard.assertNoNetwork,/Pi attempted external I\/O/);
});
