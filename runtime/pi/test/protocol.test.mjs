import assert from 'node:assert/strict';
import test from 'node:test';
import {JsonlDecoder, validateInit, validateCommand, validateSession, validateToolResult, wireEvent} from '../protocol.mjs';
import {isolateEnvironment} from '../sidecar.mjs';

import {init} from './fixtures.mjs';
test('LF framing preserves Unicode separators and partial UTF-8', () => {
  const records = [], errors = [];
  const d = new JsonlDecoder((r) => records.push(r), (e) => errors.push(e));
  const bytes = Buffer.from(JSON.stringify({text:'x\u2028y\u2029🌏'}) + '\r\n');
  for (const byte of bytes) d.push(Buffer.from([byte]));
  d.end(); assert.deepEqual(records, [{text:'x\u2028y\u2029🌏'}]); assert.equal(errors.length, 0);
});
test('framing rejects malformed and oversize records without echoing payload', () => {
  const errors=[]; const d=new JsonlDecoder(()=>{}, (e,fatal)=>errors.push({text:e.message,fatal}), 32);
  d.push('not-json-secret\n'); d.push('x'.repeat(33));
  assert.equal(errors.length,2); assert.equal(errors[1].fatal,true); assert(!JSON.stringify(errors).includes('secret'));
});
test('EOF with an unfinished record fails', () => {
  const errors=[]; const d=new JsonlDecoder(()=>{}, e=>errors.push(e)); d.push('{'); d.end(); assert.equal(errors.length,1);
});
test('configuration accepts explicit custom provider and rejects ambient paths/settings', () => {
  const config=validateInit(init()); assert.equal(config.apiKey,'literal-test-key'); assert.equal(config.session.mode,'create');
  assert.throws(()=>validateInit({...init(), cwd:'relative'}));
  assert.throws(()=>validateInit({...init(), api:'unknown'}));
  assert.throws(()=>validateInit({...init(), baseUrl:'https://secret@example.invalid/v1'}));
  assert.throws(()=>validateInit({...init(), toolTimeoutMs:300001}));
  assert.throws(()=>validateInit({...init(), tools:[init().tools[0],init().tools[0]]}));
  assert.throws(()=>validateSession({mode:'memory'}));
  assert.throws(()=>validateCommand({id:'r',type:'bash',command:'echo forbidden'}));
});
test('invalid tool result content is rejected', () => {
  assert.throws(()=>validateToolResult({callId:'a',requestId:'p',result:{content:[{type:'file',path:'/etc/passwd'}]}}));
  assert.deepEqual(validateToolResult({callId:'a',requestId:'p',result:{content:[{type:'text',text:'ok'}]},isError:true}), {content:[{type:'text',text:'ok'}],details:null,isError:true});
});
test('wire deltas drop cumulative snapshots and preserve tool identity', () => {
  const wire=wireEvent({type:'message_update',message:{usage:{input:1}},assistantMessageEvent:{type:'toolcall_start',contentIndex:0,partial:{content:[{type:'toolCall',id:'c1',name:'bridge_echo'}]}}});
  assert.deepEqual(wire,{type:'message_update',usage:{input:1},assistantMessageEvent:{type:'toolcall_start',contentIndex:0,id:'c1',toolName:'bridge_echo'}});
});
test('isolated environment keeps only process essentials', () => {
  const env={PATH:'/usr/bin',OPENAI_API_KEY:'fake',HOME:'/fake',NODE_OPTIONS:'--import malicious',PI_CODING_AGENT_DIR:'/fake'};
  isolateEnvironment(env); assert.deepEqual(env,{PATH:'/usr/bin',PI_OFFLINE:'1'});
});
