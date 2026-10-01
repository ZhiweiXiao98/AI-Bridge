import assert from 'node:assert/strict';
import test from 'node:test';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {init} from './fixtures.mjs';

test('guarded real-SDK subprocess keeps native session errors sanitized', {timeout:10000}, async(t)=>{
  const root=await mkdtemp(join(tmpdir(),'pi-stdio-contract-'));
  const config=init(root);
  const records=[];
  const child=spawn(process.execPath,[fileURLToPath(new URL('./fixture-sidecar.mjs',import.meta.url))],
    {cwd:root,env:{PATH:process.env.PATH},stdio:['pipe','pipe','pipe']});
  t.after(async()=>{if(child.exitCode===null) child.kill();await rm(root,{recursive:true,force:true});});
  let buffer='';
  const send=(record)=>child.stdin.write(JSON.stringify(record)+'\n');
  child.stdout.setEncoding('utf8');
  child.stdout.on('data',(chunk)=>{
    buffer+=chunk;
    let end;
    while((end=buffer.indexOf('\n'))!==-1) {
      const line=buffer.slice(0,end);buffer=buffer.slice(end+1);
      if(!line) continue;
      const record=JSON.parse(line);records.push(record);
      if(record.id===config.id) send({id:'prompt',type:'prompt',message:'test:secret-error'});
      if(record.event?.type==='agent_settled') send({id:'close',type:'close'});
    }
  });
  // Consume diagnostics without displaying content that could contain a fixture secret.
  child.stderr.resume();
  const ended=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',(code,signal)=>resolve({code,signal}));});
  send(config);
  const outcome=await ended;
  assert.deepEqual(outcome,{code:0,signal:null});
  assert(records.some(r=>r.id==='close'&&r.success));
  assert(!JSON.stringify(records).includes(config.apiKey));
  const path=records.find(r=>r.id===config.id).data.sessionFile;
  const persisted=await readFile(path,'utf8');
  assert(!persisted.includes(config.apiKey));
  assert(persisted.includes('Fake provider echoed [REDACTED]'));
});
