"""Reportes de ventas: /reportes. Solo para administradores."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from libreria.api.dependencies import GastoPorUsuarioDep, LibrosMasVendidosDep, requiere_admin
from libreria.api.schemas import LibroVendidoRead, TotalUsuarioRead

router = APIRouter(
    prefix="/reportes",
    tags=["reportes"],
    # Dependencia a nivel router: se ejecuta antes de CADA endpoint de este archivo
    dependencies=[Depends(requiere_admin)],
    responses={401: {"description": "No autenticado"}, 403: {"description": "Solo admin"}},
)


@router.get("/usuarios", response_model=list[TotalUsuarioRead], summary="Gasto por usuario")
def total_por_usuario(caso: GastoPorUsuarioDep) -> list[TotalUsuarioRead]:
    return [
        TotalUsuarioRead(nombre=g.nombre, pedidos=g.pedidos, total=g.total) for g in caso.ejecutar()
    ]


@router.get("/mas-vendidos", response_model=list[LibroVendidoRead], summary="Libros más vendidos")
def libros_mas_vendidos(
    caso: LibrosMasVendidosDep, limite: Annotated[int, Query(ge=1, le=50)] = 5
) -> list[LibroVendidoRead]:
    return [LibroVendidoRead(titulo=v.titulo, cantidad=v.cantidad) for v in caso.ejecutar(limite)]
