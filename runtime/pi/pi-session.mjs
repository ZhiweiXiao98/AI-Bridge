/** The ONLY SDK boundary. Never discovers host resources or executes host tools. */
import { existsSync, statSync } from 'node:fs';
import { PI_VERSION, ProtocolError } from './protocol.mjs';

export function emptyResources(sdk, systemPrompt) {
  const runtime = sdk.createExtensionRuntime();
  return {
    getExtensions:() => ({extensions:[], errors:[], runtime}),
    getSkills:() => ({skills:[], diagnostics:[]}),
    getPrompts:() => ({prompts:[], diagnostics:[]}),
    getThemes:() => ({themes:[], diagnostics:[]}),
    getAgentsFiles:() => ({agentsFiles:[]}),
    getSystemPrompt:() => systemPrompt,
    getSystemPromptSource:() => undefined,
    getAppendSystemPrompt:() => [], getAppendSystemPromptSources:() => [],
    extendResources:() => {}, reload:async () => {},
  };
}
function emptyCredentialStore() {
  return {read:async () => undefined, list:async () => [],
    modify:async () => { throw new Error('Credential persistence is disabled'); },
    delete:async () => { throw new Error('Credential persistence is disabled'); }};
}

/** Clone JSON-shaped content so neither caller values nor SDK event objects are mutated. */
export function redactLiteral(value, secret) {
  if (typeof value === 'string') return secret ? value.split(secret).join('[REDACTED]') : value;
  if (Array.isArray(value)) return value.map((entry) => redactLiteral(entry, secret));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .map(([key, entry]) => [redactLiteral(key, secret), redactLiteral(entry, secret)]));
  return value;
}

/**
 * Pin-scoped adaptation of SessionManager's public append API, before native entries exist.
 * Pi still owns entry IDs, parent links, compaction, serialization, and lazy file creation.
 * Do not replace _persist(), rewrite JSONL, or mutate SDK message/event objects in a listener.
 * This protects newly appended content; it does not rewrite pre-existing session history.
 */
export function protectSessionContent(manager, secret) {
  const contentArguments = {
    appendMessage:[0], appendCompaction:[0, 3], appendCustomEntry:[0, 1],
    appendCustomMessageEntry:[0, 1, 3], appendContextEdit:[1], appendUsage:[4],
    appendSessionInfo:[0], appendLabelChange:[1], branchWithSummary:[1, 2],
  };
  for (const [name, positions] of Object.entries(contentArguments)) {
    const append = manager[name];
    if (typeof append !== 'function') throw new ProtocolError('Pinned Pi session append API is unavailable');
    manager[name] = function (...args) {
      for (const position of positions) {
        if (position < args.length) args[position] = redactLiteral(args[position], secret);
      }
      return append.apply(this, args);
    };
  }
  return manager;
}
export async function createPiSession(config, onEvent, callTool, options = {}) {
  const sdk = options.sdk ?? await import('@earendil-works/pi-coding-agent');
  if (sdk.VERSION !== PI_VERSION) throw new ProtocolError('Installed Pi SDK version does not match the pinned version');
  const modelRuntime = await sdk.ModelRuntime.create({
    credentials:emptyCredentialStore(), modelsPath:null,
    allowModelNetwork:false, refreshOnCreate:false,
  });
  const xiaomi = config.provider === 'xiaomi';
  if (xiaomi && config.api !== 'openai-completions') throw new ProtocolError('Xiaomi requires openai-completions');
  // Capture Pi's pinned native transport before replacing its catalog with this profile.
  const xiaomiTransport = xiaomi ? modelRuntime.getProvider('xiaomi') : undefined;
  if (xiaomi && !xiaomiTransport) throw new ProtocolError('Pinned Xiaomi provider is unavailable');
  const definition = {
    id:config.model, name:config.model, reasoning:xiaomi || config.reasoning,
    input:['text'], contextWindow:config.contextWindow, maxTokens:config.maxTokens,
    cost:{input:0, output:0, cacheRead:0, cacheWrite:0},
    // Pi's Xiaomi catalog uses DeepSeek-style thinking and reasoning-content replay.
    // MiMo exposes an on/off switch, so never send generic reasoning_effort values.
    ...(xiaomi ? {compat:{thinkingFormat:'deepseek', requiresReasoningContentOnAssistantMessages:true,
      supportsReasoningEffort:false, supportsStore:false, supportsDeveloperRole:false,
      maxTokensField:'max_completion_tokens'}} : {}),
  };
  const streamSimple = options.streamSimple ?? (xiaomi ? (model, context, requestOptions) =>
    xiaomiTransport.streamSimple(model, context, {...requestOptions,
      // Runtime headers are literal. Provider-config headers would interpolate $ENV/!commands.
      headers:{...requestOptions?.headers, 'api-key':requestOptions.apiKey},
      ...(options.fetch ? {fetch:options.fetch} : {}),
    }) : undefined);
  modelRuntime.registerProvider(config.provider, {
    baseUrl:config.baseUrl, api:config.api, models:[definition],
    ...(streamSimple ? {streamSimple} : {}),
  });
  // A runtime overlay preserves the literal value (no $ENV/!command interpolation).
  await modelRuntime.setRuntimeApiKey(config.provider, config.apiKey);
  const model = modelRuntime.getModel(config.provider, config.model);
  if (!model) throw new ProtocolError('Configured model is unavailable');
  const spec = config.session;
  if (spec.mode === 'open' && (!existsSync(spec.path) || !statSync(spec.path).isFile())) throw new ProtocolError('Session file does not exist');
  const sessionManager = protectSessionContent(spec.mode === 'open'
    ? sdk.SessionManager.open(spec.path, undefined, config.cwd)
    : sdk.SessionManager.create(config.cwd, spec.dir, spec.id ? {id:spec.id} : undefined), config.apiKey);
  const settingsManager = sdk.SettingsManager.inMemory({
    defaultProjectTrust:'never', cacheWarming:'off',
    compaction:{enabled:true},
    retry:{enabled:true, maxRetries:2, baseDelayMs:500, maxAgentDelayMs:5000,
      provider:{timeoutMs:120000, maxRetries:0, maxRetryDelayMs:5000}},
  });
  const customTools = config.tools.map((tool) => ({...tool, label:tool.name,
    executionMode:'sequential',
    execute:(callId, args, signal) => callTool(callId, tool.name, args, signal),
  }));
  const {session} = await sdk.createAgentSession({
    cwd:config.cwd, agentDir:config.agentDir, model, modelRuntime,
    thinkingLevel:config.thinkingLevel, settingsManager, sessionManager,
    resourceLoader:emptyResources(sdk, config.systemPrompt),
    tools:customTools.map((tool) => tool.name), customTools,
  });
  const actual = session.getActiveToolNames().slice().sort();
  const expected = config.tools.map((tool) => tool.name).sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    session.dispose(); throw new ProtocolError('Pi tool allowlist could not be enforced');
  }
  const unsubscribe = session.subscribe(onEvent);
  return {
    prompt:(message, preflightResult) => session.prompt(message, {expandPromptTemplates:false, source:'rpc', preflightResult}),
    abort:async () => { session.clearQueue(); await session.abort(); },
    dispose:() => { unsubscribe(); session.dispose(); },
    snapshot:() => ({sessionId:session.sessionId, sessionFile:session.sessionFile, activeTools:session.getActiveToolNames()}),
  };
}
