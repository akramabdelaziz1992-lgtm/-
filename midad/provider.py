"""مولّد الخطة: نموذج متوافق مع OpenAI، أو وضع تجربة من غير مفتاح."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import httpx

from midad.safety import Operation

MAX_FILE_CHARS = 20_000
MAX_TOTAL_CHARS = 80_000

SYSTEM_PROMPT = """You are Midad, a careful coding assistant inside an Arabic workshop.
The user writes in Arabic. Return one JSON object and nothing else:
{"reply_ar":"short Arabic explanation","operations":[{"op":"replace","path":"main.py","search":"exact unique snippet","replace":"new snippet"}]}
Operations may also be {"op":"create","path":"new.py","content":"..."} or {"op":"delete","path":"old.txt"}.
Rules:
- Prefer replace on existing files. search must be copied exactly from the file, including spaces and newlines, and must occur once.
- Use create only for a path that does not exist. Never recreate an existing file.
- Use delete only when the user explicitly asked to delete that file.
- Do not touch files unrelated to the request.
- Keep the project runnable. Small edits only.
- reply_ar is Arabic, plain text, no markdown fence.
"""


def prompt_for(mode: str) -> str:
    extra = {
        "site": "Mode website: create a complete responsive Arabic site in web/index.html, web/styles.css and web/site.js. Distinct art direction, real copy, no purple gradient, no lorem ipsum.",
        "game": "Mode game: create a playable canvas game in play/index.html, play/game.js and play/style.css. Include score, restart, keyboard controls and Web Audio sounds.",
        "image": "Mode image: do not rewrite source files.",
        "sound": "Mode sound: create only sound/index.html and sound/sfx.js using the Web Audio API.",
        "edit": "Mode edit: change existing files with one unique search snippet. Do not recreate files.",
    }.get(mode, "Mode edit: change existing files with one unique search snippet.")
    return SYSTEM_PROMPT + "\n" + extra


class ProviderError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class PlanRequest:
    message: str
    tree: list[str]
    files: dict[str, str]
    history: list[dict]
    active_file: str | None = None
    mode: str = "edit"


@dataclass
class Plan:
    reply: str
    operations: list[Operation] = field(default_factory=list)
    blobs: list = field(default_factory=list)


def visible_files(files: dict[str, str]) -> dict[str, str]:
    shown: dict[str, str] = {}
    budget = MAX_TOTAL_CHARS
    for path in sorted(files):
        if budget <= 0:
            break
        chunk = files[path][: min(MAX_FILE_CHARS, budget)]
        shown[path] = chunk
        budget -= len(chunk)
    return shown


def extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("رد النموذج مش JSON، فملفاتك ما اتغيرتش.") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError("رد النموذج مش مفهوم، فملفاتك ما اتغيرتش.") from exc
    if not isinstance(data, dict):
        raise ProviderError("رد النموذج مش مفهوم، فملفاتك ما اتغيرتش.")
    return data


def plan_from_json(data: dict) -> Plan:
    reply = str(data.get("reply_ar") or data.get("reply") or "").strip()
    raw_operations = data.get("operations") or []
    if not isinstance(raw_operations, list):
        raise ProviderError("قائمة التعديلات مش مفهومة، فملفاتك ما اتغيرتش.")
    operations: list[Operation] = []
    for item in raw_operations:
        if not isinstance(item, dict):
            raise ProviderError("تعديل مش مفهوم، فملفاتك ما اتغيرتش.")
        replace = item.get("replace")
        operations.append(
            Operation(
                op=str(item.get("op") or ""),
                path=str(item.get("path") or ""),
                content=str(item.get("content") or ""),
                search=str(item.get("search") or ""),
                replace="" if replace is None else str(replace),
            )
        )
    if not reply and not operations:
        raise ProviderError("النموذج رجّع رد فاضي.")
    return Plan(reply=reply or "جهّزت تعديل للمراجعة.", operations=operations)


class DemoProvider:
    name = "demo"

    def plan(self, request: PlanRequest) -> Plan:
        from midad.studio import studio_plan

        message = request.message
        files = request.files
        if request.mode in {"site", "game", "image", "sound"}:
            studio = studio_plan(request.mode, request.tree)
            if studio is not None:
                return studio
        if any(word in message for word in ("بايظ", "باظ", "مكسور")):
            return Plan(
                reply="هحاول أحط سطر مكسور عشان تتأكد إن الفحص رافضه.",
                operations=[
                    Operation(op="replace", path="main.py", search="return a + b", replace="return a +")
                ],
            )
        if "طرح" in message:
            return _arithmetic(files, "sub", "طرح", "a - b", 'print("طرح:", sub(5, 2))')
        if "ضرب" in message:
            return _arithmetic(files, "mul", "ضرب", "a * b", 'print("ضرب:", mul(4, 3))')
        if not files and any(word in message for word in ("صفحة", "موقع", "html", "HTML")):
            return Plan(
                reply="هعمل صفحة جديدة. راجع الفرق وبعدين طبّق.",
                operations=[Operation(op="create", path="index.html", content=_PAGE)],
            )
        if not files and any(word in message for word in ("بايثون", "python", "برنامج")):
            return Plan(
                reply="هعمل برنامج بايثون صغير. راجع الفرق وبعدين طبّق.",
                operations=[Operation(op="create", path="main.py", content=_HELLO)],
            )
        return Plan(
            reply=(
                "وضع التجربة يبني موقع بيت النور، ولعبة شرارة، ورسمة فانوس، ومؤثرات صوت. "
                "وفي وضع التعديل يضيف طرح أو ضرب للآلة الحاسبة. "
                "ChatGPT وClaude وGemini يشتغلوا لما تتسجل مفاتيحهم، والكتابة برضو بعد المراجعة."
            )
        )


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, base_url: str, model: str, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._transport = transport

    def plan(self, request: PlanRequest) -> Plan:
        history = []
        for item in request.history[-6:]:
            content = str(item.get("content") or "")[:1000]
            role = "assistant" if item.get("role") == "assistant" else "user"
            history.append({"role": role, "content": content})
        payload_text = json.dumps(
            {
                "instruction": request.message,
                "mode": request.mode,
                "active_file": request.active_file,
                "tree": request.tree,
                "files": request.files,
            },
            ensure_ascii=False,
        )
        messages = [{"role": "system", "content": prompt_for(request.mode)}, *history, {"role": "user", "content": payload_text}]
        data = self._complete(messages)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("رد النموذج ناقص، فملفاتك ما اتغيرتش.") from exc
        if isinstance(content, list):
            content = "".join(
                str(part.get("text") or "") for part in content if isinstance(part, dict)
            )
        return plan_from_json(extract_json(str(content)))

    def _complete(self, messages: list[dict]) -> dict:
        url = self.base_url + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body = {"model": self.model, "temperature": 0.1, "messages": messages, "response_format": {"type": "json_object"}}
        try:
            with httpx.Client(transport=self._transport, timeout=60) as client:
                response = client.post(url, headers=headers, json=body)
                if response.status_code == 400 and "response_format" in body:
                    body.pop("response_format")
                    response = client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise ProviderError("الاتصال بالنموذج فشل. راجع المفتاح والعنوان.") from exc
        if response.status_code >= 400:
            raise ProviderError(f"النموذج ردّ برمز {response.status_code}. راجع المفتاح والنموذج والعنوان.")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("النموذج رجّع رد مش مفهوم.") from exc


def resolve_provider(settings: dict, override: object | None = None, environ: dict | None = None, engine: str = "demo", mode: str = "edit"):
    if override is not None:
        return override
    env = os.environ if environ is None else environ
    if env.get("MIDAD_PROVIDER") == "demo" or engine in {"", "demo"}:
        return DemoProvider()
    from midad.engines import (
        CLAUDE_MODEL,
        GEMINI_IMAGE_MODEL,
        GEMINI_TEXT_MODEL,
        ClaudeProvider,
        GeminiImageProvider,
        GeminiTextProvider,
        MissingKeyProvider,
    )

    if mode == "image":
        gemini_key = str(settings.get("gemini_api_key") or env.get("GEMINI_API_KEY") or "")
        if not gemini_key:
            return MissingKeyProvider("توليد الصورة من Gemini يحتاج مفتاح Google في الإعدادات.")
        return GeminiImageProvider(gemini_key, str(settings.get("gemini_image_model") or GEMINI_IMAGE_MODEL))
    if engine == "claude":
        key = str(settings.get("anthropic_api_key") or env.get("ANTHROPIC_API_KEY") or "")
        if not key:
            return MissingKeyProvider("Claude يحتاج مفتاح Anthropic في الإعدادات.")
        return ClaudeProvider(key, str(settings.get("anthropic_model") or CLAUDE_MODEL))
    if engine == "gemini":
        key = str(settings.get("gemini_api_key") or env.get("GEMINI_API_KEY") or "")
        if not key:
            return MissingKeyProvider("Gemini يحتاج مفتاح Google في الإعدادات.")
        return GeminiTextProvider(key, str(settings.get("gemini_text_model") or GEMINI_TEXT_MODEL))
    if engine in {"chatgpt", "openai"}:
        key = str(settings.get("openai_api_key") or settings.get("api_key") or env.get("OPENAI_API_KEY") or "")
        if not key:
            return MissingKeyProvider("ChatGPT يحتاج مفتاح OpenAI في الإعدادات.")
        base_url = str(settings.get("base_url") or env.get("OPENAI_BASE_URL") or "https://api.openai.com/v1")
        model = str(settings.get("openai_model") or settings.get("model") or env.get("OPENAI_MODEL") or "gpt-4.1")
        return OpenAIProvider(api_key=key, base_url=base_url, model=model)
    return DemoProvider()


def _arithmetic(files: dict[str, str], function_name: str, label: str, expression: str, print_line: str) -> Plan:
    main = files.get("main.py", "")
    if f"def {function_name}(" in main:
        return Plan(reply=f"دالة {label} موجودة أصلًا، فسيبت الملفات زي ما هي.")
    anchor = "def add(a, b):\n    return a + b\n"
    printed = '    print("جمع:", add(2, 3))\n'
    if main.count(anchor) != 1 or printed not in main:
        return Plan(
            reply="مش لاقي موضع واحد آمن في main.py، فسيبت الملفات زي ما هي. وصّل مفتاح النموذج عشان يفهم المشروع كما هو."
        )
    added = anchor + f"\n\ndef {function_name}(a, b):\n    return {expression}\n"
    return Plan(
        reply=f"هضيف دالة {label} في main.py بس. notes.txt وباقي الملفات مش هتتلمس. راجع الفرق وبعدين طبّق.",
        operations=[
            Operation(op="replace", path="main.py", search=anchor, replace=added),
            Operation(op="replace", path="main.py", search=printed, replace=printed + f"    {print_line}\n"),
        ],
    )


_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>ترحيب</title>
</head>
<body>
  <h1>أهلاً</h1>
</body>
</html>
"""

_HELLO = '''def main():
    print("أهلاً")


if __name__ == "__main__":
    main()
'''
