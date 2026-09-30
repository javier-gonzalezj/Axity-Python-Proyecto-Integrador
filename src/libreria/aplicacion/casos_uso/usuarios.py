"""Casos de uso de usuarios: registro, inicio de sesión, cuenta y administración.

Las contraseñas se convierten en hash con el puerto Hasher: estos casos de uso
no saben que hoy se usa Argon2. Los tokens JWT, en cambio, son cosa de la API
(api/seguridad.py): aquí solo se decide SI las credenciales son válidas.

Los permisos basados en el token (uno mismo o admin) los revisa la API antes de
llamar a estos casos de uso. Las reglas que no dependen del token (email único,
no quitarse el propio rol de admin, no borrar usuarios con pedidos) viven aquí.
"""

import logging
from dataclasses import dataclass

from libreria.aplicacion.puertos import Hasher, UnidadDeTrabajo
from libreria.dominio.excepciones import (
    CambioDeRolInvalidoError,
    CredencialesInvalidasError,
    EmailDuplicadoError,
    PasswordIncorrectaError,
    RegistroEnUsoError,
    UsuarioNoEncontradoError,
)
from libreria.dominio.modelos import Rol, Usuario

log = logging.getLogger(__name__)


# ── Comandos ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RegistrarUsuarioComando:
    nombre: str
    email: str
    password: str
    telefono: str | None = None
    rol: Rol = "cliente"


@dataclass(frozen=True)
class ActualizarUsuarioComando:
    """Los campos en None no se tocan."""

    usuario_id: int
    nombre: str | None = None
    email: str | None = None
    telefono: str | None = None


@dataclass(frozen=True)
class CambiarRolComando:
    solicitante_id: int  # el admin que hace el cambio
    usuario_id: int
    rol: Rol


@dataclass(frozen=True)
class CambiarPasswordComando:
    usuario_id: int
    actual: str
    nueva: str


# ── Cuenta propia y autenticación ────────────────────────────────────────────


class RegistrarUsuario:
    """Da de alta un usuario con contraseña. EmailDuplicadoError si el email ya existe.

    Lo usan el registro público (siempre con rol "cliente") y el alta que hace
    un admin (con cualquier rol). Qué rol se permite lo decide quien lo llama.
    """

    def __init__(self, uow: UnidadDeTrabajo, hasher: Hasher) -> None:
        self._uow = uow
        self._hasher = hasher

    def ejecutar(self, cmd: RegistrarUsuarioComando) -> Usuario:
        usuario = Usuario(nombre=cmd.nombre, email=cmd.email, telefono=cmd.telefono, rol=cmd.rol)
        password_hash = self._hasher.hashear(cmd.password)  # antes del with: Argon2 tarda
        with self._uow as uow:
            _email_disponible(uow, usuario.email)
            uow.usuarios.agregar(usuario, password_hash)  # le asigna el id
            uow.confirmar()
        log.info("Usuario %s registrado con rol %s", usuario.id, usuario.rol)
        return usuario


class Autenticar:
    """Devuelve el usuario si el email y la contraseña coinciden.

    Si no, lanza CredencialesInvalidasError con el MISMO mensaje en ambos casos
    (email inexistente o contraseña incorrecta), y la verificación se hace
    siempre, para que tarde lo mismo: así no se revela qué emails existen.
    """

    def __init__(self, uow: UnidadDeTrabajo, hasher: Hasher) -> None:
        self._uow = uow
        self._hasher = hasher

    def ejecutar(self, email: str, password: str) -> Usuario:
        with self._uow as uow:
            usuario = uow.usuarios.buscar_por_email(email.strip().lower())
            password_hash = (
                uow.usuarios.obtener_password_hash(usuario.id)
                if usuario is not None and usuario.id is not None
                else None
            )
        valida = self._hasher.verificar(password, password_hash)
        if not valida or usuario is None:
            raise CredencialesInvalidasError("Email o contraseña incorrectos")
        return usuario


class CambiarPassword:
    """Cambia la contraseña si la actual es correcta (si no, PasswordIncorrectaError)."""

    def __init__(self, uow: UnidadDeTrabajo, hasher: Hasher) -> None:
        self._uow = uow
        self._hasher = hasher

    def ejecutar(self, cmd: CambiarPasswordComando) -> None:
        with self._uow as uow:
            guardado = uow.usuarios.obtener_password_hash(cmd.usuario_id)
            if not self._hasher.verificar(cmd.actual, guardado):
                raise PasswordIncorrectaError("La contraseña actual no es correcta")
            uow.usuarios.guardar_password_hash(cmd.usuario_id, self._hasher.hashear(cmd.nueva))
            uow.confirmar()
        log.info("Usuario %s cambió su contraseña", cmd.usuario_id)


# ── Administración de usuarios ───────────────────────────────────────────────


class ActualizarUsuario:
    """Cambia nombre, email o teléfono. EmailDuplicadoError si el email ya es de otro."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, cmd: ActualizarUsuarioComando) -> Usuario:
        with self._uow as uow:
            usuario = _obtener(uow, cmd.usuario_id)
            cambios = {
                "nombre": cmd.nombre,
                "email": cmd.email,
                "telefono": cmd.telefono,
            }
            cambios = {campo: valor for campo, valor in cambios.items() if valor is not None}
            # model_validate (y no model_copy) para que los datos nuevos se validen
            actualizado = Usuario.model_validate({**usuario.model_dump(), **cambios})
            if cmd.email is not None:
                _email_disponible(uow, actualizado.email, excepto_id=usuario.id)
            uow.usuarios.guardar(actualizado)
            uow.confirmar()
        log.info("Usuario %s actualizado", cmd.usuario_id)
        return actualizado


class CambiarRol:
    """Un admin cambia el rol de un usuario, pero nunca se quita el suyo.

    Así el último (o único) admin no se queda sin permisos por error.
    """

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, cmd: CambiarRolComando) -> Usuario:
        if cmd.usuario_id == cmd.solicitante_id and cmd.rol != "admin":
            raise CambioDeRolInvalidoError("No puedes quitarte tu propio rol de admin")
        with self._uow as uow:
            usuario = _obtener(uow, cmd.usuario_id)
            usuario.rol = cmd.rol
            uow.usuarios.guardar(usuario)
            uow.confirmar()
        log.info("Usuario %s ahora tiene rol %s", cmd.usuario_id, cmd.rol)
        return usuario


class EliminarUsuario:
    """Borra un usuario, solo si no tiene pedidos (para no perder el historial de ventas)."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, usuario_id: int) -> None:
        with self._uow as uow:
            usuario = _obtener(uow, usuario_id)
            pedidos = uow.pedidos.de_usuario(usuario_id)
            if pedidos:
                raise RegistroEnUsoError(
                    f"{usuario.nombre} tiene {len(pedidos)} pedido(s); no se puede borrar"
                )
            uow.usuarios.eliminar(usuario_id)
            uow.confirmar()
        log.info("Usuario %s eliminado", usuario_id)


class AsegurarAdministrador:
    """Deja una cuenta como admin con la contraseña indicada.

    Si el email ya existe, le da rol de admin y contraseña nueva; si no, crea
    la cuenta. Resuelve el "huevo y la gallina" (para crear admins por la API
    hay que ser admin) y lo usa api/crear_admin.py. Devuelve (usuario, creado).
    """

    def __init__(self, uow: UnidadDeTrabajo, hasher: Hasher) -> None:
        self._uow = uow
        self._hasher = hasher

    def ejecutar(self, nombre: str, email: str, password: str) -> tuple[Usuario, bool]:
        password_hash = self._hasher.hashear(password)
        with self._uow as uow:
            usuario = uow.usuarios.buscar_por_email(email)
            creado = usuario is None
            if usuario is None:
                usuario = Usuario(nombre=nombre, email=email, rol="admin")
                uow.usuarios.agregar(usuario, password_hash)
            else:
                assert usuario.id is not None  # viene de la base
                usuario.rol = "admin"
                uow.usuarios.guardar(usuario)
                uow.usuarios.guardar_password_hash(usuario.id, password_hash)
            uow.confirmar()
        log.info("Usuario %s es administrador (creado: %s)", usuario.id, creado)
        return usuario, creado


# ── Consultas ────────────────────────────────────────────────────────────────


class ObtenerUsuario:
    """Un usuario por su id. UsuarioNoEncontradoError si no existe."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, usuario_id: int) -> Usuario:
        with self._uow as uow:
            return _obtener(uow, usuario_id)


class BuscarUsuarioPorEmail:
    """El usuario con ese email, o None si no existe."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, email: str) -> Usuario | None:
        with self._uow as uow:
            return uow.usuarios.buscar_por_email(email)


class ListarUsuarios:
    """Todos los usuarios, ordenados por nombre."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self) -> list[Usuario]:
        with self._uow as uow:
            return uow.usuarios.listar()


def _obtener(uow: UnidadDeTrabajo, usuario_id: int) -> Usuario:
    usuario = uow.usuarios.obtener(usuario_id)
    if usuario is None:
        raise UsuarioNoEncontradoError(f"No existe el usuario {usuario_id}")
    return usuario


def _email_disponible(uow: UnidadDeTrabajo, email: str, excepto_id: int | None = None) -> None:
    """Regla de negocio: un email pertenece a un solo usuario."""
    otro = uow.usuarios.buscar_por_email(email)
    if otro is not None and otro.id != excepto_id:
        raise EmailDuplicadoError(f"Ya existe un usuario con email {email}")
