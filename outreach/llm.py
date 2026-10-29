"""Gemini client (REST, structured JSON output). Responses are cached, so re-runs cost nothing."""
import json

from .config import env
from .http import HttpError, request_json


class LLMError(Exception):
    pass


def available() -> bool:
    return bool(env("GEMINI_API_KEY"))


def generate_json(system: str, prompt: str, schema: dict, temperature: float = 0.8) -> dict:
    model = env("GEMINI_MODEL", "gemini-3.5-flash-lite")
    rpm = float(env("GEMINI_RPM", "8"))  # free tier is rate limited; throttle live calls only
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json",
                             "responseSchema": schema},
    }
    for use_cache in (True, False):  # a cached-but-unusable response gets one fresh retry
        try:
            r = request_json(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                             body=body, headers={"x-goog-api-key": env("GEMINI_API_KEY", required=True)},
                             min_interval=60 / rpm, cache=use_cache)
        except (HttpError, OSError) as e:  # OSError covers DNS/timeout/connection resets after retries
            raise LLMError(f"Gemini request failed: {e}") from None
        try:
            parts = r["candidates"][0]["content"]["parts"]
            return json.loads("".join(p.get("text", "") for p in parts if not p.get("thought")))
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            reason = r.get("promptFeedback") or (r.get("candidates") or [{}])[0].get("finishReason") or e
    raise LLMError(f"Unusable Gemini response ({reason})")


def embed(texts: list[str], dims: int = 256) -> list[list[float]]:
    """Unit-length Gemini embeddings, 100 texts per request (each chunk cached)."""
    model = "models/" + env("GEMINI_EMBED_MODEL", "gemini-embedding-001")
    out = []
    for i in range(0, len(texts), 100):
        reqs = [{"model": model, "content": {"parts": [{"text": t[:6000]}]}, "taskType": "SEMANTIC_SIMILARITY",
                 "outputDimensionality": dims} for t in texts[i:i + 100]]
        try:
            r = request_json(f"https://generativelanguage.googleapis.com/v1beta/{model}:batchEmbedContents",
                             body={"requests": reqs}, headers={"x-goog-api-key": env("GEMINI_API_KEY", required=True)},
                             min_interval=62, retries=2)  # free tier counts each text as a request; fail fast to the fallback
        except (HttpError, OSError) as e:  # OSError covers DNS/timeout/connection resets after retries
            raise LLMError(f"Gemini embedding failed: {e}") from None
        for e in r["embeddings"]:
            v = e["values"]
            n = sum(x * x for x in v) ** 0.5 or 1.0  # truncated dims are not normalised by the API
            out.append([x / n for x in v])
    return out
