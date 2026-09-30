"""Pruebas de integración del CRUD: los casos de uso REALES contra SQLite en memoria.

test_casos_uso.py prueba la orquestación con la unidad de trabajo en memoria;
aquí se comprueba que, con la base de verdad, los mismos casos de uso dejan
los datos como se espera (incluidos los rollbacks cuando algo falla).
"""

from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from libreria.aplicacion.casos_uso import (
    ActualizarLibro,
    ActualizarLibroComando,
    ActualizarUsuario,
    ActualizarUsuarioComando,
    BuscarUsuarioPorEmail,
    EliminarLibro,
    EliminarUsuario,
    ListarLibros,
    ListarPedidos,
    ListarUsuarios,
    RegistrarUsuario,
    RegistrarUsuarioComando,
)
from libreria.dominio.excepciones import (
    EmailDuplicadoError,
    LibroInvalidoError,
    LibroNoEncontradoError,
    PedidoNoEncontradoError,
    RegistroEnUsoError,
    TransicionEstatusError,
    UsuarioNoEncontradoError,
)
from libreria.dominio.modelos import Libro, Usuario
from libreria.infraestructura.repositorios_sql import UnidadDeTrabajoSQL
from tests.conftest import (
    HasherFalso,
    agregar_libro,
    cambiar_estatus,
    cancelar_pedido,
    crear_pedido,
    nuevo_usuario,
)

CIEN_AÑOS = "978-607-07-1234-5"  # 12 ejemplares, $349.90
RAYUELA = "978-84-9793-563-2"  # 5 ejemplares, $399.50


def id_de(usuario: Usuario) -> int:
    assert usuario.id is not None
    return usuario.id


def usuario(sesion: Session, usuario_id: int) -> Usuario | None:
    return UnidadDeTrabajoSQL(sesion).usuarios.obtener(usuario_id)


def libro(sesion: Session, isbn: str) -> Libro | None:
    return UnidadDeTrabajoSQL(sesion).libros.obtener(isbn)


def actualizar_usuario(sesion: Session, usuario_id: int, **cambios: str) -> Usuario:
    comando = ActualizarUsuarioComando(usuario_id=usuario_id, **cambios)
    return ActualizarUsuario(UnidadDeTrabajoSQL(sesion)).ejecutar(comando)


def actualizar_libro(sesion: Session, isbn: str, **cambios: Any) -> Libro:
    comando = ActualizarLibroComando(isbn=isbn, **cambios)
    return ActualizarLibro(UnidadDeTrabajoSQL(sesion)).ejecutar(comando)


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
class TestUsuarios:
    def test_crear_y_leer(self, sesion: Session) -> None:
        ana_id = id_de(nuevo_usuario(sesion))
        nuevo_usuario(sesion, "Beto", "beto@mail.com")

        ana = usuario(sesion, ana_id)
        assert ana is not None
        assert (ana.nombre, ana.email, ana.telefono) == ("Ana", "ana@mail.com", None)
        buscar = BuscarUsuarioPorEmail(UnidadDeTrabajoSQL(sesion))
        assert buscar.ejecutar(" ana@mail.com ") == ana
        listar = ListarUsuarios(UnidadDeTrabajoSQL(sesion))
        assert [u.nombre for u in listar.ejecutar()] == ["Ana", "Beto"]

    def test_leer_inexistente(self, sesion: Session) -> None:
        assert usuario(sesion, 999) is None
        assert BuscarUsuarioPorEmail(UnidadDeTrabajoSQL(sesion)).ejecutar("nadie@mail.com") is None

    def test_registrar_guarda_el_hash_no_la_contraseña(self, sesion: Session) -> None:
        caso = RegistrarUsuario(UnidadDeTrabajoSQL(sesion), HasherFalso())
        ana = caso.ejecutar(
            RegistrarUsuarioComando(nombre="Ana", email="ana@mail.com", password="secreta123")
        )

        hash_guardado = UnidadDeTrabajoSQL(sesion).usuarios.obtener_password_hash(id_de(ana))
        assert hash_guardado == "hash:secreta123"

    def test_registrar_invalido_no_guarda_nada(self, sesion: Session) -> None:
        caso = RegistrarUsuario(UnidadDeTrabajoSQL(sesion), HasherFalso())
        with pytest.raises(ValidationError):
            caso.ejecutar(RegistrarUsuarioComando(nombre="", email="ana@mail.com", password="x"))
        assert ListarUsuarios(UnidadDeTrabajoSQL(sesion)).ejecutar() == []

    def test_registrar_email_repetido(self, sesion: Session) -> None:
        nuevo_usuario(sesion)
        caso = RegistrarUsuario(UnidadDeTrabajoSQL(sesion), HasherFalso())
        with pytest.raises(EmailDuplicadoError, match="email"):
            caso.ejecutar(
                RegistrarUsuarioComando(nombre="Otra", email="ana@mail.com", password="x")
            )

    def test_actualizar_solo_campos_indicados(self, sesion: Session) -> None:
        ana_id = id_de(nuevo_usuario(sesion))

        actualizar_usuario(sesion, ana_id, telefono="55-1234-5678")
        ana = actualizar_usuario(sesion, ana_id, nombre="Ana López")

        assert ana.nombre == "Ana López"
        assert ana.email == "ana@mail.com"  # no cambió
        assert ana.telefono == "55-1234-5678"  # se conservó del cambio anterior
        assert usuario(sesion, ana_id) == ana

    def test_actualizar_con_email_de_otro(self, sesion: Session) -> None:
        ana_id = id_de(nuevo_usuario(sesion))
        nuevo_usuario(sesion, "Beto", "beto@mail.com")

        with pytest.raises(EmailDuplicadoError, match="email"):
            actualizar_usuario(sesion, ana_id, email="beto@mail.com")

        ana = usuario(sesion, ana_id)
        assert ana is not None and ana.email == "ana@mail.com"  # el rollback lo dejó igual

    def test_actualizar_inexistente(self, sesion: Session) -> None:
        with pytest.raises(UsuarioNoEncontradoError):
            actualizar_usuario(sesion, 999, nombre="X")

    def test_eliminar(self, sesion: Session) -> None:
        ana_id = id_de(nuevo_usuario(sesion))
        eliminar = EliminarUsuario(UnidadDeTrabajoSQL(sesion))
        eliminar.ejecutar(ana_id)
        assert usuario(sesion, ana_id) is None

        with pytest.raises(UsuarioNoEncontradoError):
            eliminar.ejecutar(ana_id)

    def test_no_se_elimina_usuario_con_pedidos(self, sesion: Session) -> None:
        ana_id = id_de(nuevo_usuario(sesion))
        crear_pedido(sesion, ana_id, {RAYUELA: 1})

        with pytest.raises(RegistroEnUsoError):
            EliminarUsuario(UnidadDeTrabajoSQL(sesion)).ejecutar(ana_id)
        assert usuario(sesion, ana_id) is not None


# ---------------------------------------------------------------------------
# Libros
# ---------------------------------------------------------------------------
class TestLibros:
    def test_crear_y_leer(self, sesion: Session) -> None:
        original = libro(sesion, CIEN_AÑOS)
        assert original is not None

        nuevo = original.model_copy(update={"isbn": "978-0-00-000000-0", "titulo": "Libro nuevo"})
        agregar_libro(sesion, nuevo)

        assert libro(sesion, "978-0-00-000000-0") == nuevo
        with pytest.raises(LibroInvalidoError, match="Ya existe"):
            agregar_libro(sesion, nuevo)

    def test_actualizar_precio_y_stock(self, sesion: Session) -> None:
        actualizado = actualizar_libro(sesion, RAYUELA, precio=420.0, cantidad_disponible=0)

        assert actualizado.precio == 420.0
        assert actualizado.cantidad_disponible == 0
        assert actualizado.en_stock is False  # se recalcula
        assert actualizado.titulo == "Rayuela"  # no cambió
        assert libro(sesion, RAYUELA) == actualizado

    def test_actualizar_con_datos_invalidos(self, sesion: Session) -> None:
        with pytest.raises(LibroInvalidoError):
            actualizar_libro(sesion, RAYUELA, precio=-5)

        guardado = libro(sesion, RAYUELA)
        assert guardado is not None and guardado.precio == 399.50

    def test_actualizar_inexistente(self, sesion: Session) -> None:
        with pytest.raises(LibroNoEncontradoError):
            actualizar_libro(sesion, "no-existe", precio=1)

    def test_eliminar(self, sesion: Session) -> None:
        listar = ListarLibros(UnidadDeTrabajoSQL(sesion))
        total = len(listar.ejecutar())
        EliminarLibro(UnidadDeTrabajoSQL(sesion)).ejecutar(RAYUELA)

        assert libro(sesion, RAYUELA) is None
        assert len(listar.ejecutar()) == total - 1

    def test_no_se_elimina_libro_vendido(self, sesion: Session) -> None:
        crear_pedido(sesion, id_de(nuevo_usuario(sesion)), {RAYUELA: 1})

        with pytest.raises(RegistroEnUsoError):
            EliminarLibro(UnidadDeTrabajoSQL(sesion)).ejecutar(RAYUELA)
        assert libro(sesion, RAYUELA) is not None


# ---------------------------------------------------------------------------
# Estatus de pedidos
# ---------------------------------------------------------------------------
class TestEstatusPedido:
    def test_flujo_normal(self, sesion: Session) -> None:
        pedido = crear_pedido(sesion, id_de(nuevo_usuario(sesion)), {CIEN_AÑOS: 1})

        assert cambiar_estatus(sesion, pedido.id, "pagado").estatus == "pagado"
        assert cambiar_estatus(sesion, pedido.id, "enviado").estatus == "enviado"
        listar = ListarPedidos(UnidadDeTrabajoSQL(sesion))
        assert [p.id for p in listar.ejecutar("enviado")] == [pedido.id]
        assert listar.ejecutar("pendiente") == []

    def test_no_se_salta_pasos(self, sesion: Session) -> None:
        pedido = crear_pedido(sesion, id_de(nuevo_usuario(sesion)), {CIEN_AÑOS: 1})

        with pytest.raises(TransicionEstatusError):
            cambiar_estatus(sesion, pedido.id, "enviado")
        with pytest.raises(TransicionEstatusError):
            cambiar_estatus(sesion, pedido.id, "inventado")

    def test_cancelar_regresa_stock(self, sesion: Session) -> None:
        pedido = crear_pedido(sesion, id_de(nuevo_usuario(sesion)), {CIEN_AÑOS: 2})
        cambiar_estatus(sesion, pedido.id, "pagado")

        assert cambiar_estatus(sesion, pedido.id, "cancelado").estatus == "cancelado"
        guardado = libro(sesion, CIEN_AÑOS)
        assert guardado is not None and guardado.cantidad_disponible == 12

    def test_no_se_cancela_un_pedido_enviado(self, sesion: Session) -> None:
        pedido = crear_pedido(sesion, id_de(nuevo_usuario(sesion)), {CIEN_AÑOS: 1})
        cambiar_estatus(sesion, pedido.id, "pagado")
        cambiar_estatus(sesion, pedido.id, "enviado")

        with pytest.raises(TransicionEstatusError):
            cancelar_pedido(sesion, pedido.id)
        guardado = libro(sesion, CIEN_AÑOS)
        assert guardado is not None and guardado.cantidad_disponible == 11

    def test_pedido_inexistente(self, sesion: Session) -> None:
        with pytest.raises(PedidoNoEncontradoError):
            cambiar_estatus(sesion, 999, "pagado")
        assert UnidadDeTrabajoSQL(sesion).pedidos.obtener(999) is None
