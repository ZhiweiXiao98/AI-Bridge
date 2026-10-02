import {
  baseHttpUrl,
  createDeviceId,
  parseMessages,
  sendTextRpc,
  summarizeMessage,
  websocketUrl,
} from "./app-core.mjs";

const state = {
  apiBase: "",
  ws: null,
  token: "",
  deviceId: localStorage.getItem("db.mobile.deviceId") || createDeviceId(navigator.userAgent),
  role: "user",
  mode: localStorage.getItem("db.mobile.mode") || "browser",
  messages: [],
  sessions: [],
  logs: [],
  connected: false,
  latencyMs: 0,
};

localStorage.setItem("db.mobile.deviceId", state.deviceId);

const el = {
  loginPanel: document.querySelector("#login-panel"),
  appPanel: document.querySelector("#app-panel"),
  host: document.querySelector("#host"),
  port: document.querySelector("#port"),
  username: document.querySelector("#username"),
  password: document.querySelector("#password"),
  login: document.querySelector("#login"),
  logout: document.querySelector("#logout"),
  status: document.querySelector("#status"),
  appStatus: document.querySelector("#app-status"),
  mode: document.querySelector("#mode"),
  refresh: document.querySelector("#refresh"),
  sessions: document.querySelector("#sessions"),
  messages: document.querySelector("#messages"),
  composer: document.querySelector("#composer"),
  send: document.querySelector("#send"),
  logs: document.querySelector("#logs"),
  openLogs: document.querySelector("#open-logs"),
  closeLogs: document.querySelector("#close-logs"),
  logText: document.querySelector("#log-text"),
  title: document.querySelector("#connection-title"),
};

function setStatus(text, tone = "muted") {
  el.status.textContent = text;
  el.status.dataset.tone = tone;
  if (el.appStatus) {
    el.appStatus.textContent = text;
    el.appStatus.dataset.tone = tone;
  }
}

function rememberLogin() {
  localStorage.setItem("db.mobile.host", el.host.value.trim());
  localStorage.setItem("db.mobile.port", el.port.value.trim());
  localStorage.setItem("db.mobile.username", el.username.value.trim());
}

function restoreLogin() {
  el.host.value = localStorage.getItem("db.mobile.host") || "";
  el.port.value = localStorage.getItem("db.mobile.port") || "8765";
  el.username.value = localStorage.getItem("db.mobile.username") || "admin";
}

async function apiFetch(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`${state.apiBase}${path}`, { ...options, headers });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function login() {
  const host = el.host.value.trim();
  const port = el.port.value.trim() || "8765";
  const username = el.username.value.trim();
  const password = el.password.value;
  if (!host) {
    setStatus("请输入电脑 IP", "danger");
    return;
  }
  setStatus("正在连接电脑...", "muted");
  el.login.disabled = true;
  try {
    state.apiBase = baseHttpUrl(host, port);
    const result = await apiFetch("/api/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    if (result.status !== "ok") {
      throw new Error(result.message || "登录失败");
    }
    state.token = result.token;
    state.role = result.role || "user";
    rememberLogin();
    await connectWebSocket(host, port);
    await Promise.all([loadMessages(), loadSessions()]);
    showApp();
    setStatus("已连接", "ok");
  } catch (error) {
    setStatus(`连接失败：${error.message}`, "danger");
  } finally {
    el.login.disabled = false;
  }
}

async function connectWebSocket(host, port) {
  if (state.ws) state.ws.close();
  const ws = new WebSocket(websocketUrl(host, port, state.token, state.deviceId));
  state.ws = ws;
  await new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("WebSocket 超时")), 6000);
    ws.addEventListener("open", () => {
      window.clearTimeout(timer);
      state.connected = true;
      resolve();
    }, { once: true });
    ws.addEventListener("error", () => {
      window.clearTimeout(timer);
      reject(new Error("WebSocket 连接失败"));
    }, { once: true });
  });
  ws.addEventListener("message", handleWsMessage);
  ws.addEventListener("close", () => {
    state.connected = false;
    setStatus("连接已断开", "danger");
  });
  window.setInterval(() => {
    if (state.ws?.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ action: "ping", timestamp: Date.now() }));
    }
  }, 5000);
}

function handleWsMessage(event) {
  let data;
  try {
    data = JSON.parse(event.data);
  } catch {
    return;
  }
  const { type, payload } = data;
  if (type === "pong") {
    state.latencyMs = typeof payload === "number" ? Date.now() - payload : 0;
    setStatus(`已连接 · ${state.latencyMs} ms`, "ok");
    return;
  }
  if (type === "notify_messages") loadMessages();
  if (type === "notify_sessions") loadSessions();
  if (type === "status") pushLog(String(payload || ""));
  if (type === "server_log") pushLog(typeof payload === "object" ? payload.text : payload);
  if (type === "api_stream_chunk" || type === "api_stream_status") {
    pushLog(`stream: ${payload?.status || ""}`);
  }
}

function pushLog(text) {
  const line = String(text || "").trim();
  if (!line) return;
  state.logs.push(`${new Date().toLocaleTimeString()} ${line}`);
  if (state.logs.length > 300) state.logs.shift();
  el.logText.textContent = state.logs.join("\n");
}

async function loadMessages() {
  const raw = await apiFetch("/api/sync/messages");
  state.messages = parseMessages(raw);
  renderMessages();
}

async function loadSessions() {
  const raw = await apiFetch("/api/sync/sessions");
  state.sessions = Array.isArray(raw) ? raw : [];
  renderSessions();
}

function renderSessions() {
  el.sessions.innerHTML = "";
  for (const [index, session] of state.sessions.entries()) {
    const button = document.createElement("button");
    button.className = "session";
    button.type = "button";
    button.textContent = session.title || session.name || `会话 ${index + 1}`;
    button.addEventListener("click", () => rpc("request_switch_session", [index]));
    el.sessions.append(button);
  }
}

function renderMessages() {
  el.messages.innerHTML = "";
  for (const message of state.messages) {
    const item = document.createElement("article");
    item.className = `message ${message.role === "User" ? "user" : "ai"}`;
    const header = document.createElement("header");
    header.textContent = `${message.role} · ${message.source}`;
    item.append(header);
    for (const segment of message.segments) {
      item.append(renderSegment(segment));
    }
    item.title = summarizeMessage(message);
    el.messages.append(item);
  }
  el.messages.scrollTop = el.messages.scrollHeight;
}

function renderSegment(segment) {
  if (segment.type === "code") {
    const pre = document.createElement("pre");
    pre.textContent = segment.content;
    pre.dataset.lang = segment.language;
    return pre;
  }
  if (segment.type === "image") {
    const img = document.createElement("img");
    img.src = segment.content;
    img.alt = "消息图片";
    return img;
  }
  if (segment.type === "tool_result") {
    const box = document.createElement("pre");
    box.className = segment.success ? "tool ok" : "tool danger";
    box.textContent = `${segment.toolName || "tool"}\n${segment.content}`;
    return box;
  }
  const p = document.createElement("p");
  p.textContent = segment.content;
  return p;
}

function rpc(method, args = [], kwargs = {}) {
  if (state.ws?.readyState !== WebSocket.OPEN) {
    setStatus("WebSocket 未连接", "danger");
    return;
  }
  state.ws.send(JSON.stringify({ action: "rpc_call", method, args, kwargs }));
}

function send() {
  const text = el.composer.value.trim();
  if (!text) return;
  if (state.ws?.readyState !== WebSocket.OPEN) {
    setStatus("WebSocket 未连接", "danger");
    return;
  }
  state.ws.send(sendTextRpc(state.mode, text));
  el.composer.value = "";
}

function showApp() {
  el.loginPanel.hidden = true;
  el.appPanel.hidden = false;
  el.title.textContent = `${el.host.value.trim()}:${el.port.value.trim() || "8765"}`;
}

function logout() {
  if (state.ws) state.ws.close();
  state.token = "";
  state.messages = [];
  state.sessions = [];
  el.appPanel.hidden = true;
  el.loginPanel.hidden = false;
  setStatus("未连接", "muted");
}

restoreLogin();
el.mode.value = state.mode;
el.login.addEventListener("click", login);
el.logout.addEventListener("click", logout);
el.refresh.addEventListener("click", () => Promise.all([loadMessages(), loadSessions()]));
el.send.addEventListener("click", send);
el.composer.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) send();
});
el.mode.addEventListener("change", () => {
  state.mode = el.mode.value;
  localStorage.setItem("db.mobile.mode", state.mode);
});
el.openLogs.addEventListener("click", () => el.logs.showModal());
el.closeLogs.addEventListener("click", () => el.logs.close());

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js").catch(() => {});
}
