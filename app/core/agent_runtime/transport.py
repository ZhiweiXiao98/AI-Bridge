"""Bounded, continuously drained JSONL subprocess transport; never invokes a shell."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid


class ProtocolError(RuntimeError):
    pass


class JsonlProcess:
    MAX_LINE = 4 * 1024 * 1024

    def __init__(self, command, cwd, home, *, queue_size=1024, ack_timeout=20):
        self.command = list(command)
        self.cwd = str(Path(cwd).resolve(strict=True))
        self.home = str(Path(home).resolve())
        self.ack_timeout = ack_timeout
        self.events = queue.Queue(maxsize=queue_size)
        self._pending = {}
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._failure = None
        self._closed = False
        self.stderr_bytes = 0
        self.process = None

    def start(self):
        Path(self.home).mkdir(parents=True, exist_ok=True)
        # No ambient provider keys, shell options, NODE_OPTIONS or auth locations.
        env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR") if k in os.environ}
        env.update(HOME=self.home, USERPROFILE=self.home, TMPDIR=self.home,
                   XDG_CONFIG_HOME=self.home, NO_COLOR="1")
        self.process = subprocess.Popen(self.command, cwd=self.cwd, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, bufsize=0)
        self._threads = [threading.Thread(target=self._read, daemon=True),
                         threading.Thread(target=self._stderr, daemon=True)]
        for thread in self._threads:
            thread.start()

    def _fail(self, message):
        with self._lock:
            if not self._failure:
                self._failure = ProtocolError(message)
            for slot in self._pending.values():
                slot["ready"].set()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(self.MAX_LINE + 1)
                if not line:
                    if not self._closed:
                        self._fail("Agent process exited before the session was closed")
                    return
                if len(line) > self.MAX_LINE or not line.endswith(b"\n"):
                    raise ProtocolError("Agent output exceeded the JSONL frame limit")
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    raise ProtocolError("Agent output must be a JSON object")
                if obj.get("type") == "response":
                    with self._lock:
                        slot = self._pending.get(obj.get("id"))
                        if slot is None:
                            raise ProtocolError("Uncorrelated agent response")
                        slot["value"] = obj
                        slot["ready"].set()
                else:
                    try:
                        self.events.put_nowait(obj)
                    except queue.Full:
                        raise ProtocolError("Agent consumer fell behind; bounded event queue overflow")
        except Exception as error:
            self._fail(str(error) if isinstance(error, ProtocolError) else "Malformed agent JSONL output")
            if self.process and self.process.poll() is None:
                self.process.terminate()

    def _stderr(self):
        # Drain to avoid deadlock. Raw stderr may contain provider secrets; do not retain it.
        while True:
            chunk = self.process.stderr.read(8192)
            if not chunk:
                return
            self.stderr_bytes += len(chunk)

    def send(self, kind, *, cancel_if=None, **payload):
        with self._lock:
            if self._failure:
                raise self._failure
            if self._closed:
                raise ProtocolError("Agent transport is closed")
            command_id = uuid.uuid4().hex
            slot = {"ready": threading.Event(), "value": None}
            self._pending[command_id] = slot
        packet = json.dumps({**payload, "id": command_id, "type": kind}, ensure_ascii=False).encode() + b"\n"
        try:
            if len(packet) > self.MAX_LINE:
                raise ProtocolError("Agent command exceeded the JSONL frame limit")
            # Pipes can block before ACK waiting even starts if a failed child stops
            # reading stdin. Bound the write itself on every supported platform.
            written = threading.Event()
            def write_packet():
                try:
                    with self._write_lock:
                        # Admission and cancellation must be ordered with the
                        # actual pipe write, not with spawning writer threads.
                        # An abort can overtake a writer waiting for this lock.
                        if cancel_if is not None and cancel_if():
                            slot["value"] = {"success": True, "data": {"disposition": "cancelled"}}
                            slot["ready"].set()
                            return
                        offset = 0
                        while offset < len(packet):
                            count = self.process.stdin.write(packet[offset:])
                            if not count:
                                raise OSError("Short agent pipe write")
                            offset += count
                        self.process.stdin.flush()
                except (OSError, ValueError):
                    self._fail("Agent command pipe failed")
                finally:
                    written.set()
            writer = threading.Thread(target=write_packet, daemon=True, name="agent-jsonl-write")
            writer.start()
            if not written.wait(self.ack_timeout):
                self._fail("Agent command pipe write timed out")
                if self.process.poll() is None:
                    self.process.terminate()
                raise self._failure
            if self._failure:
                raise self._failure
            if not slot["ready"].wait(self.ack_timeout):
                self._fail("Agent command acknowledgement timed out")
                raise self._failure
            if self._failure:
                raise self._failure
            response = slot["value"]
            if not response or not response.get("success"):
                # Sidecar errors are redacted there; do not include arbitrary payloads here.
                raise ProtocolError("Agent rejected " + kind + ": " + str((response or {}).get("error", "unknown error")))
            return command_id, response.get("data") or {}
        except (OSError, ValueError):
            self._fail("Agent command pipe failed")
            raise self._failure
        finally:
            with self._lock:
                self._pending.pop(command_id, None)

    def next_event(self, timeout=0.2):
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            if self._failure:
                raise self._failure
            return None

    def close(self, timeout=3.0):
        deadline = time.monotonic() + max(0.0, timeout)
        if not self._close_lock.acquire(timeout=max(0.0, timeout)):
            return False
        try:
            self._closed = True
            self._fail("Agent transport closed")
            process = self.process
            if not process:
                return True
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=min(1.0, max(0.0, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=max(0.0, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        return False
            for pipe in (process.stdin, process.stdout, process.stderr):
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass
            for thread in getattr(self, "_threads", []):
                if thread is not threading.current_thread():
                    thread.join(timeout=max(0.0, deadline - time.monotonic()))
            return True
        finally:
            self._close_lock.release()
