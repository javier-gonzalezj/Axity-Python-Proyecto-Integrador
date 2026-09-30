"""Pruebas de pedidos y reportes contra la base real (basedatos.py + repositorios_sql.py).

La fixture `sesion` (en conftest.py) da a cada prueba una base SQLite en
memoria nueva, con el catálogo de libreria.json ya importado.
"""

import pytest
from sqlalchemy.orm import Session

from libreria.aplicacion.puertos import ConsultasVentas, LibroVendido
from libreria.dominio.excepciones import (
    EmailDuplicadoError,
    LibreriaError,
    LibroInvalidoError,
    StockInsuficienteError,
    UsuarioNoEncontradoError,
)
from libreria.infraestructura import basedatos as bd
from libreria.infraestructura.almacenamiento import cargar_datos
from libreria.infraestructura.repositorios_sql import UnidadDeTrabajoSQL
from tests.conftest import CATALOGO, cancelar_pedido, crear_pedido, nuevo_usuario

CIEN_AÑOS = "978-607-07-1234-5"  # 12 ejemplares, $349.90
NOVENTA_OCHENTA_Y_CUATRO = "978-607-11-9876-3"  # 1984: 0 ejemplares
RAYUELA = "978-84-9793-563-2"  # 5 ejemplares, $399.50


def ventas(sesion: Session) -> ConsultasVentas:
    return UnidadDeTrabajoSQL(sesion).ventas


def gasto(sesion: Session) -> list[tuple[str, int, float]]:
    return [(g.nombre, g.pedidos, g.total) for g in ventas(sesion).gasto_por_usuario()]


def stock(sesion: Session, isbn: str) -> int:
    libro = UnidadDeTrabajoSQL(sesion).libros.obtener(isbn)
    assert libro is not None
    return libro.cantidad_disponible


def test_importar_catalogo_no_duplica(sesion: Session) -> None:
    total = len(UnidadDeTrabajoSQL(sesion).libros.listar())
    assert total > 0
    assert bd.importar_catalogo(sesion, cargar_datos(CATALOGO)) == 0
    assert len(UnidadDeTrabajoSQL(sesion).libros.listar()) == total


def test_libro_ida_y_vuelta_conserva_datos(sesion: Session) -> None:
    original = next(libro for libro in cargar_datos(CATALOGO)["libros"] if libro.isbn == CIEN_AÑOS)
    assert UnidadDeTrabajoSQL(sesion).libros.obtener(CIEN_AÑOS) == original


def test_email_repetido(sesion: Session) -> None:
    nuevo_usuario(sesion, "Ana", "ana@mail.com")
    with pytest.raises(EmailDuplicadoError, match="email"):
        nuevo_usuario(sesion, "Otra Ana", "ana@mail.com")


def test_crear_pedido_calcula_total_y_descuenta_stock(sesion: Session) -> None:
    ana = nuevo_usuario(sesion, "Ana", "ana@mail.com", telefono="55-1234-5678")
    assert ana.id is not None

    pedido = crear_pedido(sesion, ana.id, {CIEN_AÑOS: 2, RAYUELA: 1})

    assert pedido.estatus == "pendiente"
    assert len(pedido.items) == 2
    assert pedido.total == pytest.approx(2 * 349.90 + 399.50)
    assert stock(sesion, CIEN_AÑOS) == 10
    assert stock(sesion, RAYUELA) == 4


def test_pedido_sin_stock_no_cambia_nada(sesion: Session) -> None:
    luis = nuevo_usuario(sesion, "Luis", "luis@mail.com")
    assert luis.id is not None

    with pytest.raises(StockInsuficienteError):
        crear_pedido(sesion, luis.id, {RAYUELA: 1, NOVENTA_OCHENTA_Y_CUATRO: 1})

    assert stock(sesion, RAYUELA) == 5  # el rollback regresó el descuento
    assert UnidadDeTrabajoSQL(sesion).pedidos.de_usuario(luis.id) == []


def test_pedido_con_errores(sesion: Session) -> None:
    ana = nuevo_usuario(sesion, "Ana", "ana@mail.com")
    assert ana.id is not None

    with pytest.raises(UsuarioNoEncontradoError):
        crear_pedido(sesion, 999, {CIEN_AÑOS: 1})
    with pytest.raises(LibroInvalidoError):
        crear_pedido(sesion, ana.id, {"no-existe": 1})
    with pytest.raises(LibreriaError):
        crear_pedido(sesion, ana.id, {})


def test_precio_del_pedido_no_cambia_si_cambia_el_catalogo(sesion: Session) -> None:
    ana = nuevo_usuario(sesion, "Ana", "ana@mail.com")
    assert ana.id is not None
    pedido = crear_pedido(sesion, ana.id, {RAYUELA: 1})

    libro_db = sesion.get(bd.LibroDB, RAYUELA)
    assert libro_db is not None
    libro_db.precio = 999.0
    sesion.commit()

    guardado = UnidadDeTrabajoSQL(sesion).pedidos.obtener(pedido.id)
    assert guardado is not None
    assert guardado.total == pytest.approx(399.50)


def test_cancelar_regresa_stock_y_sale_de_reportes(sesion: Session) -> None:
    ana = nuevo_usuario(sesion, "Ana", "ana@mail.com")
    luis = nuevo_usuario(sesion, "Luis", "luis@mail.com")
    assert ana.id is not None and luis.id is not None

    pedido_ana = crear_pedido(sesion, ana.id, {CIEN_AÑOS: 2, RAYUELA: 1})
    crear_pedido(sesion, luis.id, {CIEN_AÑOS: 1})

    assert gasto(sesion) == [
        ("Ana", 1, pytest.approx(1099.30)),
        ("Luis", 1, pytest.approx(349.90)),
    ]
    assert ventas(sesion).libros_mas_vendidos()[0] == LibroVendido("Cien años de soledad", 3)

    cancelar_pedido(sesion, pedido_ana.id)
    cancelar_pedido(sesion, pedido_ana.id)  # cancelar dos veces no regresa stock doble

    assert stock(sesion, CIEN_AÑOS) == 11
    assert stock(sesion, RAYUELA) == 5
    assert gasto(sesion) == [("Luis", 1, pytest.approx(349.90))]
