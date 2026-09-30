"""Casos de uso: las acciones que el sistema ofrece (capa de aplicación).

Hay uno por acción, agrupados por recurso:

    pedidos.py    CrearPedido, CambiarEstatusPedido, ObtenerPedido, ...
    libros.py     AgregarLibro, ActualizarLibro, EliminarLibro, ListarLibros, ...
    usuarios.py   RegistrarUsuario, Autenticar, CambiarRol, EliminarUsuario, ...
    reportes.py   GastoPorUsuario, LibrosMasVendidos

Todos se usan igual: se construyen con sus puertos (UnidadDeTrabajo y, si hace
falta, Notificador o Hasher) y se llama a ejecutar(). No saben nada de HTTP ni
de SQLAlchemy: la API (o la consola, o una prueba) arma el caso de uso, le pasa
un comando y traduce el resultado (o la excepción) a su propio formato. Por eso
se prueban con UnidadDeTrabajoEnMemoria (tests/test_casos_uso.py), y las
pruebas de contrato (tests/test_contrato_repositorios.py) garantizan que con la
base real funcionan igual.

Este módulo reúne todos para poder importarlos desde un solo lugar:

    from libreria.aplicacion.casos_uso import CrearPedido, CrearPedidoComando
"""

from libreria.aplicacion.casos_uso.libros import (
    ActualizarLibro,
    ActualizarLibroComando,
    AgregarLibro,
    EliminarLibro,
    FiltrosLibros,
    ListarLibros,
    ObtenerLibro,
)
from libreria.aplicacion.casos_uso.pedidos import (
    CambiarEstatusComando,
    CambiarEstatusPedido,
    CrearPedido,
    CrearPedidoComando,
    ListarPedidos,
    ObtenerPedido,
    PedidosDeUsuario,
    Reloj,
)
from libreria.aplicacion.casos_uso.reportes import GastoPorUsuario, LibrosMasVendidos
from libreria.aplicacion.casos_uso.usuarios import (
    ActualizarUsuario,
    ActualizarUsuarioComando,
    AsegurarAdministrador,
    Autenticar,
    BuscarUsuarioPorEmail,
    CambiarPassword,
    CambiarPasswordComando,
    CambiarRol,
    CambiarRolComando,
    EliminarUsuario,
    ListarUsuarios,
    ObtenerUsuario,
    RegistrarUsuario,
    RegistrarUsuarioComando,
)

__all__ = [
    "ActualizarLibro",
    "ActualizarLibroComando",
    "ActualizarUsuario",
    "ActualizarUsuarioComando",
    "AgregarLibro",
    "AsegurarAdministrador",
    "Autenticar",
    "BuscarUsuarioPorEmail",
    "CambiarEstatusComando",
    "CambiarEstatusPedido",
    "CambiarPassword",
    "CambiarPasswordComando",
    "CambiarRol",
    "CambiarRolComando",
    "CrearPedido",
    "CrearPedidoComando",
    "EliminarLibro",
    "EliminarUsuario",
    "FiltrosLibros",
    "GastoPorUsuario",
    "LibrosMasVendidos",
    "ListarLibros",
    "ListarPedidos",
    "ListarUsuarios",
    "ObtenerLibro",
    "ObtenerPedido",
    "ObtenerUsuario",
    "PedidosDeUsuario",
    "RegistrarUsuario",
    "RegistrarUsuarioComando",
    "Reloj",
]
