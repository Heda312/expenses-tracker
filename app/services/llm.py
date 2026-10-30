"""Klien LLM lokal (Ollama) - opsional.

LLM di sini HANYA dipakai untuk memilih satu nama kategori.
LLM tidak pernah diminta menghasilkan nominal atau tanggal.
Kalau LLM mati / lambat / menjawab ngawur, aplikasi tetap jalan.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PROMPT = """Klasifikasikan merchant berikut ke satu kategori.
Merchant: {merchant}
Kategori: {categories}
Jawab hanya nama kategori, tanpa penjelasan."""


async def classify_merchant(merchant: str, categories: list[str]) -> str | None:
    """Minta LLM memilih kategori. Hasil divalidasi harus salah satu dari daftar."""
    if not settings.llm_enabled or not merchant.strip():
        return None

    payload = {
        "model": settings.ollama_model,
        "prompt": PROMPT.format(merchant=merchant[:80], categories=", ".join(categories)),
        "stream": False,
        "options": {"temperature": 0, "num_predict": 4},
    }

    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
            response = await client.post(f"{settings.ollama_url}/api/generate", json=payload)
            response.raise_for_status()
            answer = str(response.json().get("response", "")).strip()
    except Exception:
        return None

    for name in categories:
        if answer.lower() == name.lower():
            return name
    return None
