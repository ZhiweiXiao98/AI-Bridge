export type SessionSpec = {mode:'create'; dir:string; id?:string} | {mode:'open'; path:string};
export type ToolSpec = {name:string; description:string; parameters:Record<string, unknown>};
export type Content = {type:'text'; text:string} | {type:'image'; data:string; mimeType:string};
export type Command =
  | {id:string; type:'init'; provider:string; model:string; api?:'openai-completions'|'openai-responses'|'anthropic-messages'|'google-generative-ai'; baseUrl:string; apiKey:string; cwd:string; agentDir:string; systemPrompt:string; tools:ToolSpec[]; session:SessionSpec; contextWindow?:number; maxTokens?:number; reasoning?:boolean; thinkingLevel?:'off'|'minimal'|'low'|'medium'|'high'|'xhigh'|'max'; toolTimeoutMs?:number}
  | {id:string; type:'prompt'; message:string}
  | {id:string; type:'abort'|'close'}
  | {id:string; type:'resume'; session:SessionSpec}
  | {id:string; type:'tool_result'; requestId:string; callId:string; result:{content:Content[]; details?:unknown}; isError?:boolean};
export type SessionSnapshot = {sessionId:string; sessionFile?:string; activeTools:string[]; piVersion:'0.99.1'; protocolVersion:1};
export type WireRecord =
  | {id?:string; type:'response'; command:Command['type']|'parse'; success:boolean; data?:SessionSnapshot|{disposition:'started'|'handled'|'queued'}; error?:string}
  | {type:'event'; requestId:string; event:Record<string, unknown> & {type:string}}
  | {type:'tool_call'; requestId:string; callId:string; name:string; arguments:Record<string, unknown>}
  | {type:'tool_cancel'; requestId:string; callId:string; reason:string}
  | {type:'fatal'; error:string};
