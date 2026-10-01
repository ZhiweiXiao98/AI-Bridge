import assert from 'node:assert/strict';
import test from 'node:test';
import {PiSidecar} from '../sidecar.mjs';
import {init} from './fixtures.mjs';
const tick=()=>new Promise(r=>setImmediate(r));
const makeHarness = (promptHandler) => {
  const records=[];
  let emit, call, complete;
  const sidecar=new PiSidecar({send:r=>records.push(r),sessionFactory:async (config,event,tool)=>{
    emit=event; call=tool;
    return {prompt:async (message,accept)=>{accept('started'); await promptHandler?.({message,emit,call,wait:()=>new Promise(r=>complete=r)});},
      abort:async()=>{emit({type:'agent_settled'}); complete?.();}, dispose:()=>{},
      snapshot:()=>({sessionId:'s1',sessionFile:'/tmp/s1.jsonl',activeTools:['bridge_echo']})};
  }});
  return {sidecar,records,get emit(){return emit},get call(){return call},get complete(){return complete}};
};
test('acceptance and low-level agent_end never signal completion', async()=>{
  const h=makeHarness(async ({emit,wait})=>{emit({type:'agent_end',messages:[],willRetry:true});await wait();emit({type:'agent_settled'});});
  await h.sidecar.accept(init());await h.sidecar.accept({id:'p1',type:'prompt',message:'hello'});await tick();
  assert.equal(h.sidecar.active.id,'p1');assert(h.records.some(r=>r.data?.disposition==='started'));
  assert(!h.records.some(r=>r.event?.type==='agent_settled'));
  h.complete();await tick();assert.equal(h.sidecar.active,null);
});
test('tool calls wait for correctly correlated host results',async()=>{
  let result;
  const h=makeHarness(async({emit,call})=>{result=await call('c1','bridge_echo',{text:'hi'});emit({type:'agent_settled'});});
  await h.sidecar.accept(init());await h.sidecar.accept({id:'p1',type:'prompt',message:'hello'});await tick();
  assert.equal(result,undefined);
  await h.sidecar.accept({id:'bad',type:'tool_result',requestId:'old',callId:'c1',result:{content:[]}});
  assert.equal(h.records.at(-1).success,false);assert.equal(result,undefined);
  await h.sidecar.accept({id:'r1',type:'tool_result',requestId:'p1',callId:'c1',result:{content:[{type:'text',text:'host reply'}]}});await tick();
  assert.equal(result.content[0].text,'host reply');assert.equal(h.sidecar.pendingTools.size,0);
});
test('abort rejects tools, drains run, and rejects stale completion',async()=>{
  const h=makeHarness(async({call})=>{await call('c1','bridge_echo',{});});
  await h.sidecar.accept(init());await h.sidecar.accept({id:'p1',type:'prompt',message:'hello'});await tick();
  await h.sidecar.accept({id:'a1',type:'abort'});await tick();
  assert(h.records.some(r=>r.type==='tool_cancel'));assert(h.records.some(r=>r.id==='a1'&&r.success));
  await h.sidecar.accept({id:'stale',type:'tool_result',requestId:'p1',callId:'c1',result:{content:[]}});
  assert.equal(h.records.at(-1).success,false);
});
test('tool wait has a bounded timeout and cleanup',async()=>{
  const h=makeHarness(async({call,emit})=>{await assert.rejects(call('c1','bridge_echo',{}),/timed out/);emit({type:'agent_settled'});});
  await h.sidecar.accept(init());await h.sidecar.accept({id:'p1',type:'prompt',message:'hello'});
  await new Promise(r=>setTimeout(r,1050));assert.equal(h.sidecar.pendingTools.size,0);assert.equal(h.sidecar.active,null);
});
test('concurrent prompts and session switches are rejected',async()=>{
  const h=makeHarness(async({wait,emit})=>{await wait();emit({type:'agent_settled'});});
  await h.sidecar.accept(init());await h.sidecar.accept({id:'p1',type:'prompt',message:'hello'});await tick();
  await h.sidecar.accept({id:'p2',type:'prompt',message:'no'});assert.equal(h.records.at(-1).success,false);
  await h.sidecar.accept({id:'r1',type:'resume',session:{mode:'open',path:'/tmp/other'}});assert.equal(h.records.at(-1).success,false);
  await h.sidecar.accept({id:'close',type:'close'});await tick();assert(h.records.some(r=>r.id==='close'&&r.success));
});
test('events redact runtime keys recursively; arbitrary SDK failures do not expose inputs',async()=>{
  const h=makeHarness(async({emit})=>{emit({type:'message_end',message:{content:[{type:'text',text:'literal-test-key'}],apiKey:'literal-test-key'}});throw Error('literal-test-key');});
  await h.sidecar.accept(init());await h.sidecar.accept({id:'p1',type:'prompt',message:'hello'});await tick();
  assert(!JSON.stringify(h.records).includes('literal-test-key'));assert(h.records.some(r=>r.event?.type==='run_error'));
});
