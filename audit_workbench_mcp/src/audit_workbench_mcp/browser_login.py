"""Read the admin token from a dedicated Chrome profile, or pop the login page.

Owned by this MCP server. The profile directory keeps the login across sessions,
so the visible login window is only needed when the saved login has expired.

Tokens are returned in memory only; nothing is written to disk here.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROFILE_DIR = Path.home() / ".agents" / "cache" / "audit-workbench-admin-chrome"
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
]


class LoginError(Exception):
    pass


def _find_chrome() -> str | None:
    for c in CHROME_CANDIDATES:
        path = c if os.path.isabs(c) else shutil.which(c)
        if path and os.path.exists(path):
            return path
    return None


class _CDP:
    """Minimal stdlib WebSocket client for Chrome DevTools Protocol."""

    def __init__(self, url: str):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise LoginError("devtools handshake failed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise LoginError("devtools handshake rejected")
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.next_id = 0

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise LoginError("devtools closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, text: str) -> None:
        data = text.encode()
        n = len(data)
        head = bytearray([0x81])
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head += bytes([0x80 | 126]) + n.to_bytes(2, "big")
        else:
            head += bytes([0x80 | 127]) + n.to_bytes(8, "big")
        mask = os.urandom(4)
        self.sock.sendall(bytes(head) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv(self) -> str:
        msg = b""
        while True:
            b1, b2 = self._read(2)
            n = b2 & 0x7F
            if n == 126:
                n = int.from_bytes(self._read(2), "big")
            elif n == 127:
                n = int.from_bytes(self._read(8), "big")
            payload = self._read(n)
            if b1 & 0x0F == 0x8:
                raise LoginError("devtools closed")
            if b1 & 0x0F in (0x0, 0x1, 0x2):
                msg += payload
                if b1 & 0x80:
                    return msg.decode("utf-8", "replace")

    def call(self, method: str) -> dict:
        self.next_id += 1
        self._send(json.dumps({"id": self.next_id, "method": method, "params": {}}))
        while True:
            msg = json.loads(self._recv())
            if msg.get("id") == self.next_id:
                return msg.get("result") or {}


def _with_chrome(url: str, *, headless: bool, fn):
    """Start Chrome on the dedicated profile, run fn(cdp, proc), always close Chrome."""
    chrome = _find_chrome()
    if not chrome:
        raise LoginError("no_chrome")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [chrome, f"--remote-debugging-port={port}", f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run", "--no-default-browser-check"]
    args += ["--headless=new", url] if headless else ["--new-window", url]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cdp = None
    try:
        ws_url = None
        for _ in range(40):
            if proc.poll() is not None:
                # Profile already in use by another instance, or Chrome failed to start.
                raise LoginError("chrome_exited")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                    ws_url = json.load(r)["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.5)
        if not ws_url:
            raise LoginError("devtools_unreachable")
        cdp = _CDP(ws_url)
        return fn(cdp, proc)
    finally:
        if cdp:
            try:
                cdp.call("Browser.close")
            except Exception:
                pass
            cdp.sock.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()


def _cookie(cdp: _CDP, name: str) -> str | None:
    for c in cdp.call("Storage.getCookies").get("cookies", []):
        if c.get("name") == name and c.get("value"):
            return c["value"]
    return None


def read_saved_token(cookie_name: str) -> str | None:
    """Silently (headless, no window) read the admin cookie saved in the dedicated profile."""
    if not PROFILE_DIR.is_dir():
        return None
    try:
        return _with_chrome("about:blank", headless=True, fn=lambda cdp, _p: _cookie(cdp, cookie_name))
    except LoginError:
        return None


def capture_token(login_url: str, cookie_name: str, timeout: int = 300,
                  reject: str | None = None) -> str:
    """Pop a visible login window; return the admin cookie once set (and != reject)."""

    def wait(cdp: _CDP, proc: subprocess.Popen) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                raise LoginError("browser_closed")
            token = _cookie(cdp, cookie_name)
            if token and token != reject:
                return token
            time.sleep(1.5)
        raise LoginError("login_timeout")

    return _with_chrome(login_url, headless=False, fn=wait)
