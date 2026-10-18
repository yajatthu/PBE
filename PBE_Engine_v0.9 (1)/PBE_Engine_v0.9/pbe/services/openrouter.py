import json, logging
import httpx
from pbe.settings import settings

log = logging.getLogger(__name__)
class OpenRouterError(RuntimeError):
    pass

class OpenRouterClient:
    def __init__(self):
        self.key = settings.OPENROUTER_API_KEY.strip()
        self.base = settings.OPENROUTER_BASE_URL
        self.models = list(dict.fromkeys([settings.OPENROUTER_PRIMARY_MODEL] + [m.strip() for m in settings.OPENROUTER_FALLBACK_MODELS.split(",") if m.strip()]))

    @property
    def enabled(self): return bool(self.key)

    async def chat(self, system: str, user: str):
        if not self.enabled: return None
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json", "HTTP-Referer": settings.PBE_APP_URL, "X-Title": "Polymorphic Business Engine"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.OPENROUTER_TIMEOUT_SECONDS, connect=10)) as c:
            for model in self.models:
                try:
                    payload = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0.1, "response_format": {"type": "json_object"}}
                    r = await c.post(f"{self.base}/chat/completions", headers=headers, json=payload)
                    r.raise_for_status()
                    content = r.json()["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    if not isinstance(parsed, dict): raise ValueError("Model response must be a JSON object")
                    return json.dumps(parsed)
                except Exception as exc:
                    # Keep secrets, provider payloads, and raw exception bodies out of API errors.
                    log.warning("OpenRouter attempt failed for configured model %s (%s)", model, type(exc).__name__)
        raise OpenRouterError("All configured OpenRouter models failed. Check server logs and provider configuration.")
