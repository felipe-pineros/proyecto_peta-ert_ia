from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException

from .config import get_settings


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    access_token: str


async def require_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar")
    token = authorization[7:].strip()
    if not token or len(token) > 8192:
        raise HTTPException(status_code=401, detail="Sesión no válida")

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{settings.supabase_url}/auth/v1/user",
                headers={"apikey": settings.supabase_anon_key, "Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="No se pudo validar la sesión") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Sesión no válida o vencida")
    try:
        user_id = response.json()["id"]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Respuesta de sesión no válida") from exc
    return AuthenticatedUser(id=str(user_id), access_token=token)
