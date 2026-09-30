"""Dependencias de la API: lógica que FastAPI ejecuta ANTES de cada endpoint.

Cada función se declara una vez y los routers la piden con Depends(...).
Para no repetir `Annotated[..., Depends(...)]` en cada endpoint, al final de
cada bloque hay un alias (SesionDep, LibroDep, ...).

También es la RAÍZ DE COMPOSICIÓN de la API: el único lugar que conoce los
adaptadores concretos (UnidadDeTrabajoSQL, NotificadorHTTP, HasherArgon2) y
arma los casos de uso con ellos. Los routers solo piden el caso de uso ya
armado (CrearPedidoDep, ListarLibrosDep, ...) y nunca tocan la base de datos.
"""

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Path, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from libreria.api import seguridad
from libreria.aplicacion.casos_uso import (
    ActualizarLibro,
    ActualizarUsuario,
    AgregarLibro,
    Autenticar,
    CambiarEstatusPedido,
    CambiarPassword,
    CambiarRol,
    CrearPedido,
    EliminarLibro,
    EliminarUsuario,
    GastoPorUsuario,
    LibrosMasVendidos,
    ListarLibros,
    ListarPedidos,
    ListarUsuarios,
    ObtenerLibro,
    ObtenerPedido,
    ObtenerUsuario,
    PedidosDeUsuario,
    RegistrarUsuario,
)
from libreria.aplicacion.puertos import Hasher, Notificador, UnidadDeTrabajo
from libreria.dominio.excepciones import UsuarioNoEncontradoError
from libreria.dominio.modelos import Libro, Usuario
from libreria.dominio.pedidos import Pedido
from libreria.infraestructura import basedatos as bd
from libreria.infraestructura.notificadores import NotificadorHTTP, NotificadorRegistro
from libreria.infraestructura.passwords import HasherArgon2
from libreria.infraestructura.repositorios_sql import UnidadDeTrabajoSQL

# Tipo del parámetro `responses` de los decoradores de FastAPI (documenta errores en /docs)
type Respuestas = dict[int | str, dict[str, Any]]


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
@lru_cache
def obtener_motor() -> Engine:
    """Un solo motor para toda la app (lru_cache lo crea la primera vez).

    La URL se puede cambiar con la variable de entorno LIBRERIA_URL_BD.
    """
    return bd.crear_motor(os.environ.get("LIBRERIA_URL_BD", bd.URL_BD))


def obtener_sesion() -> Iterator[Session]:
    """Abre una sesión por petición y la cierra al terminar (dependencia con yield).

    En las pruebas se reemplaza con app.dependency_overrides para usar una base
    en memoria.
    """
    with Session(obtener_motor()) as sesion:
        yield sesion


SesionDep = Annotated[Session, Depends(obtener_sesion)]


# ---------------------------------------------------------------------------
# Adaptadores: aquí se eligen. Los casos de uso solo ven los puertos.
# ---------------------------------------------------------------------------
def obtener_uow(sesion: SesionDep) -> UnidadDeTrabajo:
    return UnidadDeTrabajoSQL(sesion)


UowDep = Annotated[UnidadDeTrabajo, Depends(obtener_uow)]


def obtener_notificador() -> Notificador:
    """Con la variable de entorno LIBRERIA_URL_NOTIFICACIONES los avisos se envían
    por HTTP a esa URL; sin ella (p. ej. en desarrollo) solo se escriben en el log.
    """
    url = os.environ.get("LIBRERIA_URL_NOTIFICACIONES")
    return NotificadorHTTP(url) if url else NotificadorRegistro()


NotificadorDep = Annotated[Notificador, Depends(obtener_notificador)]


def obtener_hasher() -> Hasher:
    return HasherArgon2()


HasherDep = Annotated[Hasher, Depends(obtener_hasher)]


# ---------------------------------------------------------------------------
# Casos de uso (wiring)
# ---------------------------------------------------------------------------
# La mayoría solo necesita la unidad de trabajo. En lugar de escribir una
# función por cada uno, `_con_uow` la fabrica: recibe la clase y devuelve la
# dependencia que la construye con la UoW de la petición.
def _con_uow[T](clase: Callable[[UnidadDeTrabajo], T]) -> Any:
    def construir(uow: UowDep) -> T:
        return clase(uow)

    return Depends(construir)


def _con_hasher[T](clase: Callable[[UnidadDeTrabajo, Hasher], T]) -> Any:
    def construir(uow: UowDep, hasher: HasherDep) -> T:
        return clase(uow, hasher)

    return Depends(construir)


def _con_notificador[T](clase: Callable[[UnidadDeTrabajo, Notificador], T]) -> Any:
    def construir(uow: UowDep, notificador: NotificadorDep) -> T:
        return clase(uow, notificador)

    return Depends(construir)


# Libros
ListarLibrosDep = Annotated[ListarLibros, _con_uow(ListarLibros)]
ObtenerLibroDep = Annotated[ObtenerLibro, _con_uow(ObtenerLibro)]
AgregarLibroDep = Annotated[AgregarLibro, _con_uow(AgregarLibro)]
ActualizarLibroDep = Annotated[ActualizarLibro, _con_uow(ActualizarLibro)]
EliminarLibroDep = Annotated[EliminarLibro, _con_uow(EliminarLibro)]

# Usuarios y cuenta
ListarUsuariosDep = Annotated[ListarUsuarios, _con_uow(ListarUsuarios)]
ObtenerUsuarioDep = Annotated[ObtenerUsuario, _con_uow(ObtenerUsuario)]
ActualizarUsuarioDep = Annotated[ActualizarUsuario, _con_uow(ActualizarUsuario)]
CambiarRolDep = Annotated[CambiarRol, _con_uow(CambiarRol)]
EliminarUsuarioDep = Annotated[EliminarUsuario, _con_uow(EliminarUsuario)]
RegistrarUsuarioDep = Annotated[RegistrarUsuario, _con_hasher(RegistrarUsuario)]
AutenticarDep = Annotated[Autenticar, _con_hasher(Autenticar)]
CambiarPasswordDep = Annotated[CambiarPassword, _con_hasher(CambiarPassword)]

# Pedidos
ListarPedidosDep = Annotated[ListarPedidos, _con_uow(ListarPedidos)]
ObtenerPedidoDep = Annotated[ObtenerPedido, _con_uow(ObtenerPedido)]
PedidosDeUsuarioDep = Annotated[PedidosDeUsuario, _con_uow(PedidosDeUsuario)]
CrearPedidoDep = Annotated[CrearPedido, _con_notificador(CrearPedido)]
CambiarEstatusDep = Annotated[CambiarEstatusPedido, _con_notificador(CambiarEstatusPedido)]

# Reportes
GastoPorUsuarioDep = Annotated[GastoPorUsuario, _con_uow(GastoPorUsuario)]
LibrosMasVendidosDep = Annotated[LibrosMasVendidos, _con_uow(LibrosMasVendidos)]


# ---------------------------------------------------------------------------
# "¿Existe el registro?" — se escribe una vez y la usan GET, PATCH y DELETE
# ---------------------------------------------------------------------------
# Si no existe, el caso de uso lanza LibroNoEncontradoError (o similar) y
# app.py lo traduce a 404, igual que en cualquier otro endpoint.
IsbnPath = Annotated[
    str, Path(min_length=10, max_length=20, description="ISBN del libro, con o sin guiones")
]
IdPath = Annotated[int, Path(gt=0, description="Identificador numérico")]


def libro_existente(isbn: IsbnPath, caso: ObtenerLibroDep) -> Libro:
    return caso.ejecutar(isbn)


def usuario_existente(usuario_id: IdPath, caso: ObtenerUsuarioDep) -> Usuario:
    return caso.ejecutar(usuario_id)


def pedido_existente(pedido_id: IdPath, caso: ObtenerPedidoDep) -> Pedido:
    return caso.ejecutar(pedido_id)


LibroDep = Annotated[Libro, Depends(libro_existente)]
UsuarioDep = Annotated[Usuario, Depends(usuario_existente)]
PedidoDep = Annotated[Pedido, Depends(pedido_existente)]


# ---------------------------------------------------------------------------
# Paginación: ?saltar=0&limite=20 en cualquier listado
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Paginacion:
    saltar: int
    limite: int

    def aplicar[T](self, elementos: list[T]) -> list[T]:
        return elementos[self.saltar : self.saltar + self.limite]


def paginacion(
    saltar: Annotated[int, Query(ge=0, description="Cuántos registros omitir")] = 0,
    limite: Annotated[int, Query(ge=1, le=100, description="Máximo de registros")] = 20,
) -> Paginacion:
    return Paginacion(saltar=saltar, limite=limite)


PaginacionDep = Annotated[Paginacion, Depends(paginacion)]


# ---------------------------------------------------------------------------
# Autenticación (¿quién eres?) y autorización (¿qué puedes hacer?)
# ---------------------------------------------------------------------------
# Lee el encabezado "Authorization: Bearer <token>" y responde 401 si falta.
# tokenUrl le dice a /docs dónde iniciar sesión (botón "Authorize").
esquema_oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token")


def _no_autenticado(mensaje: str) -> HTTPException:
    # El encabezado WWW-Authenticate es lo que el estándar pide junto con un 401
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=mensaje,
        headers={"WWW-Authenticate": "Bearer"},
    )


def usuario_actual(
    token: Annotated[str, Depends(esquema_oauth2)], caso: ObtenerUsuarioDep
) -> Usuario:
    """El usuario dueño del token. 401 si el token no sirve o el usuario ya no existe."""
    try:
        usuario_id = seguridad.leer_token(token)
    except seguridad.TokenInvalidoError as e:
        raise _no_autenticado(str(e)) from None

    try:
        return caso.ejecutar(usuario_id)
    except UsuarioNoEncontradoError:
        raise _no_autenticado("El usuario del token ya no existe") from None


UsuarioActualDep = Annotated[Usuario, Depends(usuario_actual)]


def _prohibido(mensaje: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=mensaje)


def requiere_admin(actual: UsuarioActualDep) -> Usuario:
    if actual.rol != "admin":
        raise _prohibido("Solo un administrador puede hacer esto")
    return actual


AdminDep = Annotated[Usuario, Depends(requiere_admin)]


# El usuario autenticado va PRIMERO: así, sin token se responde 401 antes de
# revelar si el registro existe (404).
def usuario_autorizado(actual: UsuarioActualDep, usuario: UsuarioDep) -> Usuario:
    """El usuario de la URL, si es uno mismo o si quien pregunta es admin."""
    if actual.rol != "admin" and actual.id != usuario.id:
        raise _prohibido("Solo puedes consultar o modificar tu propia cuenta")
    return usuario


def pedido_autorizado(actual: UsuarioActualDep, pedido: PedidoDep) -> Pedido:
    """El pedido de la URL, si es del usuario autenticado o si quien pregunta es admin."""
    if actual.rol != "admin" and actual.id != pedido.usuario_id:
        raise _prohibido("Este pedido no es tuyo")
    return pedido


UsuarioAutorizadoDep = Annotated[Usuario, Depends(usuario_autorizado)]
PedidoAutorizadoDep = Annotated[Pedido, Depends(pedido_autorizado)]
