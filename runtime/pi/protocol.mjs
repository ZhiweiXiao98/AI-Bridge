/** Data Bridge's JSONL boundary. This is NOT Pi's CLI RPC protocol. */
import { isAbsolute } from 'node:path';

export const PROTOCOL_VERSION = 1;
export const PI_VERSION = '0.99.1';
export const MAX_LINE_BYTES = 4 * 1024 * 1024;
export const MAX_PENDING_TOOLS = 64;
const namePattern = /^[A-Za-z_][A-Za-z0-9_.-]{0,127}$/;
const apis = new Set(['openai-completions', 'openai-responses', 'anthropic-messages', 'google-generative-ai']);
const levels = new Set(['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']);

export class ProtocolError extends Error {}
export function object(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new ProtocolError(`${label} must be an object`);
  return value;
}
export function text(value, label, max = 1024 * 1024, empty = false) {
  if (typeof value !== 'string' || (!empty && !value.length) || value.length > max) throw new ProtocolError(`Invalid ${label}`);
  return value;
}
function integer(value, fallback, min, max, label) {
  const result = value ?? fallback;
  if (!Number.isSafeInteger(result) || result < min || result > max) throw new ProtocolError(`Invalid ${label}`);
  return result;
}
function absolute(value, label) {
  text(value, label, 4096);
  if (!isAbsolute(value) || value.includes('\0')) throw new ProtocolError(`${label} must be an absolute path`);
  return value;
}
export function validateSession(value) {
  object(value, 'session');
  if (value.mode === 'open') return {mode:'open', path:absolute(value.path, 'session.path')};
  if (value.mode !== 'create') throw new ProtocolError('session.mode must be create or open');
  const result = {mode:'create', dir:absolute(value.dir, 'session.dir')};
  if (value.id !== undefined) {
    if (typeof value.id !== 'string' || !/^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$/.test(value.id)) throw new ProtocolError('Invalid session.id');
    result.id = value.id;
  }
  return result;
}
export function validateInit(c) {
  const provider = text(c.provider, 'provider', 128);
  if (!namePattern.test(provider)) throw new ProtocolError('Invalid provider');
  const model = text(c.model, 'model', 256);
  const api = c.api ?? 'openai-completions';
  if (!apis.has(api)) throw new ProtocolError('Unsupported provider API');
  let url;
  try { url = new URL(c.baseUrl); } catch { throw new ProtocolError('Invalid baseUrl'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new ProtocolError('baseUrl must be an HTTP(S) endpoint without credentials, query, or fragment');
  const apiKey = text(c.apiKey, 'apiKey', 16384);
  if (!Array.isArray(c.tools) || c.tools.length > 128) throw new ProtocolError('tools must be an array of at most 128 entries');
  const names = new Set();
  const tools = c.tools.map((raw) => {
    object(raw, 'tool');
    const name = text(raw.name, 'tool.name', 128);
    if (!namePattern.test(name) || names.has(name)) throw new ProtocolError('Invalid or duplicate tool name');
    names.add(name);
    const parameters = object(raw.parameters, 'tool.parameters');
    if (parameters.type !== 'object') throw new ProtocolError('Tool parameters must have object type');
    return {name, description:text(raw.description, 'tool.description', 32768, true), parameters:structuredClone(parameters)};
  });
  const thinkingLevel = c.thinkingLevel ?? 'off';
  if (!levels.has(thinkingLevel)) throw new ProtocolError('Invalid thinkingLevel');
  const contextWindow = integer(c.contextWindow, 128000, 4096, 10000000, 'contextWindow');
  const maxTokens = integer(c.maxTokens, Math.min(8192, contextWindow / 2), 1, contextWindow, 'maxTokens');
  return {provider, model, api, baseUrl:url.toString(), apiKey, tools,
    cwd:absolute(c.cwd, 'cwd'), agentDir:absolute(c.agentDir, 'agentDir'),
    systemPrompt:text(c.systemPrompt, 'systemPrompt', 1024 * 1024, true),
    session:validateSession(c.session), contextWindow, maxTokens,
    reasoning:c.reasoning === true, thinkingLevel,
    toolTimeoutMs:integer(c.toolTimeoutMs, 120000, 1000, 300000, 'toolTimeoutMs')};
}
export function validateCommand(value) {
  object(value, 'command');
  text(value.id, 'command.id', 128);
  if (!['init', 'prompt', 'abort', 'resume', 'close', 'tool_result'].includes(value.type)) throw new ProtocolError('Unknown command');
  return value;
}
export function validateToolResult(c) {
  text(c.callId, 'callId', 1024);
  text(c.requestId, 'requestId', 128);
  const raw = object(c.result, 'result');
  if (!Array.isArray(raw.content) || raw.content.length > 256) throw new ProtocolError('Invalid result.content');
  const content = raw.content.map((block) => {
    object(block, 'content block');
    if (block.type === 'text') return {type:'text', text:text(block.text, 'result text', MAX_LINE_BYTES, true)};
    if (block.type === 'image') {
      if (!['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(block.mimeType)) throw new ProtocolError('Unsupported result image');
      return {type:'image', data:text(block.data, 'image data', MAX_LINE_BYTES), mimeType:block.mimeType};
    }
    throw new ProtocolError('Unsupported result content type');
  });
  return {content, details:raw.details ?? null, ...(c.isError === true ? {isError:true} : {})};
}

/** LF only: U+2028/U+2029 inside a JSON string must remain intact. */
export class JsonlDecoder {
  constructor(onRecord, onError, maxBytes = MAX_LINE_BYTES) { this.pending = Buffer.alloc(0); this.onRecord = onRecord; this.onError = onError; this.maxBytes = maxBytes; this.failed = false; }
  push(chunk) {
    if (this.failed) return;
    this.pending = Buffer.concat([this.pending, Buffer.from(chunk)]);
    let end;
    while ((end = this.pending.indexOf(10)) !== -1) {
      const line = this.pending.subarray(0, end);
      this.pending = this.pending.subarray(end + 1);
      if (line.length > this.maxBytes) return this.fail('JSONL record exceeds the size limit');
      if (!line.length) continue;
      try { this.onRecord(JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(line))); }
      catch { this.onError(new ProtocolError('Invalid JSONL record')); }
    }
    if (this.pending.length > this.maxBytes) this.fail('JSONL record exceeds the size limit');
  }
  fail(message) { this.failed = true; this.pending = Buffer.alloc(0); this.onError(new ProtocolError(message), true); }
  end() { if (this.pending.length && !this.failed) this.fail('Truncated JSONL record at EOF'); }
}

/** SDK events contain cumulative snapshots. Match Pi 0.99.1 JSON delta framing. */
export function wireEvent(event) {
  if (event.type !== 'message_update') return event;
  const {partial, ...update} = event.assistantMessageEvent;
  if (update.type === 'toolcall_start' && partial) {
    const call = partial.content[update.contentIndex];
    if (call?.type === 'toolCall') { update.id = call.id; update.toolName = call.name; }
  }
  return {type:'message_update', usage:event.message?.usage, assistantMessageEvent:update};
}
