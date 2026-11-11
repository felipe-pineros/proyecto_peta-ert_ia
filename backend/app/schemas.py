"""Datos que el frontend envía a la API, validados con las mismas reglas que la base.

Validar aquí da mensajes claros (422) antes de llegar a Supabase; la base de datos
vuelve a comprobarlo todo, así que esto no es la única barrera.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


def _txt(max_len: int, min_len: int = 1):
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_len, max_length=max_len)]


Size = Literal["small", "medium", "large"]
SpeciesCode = Annotated[str, StringConstraints(pattern=r"^[a-z_]{2,30}$")]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254,
                                         pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=40,
                                         pattern=r"^[0-9+()\-\s]+$")]
Lat = Annotated[float, Field(ge=-90, le=90)]
Lng = Annotated[float, Field(ge=-180, le=180)]


class _Input(BaseModel):
    # Rechaza campos desconocidos (p. ej. alguien enviando "status" o "user_id").
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
class ProfileUpdate(_Input):
    display_name: _txt(80) | None = None
    phone: Phone | None = None


# ---------------------------------------------------------------------------
class PetCreate(_Input):
    name: _txt(80) | None = None
    species: SpeciesCode
    breed: _txt(80) | None = None
    color: _txt(80)
    size: Size
    distinctive_features: _txt(1000) | None = None


class PetUpdate(_Input):
    # La especie no se cambia después de crear la mascota (regla de la base).
    name: _txt(80) | None = None
    breed: _txt(80) | None = None
    color: _txt(80) | None = None
    size: Size | None = None
    distinctive_features: _txt(1000) | None = None


# ---------------------------------------------------------------------------
def _check_event_at(value: datetime | None) -> datetime | None:
    if value is None:
        return value
    if value.tzinfo is None:
        raise ValueError("La fecha debe incluir la zona horaria")
    if value > datetime.now(timezone.utc) + timedelta(hours=1):
        raise ValueError("La fecha no puede estar en el futuro")
    if value < datetime.now(timezone.utc) - timedelta(days=365 * 5):
        raise ValueError("La fecha es demasiado antigua")
    return value


class ReportCreate(_Input):
    type: Literal["lost", "found"]
    pet_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    species: SpeciesCode
    breed: _txt(80) | None = None
    color: _txt(80)
    size: Size
    distinctive_features: _txt(1000) | None = None
    event_at: datetime
    location_label: _txt(160) | None = None
    # Ubicación EXACTA marcada en el mapa. El backend guarda una copia pública redondeada.
    lat: Lat
    lng: Lng
    contact_phone: Phone | None = None
    contact_email: Email | None = None

    _event = field_validator("event_at")(_check_event_at)

    @model_validator(mode="after")
    def _pet_by_type(self):
        if self.type == "lost" and not self.pet_id:
            raise ValueError("Un reporte de mascota perdida necesita pet_id (registra primero la mascota)")
        if self.type == "found" and self.pet_id:
            raise ValueError("Un reporte de mascota encontrada no lleva pet_id")
        return self


class ReportUpdate(_Input):
    breed: _txt(80) | None = None
    color: _txt(80) | None = None
    size: Size | None = None
    distinctive_features: _txt(1000) | None = None
    event_at: datetime | None = None
    location_label: _txt(160) | None = None
    lat: Lat | None = None
    lng: Lng | None = None
    contact_phone: Phone | None = None
    contact_email: Email | None = None

    _event = field_validator("event_at")(_check_event_at)

    @model_validator(mode="after")
    def _coords_pair(self):
        if (self.lat is None) != (self.lng is None):
            raise ValueError("Envía lat y lng juntos")
        return self
