"""Casos de uso del catálogo en la base de datos: alta, cambios, baja y consultas.

Los permisos (solo un admin modifica el catálogo) los revisa la API antes de
llamar a estos casos de uso.
"""

import logging
from dataclasses import dataclass

from libreria.aplicacion.puertos import UnidadDeTrabajo
from libreria.dominio.catalogo import aplicar_filtros, construir_filtros
from libreria.dominio.excepciones import LibroNoEncontradoError, RegistroEnUsoError
from libreria.dominio.modelos import Libro

log = logging.getLogger(__name__)


# ── Comandos ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActualizarLibroComando:
    """Los campos en None no se tocan."""

    isbn: str
    titulo: str | None = None
    precio: float | None = None
    cantidad_disponible: int | None = None
    editorial: str | None = None

    def cambios(self) -> dict[str, str | float | int]:
        campos = {
            "titulo": self.titulo,
            "precio": self.precio,
            "cantidad_disponible": self.cantidad_disponible,
            "editorial": self.editorial,
        }
        return {campo: valor for campo, valor in campos.items() if valor is not None}


@dataclass(frozen=True)
class FiltrosLibros:
    """Los mismos filtros que la opción 1 del menú de consola. Todos son opcionales."""

    autor: str | None = None
    genero: str | None = None
    en_stock: bool | None = None
    precio_max: float | None = None


# ── Escritura ────────────────────────────────────────────────────────────────


class AgregarLibro:
    """Un administrador da de alta un libro. LibroDuplicadoError si el ISBN ya existe."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, libro: Libro) -> Libro:
        with self._uow as uow:
            uow.libros.agregar(libro)
            uow.confirmar()
        log.info("Libro %s agregado", libro.isbn)
        return libro


class ActualizarLibro:
    """Cambia título, precio, cantidad o editorial de un libro.

    Los datos nuevos pasan por el dominio (Libro.con_cambios), así se aplican
    las mismas reglas que al crearlo o se lanza LibroInvalidoError sin guardar.
    """

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, cmd: ActualizarLibroComando) -> Libro:
        with self._uow as uow:
            libro = _obtener(uow, cmd.isbn)
            actualizado = libro.con_cambios(**cmd.cambios())
            uow.libros.guardar(actualizado)
            uow.confirmar()
        log.info("Libro %s actualizado: %s", cmd.isbn, cmd.cambios())
        return actualizado


class EliminarLibro:
    """Borra un libro del catálogo, solo si nunca se ha vendido.

    Si ya aparece en pedidos, se lanza RegistroEnUsoError: borrarlo dejaría
    esos pedidos sin libro. Para retirarlo de la venta basta con dejar su
    cantidad en 0.
    """

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, isbn: str) -> None:
        with self._uow as uow:
            libro = _obtener(uow, isbn)
            if uow.pedidos.incluyen_libro(isbn):
                raise RegistroEnUsoError(
                    f"'{libro.titulo}' aparece en pedidos; no se puede borrar. "
                    "Deja su cantidad en 0 para retirarlo de la venta."
                )
            uow.libros.eliminar(isbn)
            uow.confirmar()
        log.info("Libro %s eliminado", isbn)


# ── Consultas ────────────────────────────────────────────────────────────────


class ObtenerLibro:
    """Un libro por su ISBN. LibroNoEncontradoError si no existe."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, isbn: str) -> Libro:
        with self._uow as uow:
            return _obtener(uow, isbn)


class ListarLibros:
    """Los libros del catálogo (ordenados por título) que cumplen los filtros."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, filtros: FiltrosLibros | None = None) -> list[Libro]:
        filtros = filtros or FiltrosLibros()  # sin filtros: todos los libros
        with self._uow as uow:
            libros = uow.libros.listar()
        # Misma lógica que la consola: las estrategias de filtrado viven en el dominio
        estrategias = construir_filtros(
            autor=filtros.autor,
            genero=filtros.genero,
            en_stock=filtros.en_stock,
            precio_max=filtros.precio_max,
        )
        return aplicar_filtros(libros, estrategias)


def _obtener(uow: UnidadDeTrabajo, isbn: str) -> Libro:
    libro = uow.libros.obtener(isbn)
    if libro is None:
        raise LibroNoEncontradoError(f"No existe el libro {isbn}")
    return libro
