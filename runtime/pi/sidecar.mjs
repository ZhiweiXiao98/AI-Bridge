#!/usr/bin/env node
import { pathToFileURL } from 'node:url';
import { createPiSession } from './pi-session.mjs';
import { JsonlDecoder, MAX_LINE_BYTES, MAX_PENDING_TOOLS, PI_VERSION, PROTOCOL_VERSION,
  ProtocolError, text, validateCommand, validateInit, validateSession, validateToolResult, wireEvent } from './protocol.mjs';

/** One sidecar owns one conversation; only Python can execute registered tools. */
export class PiSidecar {
  constructor({send, sessionFactory = createPiSession, onClose = () => {}}) {
    this.send = send; this.sessionFactory = sessionFactory; this.onClose = onClose;
    this.session = null; this.config = null; this.active = null;
    this.pendingTools = new Map(); this.ids = new Set(); this.secrets = new Set();
    this.changing = false; this.closing = false; this.faulted = false;
  }
  redact(value) {
    if (typeof value === 'string') {
      for (const secret of this.secrets) value = value.split(secret).join('[REDACTED]');
      return value;
    }
    if (Array.isArray(value)) return value.map((entry) => this.redact(entry));
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
      .filter(([key]) => !['apiKey', 'authorization', 'Authorization', 'accessToken', 'refreshToken'].includes(key))
      .map(([key, entry]) => [key, this.redact(entry)]));
    return value;
  }
  emit(record) { this.send(this.redact(record)); }
  errorText(error) {
    return error instanceof ProtocolError ? error.message : 'Pi operation failed; check the configured model and runtime';
  }
  response(command, success, data, error) {
    this.emit({id:command.id, type:'response', command:command.type, success,
      ...(data !== undefined ? {data} : {}), ...(error ? {error} : {})});
  }
  requireSession() {
    if (!this.session || this.changing) throw new ProtocolError('Session is not initialized or is being changed');
    if (this.faulted) throw new ProtocolError('Session failed; resume it before prompting again');
  }
  snapshot() { return {...this.session.snapshot(), piVersion:PI_VERSION, protocolVersion:PROTOCOL_VERSION}; }
  async accept(raw) {
    let command;
    try {
      command = validateCommand(raw);
      if (this.ids.has(command.id)) throw new ProtocolError('Duplicate command id');
      this.ids.add(command.id);
      // Bounded correlation history; callers must always generate unique IDs.
      if (this.ids.size > 4096) this.ids.delete(this.ids.values().next().value);
      if (this.closing) throw new ProtocolError('Sidecar is closing');
      switch (command.type) {
        case 'init': return await this.init(command);
        case 'prompt': return this.prompt(command);
        case 'tool_result': return this.toolResult(command);
        case 'abort': return await this.abort(command);
        case 'resume': return await this.resume(command);
        case 'close': return await this.close(command);
      }
    } catch (error) {
      this.response(command ?? {id:typeof raw?.id === 'string' ? raw.id : undefined, type:'parse'}, false, undefined, this.errorText(error));
    }
  }
  async makeSession(config) {
    return await this.sessionFactory(config, (event) => this.sessionEvent(event),
      (callId, name, args, signal) => this.callTool(callId, name, args, signal));
  }
  async init(command) {
    if (this.session || this.changing) throw new ProtocolError('Session is already initialized');
    const config = validateInit(command);
    this.secrets.add(config.apiKey);
    this.changing = true;
    try {
      this.config = config;
      const session = await this.makeSession(config);
      if (this.closing) { session.dispose(); return; }
      this.session = session;
      this.response(command, true, this.snapshot());
    } finally { this.changing = false; }
  }
  prompt(command) {
    this.requireSession();
    if (this.active) throw new ProtocolError('A prompt is already active');
    const message = text(command.message, 'message', MAX_LINE_BYTES, true);
    const run = {id:command.id, accepted:false, settled:false, disposition:null};
    this.active = run;
    // Do not await: stdin must keep serving tool_result and abort during this run.
    Promise.resolve().then(() => this.session.prompt(message, (disposition) => {
      if (run.accepted) return;
      run.accepted = true; run.disposition = disposition;
      this.response(command, true, {disposition});
      if (disposition === 'handled' && this.active === run) this.active = null;
    })).then(() => {
      if (!run.accepted) throw new Error('SDK omitted prompt acceptance');
      if (run.disposition !== 'handled' && !run.settled) throw new Error('SDK omitted agent_settled');
    }).catch((error) => {
      if (!run.accepted) this.response(command, false, undefined, this.errorText(error));
      else if (!run.settled) {
        this.faulted = true;
        this.emit({type:'event', requestId:run.id, event:{type:'run_error', error:this.errorText(error)}});
      }
      if (this.active === run) this.active = null;
      this.cancelTools('run failed');
    });
  }
  sessionEvent(event) {
    const run = this.active;
    if (!run) return;
    if (event.type === 'agent_settled') {
      run.settled = true;
      this.active = null;
    }
    this.emit({type:'event', requestId:run.id, event:wireEvent(event)});
  }
  callTool(callId, name, args, signal) {
    const run = this.active;
    if (!run || this.closing || signal?.aborted) return Promise.reject(new Error('Tool call cancelled'));
    if (this.pendingTools.size >= MAX_PENDING_TOOLS || this.pendingTools.has(callId)) return Promise.reject(new Error('Tool call limit or duplicate id'));
    return new Promise((resolve, reject) => {
      const cancel = (reason) => {
        const pending = this.pendingTools.get(callId);
        if (!pending) return;
        this.pendingTools.delete(callId); pending.cleanup();
        this.emit({type:'tool_cancel', requestId:run.id, callId, reason});
        reject(new Error(`Tool call ${reason}`));
      };
      const onAbort = () => cancel('cancelled');
      const timer = setTimeout(() => cancel('timed out'), this.config.toolTimeoutMs);
      const cleanup = () => { clearTimeout(timer); signal?.removeEventListener('abort', onAbort); };
      this.pendingTools.set(callId, {requestId:run.id, resolve, reject, cleanup, cancel});
      signal?.addEventListener('abort', onAbort, {once:true});
      if (signal?.aborted) return cancel('cancelled');
      this.emit({type:'tool_call', requestId:run.id, callId, name, arguments:args});
    });
  }
  toolResult(command) {
    const result = validateToolResult(command);
    const pending = this.pendingTools.get(command.callId);
    if (!pending || pending.requestId !== command.requestId || this.active?.id !== command.requestId)
      throw new ProtocolError('Unknown, cancelled, or stale tool call');
    this.pendingTools.delete(command.callId); pending.cleanup();
    // A failed tool result is data for the model, never a successful host action.
    pending.resolve(result);
    this.response(command, true);
  }
  cancelTools(reason) { for (const pending of [...this.pendingTools.values()]) pending.cancel(reason); }
  async abort(command) {
    if (!this.session || this.changing) throw new ProtocolError('Session is not initialized or is being changed');
    this.cancelTools('cancelled');
    await this.session.abort();
    this.response(command, true);
  }
  async resume(command) {
    if (!this.session || this.changing || this.active || this.pendingTools.size) throw new ProtocolError('Resume requires an idle initialized session');
    const spec = validateSession(command.session);
    this.changing = true;
    try {
      const nextConfig = {...this.config, session:spec};
      const next = await this.makeSession(nextConfig);
      this.session.dispose(); this.session = next; this.config = nextConfig;
      this.faulted = false;
      this.response(command, true, this.snapshot());
    } finally { this.changing = false; }
  }
  async close(command) {
    if (this.closing) return;
    this.closing = true;
    this.cancelTools('closed');
    if (this.session) { await this.session.abort(); this.session.dispose(); this.session = null; }
    if (command) this.response(command, true);
    this.config = null; this.secrets.clear();
    this.onClose();
  }
}

/** Erase ambient provider/config values before importing the SDK. Parent also strips NODE_OPTIONS. */
export function isolateEnvironment(env) {
  const keep = new Set(['PATH', 'SystemRoot', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL']);
  for (const key of Object.keys(env)) if (!keep.has(key)) delete env[key];
  env.PI_OFFLINE = '1';
}
export async function main({sessionFactory = createPiSession} = {}) {
  isolateEnvironment(process.env);
  // Never forward third-party diagnostics containing prompts or credentials.
  for (const name of ['log', 'info', 'warn', 'error', 'debug']) console[name] = () => {};
  let queuedBytes = 0;
  let failed = false;
  let controller;
  const write = (record) => {
    if (failed) return;
    const line = Buffer.from(JSON.stringify(record) + '\n');
    if (line.length > MAX_LINE_BYTES || queuedBytes + line.length > MAX_LINE_BYTES * 2) {
      failed = true;
      process.stdout.write(JSON.stringify({type:'fatal', error:'Sidecar output exceeded its bounded buffer'}) + '\n');
      void controller.close();
      return;
    }
    queuedBytes += line.length;
    process.stdout.write(line, () => { queuedBytes -= line.length; });
  };
  controller = new PiSidecar({send:write, sessionFactory, onClose:() => { process.stdin.pause(); process.stdout.end(); }});
  const decoder = new JsonlDecoder((record) => { void controller.accept(record); }, (error, fatal) => {
    write({type:'response', command:'parse', success:false, error:error.message});
    if (fatal) void controller.close();
  });
  process.stdin.on('data', (chunk) => decoder.push(chunk));
  process.stdin.on('end', () => { decoder.end(); void controller.close(); });
  process.stdin.on('error', () => { void controller.close(); });
  process.stdout.on('error', () => { void controller.close(); });
  for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => { void controller.close(); });
  process.on('uncaughtException', () => { write({type:'fatal', error:'Sidecar failed'}); void controller.close(); });
  process.on('unhandledRejection', () => { write({type:'fatal', error:'Sidecar failed'}); void controller.close(); });
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
