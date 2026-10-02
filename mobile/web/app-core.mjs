export const DEFAULT_PORT = 8765;
export const DEFAULT_SELECTOR = "div.aa-chat-input textarea";

export function normalizeHost(input) {
  const raw = String(input || "").trim();
  if (!raw) return "";
  return raw.replace(/^https?:\/\//i, "").replace(/^wss?:\/\//i, "").replace(/\/+$/, "");
}

export function normalizePort(input) {
  const value = Number.parseInt(String(input || "").trim(), 10);
  return Number.isInteger(value) && value > 0 && value < 65536 ? value : DEFAULT_PORT;
}

export function baseHttpUrl(host, port) {
  const cleanHost = normalizeHost(host);
  const cleanPort = normalizePort(port);
  return `http://${cleanHost}:${cleanPort}`;
}

export function websocketUrl(host, port, token, deviceId) {
  const cleanHost = normalizeHost(host);
  const cleanPort = normalizePort(port);
  return `ws://${cleanHost}:${cleanPort}/ws/${encodeURIComponent(token || "")}/${encodeURIComponent(deviceId || "")}`;
}

export function createDeviceId(seed = "") {
  const source = seed || `${Date.now()}-${Math.random()}`;
  let hash = 2166136261;
  for (let i = 0; i < source.length; i += 1) {
    hash ^= source.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return `Mobile_${(hash >>> 0).toString(16).padStart(8, "0").slice(0, 8)}`;
}

export function parseSegment(segment = {}) {
  const type = String(segment.type || "text");
  if (type === "code") {
    return {
      type: "code",
      content: String(segment.code ?? segment.content ?? ""),
      language: String(segment.language || "text"),
      blockKey: String(segment.block_key || ""),
    };
  }
  if (type === "image") {
    return { type: "image", content: String(segment.content || "") };
  }
  if (type === "tool_result") {
    return {
      type: "tool_result",
      toolName: String(segment.tool_name || ""),
      content: String(segment.content || ""),
      success: segment.success !== false,
    };
  }
  return { type: "text", content: String(segment.content || "") };
}

export function parseMessages(rawList) {
  if (!Array.isArray(rawList)) return [];
  return rawList.map((raw, index) => ({
    id: String(raw.id || `msg_${index}`),
    role: String(raw.role || "AI"),
    source: String(raw.source || "browser"),
    rawLen: Number(raw.raw_len || 0),
    segments: Array.isArray(raw.segments) ? raw.segments.map(parseSegment) : [],
  }));
}

export function rpcMessage(method, args = [], kwargs = {}) {
  return JSON.stringify({
    action: "rpc_call",
    method,
    args,
    kwargs,
  });
}

export function sendTextRpc(mode, text, selector = DEFAULT_SELECTOR) {
  if (mode === "api") {
    return rpcMessage("api_send", [], { text });
  }
  return rpcMessage("send_text", [selector, text], {});
}

export function summarizeMessage(message) {
  const text = (message?.segments || [])
    .filter((segment) => segment.type === "text")
    .map((segment) => segment.content)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return message?.role || "消息";
  return text.length > 80 ? `${text.slice(0, 77).trimEnd()}...` : text;
}
