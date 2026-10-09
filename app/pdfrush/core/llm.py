"""The AI brain. Offline: a local model (GGUF) served by llama.cpp's llama-server.exe.
Online: Google Gemini / Groq (both have free tiers), Claude, OpenAI, OpenRouter or any
OpenAI-compatible server. 'Auto' uses online when a key is set and the network works,
otherwise falls back to the offline model."""
from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .. import paths

TokenFn = Callable[[str], None] | None

PROVIDERS = {
    # name: (kind, base_url, default_model, key_url)
    "Google Gemini": ("openai", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash",
                      "https://aistudio.google.com/apikey"),
    "Groq": ("openai", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "https://console.groq.com/keys"),
    "Claude (Anthropic)": ("anthropic", "https://api.anthropic.com/v1", "claude-haiku-4-5",
                           "https://console.anthropic.com/settings/keys"),
    "OpenAI": ("openai", "https://api.openai.com/v1", "gpt-4o-mini", "https://platform.openai.com/api-keys"),
    "OpenRouter": ("openai", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini", "https://openrouter.ai/keys"),
    "Custom (OpenAI-compatible)": ("openai", "", "", ""),
}


class LLMError(RuntimeError):
    pass


# ===================================================================== local llama.cpp server
class LocalServer:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.model_path: Path | None = None
        self.lock = threading.Lock()
        atexit.register(self.stop)

    @staticmethod
    def exe() -> Path | None:
        name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
        found = list(paths.LLM_DIR.rglob(name)) if paths.LLM_DIR.exists() else []
        return found[0] if found else None

    @staticmethod
    def model() -> Path | None:
        want = paths.settings.get("local_model") or ""
        if want and Path(want).exists():
            return Path(want)
        ggufs = sorted(paths.GGUF_DIR.glob("*.gguf"), key=lambda p: p.stat().st_size) if paths.GGUF_DIR.exists() else []
        return ggufs[0] if ggufs else None

    def available(self) -> bool:
        return self.exe() is not None and self.model() is not None

    def _alive(self) -> bool:
        if not self.proc or self.proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def ensure(self, progress: Callable[[str], None] | None = None) -> str:
        with self.lock:
            model = self.model()
            if self.proc and self.proc.poll() is None and model == self.model_path and self._alive():
                return f"http://127.0.0.1:{self.port}/v1"
            self.stop()
            exe = self.exe()
            if not exe or not model:
                raise LLMError("The offline AI model isn't installed. Run build.bat again, or add an online "
                               "AI key in Settings (Gemini and Groq have free keys).")
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                self.port = s.getsockname()[1]
            threads = max(1, (os.cpu_count() or 4) - 1)
            args = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(self.port),
                    "-c", "8192", "-t", str(threads), "-np", "1"]
            flags = 0x08000000 if sys.platform == "win32" else 0
            log = open(paths.config_dir() / "llama-server.log", "w", encoding="utf-8", errors="replace")
            self.proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                                         cwd=str(exe.parent))
            self.model_path = model
            if progress:
                progress("Starting the offline AI (first time takes ~10-30 s)")
            t0 = time.time()
            while time.time() - t0 < 180:
                if self.proc.poll() is not None:
                    raise LLMError("The offline AI failed to start - see llama-server.log in "
                                   f"{paths.config_dir()}")
                if self._alive():
                    return f"http://127.0.0.1:{self.port}/v1"
                time.sleep(0.5)
            raise LLMError("The offline AI took too long to start.")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None


LOCAL = LocalServer()


# ===================================================================== HTTP helpers
def _post(url: str, body: dict, headers: dict, stream: bool, on_token: TokenFn, kind: str, timeout: int = 600) -> str:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:600]
        raise LLMError(f"AI service error {e.code}: {detail}") from None
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        raise ConnectionError(str(e)) from None
    with resp:
        if not stream:
            j = json.loads(resp.read().decode())
            if kind == "anthropic":
                return "".join(b.get("text", "") for b in j.get("content", []))
            return j["choices"][0]["message"]["content"] or ""
        out = []
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if kind == "anthropic":
                piece = ev.get("delta", {}).get("text", "") if ev.get("type") == "content_block_delta" else ""
            else:
                ch = (ev.get("choices") or [{}])[0]
                piece = (ch.get("delta") or {}).get("content") or ""
            if piece:
                out.append(piece)
                if on_token:
                    on_token(piece)
        return "".join(out)


def _strip_thinking(text: str) -> str:
    import re
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S).strip()


# ===================================================================== public API
def online_config() -> tuple[str, str, str, str] | None:
    s = paths.settings
    prov = s.get("ai_provider", "")
    if prov not in PROVIDERS:
        return None
    kind, base, model, _ = PROVIDERS[prov]
    key = (s.get("ai_keys") or {}).get(prov, "")
    if prov.startswith("Custom"):
        base = s.get("ai_base_url", "")
    model = s.get("ai_model") or model
    if not base or not model or (not key and not prov.startswith("Custom")):
        return None
    return kind, base.rstrip("/"), model, key


def describe() -> str:
    mode = paths.settings.get("ai_mode", "Auto")
    on = online_config()
    if mode == "Offline" or (mode == "Auto" and not on):
        return "Offline AI" if LOCAL.available() else "AI not set up"
    return f"{paths.settings.get('ai_provider')} · {on[2]}" if on else "Online AI (no key)"


def chat(messages: list[dict], max_tokens: int = 900, temperature: float = 0.4, on_token: TokenFn = None,
         status: Callable[[str], None] | None = None) -> str:
    """messages: [{"role": "system"|"user"|"assistant", "content": str}]"""
    mode = paths.settings.get("ai_mode", "Auto")
    on = online_config()
    if mode in ("Online", "Auto") and on:
        try:
            return _online(on, messages, max_tokens, temperature, on_token)
        except ConnectionError as e:
            if mode == "Online" or not LOCAL.available():
                raise LLMError(f"Can't reach the online AI ({e}). Check your internet, or switch AI to Offline.")
            if status:
                status("No internet - using the offline AI")
    elif mode == "Online":
        raise LLMError("Add an online AI key in Settings (Gemini and Groq offer free keys).")
    base = LOCAL.ensure(status)
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": on_token is not None}
    text = _post(base + "/chat/completions", body, {}, on_token is not None, on_token, "openai")
    return _strip_thinking(text)


def _online(cfg, messages, max_tokens, temperature, on_token) -> str:
    kind, base, model, key = cfg
    stream = on_token is not None
    if kind == "anthropic":
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        msgs = [m for m in messages if m["role"] != "system"]
        body = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": msgs,
                "stream": stream}
        if system:
            body["system"] = system
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        return _post(base + "/messages", body, headers, stream, on_token, "anthropic")
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
            "stream": stream}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if "openrouter" in base:
        headers.update({"HTTP-Referer": "https://pdfrush.local", "X-Title": "PDFRush"})
    return _strip_thinking(_post(base + "/chat/completions", body, headers, stream, on_token, "openai"))
