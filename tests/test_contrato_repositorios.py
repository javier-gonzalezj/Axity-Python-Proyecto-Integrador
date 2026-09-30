"""Pruebas de CONTRATO de los puertos de la base de datos.

Cada prueba de este archivo corre dos veces: una con UnidadDeTrabajoSQL
(SQLite en memoria) y otra con UnidadDeTrabajoEnMemoria. En la salida de
pytest aparecen como `...[sql]` y `...[memoria]`.

Si ambas pasan, los casos de uso se pueden probar con la versión en memoria
(rápida y sin base) con la confianza de que la real se comporta igual.
Si agregas otro adaptador (p. ej. PostgreSQL), súmalo a `params` en la
fixture `entorno` y hereda toda la batería.

Las pruebas solo usan lo que promete el PUERTO (UnidadDeTrabajo): nada de
sesiones, filas ni detalles de un adaptador en particular.
"""

from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from libreria.aplicacion.puertos import UnidadDeTrabajo
from libreria.dominio import pedidos
from libreria.dominio.excepciones import (
    EmailDuplicadoError,
    LibroInvalidoError,
    LibroNoEncontradoError,
    PedidoNoEncontradoError,
    UsuarioNoEncontradoError,
)
from libreria.dominio.modelos import Autor, Libro, Usuario
from libreria.dominio.pedidos import Pedido, PedidoItem
from libreria.infraestructura.almacenamiento import cargar_datos
from libreria.infraestructura.repositorios_memoria import UnidadDeTrabajoEnMemoria
from libreria.infraestructura.repositorios_sql import UnidadDeTrabajoSQL
from tests.conftest import CATALOGO, nuevo_usuario

# Catálogo fijo, ver conftest.py
CIEN_AÑOS = "978-607-07-1234-5"  # 12 ejemplares, $349.90
RAYUELA = "978-84-9793-563-2"  # 5 ejemplares, $399.50
ORWELL_1984 = "978-607-11-9876-3"  # 0 ejemplares
HOY = datetime(2026, 9, 29, 12, 0)


@dataclass
class Entorno:
    uow: UnidadDeTrabajo
    ana_id: int  # una usuaria que ya existe


@pytest.fixture(params=["sql", "memoria"])
def entorno(request: pytest.FixtureRequest) -> Entorno:
    """Los MISMOS datos iniciales en los dos adaptadores: catálogo de prueba y Ana."""
    if request.param == "sql":
        sesion: Session = request.getfixturevalue("sesion")  # ya trae el catálogo
        ana = nuevo_usuario(sesion, "Ana", "ana@mail.com")
        assert ana.id is not None
        return Entorno(UnidadDeTrabajoSQL(sesion), ana.id)

    ana = Usuario(id=1, nombre="Ana", email="ana@mail.com")
    libros = cargar_datos(CATALOGO)["libros"]
    return Entorno(UnidadDeTrabajoEnMemoria(libros=libros, usuarios=[ana]), 1)


@pytest.fixture
def uow(entorno: Entorno) -> UnidadDeTrabajo:
    return entorno.uow


@pytest.fixture
def ana_id(entorno: Entorno) -> int:
    return entorno.ana_id


def libro_nuevo(isbn: str = "978-607-16-0001-1") -> Libro:
    return Libro(
        isbn=isbn,
        titulo="Pedro Páramo",
        autor=Autor(nombre="Juan Rulfo", nacionalidad="Mexicana"),
        genero=["Novela", "Realismo mágico"],
        año_publicacion=1955,
        precio=189.0,
        en_stock=True,
        cantidad_disponible=10,
        editorial="Fondo de Cultura Económica",
    )


def pedido_nuevo(usuario_id: int) -> Pedido:
    item = PedidoItem(isbn=RAYUELA, titulo="Rayuela", cantidad=2, precio_unitario=399.50)
    return Pedido(usuario_id=usuario_id, fecha=HOY, items=[item])


# ── Libros ───────────────────────────────────────────────────────────────────


class TestRepositorioLibros:
    def test_obtener_un_libro_existente(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            libro = uow.libros.obtener(CIEN_AÑOS)

        assert libro is not None
        assert libro.cantidad_disponible == 12

    def test_obtener_inexistente_devuelve_none(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            assert uow.libros.obtener("no-existe") is None

    def test_obtener_varios_omite_los_que_no_existen(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            libros = uow.libros.obtener_varios([CIEN_AÑOS, RAYUELA, "no-existe"])

        assert set(libros) == {CIEN_AÑOS, RAYUELA}
        assert libros[RAYUELA].precio == pytest.approx(399.50)

    def test_obtener_varios_sin_isbn_devuelve_vacio(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            assert uow.libros.obtener_varios([]) == {}

    def test_agregar_y_confirmar_guarda_el_libro_completo(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            uow.libros.agregar(libro_nuevo())
            uow.confirmar()

        with uow:
            assert uow.libros.obtener("978-607-16-0001-1") == libro_nuevo()  # ida y vuelta

    def test_agregar_un_isbn_repetido_se_rechaza(self, uow: UnidadDeTrabajo) -> None:
        with uow, pytest.raises(LibroInvalidoError, match="Ya existe"):
            uow.libros.agregar(libro_nuevo(isbn=CIEN_AÑOS))

    def test_guardar_actualiza_el_inventario(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            libro = uow.libros.obtener(RAYUELA)
            assert libro is not None
            libro.retirar(5)  # regla del dominio
            uow.libros.guardar(libro)
            uow.confirmar()

        with uow:
            guardado = uow.libros.obtener(RAYUELA)
        assert guardado is not None
        assert guardado.cantidad_disponible == 0
        assert not guardado.en_stock  # se deriva al leer la fila

    def test_guardar_un_libro_inexistente_se_rechaza(self, uow: UnidadDeTrabajo) -> None:
        with uow, pytest.raises(LibroNoEncontradoError):
            uow.libros.guardar(libro_nuevo())

    def test_modificar_un_libro_leido_no_cambia_nada_sin_guardar(
        self, uow: UnidadDeTrabajo
    ) -> None:
        with uow:
            libro = uow.libros.obtener(RAYUELA)
            assert libro is not None
            libro.retirar(5)  # sin uow.libros.guardar(libro)

            otra_lectura = uow.libros.obtener(RAYUELA)
            assert otra_lectura is not None and otra_lectura.cantidad_disponible == 5

    def test_listar_ordena_por_titulo(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            titulos = [libro.titulo for libro in uow.libros.listar()]

        assert len(titulos) == len(cargar_datos(CATALOGO)["libros"])
        assert titulos == sorted(titulos)

    def test_eliminar_y_confirmar_borra_el_libro(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            uow.libros.eliminar(RAYUELA)
            uow.confirmar()

        with uow:
            assert uow.libros.obtener(RAYUELA) is None
            assert RAYUELA not in [libro.isbn for libro in uow.libros.listar()]

    def test_eliminar_un_libro_inexistente_se_rechaza(self, uow: UnidadDeTrabajo) -> None:
        with uow, pytest.raises(LibroNoEncontradoError):
            uow.libros.eliminar("no-existe")


# ── Pedidos ──────────────────────────────────────────────────────────────────


class TestRepositorioPedidos:
    def test_agregar_le_asigna_id_al_pedido(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        pedido = pedido_nuevo(ana_id)

        with uow:
            uow.pedidos.agregar(pedido)
            uow.confirmar()

        assert pedido.id is not None

    def test_un_pedido_guardado_se_lee_igual(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        pedido = pedido_nuevo(ana_id)
        with uow:
            uow.pedidos.agregar(pedido)
            uow.confirmar()

        assert pedido.id is not None
        with uow:
            leido = uow.pedidos.obtener(pedido.id)
        assert leido == pedido  # mismo usuario, fecha, estatus, líneas y precios

    def test_guardar_cambia_el_estatus(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        pedido = pedido_nuevo(ana_id)
        with uow:
            uow.pedidos.agregar(pedido)
            uow.confirmar()

        assert pedido.id is not None
        with uow:
            pedido.avanzar_a("pagado")  # regla del dominio
            uow.pedidos.guardar(pedido)
            uow.confirmar()

        with uow:
            leido = uow.pedidos.obtener(pedido.id)
        assert leido is not None and leido.estatus == "pagado"

    def test_obtener_inexistente_devuelve_none(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            assert uow.pedidos.obtener(999) is None

    def test_cada_pedido_recibe_un_id_distinto(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        primero, segundo = pedido_nuevo(ana_id), pedido_nuevo(ana_id)
        with uow:
            uow.pedidos.agregar(primero)
            uow.pedidos.agregar(segundo)
            uow.confirmar()

        assert primero.id is not None and segundo.id is not None
        assert primero.id != segundo.id

    def test_modificar_un_pedido_leido_no_cambia_nada_sin_guardar(
        self, uow: UnidadDeTrabajo, ana_id: int
    ) -> None:
        pedido = pedido_nuevo(ana_id)
        with uow:
            uow.pedidos.agregar(pedido)
            uow.confirmar()

        assert pedido.id is not None
        with uow:
            leido = uow.pedidos.obtener(pedido.id)
            assert leido is not None
            leido.avanzar_a("pagado")  # sin uow.pedidos.guardar(leido)

            otra_lectura = uow.pedidos.obtener(pedido.id)
            assert otra_lectura is not None and otra_lectura.estatus == "pendiente"

    def test_guardar_un_pedido_inexistente_se_rechaza(
        self, uow: UnidadDeTrabajo, ana_id: int
    ) -> None:
        pedido = pedido_nuevo(ana_id)
        pedido.id = 999

        with uow, pytest.raises(PedidoNoEncontradoError):
            uow.pedidos.guardar(pedido)

    def test_listar_filtra_por_estatus(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        primero, segundo = pedido_nuevo(ana_id), pedido_nuevo(ana_id)
        with uow:
            uow.pedidos.agregar(primero)
            uow.pedidos.agregar(segundo)
            segundo.avanzar_a("pagado")
            uow.pedidos.guardar(segundo)
            uow.confirmar()

        with uow:
            assert [p.id for p in uow.pedidos.listar()] == [primero.id, segundo.id]
            assert [p.id for p in uow.pedidos.listar("pagado")] == [segundo.id]
            assert uow.pedidos.listar("enviado") == []

    def test_de_usuario_solo_devuelve_los_suyos(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        beto = Usuario(nombre="Beto", email="beto@mail.com")
        with uow:
            uow.usuarios.agregar(beto)
            assert beto.id is not None
            uow.pedidos.agregar(pedido_nuevo(ana_id))
            uow.pedidos.agregar(pedido_nuevo(beto.id))
            uow.confirmar()

        with uow:
            assert [p.usuario_id for p in uow.pedidos.de_usuario(ana_id)] == [ana_id]
            assert uow.pedidos.de_usuario(999) == []

    def test_incluyen_libro(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        with uow:
            assert not uow.pedidos.incluyen_libro(RAYUELA)
            uow.pedidos.agregar(pedido_nuevo(ana_id))  # lleva Rayuela
            uow.confirmar()

        with uow:
            assert uow.pedidos.incluyen_libro(RAYUELA)
            assert not uow.pedidos.incluyen_libro(CIEN_AÑOS)


# ── Usuarios ─────────────────────────────────────────────────────────────────


class TestRepositorioUsuarios:
    def test_obtener_un_usuario(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        with uow:
            usuario = uow.usuarios.obtener(ana_id)

        assert usuario is not None
        assert usuario.email == "ana@mail.com"

    def test_obtener_inexistente_devuelve_none(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            assert uow.usuarios.obtener(999) is None

    def test_buscar_por_email_ignora_espacios(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        with uow:
            ana = uow.usuarios.buscar_por_email("  ana@mail.com ")
            assert ana is not None and ana.id == ana_id
            assert uow.usuarios.buscar_por_email("nadie@mail.com") is None

    def test_agregar_le_asigna_id_y_guarda_el_hash(self, uow: UnidadDeTrabajo) -> None:
        beto = Usuario(nombre="Beto", email="beto@mail.com", telefono="55-1234-5678")
        with uow:
            uow.usuarios.agregar(beto, password_hash="hash-de-prueba")
            uow.confirmar()

        assert beto.id is not None
        with uow:
            assert uow.usuarios.obtener(beto.id) == beto
            assert uow.usuarios.obtener_password_hash(beto.id) == "hash-de-prueba"

    def test_agregar_sin_password_deja_el_hash_en_none(self, uow: UnidadDeTrabajo) -> None:
        beto = Usuario(nombre="Beto", email="beto@mail.com")
        with uow:
            uow.usuarios.agregar(beto)
            uow.confirmar()

        assert beto.id is not None
        with uow:
            assert uow.usuarios.obtener_password_hash(beto.id) is None

    def test_agregar_un_email_repetido_se_rechaza(self, uow: UnidadDeTrabajo) -> None:
        with uow, pytest.raises(EmailDuplicadoError):
            uow.usuarios.agregar(Usuario(nombre="Otra Ana", email="ana@mail.com"))

    def test_listar_ordena_por_nombre(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            uow.usuarios.agregar(Usuario(nombre="Zoe", email="zoe@mail.com"))
            uow.usuarios.agregar(Usuario(nombre="Beto", email="beto@mail.com"))
            uow.confirmar()

        with uow:
            assert [u.nombre for u in uow.usuarios.listar()] == ["Ana", "Beto", "Zoe"]

    def test_guardar_actualiza_datos_y_rol(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        with uow:
            ana = uow.usuarios.obtener(ana_id)
            assert ana is not None
            ana.nombre, ana.telefono, ana.rol = "Ana López", "55-0000-0000", "admin"
            uow.usuarios.guardar(ana)
            uow.confirmar()

        with uow:
            assert uow.usuarios.obtener(ana_id) == ana

    def test_guardar_con_email_de_otro_se_rechaza(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        with uow:
            uow.usuarios.agregar(Usuario(nombre="Beto", email="beto@mail.com"))
            uow.confirmar()

        with uow, pytest.raises(EmailDuplicadoError):
            ana = uow.usuarios.obtener(ana_id)
            assert ana is not None
            ana.email = "beto@mail.com"
            uow.usuarios.guardar(ana)

        with uow:
            guardada = uow.usuarios.obtener(ana_id)
            assert guardada is not None and guardada.email == "ana@mail.com"

    def test_guardar_un_usuario_inexistente_se_rechaza(self, uow: UnidadDeTrabajo) -> None:
        with uow, pytest.raises(UsuarioNoEncontradoError):
            uow.usuarios.guardar(Usuario(id=999, nombre="Nadie", email="nadie@mail.com"))

    def test_eliminar_y_confirmar_borra_el_usuario(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        with uow:
            uow.usuarios.eliminar(ana_id)
            uow.confirmar()

        with uow:
            assert uow.usuarios.obtener(ana_id) is None
        with uow, pytest.raises(UsuarioNoEncontradoError):
            uow.usuarios.eliminar(ana_id)

    def test_cambiar_el_hash(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        with uow:
            uow.usuarios.guardar_password_hash(ana_id, "hash-nuevo")
            uow.confirmar()

        with uow:
            assert uow.usuarios.obtener_password_hash(ana_id) == "hash-nuevo"
            assert uow.usuarios.obtener_password_hash(999) is None
        with uow, pytest.raises(UsuarioNoEncontradoError):
            uow.usuarios.guardar_password_hash(999, "x")


# ── Reportes de ventas ───────────────────────────────────────────────────────


class TestConsultasVentas:
    def test_sin_pedidos_los_reportes_estan_vacios(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            assert uow.ventas.gasto_por_usuario() == []
            assert uow.ventas.libros_mas_vendidos() == []

    def test_suman_por_usuario_y_por_libro_sin_cancelados(
        self, uow: UnidadDeTrabajo, ana_id: int
    ) -> None:
        beto = Usuario(nombre="Beto", email="beto@mail.com")
        with uow:
            uow.usuarios.agregar(beto)
            assert beto.id is not None
            libros = uow.libros.obtener_varios([CIEN_AÑOS, RAYUELA])
            de_ana = pedidos.crear_pedido(ana_id, {CIEN_AÑOS: 2, RAYUELA: 1}, libros, fecha=HOY)
            de_beto = pedidos.crear_pedido(beto.id, {CIEN_AÑOS: 1}, libros, fecha=HOY)
            cancelado = pedidos.crear_pedido(beto.id, {RAYUELA: 3}, libros, fecha=HOY)
            for pedido in (de_ana, de_beto, cancelado):
                uow.pedidos.agregar(pedido)
            cancelado.estatus = "cancelado"
            uow.pedidos.guardar(cancelado)
            uow.confirmar()

        with uow:
            gasto = uow.ventas.gasto_por_usuario()
            vendidos = uow.ventas.libros_mas_vendidos()
            solo_uno = uow.ventas.libros_mas_vendidos(limite=1)

        assert [(g.nombre, g.pedidos) for g in gasto] == [("Ana", 1), ("Beto", 1)]
        assert gasto[0].total == pytest.approx(2 * 349.90 + 399.50)
        assert gasto[1].total == pytest.approx(349.90)
        assert [(v.titulo, v.cantidad) for v in vendidos] == [
            ("Cien años de soledad", 3),
            ("Rayuela", 1),
        ]
        assert len(solo_uno) == 1


# ── Unidad de trabajo ────────────────────────────────────────────────────────


class TestUnidadDeTrabajo:
    def test_sin_confirmar_los_cambios_se_descartan(self, uow: UnidadDeTrabajo) -> None:
        with uow:
            uow.libros.agregar(libro_nuevo())
            # se olvida confirmar()

        with uow:
            assert uow.libros.obtener("978-607-16-0001-1") is None

    def test_si_hay_una_excepcion_se_revierte_y_se_propaga(self, uow: UnidadDeTrabajo) -> None:
        with pytest.raises(RuntimeError, match="algo falló"), uow:
            uow.libros.agregar(libro_nuevo())
            raise RuntimeError("algo falló")

        with uow:
            assert uow.libros.obtener("978-607-16-0001-1") is None

    def test_varios_cambios_se_guardan_juntos(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        # Así se verá el caso de uso CrearPedido del paso 3: dominio + puertos
        with uow:
            libros = uow.libros.obtener_varios([CIEN_AÑOS, RAYUELA])
            pedido = pedidos.crear_pedido(ana_id, {CIEN_AÑOS: 2, RAYUELA: 1}, libros, fecha=HOY)
            for libro in libros.values():
                uow.libros.guardar(libro)
            uow.pedidos.agregar(pedido)
            uow.confirmar()

        assert pedido.id is not None
        with uow:
            assert uow.pedidos.obtener(pedido.id) is not None
            stock = uow.libros.obtener_varios([CIEN_AÑOS, RAYUELA])
        assert stock[CIEN_AÑOS].cantidad_disponible == 10
        assert stock[RAYUELA].cantidad_disponible == 4

    def test_si_falla_a_la_mitad_no_se_guarda_nada(self, uow: UnidadDeTrabajo, ana_id: int) -> None:
        with pytest.raises(RuntimeError), uow:
            libros = uow.libros.obtener_varios([RAYUELA])
            pedido = pedidos.crear_pedido(ana_id, {RAYUELA: 2}, libros, fecha=HOY)
            uow.libros.guardar(libros[RAYUELA])  # stock descontado...
            uow.pedidos.agregar(pedido)  # ...y pedido registrado (con id)...
            raise RuntimeError("se cayó antes de confirmar")

        with uow:
            libro = uow.libros.obtener(RAYUELA)
            assert libro is not None and libro.cantidad_disponible == 5  # ...pero nada quedó
            assert pedido.id is not None and uow.pedidos.obtener(pedido.id) is None
