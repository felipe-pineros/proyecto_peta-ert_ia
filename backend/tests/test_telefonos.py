"""Teléfonos: se guardan siempre como "+57 300 123 4567" y se rechazan los mal escritos.

Antes un número con un dígito de más o de menos se guardaba tal cual y el botón de WhatsApp
lo enviaba a otro país ("+35…" en vez de "+57…"). Estas pruebas no usan internet.
"""
from pydantic import TypeAdapter, ValidationError
import pytest

from app.schemas import Phone, ReportCreate


PHONE = TypeAdapter(Phone)


@pytest.mark.parametrize("escrito, guardado", [
    ("300 123 4567", "+57 300 123 4567"),
    ("3001234567", "+57 300 123 4567"),
    ("+57 300 123 4567", "+57 300 123 4567"),
    ("57 300-123-4567", "+57 300 123 4567"),
    ("(601) 234 5678", "+57 601 234 5678"),     # fijo de Bogotá
    ("+1 415 555 0100", "+14155550100"),         # otro país: con "+"
])
def test_telefonos_validos_se_normalizan(escrito, guardado):
    assert PHONE.validate_python(escrito) == guardado


@pytest.mark.parametrize("escrito", ["300 123 456", "30012345678", "322222222222", "1234567890", "+57 300 123 45"])
def test_telefonos_mal_escritos_se_rechazan(escrito):
    with pytest.raises(ValidationError, match="10 dígitos"):
        PHONE.validate_python(escrito)


def test_el_reporte_usa_la_misma_regla():
    with pytest.raises(ValidationError, match="10 dígitos"):
        ReportCreate.model_validate({"type": "found", "species": "dog", "event_at": "2026-11-18T10:00:00Z",
                                     "lat": 4.6, "lng": -74.1, "contact_phone": "300 123 456"})
