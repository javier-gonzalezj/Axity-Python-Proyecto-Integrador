"""Puertos: lo que la lógica de negocio necesita del mundo exterior.

Un puerto describe QUÉ necesita el servicio, no CÓMO se hace. Las clases que
lo cumplen (los adaptadores, en la capa de infraestructura) no heredan de él:
basta con que tengan los mismos métodos (tipado estructural). mypy verifica que
efectivamente los tengan.

Este módulo solo importa modelos del dominio; nunca json, sqlalchemy ni httpx.

Familias de puertos:

- RepositorioCatalogo y LectorLibros: el catálogo completo de la consola (un
  archivo JSON) y la lectura de libros desde archivos externos (CSV).
- RepositorioLibros, RepositorioPedidos, RepositorioUsuarios,
  ConsultasVentas y UnidadDeTrabajo: todo lo que los casos de uso necesitan de
  la base de datos, sin conocer SQLAlchemy.
- Notificador: avisarle algo a una persona (hoy, al cliente sobre su pedido),
  sin saber si viaja por HTTP, correo o solo queda en el log.
- Hasher: convertir contraseñas en hashes y verificarlas, sin saber qué
  algoritmo se usa (hoy, Argon2).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self

from libreria.dominio.modelos import Libreria, Libro, Usuario
from libreria.dominio.pedidos import Pedido


class RepositorioCatalogo(Protocol):
    """Persistencia del catálogo completo de la librería.

    Contrato que todo adaptador debe respetar (principio de Liskov):
    - cargar() devuelve los libros ya validados como objetos Libro.
    - Si algo falla, ambos métodos lanzan LibreriaError (o una subclase),
      nunca OSError, json.JSONDecodeError ni errores de SQLAlchemy.
      ServicioCatalogo depende de esto para revertir los cambios.
    """

    def cargar(self) -> Libreria: ...

    def guardar(self, data: Libreria) -> None: ...


class LectorLibros(Protocol):
    """Lee libros de un archivo externo (hoy, CSV).

    Contrato:
    - Devuelve (libros válidos, errores). Una fila inválida no detiene la
      lectura: su motivo queda en la lista de errores ("Línea 3: ...").
    - Si el archivo no se puede leer en absoluto, lanza LibreriaError (o una
      subclase), nunca OSError ni csv.Error.
    """

    def leer(self, ruta: str | Path) -> tuple[list[Libro], list[str]]: ...


# ── Base de datos: repositorios + unidad de trabajo ─────────────────────────
# Contrato común de los tres repositorios:
# - Reciben y devuelven objetos del dominio (Libro, Pedido, Usuario), nunca
#   filas ni sesiones.
# - NUNCA confirman (commit): solo registran cambios. Confirmar o revertir le
#   toca a la UnidadDeTrabajo, para que varios cambios se guarden juntos o
#   ninguno (p. ej. descontar stock y crear el pedido).
# - Los errores de la base se traducen a LibreriaError.


class RepositorioLibros(Protocol):
    def obtener(self, isbn: str) -> Libro | None:
        """El libro con ese ISBN, o None si no existe."""
        ...

    def obtener_varios(self, isbns: Iterable[str]) -> dict[str, Libro]:
        """Los libros que existen, por ISBN. Los que no existen no aparecen."""
        ...

    def listar(self) -> list[Libro]:
        """Todos los libros, ordenados por título."""
        ...

    def agregar(self, libro: Libro) -> None:
        """Registra un libro nuevo. LibroDuplicadoError si el ISBN ya existe."""
        ...

    def guardar(self, libro: Libro) -> None:
        """Guarda los cambios de un libro existente. LibroNoEncontradoError si no existe."""
        ...

    def eliminar(self, isbn: str) -> None:
        """Borra el libro. LibroNoEncontradoError si no existe.

        No revisa si tiene ventas: esa regla la aplica el caso de uso.
        """
        ...


class RepositorioPedidos(Protocol):
    def obtener(self, pedido_id: int) -> Pedido | None:
        """El pedido con ese id, o None si no existe."""
        ...

    def listar(self, estatus: str | None = None) -> list[Pedido]:
        """Todos los pedidos (o solo los de un estatus), del más antiguo al más nuevo."""
        ...

    def de_usuario(self, usuario_id: int) -> list[Pedido]:
        """Los pedidos de un usuario, del más antiguo al más nuevo."""
        ...

    def incluyen_libro(self, isbn: str) -> bool:
        """True si algún pedido (de cualquier estatus) contiene ese libro."""
        ...

    def agregar(self, pedido: Pedido) -> None:
        """Registra un pedido nuevo y le asigna su id (pedido.id deja de ser None)."""
        ...

    def guardar(self, pedido: Pedido) -> None:
        """Guarda el estatus de un pedido existente. PedidoNoEncontradoError si no existe.

        Las líneas no se guardan: una vez creado, un pedido no cambia de libros.
        """
        ...


class RepositorioUsuarios(Protocol):
    """Usuarios y sus contraseñas.

    El hash de la contraseña viaja APARTE del objeto Usuario (que no lo tiene),
    así nunca termina en una respuesta de la API por accidente.
    """

    def obtener(self, usuario_id: int) -> Usuario | None:
        """El usuario con ese id, o None si no existe."""
        ...

    def buscar_por_email(self, email: str) -> Usuario | None:
        """El usuario con ese email (sin espacios alrededor), o None."""
        ...

    def listar(self) -> list[Usuario]:
        """Todos los usuarios, ordenados por nombre."""
        ...

    def agregar(self, usuario: Usuario, password_hash: str | None = None) -> None:
        """Registra un usuario nuevo y le asigna su id (usuario.id deja de ser None).

        EmailDuplicadoError si el email ya existe.
        """
        ...

    def guardar(self, usuario: Usuario) -> None:
        """Guarda nombre, email, teléfono y rol de un usuario existente.

        UsuarioNoEncontradoError si no existe; EmailDuplicadoError si el email
        nuevo ya lo usa otro usuario.
        """
        ...

    def eliminar(self, usuario_id: int) -> None:
        """Borra el usuario. UsuarioNoEncontradoError si no existe.

        No revisa si tiene pedidos: esa regla la aplica el caso de uso.
        """
        ...

    def obtener_password_hash(self, usuario_id: int) -> str | None:
        """El hash guardado (None si el usuario no existe o no tiene contraseña)."""
        ...

    def guardar_password_hash(self, usuario_id: int, password_hash: str) -> None:
        """Reemplaza el hash de la contraseña. UsuarioNoEncontradoError si no existe."""
        ...


# Lo que devuelven los reportes. No son entidades del dominio: son "fotos" de
# solo lectura, armadas por la base con una consulta de agregación.
@dataclass(frozen=True)
class GastoUsuario:
    nombre: str
    pedidos: int
    total: float


@dataclass(frozen=True)
class LibroVendido:
    titulo: str
    cantidad: int


class ConsultasVentas(Protocol):
    """Reportes de ventas. Los pedidos cancelados nunca cuentan."""

    def gasto_por_usuario(self) -> list[GastoUsuario]:
        """Cuánto ha gastado cada usuario con pedidos, de mayor a menor gasto."""
        ...

    def libros_mas_vendidos(self, limite: int = 5) -> list[LibroVendido]:
        """Los `limite` libros con más ejemplares vendidos, de mayor a menor."""
        ...


class UnidadDeTrabajo(Protocol):
    """Agrupa los repositorios y decide si sus cambios se guardan juntos o ninguno.

    Uso:

        with uow:
            libros = uow.libros.obtener_varios(...)
            ...
            uow.confirmar()        # si no se llama, los cambios se descartan

    Al salir del `with` se revierte todo lo que no se confirmó, también si hubo
    una excepción.
    """

    # Propiedades de solo lectura: así un adaptador puede declarar un tipo más
    # concreto (LibrosSQL) y mypy lo sigue aceptando.
    @property
    def libros(self) -> RepositorioLibros: ...

    @property
    def pedidos(self) -> RepositorioPedidos: ...

    @property
    def usuarios(self) -> RepositorioUsuarios: ...

    @property
    def ventas(self) -> ConsultasVentas: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        error: BaseException | None,
        traza: TracebackType | None,
    ) -> None: ...

    def confirmar(self) -> None:
        """Guarda de forma definitiva todos los cambios registrados."""
        ...

    def revertir(self) -> None:
        """Descarta los cambios que no se han confirmado."""
        ...


# ── Notificaciones ───────────────────────────────────────────────────────────


class Notificador(Protocol):
    """Envía un aviso a una persona.

    Contrato:
    - El aviso llega completo (destinatario, asunto y mensaje, con acentos y
      saltos de línea) y en el mismo orden en que se envió.
    - Si no se puede entregar, lanza ServicioExternoError (nunca un error de
      httpx, smtplib, etc.). Quien lo usa decide si eso es grave.
    """

    def enviar(self, destinatario: str, asunto: str, mensaje: str) -> None: ...


# ── Contraseñas ──────────────────────────────────────────────────────────────


class Hasher(Protocol):
    """Convierte contraseñas en hashes y las verifica.

    Contrato:
    - hashear() nunca devuelve la contraseña en claro, y dos llamadas con la
      misma contraseña pueden dar hashes distintos (llevan "sal").
    - verificar() con hash None (usuario inexistente o sin contraseña) siempre
      es False, pero debe tardar lo mismo que una verificación real: así no se
      delata qué emails existen.
    """

    def hashear(self, password: str) -> str: ...

    def verificar(self, password: str, password_hash: str | None) -> bool: ...
