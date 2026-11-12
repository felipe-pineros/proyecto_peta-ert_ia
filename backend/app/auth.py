"""Validación de la sesión del usuario.

El navegador inicia sesión con supabase-js y envía `Authorization: Bearer <token>`.
Aquí se pregunta a Supabase Auth si el token es válido. Ventaja frente a validar la
firma localmente: si la sesión se cierra o la cuenta se borra, deja de servir al instante.
"""
from dataclasses import dataclass

from fastapi import Header, HTTPException
import httpx

from . import supabase
from .config import get_settings


@dataclass(frozen=True)
class User:
    id: str
    email: str | None
    token: str
    # Invitado creado por el reporte rápido de la página principal (sin correo ni contraseña).
    is_anonymous: bool = False


async def require_user(authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar")
    token = authorization[7:].strip()
    if not token or len(token) > 8192:
        raise HTTPException(status_code=401, detail="Sesión no válida")

    s = get_settings()
    try:
        response = await supabase.client().get(
            f"{s.supabase_url}/auth/v1/user",
            headers={"apikey": s.publishable_key, "Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="No se pudo validar la sesión") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Sesión no válida o vencida")
    try:
        data = response.json()
        return User(id=str(data["id"]), email=data.get("email") or None, token=token,
                    is_anonymous=bool(data.get("is_anonymous", False)))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Sesión no válida") from exc
