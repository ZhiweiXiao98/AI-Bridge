import assert from "node:assert/strict";
import {
  baseHttpUrl,
  createDeviceId,
  parseMessages,
  rpcMessage,
  sendTextRpc,
  websocketUrl,
} from "../mobile/web/app-core.mjs";

assert.equal(baseHttpUrl("http://192.168.1.2/", "bad"), "http://192.168.1.2:8765");
assert.equal(websocketUrl("ws://pc.local/", "9000", "tok en", "dev/1"), "ws://pc.local:9000/ws/tok%20en/dev%2F1");

assert.match(createDeviceId("stable-device"), /^Mobile_[0-9a-f]{8}$/);
assert.equal(createDeviceId("stable-device"), createDeviceId("stable-device"));

const messages = parseMessages([
  {
    id: "m1",
    role: "AI",
    source: "browser",
    raw_len: 42,
    segments: [
      { type: "text", content: "hello" },
      { type: "code", language: "python", content: "print(1)" },
      { type: "tool_result", tool_name: "run", content: "ok", success: true },
    ],
  },
]);

assert.equal(messages.length, 1);
assert.equal(messages[0].segments[1].content, "print(1)");
assert.equal(messages[0].segments[2].toolName, "run");

assert.deepEqual(JSON.parse(rpcMessage("new_chat")), {
  action: "rpc_call",
  method: "new_chat",
  args: [],
  kwargs: {},
});

assert.deepEqual(JSON.parse(sendTextRpc("api", "hi")), {
  action: "rpc_call",
  method: "api_send",
  args: [],
  kwargs: { text: "hi" },
});

assert.deepEqual(JSON.parse(sendTextRpc("browser", "hi")), {
  action: "rpc_call",
  method: "send_text",
  args: ["div.aa-chat-input textarea", "hi"],
  kwargs: {},
});

console.log("mobile web core tests passed");
