import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile, mkdir, writeFile, readdir, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createPiSession, protectSessionContent} from '../pi-session.mjs';
import {PiSidecar, isolateEnvironment} from '../sidecar.mjs';
import {init} from './fixtures.mjs';
import {fakeProvider} from './fake-provider.mjs';
import {installNetworkGuard} from './offline-network.mjs';
isolateEnvironment(process.env);
const networkGuard=installNetworkGuard();
test.afterEach(()=>networkGuard.assertNoNetwork());
const eventually = async(predicate) => {
  const deadline=Date.now()+10000;
  while (!predicate()) { if(Date.now()>deadline) throw Error('Test event deadline exceeded'); await new Promise(r=>setTimeout(r,10)); }
};
async function harness({onRequest, beforeInit}={}) {
  const root=await mkdtemp(join(tmpdir(),'pi-contract-'));
  const records=[];
  const sidecar=new PiSidecar({send:r=>records.push(r),sessionFactory:(config,onEvent,callTool)=>createPiSession(config,onEvent,callTool,{streamSimple:fakeProvider({onRequest})})});
  const config=init(root);
  config.apiKey='$NOT_AN_ENV_VAR !not-a-command';
  await beforeInit?.({root, config});
  await sidecar.accept(config);
  assert.equal(records[0].success,true,JSON.stringify(records[0]));
  return {root,config,sidecar,records};
}
test('real SDK owns tool loop; bridge supplies result; persistent resume restores history',async()=>{
  const requests=[];
  const h=await harness({onRequest:r=>requests.push(r)});
  assert.deepEqual(h.records[0].data.activeTools,['bridge_echo']);
  await h.sidecar.accept({id:'p1',type:'prompt',message:'test:tool'});
  await eventually(()=>h.records.some(r=>r.type==='tool_call'));
  const tool=h.records.find(r=>r.type==='tool_call');
  await h.sidecar.accept({id:'r1',type:'tool_result',requestId:'p1',callId:tool.callId,result:{content:[{type:'text',text:'approved host result'}]}});
  await eventually(()=>h.records.some(r=>r.event?.type==='agent_settled'));
  assert.equal(requests.length,2);
  assert.equal(requests[0].options.apiKey,h.config.apiKey,'Runtime credential must stay literal');
  const path=h.records[0].data.sessionFile;
  const persisted=await readFile(path,'utf8');
  assert(persisted.includes('approved host result'));assert(!persisted.includes(h.config.apiKey));
  await h.sidecar.accept({id:'resume',type:'resume',session:{mode:'open',path}});
  assert.equal(h.records.at(-1).success,true);
  await h.sidecar.accept({id:'p2',type:'prompt',message:'test:resume'});
  await eventually(()=>h.records.some(r=>r.requestId==='p2'&&r.event?.type==='agent_settled'));
  assert(h.records.some(r=>r.requestId==='p2'&&r.event?.assistantMessageEvent?.delta?.includes('2 user messages')));
  await h.sidecar.close();
});
test('real SDK exposes no builtin host tools and loads no project extensions or AGENTS',async()=>{
  const seen=[];const h=await harness({onRequest:r=>seen.push(r.context),beforeInit:async({root})=>{
    await mkdir(join(root,'.pi','extensions'),{recursive:true});
    await writeFile(join(root,'AGENTS.md'),'AMBIENT_INSTRUCTION_MUST_NOT_LOAD');
    await writeFile(join(root,'.pi','extensions','attack.ts'),'throw new Error("AMBIENT_EXTENSION_MUST_NOT_LOAD");');
  }});
  await h.sidecar.accept({id:'p1',type:'prompt',message:'test:host-builtin'});
  await eventually(()=>h.records.some(r=>r.event?.type==='agent_settled'));
  assert(!h.records.some(r=>r.type==='tool_call'));
  assert(!JSON.stringify(seen).includes('AMBIENT_INSTRUCTION_MUST_NOT_LOAD'));
  assert(h.records.some(r=>r.event?.type==='tool_execution_end'&&r.event.isError===true));
  await h.sidecar.close();
});
test('real SDK preserves failed bridge results and redacts echoed keys before persistence',async()=>{
  const requests=[];
  const h=await harness({onRequest:r=>requests.push(r)});
  await h.sidecar.accept({id:'p1',type:'prompt',message:'test:tool'});
  await eventually(()=>h.records.some(r=>r.type==='tool_call'));
  const call=h.records.find(r=>r.type==='tool_call');
  await h.sidecar.accept({id:'result',type:'tool_result',requestId:'p1',callId:call.callId,isError:true,
    result:{content:[{type:'text',text:`Host rejected ${h.config.apiKey}`}],details:{nested:{echo:h.config.apiKey}}}});
  await eventually(()=>h.records.some(r=>r.event?.type==='agent_settled'));
  const nextToolResult=requests[1].context.messages.find(m=>m.role==='toolResult');
  assert.equal(nextToolResult.isError,true);
  assert(!JSON.stringify(nextToolResult).includes(h.config.apiKey));
  assert(h.records.some(r=>r.event?.type==='tool_execution_end'&&r.event.isError===true));
  const path=h.records[0].data.sessionFile;
  const persisted=await readFile(path,'utf8');
  assert(!persisted.includes(h.config.apiKey));
  const stored=persisted.trim().split('\n').map(JSON.parse).find(e=>e.message?.role==='toolResult').message;
  assert.equal(stored.isError,true);
  assert.equal(stored.content[0].text,'Host rejected [REDACTED]');
  assert.equal(stored.details.nested.echo,'[REDACTED]');
  await h.sidecar.accept({id:'resume',type:'resume',session:{mode:'open',path}});
  assert.equal(h.records.at(-1).success,true);
  await h.sidecar.accept({id:'p2',type:'prompt',message:'test:resume'});
  await eventually(()=>h.records.some(r=>r.requestId==='p2'&&r.event?.type==='agent_settled'));
  assert(!JSON.stringify(requests.at(-1).context).includes(h.config.apiKey));
  assert.equal(requests.at(-1).context.messages.find(m=>m.role==='toolResult').isError,true);
  await h.sidecar.close();
});
for (const scenario of ['secret-error','secret-text']) {
  test(`real SDK redacts provider ${scenario} in native session history`,async()=>{
    const h=await harness();
    await h.sidecar.accept({id:'p1',type:'prompt',message:`test:${scenario}`});
    await eventually(()=>h.records.some(r=>r.event?.type==='agent_settled'));
    const persisted=await readFile(h.records[0].data.sessionFile,'utf8');
    assert(!persisted.includes(h.config.apiKey));
    assert(persisted.includes('Fake provider echoed [REDACTED]'));
    assert(!JSON.stringify(h.records).includes(h.config.apiKey));
    await h.sidecar.close();
  });
}
test('aborting before the first prompt leaves no session file or provider request',async()=>{
  const requests=[];const h=await harness({onRequest:r=>requests.push(r)});
  const path=h.records[0].data.sessionFile;
  await h.sidecar.accept({id:'cancel',type:'abort'});
  assert(h.records.some(r=>r.id==='cancel'&&r.success));
  assert.equal(requests.length,0);
  await assert.rejects(access(path),{code:'ENOENT'});
  assert.deepEqual(await readdir(h.config.session.dir),[]);
  await h.sidecar.close();
});
test('content protection retains native compaction tree and does not mutate caller messages',async()=>{
  const {SessionManager}=await import('@earendil-works/pi-coding-agent');
  const secret='unit-test-private-key';
  const manager=protectSessionContent(SessionManager.inMemory(),secret);
  const message={role:'user',content:[{type:'text',text:`Input ${secret}`}],timestamp:1};
  const messageId=manager.appendMessage(message);
  const compactId=manager.appendCompaction(`Summary ${secret}`,messageId,100,{echo:secret});
  const compact=manager.getEntry(compactId);
  assert.equal(compact.parentId,messageId);
  assert.equal(compact.firstKeptEntryId,messageId);
  assert.equal(compact.summary,'Summary [REDACTED]');
  assert.equal(compact.details.echo,'[REDACTED]');
  assert.equal(message.content[0].text,`Input ${secret}`);
  manager.appendContextEdit(messageId,{content:`Edited ${secret}`});
  manager.appendCustomEntry('audit',{[secret]:{echo:secret}});
  manager.appendCustomMessageEntry('custom',`Custom ${secret}`,false,{echo:secret});
  manager.appendSessionInfo(`Session ${secret}`);
  manager.appendLabelChange(messageId,`Label ${secret}`);
  manager.branchWithSummary(messageId,`Branch ${secret}`,{echo:secret});
  assert(!JSON.stringify(manager.getEntries()).includes(secret));
});
test('real SDK retry emits agent_end before eventual agent_settled',async()=>{
  const h=await harness();await h.sidecar.accept({id:'p1',type:'prompt',message:'test:retry'});
  await eventually(()=>h.records.some(r=>r.event?.type==='agent_settled'));
  const kinds=h.records.filter(r=>r.type==='event').map(r=>r.event.type);
  assert(kinds.includes('auto_retry_start'));assert.equal(kinds.at(-1),'agent_settled');
  assert(kinds.filter(k=>k==='agent_end').length>=2);
  await h.sidecar.close();
});
test('real SDK final provider failure settles with an authoritative error message',async()=>{
  const h=await harness();await h.sidecar.accept({id:'p1',type:'prompt',message:'test:error'});
  await eventually(()=>h.records.some(r=>r.event?.type==='agent_settled'));
  assert(h.records.some(r=>r.event?.message?.stopReason==='error'));
  await h.sidecar.close();
});
test('real SDK abort resolves pending tool and becomes idle',async()=>{
  const h=await harness();await h.sidecar.accept({id:'p1',type:'prompt',message:'test:abort'});
  await eventually(()=>h.records.some(r=>r.type==='tool_call'));
  await h.sidecar.accept({id:'a1',type:'abort'});
  assert(h.records.some(r=>r.id==='a1'&&r.success));assert.equal(h.sidecar.pendingTools.size,0);assert.equal(h.sidecar.active,null);
  await h.sidecar.close();
});
