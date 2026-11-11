"""Mi perfil y catálogo de especies."""
from fastapi import APIRouter, Depends, HTTPException

from .. import supabase
from ..auth import User, require_user
from ..schemas import ProfileUpdate


router = APIRouter(prefix="/api", tags=["perfil"])

PROFILE_COLS = "id,display_name,phone,created_at,updated_at"


@router.get("/me")
async def get_me(user: User = Depends(require_user)):
    rows = await supabase.db("GET", "profiles", token=user.token,
                             params={"select": PROFILE_COLS, "id": f"eq.{user.id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return rows[0] | {"email": user.email}


@router.patch("/me")
async def update_me(body: ProfileUpdate, user: User = Depends(require_user)):
    changes = body.model_dump(exclude_unset=True)
    if changes:
        await supabase.db("PATCH", "profiles", token=user.token,
                          params={"id": f"eq.{user.id}"}, json=changes, return_rows=False)
    return await get_me(user)


@router.get("/species")
async def list_species(user: User = Depends(require_user)):
    return await supabase.db("GET", "species", token=user.token,
                             params={"select": "code,name_es", "active": "eq.true", "order": "name_es"})
