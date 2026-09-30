"""Adaptadores en memoria de los puertos (ver puertos.py).

Sirven para probar servicios y casos de uso sin archivos ni base de datos:
son rápidos y fáciles de preparar. Para que esas pruebas no mientan, estos
adaptadores tienen que comportarse IGUAL que los reales (CatalogoJSON y
UnidadDeTrabajoSQL); eso lo garantizan las pruebas de contrato
(tests/test_contrato_*.py), que corren la misma batería contra ambos.

Dos detalles copian a los adaptadores reales a propósito:

- Siempre se guardan y se devuelven COPIAS. Un archivo o una base no se
  enteran si alguien modifica un objeto que ya leyó; aquí tampoco.
- La unidad de trabajo trabaja sobre una copia del estado confirmado:
  confirmar() la vuelve definitiva y revertir() la descarta.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from libreria.aplicacion.puertos import (
    ConsultasVentas,
    GastoUsuario,
    LibroVendido,
    RepositorioLibros,
    RepositorioPedidos,
    RepositorioUsuarios,
)
from libreria.dominio.excepciones import (
    EmailDuplicadoError,
    LibroDuplicadoError,
    LibroNoEncontradoError,
    PedidoNoEncontradoError,
    UsuarioNoEncontradoError,
)
from libreria.dominio.modelos import Libreria, Libro, Usuario
from libreria.dominio.pedidos import Pedido

# ── Catálogo (consola) ───────────────────────────────────────────────────────


class CatalogoEnMemoria:
    """Adaptador de RepositorioCatalogo que guarda el catálogo en una variable."""

    def __init__(self, data: Libreria) -> None:
        self._guardado = deepcopy(data)

    def cargar(self) -> Libreria:
        return deepcopy(self._guardado)

    def guardar(self, data: Libreria) -> None:
        self._guardado = deepcopy(data)


# ── Base de datos: repositorios + unidad de trabajo ─────────────────────────


@dataclass
class _Estado:
    """Todo lo que "hay en la base": libros, pedidos, usuarios y los últimos ids."""

    libros: dict[str, Libro] = field(default_factory=dict)
    pedidos: dict[int, Pedido] = field(default_factory=dict)
    usuarios: dict[int, Usuario] = field(default_factory=dict)
    password_hashes: dict[int, str | None] = field(default_factory=dict)
    ultimo_id_pedido: int = 0
    ultimo_id_usuario: int = 0

    def copiar_desde(self, otro: "_Estado") -> None:
        """Reemplaza el contenido por una copia independiente de `otro`."""
        self.libros = deepcopy(otro.libros)
        self.pedidos = deepcopy(otro.pedidos)
        self.usuarios = deepcopy(otro.usuarios)
        self.password_hashes = dict(otro.password_hashes)
        self.ultimo_id_pedido = otro.ultimo_id_pedido
        self.ultimo_id_usuario = otro.ultimo_id_usuario


class LibrosEnMemoria:
    """Adaptador de RepositorioLibros."""

    def __init__(self, estado: _Estado) -> None:
        self._estado = estado

    def obtener(self, isbn: str) -> Libro | None:
        libro = self._estado.libros.get(isbn)
        return libro.model_copy(deep=True) if libro else None

    def obtener_varios(self, isbns: Iterable[str]) -> dict[str, Libro]:
        return {
            isbn: self._estado.libros[isbn].model_copy(deep=True)
            for isbn in set(isbns)
            if isbn in self._estado.libros
        }

    def listar(self) -> list[Libro]:
        ordenados = sorted(self._estado.libros.values(), key=lambda li: (li.titulo, li.isbn))
        return [libro.model_copy(deep=True) for libro in ordenados]

    def agregar(self, libro: Libro) -> None:
        if libro.isbn in self._estado.libros:
            raise LibroDuplicadoError(f"Ya existe un libro con ISBN {libro.isbn}")
        self._estado.libros[libro.isbn] = libro.model_copy(deep=True)

    def guardar(self, libro: Libro) -> None:
        self._existe(libro.isbn)
        self._estado.libros[libro.isbn] = libro.model_copy(deep=True)

    def eliminar(self, isbn: str) -> None:
        self._existe(isbn)
        del self._estado.libros[isbn]

    def _existe(self, isbn: str) -> None:
        if isbn not in self._estado.libros:
            raise LibroNoEncontradoError(f"No existe el libro {isbn}")


class PedidosEnMemoria:
    """Adaptador de RepositorioPedidos."""

    def __init__(self, estado: _Estado) -> None:
        self._estado = estado

    def obtener(self, pedido_id: int) -> Pedido | None:
        pedido = self._estado.pedidos.get(pedido_id)
        return pedido.model_copy(deep=True) if pedido else None

    def listar(self, estatus: str | None = None) -> list[Pedido]:
        return self._ordenados(
            p for p in self._estado.pedidos.values() if estatus in (None, p.estatus)
        )

    def de_usuario(self, usuario_id: int) -> list[Pedido]:
        return self._ordenados(
            p for p in self._estado.pedidos.values() if p.usuario_id == usuario_id
        )

    def incluyen_libro(self, isbn: str) -> bool:
        return any(item.isbn == isbn for p in self._estado.pedidos.values() for item in p.items)

    def agregar(self, pedido: Pedido) -> None:
        self._estado.ultimo_id_pedido += 1  # como el autoincremento de la base
        pedido.id = self._estado.ultimo_id_pedido
        self._estado.pedidos[pedido.id] = pedido.model_copy(deep=True)

    def guardar(self, pedido: Pedido) -> None:
        guardado = self._estado.pedidos.get(pedido.id) if pedido.id is not None else None
        if guardado is None:
            raise PedidoNoEncontradoError(f"No existe el pedido {pedido.id}")
        guardado.estatus = pedido.estatus  # igual que en SQL: solo el estatus

    @staticmethod
    def _ordenados(pedidos: Iterable[Pedido]) -> list[Pedido]:
        # Igual que en SQL: por fecha y, si empatan, por id
        return [p.model_copy(deep=True) for p in sorted(pedidos, key=lambda p: (p.fecha, p.id))]


class UsuariosEnMemoria:
    """Adaptador de RepositorioUsuarios."""

    def __init__(self, estado: _Estado) -> None:
        self._estado = estado

    def obtener(self, usuario_id: int) -> Usuario | None:
        usuario = self._estado.usuarios.get(usuario_id)
        return usuario.model_copy(deep=True) if usuario else None

    def buscar_por_email(self, email: str) -> Usuario | None:
        return next(
            (
                u.model_copy(deep=True)
                for u in self._estado.usuarios.values()
                if u.email == email.strip()
            ),
            None,
        )

    def listar(self) -> list[Usuario]:
        ordenados = sorted(self._estado.usuarios.values(), key=lambda u: (u.nombre, u.id or 0))
        return [usuario.model_copy(deep=True) for usuario in ordenados]

    def agregar(self, usuario: Usuario, password_hash: str | None = None) -> None:
        self._email_libre(usuario.email, excepto_id=None)
        self._estado.ultimo_id_usuario += 1
        usuario.id = self._estado.ultimo_id_usuario
        self._estado.usuarios[usuario.id] = usuario.model_copy(deep=True)
        self._estado.password_hashes[usuario.id] = password_hash

    def guardar(self, usuario: Usuario) -> None:
        usuario_id = self._existe(usuario.id)
        self._email_libre(usuario.email, excepto_id=usuario_id)
        self._estado.usuarios[usuario_id] = usuario.model_copy(deep=True)

    def eliminar(self, usuario_id: int) -> None:
        self._existe(usuario_id)
        del self._estado.usuarios[usuario_id]
        self._estado.password_hashes.pop(usuario_id, None)

    def obtener_password_hash(self, usuario_id: int) -> str | None:
        return self._estado.password_hashes.get(usuario_id)

    def guardar_password_hash(self, usuario_id: int, password_hash: str) -> None:
        self._existe(usuario_id)
        self._estado.password_hashes[usuario_id] = password_hash

    def _existe(self, usuario_id: int | None) -> int:
        if usuario_id is None or usuario_id not in self._estado.usuarios:
            raise UsuarioNoEncontradoError(f"No existe el usuario {usuario_id}")
        return usuario_id

    def _email_libre(self, email: str, excepto_id: int | None) -> None:
        # Imita la restricción UNIQUE de la columna email
        if any(u.email == email and uid != excepto_id for uid, u in self._estado.usuarios.items()):
            raise EmailDuplicadoError(f"Ya existe un usuario con email {email}")


class VentasEnMemoria:
    """Adaptador de ConsultasVentas: los mismos reportes, calculados con Python."""

    def __init__(self, estado: _Estado) -> None:
        self._estado = estado

    def _vigentes(self) -> list[Pedido]:
        return [p for p in self._estado.pedidos.values() if p.estatus != "cancelado"]

    def gasto_por_usuario(self) -> list[GastoUsuario]:
        pedidos: Counter[int] = Counter()
        totales: defaultdict[int, float] = defaultdict(float)
        for pedido in self._vigentes():
            pedidos[pedido.usuario_id] += 1
            totales[pedido.usuario_id] += pedido.total
        reporte = [
            GastoUsuario(
                nombre=self._estado.usuarios[uid].nombre,
                pedidos=pedidos[uid],
                total=round(totales[uid], 2),
            )
            for uid in pedidos
        ]
        return sorted(reporte, key=lambda g: (-g.total, g.nombre))

    def libros_mas_vendidos(self, limite: int = 5) -> list[LibroVendido]:
        vendidos: Counter[str] = Counter()
        for pedido in self._vigentes():
            for item in pedido.items:
                vendidos[item.isbn] += item.cantidad
        reporte = [
            LibroVendido(titulo=self._estado.libros[isbn].titulo, cantidad=cantidad)
            for isbn, cantidad in vendidos.items()
        ]
        return sorted(reporte, key=lambda li: (-li.cantidad, li.titulo))[:limite]


class UnidadDeTrabajoEnMemoria:
    """Adaptador de UnidadDeTrabajo sin base de datos.

    Se prepara con los libros y usuarios iniciales (los usuarios deben tener id):

        uow = UnidadDeTrabajoEnMemoria(libros=[...], usuarios=[...])
    """

    def __init__(self, libros: Iterable[Libro] = (), usuarios: Iterable[Usuario] = ()) -> None:
        self._confirmado = _Estado()
        for libro in libros:
            self._confirmado.libros[libro.isbn] = libro.model_copy(deep=True)
        for usuario in usuarios:
            if usuario.id is None:
                raise ValueError(f"El usuario {usuario.email} necesita un id")
            self._confirmado.usuarios[usuario.id] = usuario.model_copy(deep=True)
            self._confirmado.password_hashes[usuario.id] = None
        self._confirmado.ultimo_id_usuario = max(self._confirmado.usuarios, default=0)

        # Los repositorios trabajan sobre esta copia; nunca sobre _confirmado
        self._trabajo = _Estado()
        self._trabajo.copiar_desde(self._confirmado)

        # Anotar con el puerto hace que mypy verifique que cada adaptador lo cumple
        self.libros: RepositorioLibros = LibrosEnMemoria(self._trabajo)
        self.pedidos: RepositorioPedidos = PedidosEnMemoria(self._trabajo)
        self.usuarios: RepositorioUsuarios = UsuariosEnMemoria(self._trabajo)
        self.ventas: ConsultasVentas = VentasEnMemoria(self._trabajo)
        self.confirmaciones = 0  # útil en pruebas: ¿el caso de uso confirmó?

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        error: BaseException | None,
        traza: TracebackType | None,
    ) -> None:
        self.revertir()

    def confirmar(self) -> None:
        self._confirmado.copiar_desde(self._trabajo)
        self.confirmaciones += 1

    def revertir(self) -> None:
        self._trabajo.copiar_desde(self._confirmado)
