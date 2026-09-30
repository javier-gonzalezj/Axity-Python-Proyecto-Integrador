"""Adaptadores SQLAlchemy de los puertos de la base de datos (ver aplicacion/puertos.py).

Cada repositorio traduce entre filas (LibroDB, PedidoDB, ...) y objetos del
dominio (Libro, Pedido, Usuario). Ninguno hace commit: todos comparten la
sesión de UnidadDeTrabajoSQL, que es la única que confirma o revierte.

Las tablas y las funciones de traducción viven en basedatos.py; aquí se
reutilizan para no escribirlas dos veces.
"""

import logging
from collections.abc import Iterable
from types import TracebackType
from typing import Self

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

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
    PersistenciaError,
    UsuarioNoEncontradoError,
)
from libreria.dominio.modelos import Libro, Usuario
from libreria.dominio.pedidos import Pedido
from libreria.infraestructura.basedatos import (
    LibroDB,
    PedidoDB,
    PedidoItemDB,
    UsuarioDB,
    fila_a_libro,
    fila_a_pedido,
    fila_a_usuario,
    libro_a_fila,
)

log = logging.getLogger(__name__)


class LibrosSQL:
    """Adaptador de RepositorioLibros."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def obtener(self, isbn: str) -> Libro | None:
        fila = self._sesion.get(LibroDB, isbn)
        return fila_a_libro(fila) if fila else None

    def obtener_varios(self, isbns: Iterable[str]) -> dict[str, Libro]:
        buscados = set(isbns)
        if not buscados:
            return {}
        # Una sola consulta (WHERE isbn IN (...)) en lugar de una por libro
        filas = self._sesion.scalars(select(LibroDB).where(LibroDB.isbn.in_(buscados)))
        return {fila.isbn: fila_a_libro(fila) for fila in filas}

    def listar(self) -> list[Libro]:
        filas = self._sesion.scalars(select(LibroDB).order_by(LibroDB.titulo, LibroDB.isbn))
        return [fila_a_libro(fila) for fila in filas]

    def agregar(self, libro: Libro) -> None:
        if self._sesion.get(LibroDB, libro.isbn) is not None:
            raise LibroDuplicadoError(f"Ya existe un libro con ISBN {libro.isbn}")
        self._sesion.add(libro_a_fila(libro))

    def guardar(self, libro: Libro) -> None:
        fila = self._fila(libro.isbn)
        # dominio -> fila (en_stock no se guarda: se deriva de cantidad_disponible)
        fila.titulo = libro.titulo
        fila.autor_nombre = libro.autor.nombre
        fila.autor_nacionalidad = libro.autor.nacionalidad
        fila.generos = list(libro.genero)
        fila.año_publicacion = libro.año_publicacion
        fila.precio = libro.precio
        fila.cantidad_disponible = libro.cantidad_disponible
        fila.editorial = libro.editorial

    def eliminar(self, isbn: str) -> None:
        self._sesion.delete(self._fila(isbn))

    def _fila(self, isbn: str) -> LibroDB:
        fila = self._sesion.get(LibroDB, isbn)
        if fila is None:
            raise LibroNoEncontradoError(f"No existe el libro {isbn}")
        return fila


class PedidosSQL:
    """Adaptador de RepositorioPedidos."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def obtener(self, pedido_id: int) -> Pedido | None:
        fila = self._sesion.get(PedidoDB, pedido_id)
        return fila_a_pedido(fila) if fila else None

    def listar(self, estatus: str | None = None) -> list[Pedido]:
        consulta = select(PedidoDB).order_by(PedidoDB.fecha, PedidoDB.id)
        if estatus is not None:
            consulta = consulta.where(PedidoDB.estatus == estatus)
        return [fila_a_pedido(fila) for fila in self._sesion.scalars(consulta)]

    def de_usuario(self, usuario_id: int) -> list[Pedido]:
        consulta = (
            select(PedidoDB)
            .where(PedidoDB.usuario_id == usuario_id)
            .order_by(PedidoDB.fecha, PedidoDB.id)
        )
        return [fila_a_pedido(fila) for fila in self._sesion.scalars(consulta)]

    def incluyen_libro(self, isbn: str) -> bool:
        consulta = select(PedidoItemDB.id).where(PedidoItemDB.isbn == isbn).limit(1)
        return self._sesion.scalar(consulta) is not None

    def agregar(self, pedido: Pedido) -> None:
        fila = PedidoDB(
            usuario_id=pedido.usuario_id,
            fecha=pedido.fecha,
            estatus=pedido.estatus,
            items=[
                PedidoItemDB(
                    isbn=item.isbn,
                    cantidad=item.cantidad,
                    precio_unitario=item.precio_unitario,
                )
                for item in pedido.items
            ],
        )
        self._sesion.add(fila)
        try:
            # flush envía el INSERT sin confirmarlo: así la base asigna el id,
            # pero todo se sigue pudiendo revertir.
            self._sesion.flush()
        except SQLAlchemyError as e:
            raise PersistenciaError(f"No se pudo registrar el pedido: {e}") from e
        pedido.id = fila.id

    def guardar(self, pedido: Pedido) -> None:
        fila = self._sesion.get(PedidoDB, pedido.id) if pedido.id is not None else None
        if fila is None:
            raise PedidoNoEncontradoError(f"No existe el pedido {pedido.id}")
        fila.estatus = pedido.estatus


class UsuariosSQL:
    """Adaptador de RepositorioUsuarios."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def obtener(self, usuario_id: int) -> Usuario | None:
        fila = self._sesion.get(UsuarioDB, usuario_id)
        return fila_a_usuario(fila) if fila else None

    def buscar_por_email(self, email: str) -> Usuario | None:
        fila = self._sesion.scalar(select(UsuarioDB).where(UsuarioDB.email == email.strip()))
        return fila_a_usuario(fila) if fila else None

    def listar(self) -> list[Usuario]:
        filas = self._sesion.scalars(select(UsuarioDB).order_by(UsuarioDB.nombre, UsuarioDB.id))
        return [fila_a_usuario(fila) for fila in filas]

    def agregar(self, usuario: Usuario, password_hash: str | None = None) -> None:
        if self.buscar_por_email(usuario.email) is not None:
            raise _email_duplicado(usuario.email)
        fila = UsuarioDB(
            nombre=usuario.nombre,
            email=usuario.email,
            telefono=usuario.telefono,
            rol=usuario.rol,
            password_hash=password_hash,
        )
        self._sesion.add(fila)
        self._enviar(usuario.email)  # la base asigna el id sin confirmar nada
        usuario.id = fila.id

    def guardar(self, usuario: Usuario) -> None:
        fila = self._fila(usuario.id)
        fila.nombre = usuario.nombre
        fila.email = usuario.email
        fila.telefono = usuario.telefono
        fila.rol = usuario.rol
        self._enviar(usuario.email)  # detecta ya el email repetido, no hasta confirmar

    def eliminar(self, usuario_id: int) -> None:
        self._sesion.delete(self._fila(usuario_id))

    def obtener_password_hash(self, usuario_id: int) -> str | None:
        fila = self._sesion.get(UsuarioDB, usuario_id)
        return fila.password_hash if fila else None

    def guardar_password_hash(self, usuario_id: int, password_hash: str) -> None:
        self._fila(usuario_id).password_hash = password_hash

    def _fila(self, usuario_id: int | None) -> UsuarioDB:
        fila = self._sesion.get(UsuarioDB, usuario_id) if usuario_id is not None else None
        if fila is None:
            raise UsuarioNoEncontradoError(f"No existe el usuario {usuario_id}")
        return fila

    def _enviar(self, email: str) -> None:
        """flush(): manda los cambios a la base SIN confirmarlos.

        Si el email choca con la restricción UNIQUE, se traduce el error de
        SQLAlchemy a uno del dominio. Revertir le toca a la unidad de trabajo.
        """
        try:
            self._sesion.flush()
        except IntegrityError:
            raise _email_duplicado(email) from None


def _email_duplicado(email: str) -> EmailDuplicadoError:
    return EmailDuplicadoError(f"Ya existe un usuario con email {email}")


class VentasSQL:
    """Adaptador de ConsultasVentas: consultas de agregación (GROUP BY)."""

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def gasto_por_usuario(self) -> list[GastoUsuario]:
        total = func.round(func.sum(PedidoItemDB.cantidad * PedidoItemDB.precio_unitario), 2)
        consulta = (
            select(UsuarioDB.nombre, func.count(func.distinct(PedidoDB.id)), total)
            .join(PedidoDB, PedidoDB.usuario_id == UsuarioDB.id)
            .join(PedidoItemDB, PedidoItemDB.pedido_id == PedidoDB.id)
            .where(PedidoDB.estatus != "cancelado")
            .group_by(UsuarioDB.id)
            .order_by(total.desc(), UsuarioDB.nombre)
        )
        return [
            GastoUsuario(nombre=nombre, pedidos=pedidos, total=gasto)
            for nombre, pedidos, gasto in self._sesion.execute(consulta)
        ]

    def libros_mas_vendidos(self, limite: int = 5) -> list[LibroVendido]:
        vendidos = func.sum(PedidoItemDB.cantidad)
        consulta = (
            select(LibroDB.titulo, vendidos)
            .join(PedidoItemDB, PedidoItemDB.isbn == LibroDB.isbn)
            .join(PedidoDB, PedidoDB.id == PedidoItemDB.pedido_id)
            .where(PedidoDB.estatus != "cancelado")
            .group_by(LibroDB.isbn)
            .order_by(vendidos.desc(), LibroDB.titulo)
            .limit(limite)
        )
        return [
            LibroVendido(titulo=titulo, cantidad=cantidad)
            for titulo, cantidad in self._sesion.execute(consulta)
        ]


class UnidadDeTrabajoSQL:
    """Adaptador de UnidadDeTrabajo sobre una Session de SQLAlchemy.

    No crea ni cierra la sesión: la recibe ya abierta (en la API viene de
    obtener_sesion() y en las pruebas, de una base en memoria). Su trabajo es
    decidir entre commit y rollback. Mientras se use, esa sesión solo debe
    tocarse a través de los repositorios, porque al salir del `with` se revierte
    todo lo que no se haya confirmado.
    """

    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion
        # Anotar con el puerto hace que mypy verifique que cada adaptador lo cumple
        self.libros: RepositorioLibros = LibrosSQL(sesion)
        self.pedidos: RepositorioPedidos = PedidosSQL(sesion)
        self.usuarios: RepositorioUsuarios = UsuariosSQL(sesion)
        self.ventas: ConsultasVentas = VentasSQL(sesion)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        error: BaseException | None,
        traza: TracebackType | None,
    ) -> None:
        # Después de confirmar() no queda nada pendiente, así que esto no borra
        # nada guardado; si hubo una excepción o se olvidó confirmar, descarta.
        self.revertir()

    def confirmar(self) -> None:
        try:
            self._sesion.commit()
        except SQLAlchemyError as e:
            self._sesion.rollback()
            log.warning("No se pudo confirmar; se revirtieron los cambios: %s", e)
            raise PersistenciaError(f"No se pudieron guardar los cambios: {e}") from e

    def revertir(self) -> None:
        self._sesion.rollback()
