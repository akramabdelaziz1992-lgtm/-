"""موصلات ChatGPT وClaude وGemini. المفتاح يفضل عند اللي يشغّل البرنامج."""

from __future__ import annotations

import base64
import json

import httpx

from midad.provider import Plan, ProviderError, extract_json, plan_from_json, prompt_for
from midad.safety import safe_rel

GEMINI_TEXT_MODEL = "gemini-3.1-pro-preview"
GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"
CLAUDE_MODEL = "claude-sonnet-5-5"


class MissingKeyProvider:
    name = "missing"

    def __init__(self, message: str):
        self._message = message

    def plan(self, request) -> Plan:
        raise ProviderError(self._message)


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str, model: str = CLAUDE_MODEL, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.model = model or CLAUDE_MODEL
        self._transport = transport

    def plan(self, request) -> Plan:
        payload = _payload(request)
        body = {
            "model": self.model,
            "max_tokens": 16000,
            "system": prompt_for(request.mode),
            "messages": [{"role": "user", "content": payload}],
        }
        data = _post(
            "https://api.anthropic.com/v1/messages",
            body,
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            self._transport,
            "Claude",
        )
        parts = data.get("content") or []
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
        if not text:
            raise ProviderError("Claude رجّع رد فاضي، فملفاتك ما اتغيرتش.")
        return plan_from_json(extract_json(text))


class GeminiTextProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str = GEMINI_TEXT_MODEL, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.model = model or GEMINI_TEXT_MODEL
        self._transport = transport

    def plan(self, request) -> Plan:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": prompt_for(request.mode)}]},
            "contents": [{"role": "user", "parts": [{"text": _payload(request)}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        data = _post(url, body, {"x-goog-api-key": self.api_key}, self._transport, "Gemini")
        return plan_from_json(extract_json(_gemini_text(data)))


class GeminiImageProvider:
    name = "gemini-image"

    def __init__(self, api_key: str, model: str = GEMINI_IMAGE_MODEL, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.model = model or GEMINI_IMAGE_MODEL
        self._transport = transport

    def plan(self, request) -> Plan:
        image, mime = fetch_gemini_image(self.api_key, self.model, request.message, self._transport)
        safe_rel("assets/gemini.png")
        return Plan(
            reply="صورة Gemini جاهزة للمراجعة. لسه ما اتكتبتش في المشروع.",
            blobs=[{"path": "assets/gemini.png", "data": image, "mime": mime}],
        )


def fetch_gemini_image(api_key: str, model: str, prompt: str, transport: httpx.BaseTransport | None = None) -> tuple[bytes, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    data = _post(url, body, {"x-goog-api-key": api_key}, transport, "Gemini")
    return parse_gemini_image(data)


def parse_gemini_image(data: dict) -> tuple[bytes, str]:
    for candidate in data.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            raw = inline.get("data")
            if not raw:
                continue
            mime = str(inline.get("mimeType") or inline.get("mime_type") or "image/png")
            try:
                blob = base64.b64decode(raw)
            except ValueError as exc:
                raise ProviderError("صورة Gemini مش مفهومة، فملفاتك ما اتغيرتش.") from exc
            if not blob:
                continue
            return blob, mime
    raise ProviderError("Gemini ما رجّعش صورة، فملفاتك ما اتغيرتش.")


def _payload(request) -> str:
    return json.dumps(
        {
            "mode": request.mode,
            "instruction": request.message,
            "active_file": request.active_file,
            "tree": request.tree,
            "files": request.files,
        },
        ensure_ascii=False,
    )


def _gemini_text(data: dict) -> str:
    texts = []
    for candidate in data.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            if part.get("thought"):
                continue
            if part.get("text"):
                texts.append(str(part["text"]))
    if not texts:
        raise ProviderError("Gemini رجّع رد فاضي، فملفاتك ما اتغيرتش.")
    return "\n".join(texts)


def _post(url: str, body: dict, headers: dict, transport: httpx.BaseTransport | None, label: str) -> dict:
    try:
        with httpx.Client(transport=transport, timeout=90) as client:
            response = client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise ProviderError(f"الاتصال بـ {label} فشل. راجع المفتاح.") from exc
    if response.status_code >= 400:
        raise ProviderError(f"{label} ردّ برمز {response.status_code}. راجع المفتاح والنموذج.")
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise ProviderError(f"{label} رجّع رد مش مفهوم.") from exc
