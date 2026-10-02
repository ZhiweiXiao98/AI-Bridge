"""只供本地回归使用的 WebAI DOM 聊天页面，无账号、模型或外部网络。

用法::

    with BrowserFixture(chunk_delay=0.25, initial_delay=0.4) as fixture:
        driver.get(fixture.url)
        # 使用真实 ChromeConnector 发送、解析、取消和切换会话。
        assert fixture.request_count == 1

回复由浏览器定时分块构造；HTTP 服务仅提供页面与记录测试事件。
聊天历史保存于该随机地址的 localStorage，同一 fixture 服务与浏览器 profile
可跨浏览器进程恢复；重启时未完成的回复标记为取消，不恢复旧计时器。
``requests`` / ``responses`` 返回含 text、session_id、message_id 的事件副本。
浏览器中的 ``window.__browserFixture.snapshot()`` 提供同步 DOM 状态快照，
``flush()`` 等待事件落盘到本机内存；不暴露模型或代码执行接口。
"""

from __future__ import annotations

import copy
import json
import math
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


_HTML = r'''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Bridge 本地浏览器测试</title>
<style>
* { box-sizing: border-box; } [hidden] { display: none !important; }
body { margin: 0; color: #172b3a; background: #f4f7fb; font: 16px system-ui,sans-serif; }
main { display: grid; grid-template-columns: 220px 1fr; min-height: 100vh; }
aside { background: #e8eef5; padding: 18px; }
section { min-width: 0; display: flex; flex-direction: column; padding: 20px; }
button { cursor: pointer; padding: 10px 14px; border: 1px solid #bdcddd; border-radius: 7px; background: white; }
button:disabled { cursor: default; opacity: .5; }
.aa-sidebar-list-item { display: block; width: 100%; margin: 10px 0; text-align: left; }
.aa-sidebar-list-item.active { background: #cddfff; border-color: #466db2; }
.notice { margin: 0 0 14px; color: #526376; }
.n-scrollbar-container { overflow: auto; height: 60vh; padding: 12px; background: white; border-radius: 10px; }
.chat-item { min-height: 24px; margin: 10px 0; padding: 12px; border-radius: 7px; background: #eff4fa; }
.chat-item[data-message-ai="false"] { background: #dceafe; }
.chat-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.chat-text p { margin: 0; } pre { white-space: pre-wrap; background: #182232; color: #e6edf5; padding: 12px; }
.aa-chat-input { margin-top: 12px; } textarea { width: 100%; min-height: 90px; padding: 12px; font: inherit; }
.controls { display: flex; gap: 10px; margin-top: 8px; align-items: center; }
.spinner-box { color: #3856ad; } .n-button--error-type { color: #ac2730; }
</style></head>
<body><main>
<aside><button id="new-chat" data-action="new-chat" aria-label="新建对话">新建对话</button>
<nav id="sessions" aria-label="会话列表">
<button class="aa-sidebar-list-item active" data-session-id="session-1">测试会话一</button>
<button class="aa-sidebar-list-item" data-session-id="session-2">测试会话二</button>
</nav></aside>
<section><h1>本地浏览器回归测试</h1>
<p class="notice">所有回复均为本机模拟文本，无登录、付费或外部模型。代码仅展示，不会执行。</p>
<div id="messages" class="n-scrollbar-container" aria-label="聊天内容" aria-live="polite"></div>
<div class="aa-chat-input chat-input-box">
<textarea class="n-input__textarea-el" aria-label="消息" placeholder="输入测试消息；Enter 发送，Shift+Enter 换行"></textarea>
<div class="controls">
<button id="send" class="n-button send"><span>发送</span></button>
<button id="stop" class="n-button n-button--error-type" data-action="stop" hidden><span>停止</span></button>
<button id="clear-chat" data-action="clear-chat"><span>清空</span></button>
<span class="spinner-box" role="status" hidden>正在分块生成…</span>
</div></div></section></main>
<template id="user-message-template"><div class="chat-item user" data-message-ai="false"><div class="chat-text"></div></div></template>
<template id="ai-message-template"><div class="chat-item ai" data-message-ai="true"><div class="chat-text"></div></div></template>
<script>
'use strict';
const config = __CONFIG_JSON__;
const messages = document.getElementById('messages');
const sessionsNode = document.getElementById('sessions');
const input = document.querySelector('.aa-chat-input textarea');
const sendButton = document.getElementById('send');
const stopButton = document.getElementById('stop');
const spinner = document.querySelector('.spinner-box');
const storageKey = 'ai-bridge-browser-fixture:' + location.pathname;
let state = {active: 'session-1', nextSession: 3, nextMessage: 1, sessions: [
  {id: 'session-1', title: '测试会话一', messages: []},
  {id: 'session-2', title: '测试会话二', messages: []}
]};
let restoredMessageCount = 0;
try {
  const saved = JSON.parse(localStorage.getItem(storageKey));
  if (saved && Array.isArray(saved.sessions) && saved.sessions.length) {
    state = saved;
    restoredMessageCount = state.sessions.reduce((count, session) =>
      count + (Array.isArray(session.messages) ? session.messages.length : 0), 0);
  }
} catch (_) {}
let generation = null;
let pendingEvents = 0;
let eventError = '';
let eventQueue = Promise.resolve();
let eventSequence = 0;
const pageId = Math.random().toString(36).slice(2);
function emit(type, detail = {}) {
  const payload = Object.assign({type, event_id: pageId + ':' + (++eventSequence)}, detail);
  pendingEvents++;
  eventQueue = eventQueue.then(async () => {
    const response = await fetch(new URL('events', location.href), {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    if (!response.ok) throw new Error('fixture event HTTP ' + response.status);
  }).catch(error => { eventError = String(error); }).finally(() => { pendingEvents--; });
}
function save() { try { localStorage.setItem(storageKey, JSON.stringify(state)); } catch (_) {} }
function activeSession() { return state.sessions.find(session => session.id === state.active); }
function drawMessage(message) {
  const template = document.getElementById(message.ai ? 'ai-message-template' : 'user-message-template');
  const element = template.content.firstElementChild.cloneNode(true);
  element.dataset.messageId = message.id;
  element.dataset.state = message.status || 'complete';
  const content = element.querySelector('.chat-text');
  const paragraph = document.createElement('p');
  paragraph.textContent = message.text;
  content.appendChild(paragraph);
  if (message.code) {
    const pre = document.createElement('pre');
    pre.dataset.language = 'python';
    const code = document.createElement('code');
    code.className = 'language-python';
    code.textContent = message.code;
    pre.appendChild(code);
    content.appendChild(pre);
  }
  return element;
}
function render() {
  sessionsNode.replaceChildren();
  for (const session of state.sessions) {
    const button = document.createElement('button');
    button.className = 'aa-sidebar-list-item' + (session.id === state.active ? ' active' : '');
    button.dataset.sessionId = session.id;
    button.textContent = session.title;
    button.addEventListener('click', () => switchSession(session.id));
    sessionsNode.appendChild(button);
  }
  messages.replaceChildren(...activeSession().messages.map(drawMessage));
  messages.scrollTop = messages.scrollHeight;
  const busy = Boolean(generation);
  sendButton.disabled = busy;
  input.disabled = busy;
  stopButton.hidden = !busy;
  spinner.hidden = !busy;
  document.body.dataset.busy = String(busy);
}
function stop(reason = 'user') {
  if (!generation) return false;
  const current = generation;
  clearTimeout(current.timer);
  generation = null;
  current.message.status = 'cancelled';
  emit('cancel', {session_id: current.session.id, message_id: current.message.id,
    text: current.message.text, reason});
  save(); render();
  return true;
}
function switchSession(id, updateHash = true) {
  if (!state.sessions.some(session => session.id === id)) return false;
  if (id !== state.active) {
    stop('session_switch');
    state.active = id;
    emit('switch', {session_id: id});
  }
  if (updateHash) history.replaceState(null, '', '#session=' + encodeURIComponent(id));
  input.value = '';
  save(); render();
  return true;
}
function newChat() {
  stop('new_chat');
  const number = state.nextSession++;
  const session = {id: 'session-' + number, title: '新建测试会话 ' + number, messages: []};
  state.sessions.push(session);
  emit('new_chat', {session_id: session.id});
  switchSession(session.id);
  input.focus();
}
function submit() {
  const prompt = input.value.trim();
  if (!prompt || generation) return false;
  const session = activeSession();
  const user = {id: 'user-' + state.nextMessage++, ai: false, text: prompt, status: 'complete'};
  const answer = {id: 'ai-' + state.nextMessage++, ai: true, text: '', status: 'streaming'};
  session.messages.push(user, answer);
  input.value = '';
  const fullText = '这是本地浏览器测试回复。已收到：' + prompt + '\n分块输出已完成。';
  const chunks = Array.from(fullText);
  const current = {session, message: answer, cursor: 0, timer: null};
  generation = current;
  emit('request', {session_id: session.id, message_id: user.id, text: prompt});
  save(); render();
  function nextChunk() {
    if (generation !== current) return;
    answer.text += chunks.slice(current.cursor, current.cursor + config.chunkSize).join('');
    current.cursor += config.chunkSize;
    emit('chunk', {session_id: session.id, message_id: answer.id, text: answer.text});
    if (current.cursor >= chunks.length) {
      if (config.includeCode) answer.code = "# 仅供显示，不执行\nprint('browser fixture')";
      answer.status = 'complete';
      generation = null;
      emit('response', {session_id: session.id, message_id: answer.id, text: answer.text});
    } else current.timer = setTimeout(nextChunk, config.chunkDelayMs);
    save(); render();
  }
  current.timer = setTimeout(nextChunk, config.initialDelayMs);
  return true;
}
sendButton.addEventListener('click', submit);
stopButton.addEventListener('click', () => stop());
input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); }
});
document.getElementById('new-chat').addEventListener('click', newChat);
document.getElementById('clear-chat').addEventListener('click', () => {
  stop('clear'); activeSession().messages = [];
  emit('clear', {session_id: state.active}); save(); render();
});
function restoreHash() {
  const id = new URLSearchParams(location.hash.slice(1)).get('session');
  if (!id || !switchSession(id, false)) render();
}
window.addEventListener('hashchange', restoreHash);
window.addEventListener('pagehide', () => stop('pagehide'));
// Reloaded incomplete messages cannot keep a timer alive; mark their true terminal state.
for (const session of state.sessions) for (const message of session.messages) {
  if (message.status === 'streaming') message.status = 'cancelled';
}
window.__browserFixture = Object.freeze({
  snapshot: () => JSON.parse(JSON.stringify(Object.assign({}, state, {
    busy: Boolean(generation), pending_events: pendingEvents, event_error: eventError
  }))),
  flush: () => eventQueue
});
restoreHash();
save();
document.body.dataset.fixtureReady = 'true';
emit('page_ready', {restored_message_count: restoredMessageCount, session_count: state.sessions.length});
</script></body></html>'''


class BrowserFixture:
    """临时 loopback HTTP 服务；每个实例使用不可猜测的随机路径。

    ``request_count`` 是发送次数，``response_count`` 仅统计完整回复，取消不算完成。
    浏览器事件异步提交；跨线程断言应轮询计数或先等待页面的 ``flush()``。
    服务关闭后仍可读取最后快照；``close()`` 可安全重复调用。
    """

    _COUNTERS = {
        'request': 'request_count', 'response': 'response_count',
        'cancel': 'cancel_count', 'chunk': 'chunk_count',
        'switch': 'session_switch_count', 'new_chat': 'new_chat_count', 'clear': 'clear_count',
        'page_ready': 'page_ready_count',
    }
    _MAX_EVENT_BYTES = 128 * 1024

    def __init__(self, *, chunk_delay=0.25, initial_delay=0.4, chunk_size=7, include_code=False):
        for name, value in (('chunk_delay', chunk_delay), ('initial_delay', initial_delay)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f'{name} 必须为非负有限秒数')
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
            raise ValueError('chunk_size 必须为正整数')
        self._config = dict(chunkDelayMs=round(chunk_delay * 1000), initialDelayMs=round(initial_delay * 1000),
                            chunkSize=chunk_size, includeCode=bool(include_code))
        self._path = '/browser-fixture/' + secrets.token_urlsafe(24) + '/'
        self._url = ''
        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self._events = []
        self._event_ids = set()
        self._counts = {key: 0 for key in self._COUNTERS.values()}

    @property
    def url(self):
        if not self._url:
            raise RuntimeError('请先 start() 或使用 with BrowserFixture()')
        return self._url

    @property
    def html(self):
        """返回页面源码，便于不启动浏览器的选择器兼容性测试。"""
        return _HTML.replace('__CONFIG_JSON__', json.dumps(self._config, ensure_ascii=True))

    @property
    def is_running(self):
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    def snapshot(self):
        with self._lock:
            return dict(self._counts, events=copy.deepcopy(self._events),
                        page_ready_events=copy.deepcopy([event for event in self._events
                                                        if event['type'] == 'page_ready']))

    @property
    def request_count(self):
        return self.snapshot()['request_count']

    @property
    def response_count(self):
        return self.snapshot()['response_count']

    @property
    def cancel_count(self):
        return self.snapshot()['cancel_count']

    @property
    def page_ready_count(self):
        return self.snapshot()['page_ready_count']

    @property
    def page_ready_events(self):
        return self.snapshot()['page_ready_events']

    @property
    def requests(self):
        return [event for event in self.snapshot()['events'] if event['type'] == 'request']

    @property
    def responses(self):
        return [event for event in self.snapshot()['events'] if event['type'] == 'response']

    def _record_event(self, event):
        if not isinstance(event, dict) or event.get('type') not in self._COUNTERS:
            raise ValueError('未知测试事件')
        event_id = event.get('event_id')
        if not isinstance(event_id, str) or not event_id or len(event_id) > 128:
            raise ValueError('事件缺少有效 event_id')
        for name in ('session_id', 'message_id', 'text', 'reason'):
            if name in event and not isinstance(event[name], str):
                raise ValueError('测试事件字段必须为字符串')
        if event['type'] == 'page_ready':
            count = event.get('restored_message_count')
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError('page_ready 的 restored_message_count 必须为非负整数')
            if 'session_count' in event:
                count = event['session_count']
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ValueError('page_ready 的 session_count 必须为非负整数')
        with self._lock:
            if event_id not in self._event_ids:
                self._event_ids.add(event_id)
                self._events.append(copy.deepcopy(event))
                self._counts[self._COUNTERS[event['type']]] += 1

    def start(self):
        if self.is_running:
            return self
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *_args):
                pass

            def _reply(self, status, body=b'', content_type='application/json; charset=utf-8'):
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _authorized_path(self):
                parsed = urlsplit(fixture.url)
                if self.headers.get('Host') != parsed.netloc:
                    self._reply(403)
                    return None
                origin = self.headers.get('Origin')
                if origin and origin != f'http://{parsed.netloc}':
                    self._reply(403)
                    return None
                path = urlsplit(self.path).path
                if not path.startswith(fixture._path):
                    self._reply(404)
                    return None
                return path[len(fixture._path):]

            def do_GET(self):
                route = self._authorized_path()
                if route is None:
                    return
                if route == '':
                    self._reply(200, fixture.html.encode('utf-8'), 'text/html; charset=utf-8')
                elif route == 'state':
                    self._reply(200, json.dumps(fixture.snapshot(), ensure_ascii=False).encode('utf-8'))
                else:
                    self._reply(404)

            def do_POST(self):
                route = self._authorized_path()
                if route is None:
                    return
                if route != 'events':
                    self._reply(404)
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    self._reply(400)
                    return
                if length <= 0 or length > fixture._MAX_EVENT_BYTES:
                    self._reply(413)
                    return
                if self.headers.get_content_type() != 'application/json':
                    self._reply(415)
                    return
                try:
                    fixture._record_event(json.loads(self.rfile.read(length)))
                except (ValueError, UnicodeDecodeError, TypeError):
                    self._reply(400)
                    return
                self._reply(200, b'{"ok":true}')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        self._server = server
        self._url = f'http://127.0.0.1:{server.server_port}{self._path}'
        self._thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05},
                                        name='browser-fixture', daemon=True)
        self._thread.start()
        return self

    def close(self):
        server, thread = self._server, self._thread
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._server = None
        self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.close()
