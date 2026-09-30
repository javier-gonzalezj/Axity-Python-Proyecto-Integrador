"""Pruebas de los casos de uso de libros, usuarios, autenticación y reportes.

Igual que test_casos_uso.py: sin base de datos, con UnidadDeTrabajoEnMemoria
(el contrato garantiza que se comporta como la de SQL) y con HasherFalso en
lugar de Argon2, para que corran en milisegundos.

Se prueban sobre todo las REGLAS que antes vivían en los routers de la API y
ahora viven en la capa de aplicación: email único, no quitarse el propio rol
de admin, no borrar libros vendidos ni usuarios con pedidos, y que un error
no deje nada a medias (no se confirma).
"""

from datetime import datetime

import pytest

from libreria.aplicacion.casos_uso import (
    ActualizarLibro,
    ActualizarLibroComando,
    ActualizarUsuario,
    ActualizarUsuarioComando,
    AsegurarAdministrador,
    Autenticar,
    CambiarPassword,
    CambiarPasswordComando,
    CambiarRol,
    CambiarRolComando,
    CrearPedido,
    CrearPedidoComando,
    EliminarLibro,
    EliminarUsuario,
    FiltrosLibros,
    GastoPorUsuario,
    LibrosMasVendidos,
    ListarLibros,
    ObtenerLibro,
    ObtenerPedido,
    ObtenerUsuario,
    PedidosDeUsuario,
    RegistrarUsuario,
    RegistrarUsuarioComando,
)
from libreria.aplicacion.puertos import GastoUsuario, LibroVendido
from libreria.dominio.excepciones import (
    CambioDeRolInvalidoError,
    CredencialesInvalidasError,
    EmailDuplicadoError,
    LibroInvalidoError,
    LibroNoEncontradoError,
    PasswordIncorrectaError,
    PedidoNoEncontradoError,
    RegistroEnUsoError,
    UsuarioNoEncontradoError,
)
from libreria.dominio.modelos import Autor, Libro, Usuario
from libreria.infraestructura.notificadores import NotificadorEnMemoria
from libreria.infraestructura.repositorios_memoria import UnidadDeTrabajoEnMemoria
from tests.conftest import HasherFalso

HOY = datetime(2026, 9, 29, 12, 0)
ADMIN, ANA = 1, 2


def hacer_libro(isbn: str, cantidad: int, precio: float = 100.0, autor: str = "Rulfo") -> Libro:
    return Libro(
        isbn=isbn,
        titulo=f"Libro {isbn}",
        autor=Autor(nombre=autor),
        genero=["Novela"],
        año_publicacion=2000,
        precio=precio,
        en_stock=cantidad > 0,
        cantidad_disponible=cantidad,
        editorial="Editorial X",
    )


@pytest.fixture
def uow() -> UnidadDeTrabajoEnMemoria:
    """Libros A (5 ejemplares, Rulfo) y B (sin stock, Borges); un admin y Ana."""
    uow = UnidadDeTrabajoEnMemoria(
        libros=[hacer_libro("A", 5, precio=200.0), hacer_libro("B", 0, autor="Borges")],
        usuarios=[
            Usuario(id=ADMIN, nombre="Admin", email="admin@libreria.mx", rol="admin"),
            Usuario(id=ANA, nombre="Ana", email="ana@mail.com"),
        ],
    )
    # Ana tiene contraseña; el admin no (como un usuario anterior a la migración 0003)
    uow.usuarios.guardar_password_hash(ANA, HasherFalso().hashear("libros2026"))
    uow.confirmar()
    uow.confirmaciones = 0
    return uow


def pedido_de_ana(uow: UnidadDeTrabajoEnMemoria, lineas: dict[str, int]) -> int:
    caso = CrearPedido(uow, NotificadorEnMemoria(), ahora=lambda: HOY)
    pedido = caso.ejecutar(CrearPedidoComando(usuario_id=ANA, lineas=lineas))
    assert pedido.id is not None
    return pedido.id


# ── Libros ───────────────────────────────────────────────────────────────────


class TestLibros:
    def test_actualizar_cambia_solo_lo_indicado_y_recalcula_en_stock(
        self, uow: UnidadDeTrabajoEnMemoria
    ) -> None:
        comando = ActualizarLibroComando(isbn="A", precio=250.0, cantidad_disponible=0)
        libro = ActualizarLibro(uow).ejecutar(comando)

        assert (libro.precio, libro.cantidad_disponible, libro.en_stock) == (250.0, 0, False)
        assert libro.titulo == "Libro A"  # no cambió
        assert uow.libros.obtener("A") == libro
        assert uow.confirmaciones == 1

    def test_actualizar_con_datos_invalidos_no_guarda(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        with pytest.raises(LibroInvalidoError):
            ActualizarLibro(uow).ejecutar(ActualizarLibroComando(isbn="A", precio=-1))

        libro = uow.libros.obtener("A")
        assert libro is not None and libro.precio == 200.0
        assert uow.confirmaciones == 0

    def test_actualizar_inexistente(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        with pytest.raises(LibroNoEncontradoError):
            ActualizarLibro(uow).ejecutar(ActualizarLibroComando(isbn="Z", precio=1))

    def test_eliminar_un_libro_sin_ventas(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        EliminarLibro(uow).ejecutar("B")

        assert uow.libros.obtener("B") is None
        assert uow.confirmaciones == 1

    def test_no_se_elimina_un_libro_vendido(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        pedido_de_ana(uow, {"A": 1})
        antes = uow.confirmaciones

        with pytest.raises(RegistroEnUsoError, match="aparece en pedidos"):
            EliminarLibro(uow).ejecutar("A")

        assert uow.libros.obtener("A") is not None
        assert uow.confirmaciones == antes

    def test_obtener_inexistente(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        assert ObtenerLibro(uow).ejecutar("A").titulo == "Libro A"
        with pytest.raises(LibroNoEncontradoError, match="No existe"):
            ObtenerLibro(uow).ejecutar("Z")

    def test_listar_aplica_los_filtros_del_dominio(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        listar = ListarLibros(uow)

        assert [li.isbn for li in listar.ejecutar()] == ["A", "B"]
        assert [li.isbn for li in listar.ejecutar(FiltrosLibros(en_stock=True))] == ["A"]
        assert [li.isbn for li in listar.ejecutar(FiltrosLibros(autor="borges"))] == ["B"]
        assert listar.ejecutar(FiltrosLibros(precio_max=50)) == []


# ── Registro y autenticación ─────────────────────────────────────────────────


class TestRegistroYAutenticacion:
    def test_registrar_asigna_id_y_guarda_solo_el_hash(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        comando = RegistrarUsuarioComando(nombre="Beto", email="beto@mail.com", password="secreta1")
        beto = RegistrarUsuario(uow, HasherFalso()).ejecutar(comando)

        assert beto.id is not None and beto.rol == "cliente"
        assert uow.usuarios.obtener_password_hash(beto.id) == "hash:secreta1"
        assert uow.confirmaciones == 1

    def test_registrar_email_repetido_no_guarda(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        comando = RegistrarUsuarioComando(nombre="Otra", email="ana@mail.com", password="x")
        with pytest.raises(EmailDuplicadoError, match="ana@mail.com"):
            RegistrarUsuario(uow, HasherFalso()).ejecutar(comando)
        assert uow.confirmaciones == 0

    def test_autenticar_con_datos_correctos(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        # El email se normaliza: espacios y mayúsculas no importan
        usuario = Autenticar(uow, HasherFalso()).ejecutar("  ANA@mail.com ", "libros2026")
        assert usuario.id == ANA

    @pytest.mark.parametrize(
        ("email", "password"),
        [
            ("ana@mail.com", "incorrecta"),  # contraseña mala
            ("nadie@mail.com", "libros2026"),  # email que no existe
            ("admin@libreria.mx", "cualquiera"),  # usuario sin contraseña
        ],
    )
    def test_autenticar_falla_siempre_con_el_mismo_mensaje(
        self, uow: UnidadDeTrabajoEnMemoria, email: str, password: str
    ) -> None:
        with pytest.raises(CredencialesInvalidasError, match="^Email o contraseña incorrectos$"):
            Autenticar(uow, HasherFalso()).ejecutar(email, password)

    def test_cambiar_password(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        comando = CambiarPasswordComando(usuario_id=ANA, actual="libros2026", nueva="nueva1234")
        CambiarPassword(uow, HasherFalso()).ejecutar(comando)

        assert Autenticar(uow, HasherFalso()).ejecutar("ana@mail.com", "nueva1234").id == ANA

    def test_cambiar_password_con_la_actual_incorrecta(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        comando = CambiarPasswordComando(usuario_id=ANA, actual="otra", nueva="nueva1234")
        with pytest.raises(PasswordIncorrectaError):
            CambiarPassword(uow, HasherFalso()).ejecutar(comando)
        assert uow.usuarios.obtener_password_hash(ANA) == "hash:libros2026"


# ── Administración de usuarios ───────────────────────────────────────────────


class TestAdministracionUsuarios:
    def test_actualizar_solo_lo_indicado(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        comando = ActualizarUsuarioComando(usuario_id=ANA, telefono="55-1234-5678")
        ana = ActualizarUsuario(uow).ejecutar(comando)

        assert (ana.nombre, ana.email, ana.telefono) == ("Ana", "ana@mail.com", "55-1234-5678")
        assert uow.usuarios.obtener(ANA) == ana

    def test_actualizar_con_su_propio_email_no_es_duplicado(
        self, uow: UnidadDeTrabajoEnMemoria
    ) -> None:
        comando = ActualizarUsuarioComando(usuario_id=ANA, nombre="Ana L.", email="ana@mail.com")
        assert ActualizarUsuario(uow).ejecutar(comando).nombre == "Ana L."

    def test_actualizar_con_email_de_otro(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        comando = ActualizarUsuarioComando(usuario_id=ANA, email="admin@libreria.mx")
        with pytest.raises(EmailDuplicadoError):
            ActualizarUsuario(uow).ejecutar(comando)
        assert uow.confirmaciones == 0

    def test_un_admin_cambia_el_rol_de_otro(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        comando = CambiarRolComando(solicitante_id=ADMIN, usuario_id=ANA, rol="admin")
        assert CambiarRol(uow).ejecutar(comando).rol == "admin"

    def test_un_admin_no_se_quita_su_propio_rol(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        comando = CambiarRolComando(solicitante_id=ADMIN, usuario_id=ADMIN, rol="cliente")
        with pytest.raises(CambioDeRolInvalidoError):
            CambiarRol(uow).ejecutar(comando)

        admin = uow.usuarios.obtener(ADMIN)
        assert admin is not None and admin.rol == "admin"

    def test_cambiar_rol_de_inexistente(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        comando = CambiarRolComando(solicitante_id=ADMIN, usuario_id=999, rol="admin")
        with pytest.raises(UsuarioNoEncontradoError):
            CambiarRol(uow).ejecutar(comando)

    def test_eliminar_usuario_sin_pedidos(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        EliminarUsuario(uow).ejecutar(ANA)

        with pytest.raises(UsuarioNoEncontradoError):
            ObtenerUsuario(uow).ejecutar(ANA)

    def test_no_se_elimina_usuario_con_pedidos(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        pedido_de_ana(uow, {"A": 1})

        with pytest.raises(RegistroEnUsoError, match="1 pedido"):
            EliminarUsuario(uow).ejecutar(ANA)
        assert uow.usuarios.obtener(ANA) is not None

    def test_asegurar_administrador_crea_la_cuenta(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        caso = AsegurarAdministrador(uow, HasherFalso())
        usuario, creado = caso.ejecutar("Luis", "luis@mail.com", "clave1234")

        assert creado and usuario.rol == "admin"
        assert Autenticar(uow, HasherFalso()).ejecutar("luis@mail.com", "clave1234") == usuario

    def test_asegurar_administrador_promueve_una_cuenta_existente(
        self, uow: UnidadDeTrabajoEnMemoria
    ) -> None:
        caso = AsegurarAdministrador(uow, HasherFalso())
        usuario, creado = caso.ejecutar("se ignora", "ana@mail.com", "clave1234")

        assert not creado
        assert (usuario.id, usuario.nombre, usuario.rol) == (ANA, "Ana", "admin")
        assert Autenticar(uow, HasherFalso()).ejecutar("ana@mail.com", "clave1234").id == ANA


# ── Consultas de pedidos y reportes ──────────────────────────────────────────


class TestConsultas:
    def test_obtener_pedido(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        pedido_id = pedido_de_ana(uow, {"A": 1})

        assert ObtenerPedido(uow).ejecutar(pedido_id).usuario_id == ANA
        with pytest.raises(PedidoNoEncontradoError):
            ObtenerPedido(uow).ejecutar(999)

    def test_pedidos_de_usuario(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        pedido_id = pedido_de_ana(uow, {"A": 1})

        assert [p.id for p in PedidosDeUsuario(uow).ejecutar(ANA)] == [pedido_id]
        assert PedidosDeUsuario(uow).ejecutar(ADMIN) == []
        with pytest.raises(UsuarioNoEncontradoError):
            PedidosDeUsuario(uow).ejecutar(999)

    def test_reportes(self, uow: UnidadDeTrabajoEnMemoria) -> None:
        pedido_de_ana(uow, {"A": 2})

        assert GastoPorUsuario(uow).ejecutar() == [GastoUsuario("Ana", 1, 400.0)]
        assert LibrosMasVendidos(uow).ejecutar() == [LibroVendido("Libro A", 2)]
