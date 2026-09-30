"""Endpoints del catálogo: /libros."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from libreria.api.dependencies import (
    ActualizarLibroDep,
    AgregarLibroDep,
    EliminarLibroDep,
    LibroDep,
    ListarLibrosDep,
    PaginacionDep,
    Respuestas,
    requiere_admin,
)
from libreria.api.schemas import LibroCreate, LibroRead, LibroUpdate
from libreria.aplicacion.casos_uso import ActualizarLibroComando, FiltrosLibros
from libreria.dominio.modelos import Libro

router = APIRouter(prefix="/libros", tags=["libros"])

# Consultar el catálogo es público; modificarlo es solo para administradores.
# La dependencia se pone en el decorador (no como parámetro) porque el endpoint
# no necesita el usuario, solo que la verificación pase.
SOLO_ADMIN = [Depends(requiere_admin)]
_ERRORES_AUTH: Respuestas = {
    401: {"description": "No autenticado"},
    403: {"description": "Se requiere rol de administrador"},
}


@router.get("/", response_model=list[LibroRead], summary="Listar y filtrar libros")
def listar_libros(
    caso: ListarLibrosDep,
    pagina: PaginacionDep,
    autor: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    genero: Annotated[str | None, Query(min_length=2, max_length=50)] = None,
    en_stock: bool | None = None,
    precio_max: Annotated[float | None, Query(gt=0)] = None,
) -> list[Libro]:
    """Los mismos filtros que la opción 1 del menú de consola. Todos son opcionales."""
    filtros = FiltrosLibros(autor=autor, genero=genero, en_stock=en_stock, precio_max=precio_max)
    return pagina.aplicar(caso.ejecutar(filtros))


@router.post(
    "/",
    response_model=LibroRead,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar un libro",
    dependencies=SOLO_ADMIN,
    responses={**_ERRORES_AUTH, 409: {"description": "Ya existe un libro con ese ISBN"}},
)
def crear_libro(datos: LibroCreate, caso: AgregarLibroDep) -> Libro:
    # ISBN repetido -> LibroDuplicadoError -> 409 (ver app.py)
    return caso.ejecutar(datos.a_libro())


@router.get(
    "/{isbn}",
    response_model=LibroRead,
    summary="Obtener un libro",
    responses={404: {"description": "Libro no encontrado"}},
)
def obtener_libro(libro: LibroDep) -> Libro:
    # La dependencia ya buscó el libro (o respondió 404); aquí solo se devuelve
    return libro


@router.patch(
    "/{isbn}",
    response_model=LibroRead,
    summary="Modificar título, precio, cantidad o editorial",
    dependencies=SOLO_ADMIN,
    responses={**_ERRORES_AUTH, 404: {"description": "Libro no encontrado"}},
)
def actualizar_libro(libro: LibroDep, cambios: LibroUpdate, caso: ActualizarLibroDep) -> Libro:
    comando = ActualizarLibroComando(isbn=libro.isbn, **cambios.model_dump(exclude_none=True))
    return caso.ejecutar(comando)


@router.delete(
    "/{isbn}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un libro",
    dependencies=SOLO_ADMIN,
    responses={
        **_ERRORES_AUTH,
        404: {"description": "Libro no encontrado"},
        409: {"description": "El libro aparece en pedidos"},
    },
)
def eliminar_libro(libro: LibroDep, caso: EliminarLibroDep) -> None:
    caso.ejecutar(libro.isbn)  # RegistroEnUsoError -> 409 (ver app.py)
