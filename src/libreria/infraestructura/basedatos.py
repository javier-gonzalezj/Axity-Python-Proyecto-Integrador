"""Persistencia en SQLite con SQLAlchemy: Usuario / Pedido / PedidoItem.

Tablas:
    libros        catálogo (lo que hoy vive en libreria.json)
    usuarios      clientes de la librería
    pedidos       un pedido pertenece a un usuario            (1 usuario -> N pedidos)
    pedido_items  cada línea del pedido: libro + cantidad     (1 pedido  -> N items)

    usuarios 1 ──< pedidos 1 ──< pedido_items >── 1 libros

El esquema de la base lo administra Alembic (carpeta `migraciones/`). Las clases
*DB de este módulo son la "fuente de verdad": si cambias una, genera una
migración con `alembic revision --autogenerate -m "..."`.

Este módulo solo tiene lo técnico de la base: las tablas, el motor y las
funciones que traducen entre filas y objetos del dominio (Libro, Usuario,
Pedido). No decide reglas de negocio ni ofrece operaciones de lectura o
escritura: esas las hacen los repositorios de repositorios_sql.py, que es lo
único que usan los casos de uso (a través de los puertos).
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Engine,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    create_engine,
    event,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from libreria.dominio.modelos import Autor, Libreria, Libro, Rol, Usuario
from libreria.dominio.pedidos import Estatus, Pedido, PedidoItem

log = logging.getLogger(__name__)

URL_BD = "sqlite:///data/libreria.db"


# ---------------------------------------------------------------------------
# Tablas (modelos de SQLAlchemy)
# ---------------------------------------------------------------------------
# Nombres fijos para índices y restricciones. Alembic los necesita para poder
# modificarlos o borrarlos después (sobre todo en SQLite, con batch mode).
CONVENCION_NOMBRES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


class LibroDB(Base):
    __tablename__ = "libros"
    __table_args__ = (
        CheckConstraint("año_publicacion BETWEEN 0 AND 2100", name="año_valido"),
        CheckConstraint("precio >= 0", name="precio_positivo"),
        CheckConstraint("cantidad_disponible >= 0", name="cantidad_positiva"),
    )

    isbn: Mapped[str] = mapped_column(String(20), primary_key=True)
    titulo: Mapped[str] = mapped_column(String(200))
    autor_nombre: Mapped[str] = mapped_column(String(100))
    autor_nacionalidad: Mapped[str] = mapped_column(String(50), default="")
    generos: Mapped[list[str]] = mapped_column(JSON)  # lista guardada como JSON
    año_publicacion: Mapped[int] = mapped_column(Integer)
    precio: Mapped[float] = mapped_column(Float)
    cantidad_disponible: Mapped[int] = mapped_column(Integer)
    editorial: Mapped[str] = mapped_column(String(100))


class UsuarioDB(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    telefono: Mapped[str | None] = mapped_column(String(20))  # agregado en la migración 0002
    # Agregados en la migración 0003 (autenticación con JWT)
    rol: Mapped[str] = mapped_column(String(20), default="cliente", server_default="cliente")
    # Nunca se guarda la contraseña, solo su hash. None = aún no puede iniciar sesión
    password_hash: Mapped[str | None] = mapped_column(String(255))

    pedidos: Mapped[list["PedidoDB"]] = relationship(back_populates="usuario")


class PedidoDB(Base):
    __tablename__ = "pedidos"
    __table_args__ = (
        CheckConstraint(
            "estatus IN ('pendiente', 'pagado', 'enviado', 'cancelado')", name="estatus_valido"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    fecha: Mapped[datetime] = mapped_column(default=datetime.now)
    estatus: Mapped[str] = mapped_column(String(20), default="pendiente")

    usuario: Mapped[UsuarioDB] = relationship(back_populates="pedidos")
    # delete-orphan: una línea no existe sin su pedido
    items: Mapped[list["PedidoItemDB"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan"
    )


class PedidoItemDB(Base):
    __tablename__ = "pedido_items"
    __table_args__ = (
        UniqueConstraint("pedido_id", "isbn"),  # un libro aparece una vez por pedido
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        CheckConstraint("precio_unitario >= 0", name="precio_positivo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id", ondelete="CASCADE"), index=True)
    isbn: Mapped[str] = mapped_column(ForeignKey("libros.isbn"))
    cantidad: Mapped[int] = mapped_column(Integer)
    precio_unitario: Mapped[float] = mapped_column(Float)  # precio AL MOMENTO de la compra

    pedido: Mapped[PedidoDB] = relationship(back_populates="items")
    libro: Mapped[LibroDB] = relationship()


# ---------------------------------------------------------------------------
# Motor (conexión)
# ---------------------------------------------------------------------------
def crear_motor(url: str = URL_BD, echo: bool = False, **opciones: Any) -> Engine:
    """Crea el motor de SQLAlchemy. Con echo=True imprime el SQL que genera.

    `opciones` se pasan tal cual a create_engine (p. ej. poolclass o connect_args,
    que usan las pruebas de la API para compartir una base en memoria entre hilos).
    """
    motor = create_engine(url, echo=echo, **opciones)

    if motor.dialect.name == "sqlite":

        @event.listens_for(motor, "connect")
        def _activar_llaves_foraneas(conexion: Any, _registro: Any) -> None:
            # En SQLite vienen apagadas y hay que encenderlas en cada conexión
            cursor = conexion.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

    return motor


def crear_esquema(motor: Engine) -> None:
    """Crea las tablas directamente, SIN Alembic.

    Solo para pruebas con bases temporales (sqlite:// en memoria). La base real
    se crea y actualiza con `alembic upgrade head`.
    """
    Base.metadata.create_all(motor)


# ---------------------------------------------------------------------------
# Conversiones entre tablas y modelos pydantic
# ---------------------------------------------------------------------------
# Son públicas porque también las usan los repositorios de repositorios_sql.py.
def fila_a_libro(fila: LibroDB) -> Libro:
    return Libro(
        isbn=fila.isbn,
        titulo=fila.titulo,
        autor=Autor(nombre=fila.autor_nombre, nacionalidad=fila.autor_nacionalidad),
        genero=list(fila.generos),
        año_publicacion=fila.año_publicacion,
        precio=fila.precio,
        en_stock=fila.cantidad_disponible > 0,  # se deriva, no se guarda
        cantidad_disponible=fila.cantidad_disponible,
        editorial=fila.editorial,
    )


def libro_a_fila(libro: Libro) -> LibroDB:
    return LibroDB(
        isbn=libro.isbn,
        titulo=libro.titulo,
        autor_nombre=libro.autor.nombre,
        autor_nacionalidad=libro.autor.nacionalidad,
        generos=libro.genero,
        año_publicacion=libro.año_publicacion,
        precio=libro.precio,
        cantidad_disponible=libro.cantidad_disponible,
        editorial=libro.editorial,
    )


def fila_a_usuario(fila: UsuarioDB) -> Usuario:
    return Usuario(
        id=fila.id,
        nombre=fila.nombre,
        email=fila.email,
        telefono=fila.telefono,
        rol=cast(Rol, fila.rol),  # la columna es str; pydantic valida el valor
    )


def fila_a_pedido(fila: PedidoDB) -> Pedido:
    return Pedido(
        id=fila.id,
        usuario_id=fila.usuario_id,
        fecha=fila.fecha,
        estatus=cast(Estatus, fila.estatus),  # la columna es str; pydantic valida el valor
        items=[
            PedidoItem(
                isbn=item.isbn,
                titulo=item.libro.titulo,
                cantidad=item.cantidad,
                precio_unitario=item.precio_unitario,
            )
            for item in sorted(fila.items, key=lambda i: i.libro.titulo)
        ],
    )


# ---------------------------------------------------------------------------
# Carga inicial del catálogo (la usan main() y las pruebas)
# ---------------------------------------------------------------------------
def importar_catalogo(sesion: Session, data: Libreria) -> int:
    """Migra los libros que ya cargó almacenamiento.cargar_datos() a la base.

    Los ISBN que ya existen se saltan. Devuelve cuántos libros se agregaron.
    """
    existentes = set(sesion.scalars(select(LibroDB.isbn)))
    nuevos = [libro for libro in data["libros"] if libro.isbn not in existentes]

    sesion.add_all(libro_a_fila(libro) for libro in nuevos)
    sesion.commit()

    log.info("Catálogo importado: %d libros nuevos", len(nuevos))
    return len(nuevos)


# ---------------------------------------------------------------------------
# Uso directo: poetry run python -m libreria.infraestructura.basedatos
# ---------------------------------------------------------------------------
def main() -> None:
    """Importa data/libreria.json a data/libreria.db (después de `alembic upgrade head`)."""
    from libreria.infraestructura.almacenamiento import cargar_datos

    if not Path("data/libreria.db").exists():
        print("No existe data/libreria.db. Primero ejecuta: poetry run alembic upgrade head")
        return

    with Session(crear_motor()) as sesion:
        nuevos = importar_catalogo(sesion, cargar_datos("data/libreria.json"))
    print(f"Libros importados: {nuevos}")


if __name__ == "__main__":
    main()
