import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createPiSession} from '../pi-session.mjs';
import {validateInit} from '../protocol.mjs';
import {isolateEnvironment} from '../sidecar.mjs';
import {init} from './fixtures.mjs';
import {installNetworkGuard} from './offline-network.mjs';

isolateEnvironment(process.env);
const guard=installNetworkGuard();
test.afterEach(()=>guard.assertNoNetwork());
const sse=(chunks)=>new Response(chunks.map(chunk=>`data: ${JSON.stringify(chunk)}\n\n`).join('')+'data: [DONE]\n\n',
  {headers:{'content-type':'text/event-stream'}});
async function configFor(t, changes) {
  const root=await mkdtemp(join(tmpdir(),'pi-provider-wire-'));
  t.after(()=>rm(root,{recursive:true,force:true}));
  return validateInit({...init(root),apiKey:'literal-$NOT_INTERPOLATED-!not-a-command',...changes});
}
async function captureRequest(input, options) {
  const request=new Request(input,options);
  return {url:request.url,headers:request.headers,body:JSON.parse(await request.text())};
}
for (const enabled of [false,true]) {
  test(`native Xiaomi serialization preserves ${enabled?'enabled':'disabled'} thinking and max tokens`,async(t)=>{
    const config=await configFor(t,{provider:'xiaomi',model:'mimo-v2.5-pro',baseUrl:'https://api.xiaomimimo.com/v1',
      reasoning:enabled,thinkingLevel:enabled?'high':'off',maxTokens:1536,contextWindow:32768});
    const requests=[];
    const fetch=async(input,options)=>{
      requests.push(await captureRequest(input,options));
      return sse([{id:'fake',object:'chat.completion.chunk',choices:[{index:0,delta:{content:'offline answer'},finish_reason:'stop'}]}]);
    };
    const session=await createPiSession(config,()=>{},()=>assert.fail('No tools expected'),{fetch});
    try {await session.prompt('hello');} finally {session.dispose();}
    assert.equal(requests.length,1);
    const wire=requests[0];
    assert.equal(wire.url,'https://api.xiaomimimo.com/v1/chat/completions');
    assert.equal(wire.headers.get('api-key'),config.apiKey);
    assert.deepEqual(wire.body.thinking,{type:enabled?'enabled':'disabled'});
    assert.equal(wire.body.max_completion_tokens,1536);
    assert.equal(wire.body.max_tokens,undefined);
    assert.equal(wire.body.reasoning_effort,undefined);
    assert.equal(wire.body.store,undefined);
    assert(wire.body.messages.some(message=>message.role==='system'));
  });
}
test('native Xiaomi adapter returns thinking and replays it around host tool calls',async(t)=>{
  const config=await configFor(t,{provider:'xiaomi',model:'mimo-v2.5-pro',baseUrl:'https://api.xiaomimimo.com/v1',
    reasoning:true,thinkingLevel:'medium',maxTokens:2048,contextWindow:32768});
  const requests=[],events=[],calls=[];
  const fetch=async(input,options)=>{
    requests.push(await captureRequest(input,options));
    const delta=requests.length===1
      ? {reasoning_content:'offline reasoning',tool_calls:[{index:0,id:'call-1',type:'function',function:{name:'bridge_echo',arguments:'{"text":"hello"}'}}]}
      : {content:'offline answer'};
    return sse([{id:'fake',object:'chat.completion.chunk',choices:[{index:0,delta,finish_reason:requests.length===1?'tool_calls':'stop'}]}]);
  };
  const session=await createPiSession(config,event=>events.push(event),async(id,name,args)=>{
    calls.push({id,name,args});return {content:[{type:'text',text:'host output'}],details:{}};
  },{fetch});
  try {await session.prompt('hello');} finally {session.dispose();}
  assert.equal(requests.length,2);assert.equal(calls.length,1);
  assert.equal(calls[0].name,'bridge_echo');
  assert(events.some(event=>event.assistantMessageEvent?.type==='thinking_delta'));
  assert.equal(requests[1].body.messages.find(message=>message.role==='assistant').reasoning_content,'offline reasoning');
  assert.equal(requests[1].body.messages.find(message=>message.role==='tool').content,'host output');
});
for (const enabled of [false,true]) {
test(`native Google serializer preserves ${enabled?'enabled':'disabled'} thinking and output cap`,async(t)=>{
  const config=await configFor(t,{provider:'google',api:'google-generative-ai',model:'gemini-2.5-flash',
    baseUrl:'https://generativelanguage.googleapis.com/v1beta',reasoning:true,thinkingLevel:enabled?'high':'off',
    maxTokens:enabled?32768:1536,contextWindow:128000});
  const requests=[];
  const guardedFetch=globalThis.fetch;
  globalThis.fetch=async(input,options)=>{
    requests.push(await captureRequest(input,options));
    return new Response('data: '+JSON.stringify({candidates:[{content:{role:'model',parts:[{text:'offline answer'}]},finishReason:'STOP'}],
      usageMetadata:{promptTokenCount:10,candidatesTokenCount:3,totalTokenCount:13}})+'\n\n',
      {headers:{'content-type':'text/event-stream'}});
  };
  t.after(()=>{globalThis.fetch=guardedFetch;});
  const session=await createPiSession(config,()=>{},()=>assert.fail('No tools expected'));
  try {await session.prompt('hello');} finally {session.dispose();globalThis.fetch=guardedFetch;}
  assert.equal(requests.length,1);
  assert.equal(requests[0].url,'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse');
  assert.equal(requests[0].headers.get('x-goog-api-key'),config.apiKey);
  assert.equal(requests[0].body.generationConfig.maxOutputTokens,config.maxTokens);
  assert.equal(requests[0].body.generationConfig.thinkingConfig.thinkingBudget,enabled?24576:0);
});
}
test('Xiaomi rejects an incompatible transport instead of silently changing protocols',async(t)=>{
  const config=await configFor(t,{provider:'xiaomi',api:'google-generative-ai'});
  await assert.rejects(createPiSession(config,()=>{},()=>{}),/Xiaomi requires openai-completions/);
});
