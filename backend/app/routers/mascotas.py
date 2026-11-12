"""Mis mascotas (identidad del animal, separada de los reportes)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from .. import supabase
from ..auth import User, require_user
from ..schemas import PetCreate, PetUpdate


router = APIRouter(prefix="/api/pets", tags=["mascotas"])

PET_COLS = "id,name,species,breed,color,size,distinctive_features,created_at,updated_at"


@router.get("")
async def list_pets(user: User = Depends(require_user)):
    # RLS ya limita a las mascotas del usuario; el filtro es solo por claridad.
    return await supabase.db("GET", "pets", token=user.token, params={
        "select": PET_COLS, "owner_id": f"eq.{user.id}", "order": "created_at.desc"})


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_pet(body: PetCreate, user: User = Depends(require_user)):
    if user.is_anonymous:  # la base también lo impide (migración 4)
        raise HTTPException(status_code=403, detail="Para registrar una mascota crea una cuenta")
    rows = await supabase.db("POST", "pets", token=user.token,
                             params={"select": PET_COLS}, json=body.model_dump(exclude_none=True))
    return rows[0]


@router.get("/{pet_id}")
async def get_pet(pet_id: UUID, user: User = Depends(require_user)):
    rows = await supabase.db("GET", "pets", token=user.token,
                             params={"select": PET_COLS, "id": f"eq.{pet_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Mascota no encontrada")
    return rows[0]


@router.patch("/{pet_id}")
async def update_pet(pet_id: UUID, body: PetUpdate, user: User = Depends(require_user)):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return await get_pet(pet_id, user)
    rows = await supabase.db("PATCH", "pets", token=user.token,
                             params={"select": PET_COLS, "id": f"eq.{pet_id}"}, json=changes)
    if not rows:  # no existe o no es del usuario (RLS)
        raise HTTPException(status_code=404, detail="Mascota no encontrada")
    return rows[0]
