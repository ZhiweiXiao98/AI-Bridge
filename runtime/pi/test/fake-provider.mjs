/** Deterministic in-process provider; no network, credentials, or paid requests. */
export function fakeProvider({onRequest = () => {}} = {}) {
  let requestCount = 0;
  return (model, context, options) => {
    onRequest({model, context, options});
    requestCount++;
    const users = context.messages.filter((m) => m.role === 'user');
    const prompt = users.at(-1)?.content;
    const text = typeof prompt === 'string' ? prompt : (prompt ?? []).filter(b=>b.type==='text').map(b=>b.text).join('');
    const last = context.messages.at(-1);
    const message = {role:'assistant', api:model.api, provider:model.provider, model:model.id,
      content:[], stopReason:'stop', timestamp:Date.now(),
      usage:{input:20,output:10,cacheRead:0,cacheWrite:0,totalTokens:30,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}};
    if (text.includes('test:secret-error')) {
      message.stopReason='error'; message.errorMessage=`Fake provider echoed ${options.apiKey}`;
    } else if (text.includes('test:secret-text')) {
      message.content=[{type:'text',text:`Fake provider echoed ${options.apiKey}`}];
    } else if (text.includes('test:error') || (text.includes('test:retry') && requestCount === 1)) {
      message.stopReason='error'; message.errorMessage=text.includes('test:retry')?'529 overloaded':'Fake provider rejected the request';
    } else if (last?.role !== 'toolResult' && (text.includes('test:tool') || text.includes('test:abort') || text.includes('test:host-builtin'))) {
      message.stopReason='toolUse';
      message.content=[{type:'toolCall',id:`fake-call-${requestCount}`,name:text.includes('host-builtin')?'bash':'bridge_echo',arguments:{text:'hello from model'}}];
    } else {
      const output=last?.role==='toolResult' ? `Tool result: ${last.content.filter(b=>b.type==='text').map(b=>b.text).join('')}` : `Fake answer (${users.length} user messages)`;
      message.content=[{type:'text',text:output}];
    }
    return {
      async *[Symbol.asyncIterator]() {
        if (message.stopReason === 'error') { yield {type:'error',reason:'error',error:message}; return; }
        const partial={...message,content:[]};
        yield {type:'start',partial};
        for (const [contentIndex, block] of message.content.entries()) {
          partial.content.push(block);
          if (block.type === 'toolCall') {
            yield {type:'toolcall_start',contentIndex,partial};
            yield {type:'toolcall_delta',contentIndex,delta:JSON.stringify(block.arguments),partial};
            yield {type:'toolcall_end',contentIndex,toolCall:block,partial};
          } else {
            yield {type:'text_start',contentIndex,partial};
            yield {type:'text_delta',contentIndex,delta:block.text,partial};
            yield {type:'text_end',contentIndex,content:block.text,partial};
          }
        }
        yield {type:'done',reason:message.stopReason,message};
      },
      async result() { return message; },
    };
  };
}
