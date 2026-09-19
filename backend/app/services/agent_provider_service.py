"""
Agent provider service.

Manages AI provider configurations (Anthropic, Ollama, OpenAI-compatible),
storing API keys Fernet-encrypted at rest — the same pattern used for DB
connection passwords. Handles the actual code-generation call, adapting the
request/response shape to whichever provider is active.
"""
from __future__ import annotations

import uuid
import base64
from typing import Any

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent_provider import AgentProvider


# ── Encryption (mirrors connection_service) ───────────────────────────────────

def _fernet() -> Fernet:
    key = settings.SECRET_KEY.encode()[:32].ljust(32, b"0")
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    return _fernet().decrypt(s.encode()).decode()


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def list_providers(db: AsyncSession) -> list[AgentProvider]:
    r = await db.execute(select(AgentProvider).order_by(AgentProvider.name))
    return list(r.scalars().all())


async def get_provider(db: AsyncSession, pid: str) -> AgentProvider | None:
    return await db.get(AgentProvider, pid)


async def get_active_provider(db: AsyncSession) -> AgentProvider | None:
    r = await db.execute(select(AgentProvider).where(AgentProvider.is_active == True))  # noqa: E712
    return r.scalars().first()


async def create_provider(db: AsyncSession, data: dict) -> AgentProvider:
    # If this is the first provider, make it active by default
    existing = await list_providers(db)
    make_active = data.get("is_active", False) or len(existing) == 0

    if make_active:
        # Deactivate all others — only one active at a time
        await db.execute(update(AgentProvider).values(is_active=False))

    provider = AgentProvider(
        id=str(uuid.uuid4()),
        name=data["name"],
        provider_type=data["provider_type"],
        model=data["model"],
        base_url=data.get("base_url"),
        api_key_enc=encrypt(data["api_key"]) if data.get("api_key") else None,
        is_active=make_active,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


async def update_provider(db: AsyncSession, pid: str, data: dict) -> AgentProvider | None:
    provider = await db.get(AgentProvider, pid)
    if not provider:
        return None

    if "name" in data:          provider.name = data["name"]
    if "provider_type" in data: provider.provider_type = data["provider_type"]
    if "model" in data:         provider.model = data["model"]
    if "base_url" in data:      provider.base_url = data["base_url"]
    # Only update the key if a new one was provided (blank means "keep existing")
    if data.get("api_key"):
        provider.api_key_enc = encrypt(data["api_key"])

    await db.commit()
    await db.refresh(provider)
    return provider


async def set_active(db: AsyncSession, pid: str) -> bool:
    provider = await db.get(AgentProvider, pid)
    if not provider:
        return False
    await db.execute(update(AgentProvider).values(is_active=False))
    provider.is_active = True
    await db.commit()
    return True


async def delete_provider(db: AsyncSession, pid: str) -> bool:
    r = await db.execute(delete(AgentProvider).where(AgentProvider.id == pid))
    await db.commit()
    return r.rowcount > 0


# ── Provider-aware completion ─────────────────────────────────────────────────

async def _call_anthropic(provider: AgentProvider, system: str, user_message: str) -> str:
    api_key = decrypt(provider.api_key_enc) if provider.api_key_enc else None
    if not api_key:
        raise ValueError("Anthropic provider requires an API key.")

    url = (provider.base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
    payload = {
        "model": provider.model,
        "max_tokens": 1500,
        "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return "\n".join(
        block["text"] for block in data.get("content", []) if block.get("type") == "text"
    )


async def _call_openai_compatible(provider: AgentProvider, system: str, user_message: str) -> str:
    """
    Handles Ollama and any OpenAI-compatible endpoint. Ollama's OpenAI-compatible
    API lives at {base_url}/v1/chat/completions and uses the system prompt as a
    message with role 'system'.
    """
    base = (provider.base_url or "http://localhost:11434").rstrip("/")
    # Allow base_url to already include /v1
    if base.endswith("/v1"):
        url = base + "/chat/completions"
    else:
        url = base + "/v1/chat/completions"

    payload = {
        "model": provider.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    headers = {"content-type": "application/json"}
    # Some OpenAI-compatible servers (not Ollama) require a key
    if provider.api_key_enc:
        headers["authorization"] = f"Bearer {decrypt(provider.api_key_enc)}"

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


async def complete(provider: AgentProvider, system: str, user_message: str) -> str:
    if provider.provider_type == "anthropic":
        return await _call_anthropic(provider, system, user_message)
    else:  # ollama or openai_compatible
        return await _call_openai_compatible(provider, system, user_message)


async def test_provider(provider: AgentProvider) -> dict:
    """Ping the provider with a trivial prompt to confirm it works."""
    try:
        text = await complete(
            provider,
            system="You are a test. Reply with exactly the word: ok",
            user_message="Say ok",
        )
        return {"ok": True, "error": None, "sample": text.strip()[:100]}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
