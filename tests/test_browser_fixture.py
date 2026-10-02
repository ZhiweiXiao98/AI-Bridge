"""本机浏览器 fixture 的传输、生命周期与现有 DOM 选择器契约。"""

import json
import importlib.util
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pytest
from bs4 import BeautifulSoup

from app.core.browser_fixture import BrowserFixture


@pytest.fixture
def loopback(request):
    """尊重严格无 socket CI；不自行解除其网络封锁。"""
    if request.config.getoption('disable_socket', default=False):
        pytest.skip('严格无 socket 模式不启动本机 HTTP；正常回归覆盖 loopback 传输')


def read(url, *, data=None, headers=None):
    request = Request(url, data=data, headers=headers or {})
    with urlopen(request, timeout=2) as response:
        return response.status, response.headers, response.read()


def event(fixture, kind, event_id='event-1', **fields):
    return read(fixture.url + 'events', data=json.dumps(dict(type=kind, event_id=event_id, **fields)).encode(),
                headers={'Content-Type': 'application/json'})


def test_fixture_matches_browser_dom_contract_without_server():
    soup = BeautifulSoup(BrowserFixture().html, 'html.parser')
    assert soup.select_one('div.aa-chat-input textarea.n-input__textarea-el')
    assert len(soup.select('.aa-sidebar-list-item')) == 2
    assert soup.select_one('.aa-sidebar-list-item.active').get_text() == '测试会话一'
    assert soup.select_one('.n-scrollbar-container')
    assert soup.select_one('.spinner-box[hidden]')
    assert soup.select_one('button.n-button--error-type span').get_text() == '停止'
    assert soup.select_one('#new-chat[data-action="new-chat"]').get_text() == '新建对话'
    for role in ('false', 'true'):
        assert soup.select_one(f'template .chat-item[data-message-ai="{role}"] .chat-text')
    assert not soup.select('[src],link[href]')


def test_stream_config_is_explicit_and_code_is_display_only():
    html = BrowserFixture(chunk_delay=.12, initial_delay=.35, chunk_size=3, include_code=True).html
    assert '"chunkDelayMs": 120' in html
    assert '"initialDelayMs": 350' in html
    assert '"chunkSize": 3' in html
    assert '"includeCode": true' in html
    assert 'paragraph.textContent = message.text' in html
    assert 'code.textContent = message.code' in html
    assert 'setTimeout(nextChunk, config.initialDelayMs)' in html
    assert 'setTimeout(nextChunk, config.chunkDelayMs)' in html
    assert 'eval(' not in html
    assert 'new Function' not in html


def test_message_template_content_roundtrips_through_actual_dom_parser():
    # 独立导入纯 DOM 解析器，避免导入整个 Selenium/Qt connector 包。
    path = Path(__file__).parents[1] / 'app/core/driver/parser.py'
    spec = importlib.util.spec_from_file_location('fixture_dom_parser', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    soup = BeautifulSoup(BrowserFixture().html, 'html.parser')
    content = soup.select_one('#ai-message-template .chat-text')
    paragraph = soup.new_tag('p')
    paragraph.string = '中文多行\n<script>不会执行</script>'
    content.append(paragraph)
    pre = soup.new_tag('pre', attrs={'data-language': 'python'})
    code = soup.new_tag('code', attrs={'class': 'language-python'})
    code.string = '# 仅供显示，不执行\nprint("browser fixture")'
    pre.append(code)
    content.append(pre)
    segments = module.DOMParser().parse_node(content)
    assert len(segments) == 2
    assert segments[0]['type'] == 'text'
    assert '&lt;script&gt;' in segments[0]['content']
    assert segments[1] == {'type': 'code', 'language': 'python',
                            'content': '# 仅供显示，不执行\nprint("browser fixture")'}


@pytest.mark.parametrize('full', [False, True])
def test_fixture_stream_and_final_roundtrip_through_message_extractor(full):
    """Fixture 的稳定消息 ID 在流式、完成和缓存重读时均保留最新文本。"""
    import copy
    from app.core.driver.browser_incremental import IncrementalExtractor
    from app.core.driver.browser_js import BATCH_CHAT_CONTENT, CHAT_CONTENT_BY_INDEX, CHAT_CONTENT_PROBE
    from app.core.driver.config import SCRIPTS
    from app.core.driver.parser import DOMParser

    template = BeautifulSoup(BrowserFixture().html, 'html.parser')

    class FixtureDOM:
        items = []

        def update(self, answer):
            self.items = []
            for role, text, message_id in [('user', '中文输入', 'user-1'), ('ai', answer, 'ai-2')]:
                node = copy.deepcopy(template.select_one(f'#{role}-message-template .chat-item'))
                node['data-message-id'] = message_id
                paragraph = template.new_tag('p')
                paragraph.string = text
                node.select_one('.chat-text').append(paragraph)
                self.items.append({'id': message_id, 'ai': node['data-message-ai'],
                                   'html': str(node), 'text_len': len(node.get_text()),
                                   'html_len': len(str(node)), 'code_count': 0})

        def execute_script(self, script, *args):
            if script == SCRIPTS['scroll_check']:
                return True
            if script in (BATCH_CHAT_CONTENT, CHAT_CONTENT_PROBE):
                return self.items
            assert script == CHAT_CONTENT_BY_INDEX
            return [dict(self.items[index], idx=index) for index in args[0]]

    driver = FixtureDOM()
    extractor = IncrementalExtractor(DOMParser())
    extract = extractor._extract_full if full else extractor.extract
    observed = []
    for text, streaming in [('这是本地', True), ('这是本地浏览器测试回复。', True),
                            ('这是本地浏览器测试回复。\n分块输出已完成。', False)]:
        driver.update(text)
        messages, at_bottom, _ = extract(driver, None, streaming)
        assert at_bottom
        assert [(message['id'], message['role']) for message in messages] == [('user-1', 'User'), ('ai-2', 'AI')]
        observed.append(''.join(segment['content'] for segment in messages[-1]['segments']))
        assert text.split('\n')[-1] in observed[-1]
    assert len(set(observed)) == 3
    messages, _, _ = extract(driver, None, False)
    assert '分块输出已完成' in messages[-1]['segments'][0]['content']


@pytest.mark.parametrize('kwargs', [
    {'chunk_delay': -1}, {'initial_delay': float('nan')}, {'chunk_delay': float('inf')},
    {'initial_delay': '0.1'}, {'chunk_delay': True}, {'chunk_size': 0}, {'chunk_size': 1.5},
    {'chunk_size': True},
])
def test_invalid_stream_config_rejected(kwargs):
    with pytest.raises(ValueError):
        BrowserFixture(**kwargs)


def test_loopback_random_route_headers_and_shutdown(loopback):
    fixture = BrowserFixture()
    with pytest.raises(RuntimeError):
        _ = fixture.url
    with fixture:
        url = fixture.url
        assert urlsplit(url).hostname == '127.0.0.1'
        assert len(urlsplit(url).path.split('/')[-2]) >= 24
        assert fixture.is_running
        assert fixture.start() is fixture
        status, headers, body = read(url)
        assert status == 200
        assert '本地浏览器回归测试' in body.decode()
        assert headers['Cache-Control'] == 'no-store'
        assert "connect-src 'self'" in headers['Content-Security-Policy']
        assert 'frame-ancestors' in headers['Content-Security-Policy']
        assert fixture.request_count == 0  # 页面 GET 不是聊天请求。
        origin = urlsplit(url)
        for path in ('/', '/browser-fixture/guess/', origin.path + 'missing'):
            with pytest.raises(HTTPError) as error:
                read(f'{origin.scheme}://{origin.netloc}{path}')
            assert error.value.code == 404
    assert not fixture.is_running
    fixture.close()
    with pytest.raises((URLError, OSError)):
        read(url)


def test_unique_fixture_paths_and_restart_cleanup(loopback):
    first, second = BrowserFixture(), BrowserFixture()
    assert first._path != second._path
    with first:
        pass
    with first:
        assert read(first.url)[0] == 200
    assert not first.is_running


def test_events_counts_deduplication_and_snapshot_isolation(loopback):
    with BrowserFixture() as fixture:
        event(fixture, 'request', text='中文\n第二行 <script>alert(1)</script>', session_id='session-1', message_id='user-1')
        event(fixture, 'request', text='duplicate ignored')
        event(fixture, 'chunk', 'event-2', text='分块', session_id='session-1', message_id='ai-2')
        event(fixture, 'response', 'event-3', text='完成', session_id='session-1', message_id='ai-2')
        event(fixture, 'cancel', 'event-4', text='部分', reason='user')
        event(fixture, 'switch', 'event-5', session_id='session-2')
        event(fixture, 'new_chat', 'event-6', session_id='session-3')
        event(fixture, 'clear', 'event-7', session_id='session-3')
        assert fixture.request_count == 1
        assert fixture.response_count == 1
        assert fixture.cancel_count == 1
        snapshot = fixture.snapshot()
        assert snapshot['chunk_count'] == snapshot['session_switch_count'] == snapshot['new_chat_count'] == snapshot['clear_count'] == 1
        assert fixture.requests[0]['text'].startswith('中文\n')
        assert fixture.responses[0]['text'] == '完成'
        snapshot['events'][0]['text'] = 'mutated'
        assert fixture.requests[0]['text'] != 'mutated'
        assert json.loads(read(fixture.url + 'state')[2]) == fixture.snapshot()
    assert fixture.response_count == 1


def test_page_ready_event_counts_actual_restored_messages(loopback):
    with BrowserFixture() as fixture:
        assert fixture.page_ready_count == 0
        assert fixture.page_ready_events == []
        event(fixture, 'page_ready', 'first-page:1', restored_message_count=0, session_count=2)
        event(fixture, 'page_ready', 'second-page:1', restored_message_count=4, session_count=2)
        event(fixture, 'page_ready', 'second-page:1', restored_message_count=4, session_count=2)
        snapshot = fixture.snapshot()
        assert fixture.page_ready_count == snapshot['page_ready_count'] == 2
        assert [item['restored_message_count'] for item in snapshot['page_ready_events']] == [0, 4]
        assert fixture.page_ready_events == snapshot['page_ready_events']
        snapshot['page_ready_events'][-1]['restored_message_count'] = 999
        assert fixture.page_ready_events[-1]['restored_message_count'] == 4
        assert json.loads(read(fixture.url + 'state')[2])['page_ready_count'] == 2


@pytest.mark.parametrize(('headers', 'body', 'status'), [
    ({'Content-Type': 'text/plain'}, b'{}', 415),
    ({'Content-Type': 'application/json'}, b'not json', 400),
    ({'Content-Type': 'application/json'}, b'[]', 400),
    ({'Content-Type': 'application/json'}, b'{"type":"unknown","event_id":"1"}', 400),
    ({'Content-Type': 'application/json'}, b'{"type":"request"}', 400),
    ({'Content-Type': 'application/json'}, b'{"type":"request","event_id":"1","text":42}', 400),
    ({'Content-Type': 'application/json'}, b'{"type":"page_ready","event_id":"1"}', 400),
    ({'Content-Type': 'application/json'}, b'{"type":"page_ready","event_id":"1","restored_message_count":true}', 400),
    ({'Content-Type': 'application/json'}, b'{"type":"page_ready","event_id":"1","restored_message_count":-1}', 400),
    ({'Content-Type': 'application/json'}, b'{"type":"page_ready","event_id":"1","restored_message_count":"2"}', 400),
    ({'Content-Type': 'application/json'}, b'{"type":"page_ready","event_id":"1","restored_message_count":1.5}', 400),
    ({'Content-Type': 'application/json'}, b'x' * (128 * 1024 + 1), 413),
    ({'Content-Type': 'application/json', 'Origin': 'https://example.com'}, b'{}', 403),
    ({'Content-Type': 'application/json', 'Host': 'example.com'}, b'{}', 403),
])
def test_invalid_or_cross_origin_events_are_rejected(headers, body, status, loopback):
    with BrowserFixture() as fixture:
        with pytest.raises(HTTPError) as error:
            read(fixture.url + 'events', data=body, headers=headers)
        assert error.value.code == status
        assert not fixture.snapshot()['events']


_NODE_DOM_HARNESS = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const source = require('node:fs').readFileSync(0, 'utf8');
function page(store = new Map()) {
  class Element {
    constructor() { this.dataset = {}; this.children = []; this.listeners = {}; this.value = ''; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    appendChild(element) { this.children.push(element); }
    replaceChildren(...elements) { this.children = elements; }
    focus() {}
    click() { if (this.listeners.click) this.listeners.click(); }
    querySelector() { return this.contentNode || (this.contentNode = new Element()); }
    cloneNode() { return new Element(); }
  }
  const nodes = Object.fromEntries(['messages', 'sessions', 'send', 'stop', 'new-chat',
    'clear-chat', 'input', 'spinner'].map(id => [id, new Element()]));
  for (const id of ['user-message-template', 'ai-message-template']) {
    nodes[id] = {content: {firstElementChild: new Element()}};
  }
  const timers = [], events = [];
  const window = {addEventListener() {}};
  const location = {pathname: '/browser-fixture/token/', href: 'http://127.0.0.1:1234/browser-fixture/token/', hash: ''};
  const context = vm.createContext({window, location, URL, URLSearchParams,
    document: {body: new Element(), getElementById: id => nodes[id],
      createElement: () => new Element(),
      querySelector: selector => selector === '.spinner-box' ? nodes.spinner : nodes.input},
    history: {replaceState: (_state, _title, hash) => { location.hash = hash; }},
    localStorage: {getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value)},
    setTimeout: fn => { const timer = {fn, cleared: false}; timers.push(timer); return timer; },
    clearTimeout: timer => { timer.cleared = true; },
    fetch: async (_url, options) => { events.push(JSON.parse(options.body)); return {ok: true}; }
  });
  vm.runInContext(source, context);
  const snapshot = () => JSON.parse(JSON.stringify(window.__browserFixture.snapshot()));
  const send = text => { nodes.input.value = text; nodes.send.click(); };
  const tick = () => { const timer = timers.shift(); if (timer && !timer.cleared) timer.fn(); };
  return {store, nodes, timers, events, snapshot, send, tick, flush: window.__browserFixture.flush};
}
'''


def run_fixture_script(assertions):
    import shutil
    import subprocess

    node = shutil.which('node')
    if not node:
        pytest.skip('JavaScript 生命周期单测需要 Node.js；HTTP/DOM单测不受影响')
    script = BeautifulSoup(BrowserFixture().html, 'html.parser').script.string
    subprocess.run([node, '--check'], input=script, text=True, capture_output=True, check=True, timeout=5)
    harness = _NODE_DOM_HARNESS + '\n(async () => {\n' + assertions + '\n})().catch(error => { console.error(error); process.exitCode = 1; });'
    subprocess.run([node, '-e', harness], input=script, text=True, capture_output=True, check=True, timeout=5)


def test_fixture_script_persists_sessions_between_page_process_contexts():
    run_fixture_script(r'''
      const first = page();
      await first.flush();
      assert.equal(first.events.filter(event => event.type === 'page_ready').length, 1);
      assert.equal(first.events.find(event => event.type === 'page_ready').restored_message_count, 0);
      first.send('持久化第一条');
      while (first.timers.length) first.tick();
      await first.flush();
      assert.equal(first.events.filter(event => event.type === 'response').length, 1);
      const original = first.snapshot().sessions[0].messages;
      first.nodes.sessions.children[1].click();
      first.send('重启时尚未完成');
      first.tick();
      assert.equal(first.snapshot().busy, true);
      const second = page(first.store);
      const restored = second.snapshot();
      assert.equal(restored.active, 'session-2');
      assert.deepEqual(restored.sessions[0].messages, original);
      assert.equal(restored.sessions[1].messages[0].text, '重启时尚未完成');
      assert.equal(restored.sessions[1].messages[1].status, 'cancelled');
      assert.equal(restored.busy, false);
      assert.equal(second.timers.length, 0);
      second.nodes.sessions.children[0].click();
      assert.deepEqual(second.snapshot().sessions[0].messages, original);
      await first.flush(); await second.flush();
      const ready = second.events.filter(event => event.type === 'page_ready');
      assert.equal(ready.length, 1);
      assert.equal(ready[0].restored_message_count, 4);
      assert.equal(ready[0].session_count, 2);
    ''')


def test_fixture_script_cancel_rejects_even_already_queued_chunk_callback():
    run_fixture_script(r'''
      const current = page();
      current.send('取消后不能继续追加回复');
      current.tick();
      const staleTimer = current.timers[0];
      current.nodes.stop.click();
      const stopped = current.snapshot();
      assert.equal(stopped.busy, false);
      assert.equal(stopped.sessions[0].messages[1].status, 'cancelled');
      assert.equal(staleTimer.cleared, true);
      staleTimer.fn(); // 模拟取消前已经进入事件队列的回调。
      while (current.timers.length) current.tick();
      assert.deepEqual(current.snapshot().sessions, stopped.sessions);
      await current.flush();
      assert.equal(current.events.filter(event => event.type === 'cancel').length, 1);
      assert.equal(current.events.filter(event => event.type === 'response').length, 0);
      current.send('取消后再次发送正常');
      staleTimer.fn(); // 旧 generation 也不能污染下一次发送。
      while (current.timers.length) current.tick();
      await current.flush();
      assert.equal(current.events.filter(event => event.type === 'response').length, 1);
      assert.deepEqual(current.snapshot().sessions[0].messages[1], stopped.sessions[0].messages[1]);
    ''')
