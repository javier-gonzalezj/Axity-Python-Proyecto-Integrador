"""Casos de uso de pedidos: crear, cambiar estatus y consultar.

Cada caso de uso ORQUESTA; no decide reglas:

1. obtiene lo que necesita a través de los puertos (UnidadDeTrabajo),
2. le deja las decisiones al dominio (pedidos.py, Libro),
3. guarda el resultado y confirma todo junto o nada,
4. y solo entonces avisa al cliente (puerto Notificador).

El aviso va DESPUÉS de confirmar y fuera de la transacción: no se avisa de algo
que luego se revirtió. Y si el aviso falla, el pedido ya quedó guardado: solo
se registra una advertencia en el log, no se deshace nada.

Las reglas de QUIÉN puede hacer cada cosa (dueño del pedido, rol admin) se
quedan en la API (api/dependencies.py), porque dependen del token.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from libreria.aplicacion.puertos import Notificador, UnidadDeTrabajo
from libreria.dominio import pedidos
from libreria.dominio.excepciones import (
    PedidoNoEncontradoError,
    ServicioExternoError,
    UsuarioNoEncontradoError,
)
from libreria.dominio.modelos import Usuario
from libreria.dominio.pedidos import Pedido

log = logging.getLogger(__name__)

# El reloj también es una dependencia: en las pruebas se pasa uno fijo
type Reloj = Callable[[], datetime]


# ── Comandos: lo que entra a cada caso de uso ────────────────────────────────


@dataclass(frozen=True)
class CrearPedidoComando:
    usuario_id: int
    lineas: Mapping[str, int]  # {isbn: cantidad}


@dataclass(frozen=True)
class CambiarEstatusComando:
    pedido_id: int
    estatus: str


# ── Casos de uso ─────────────────────────────────────────────────────────────


class CrearPedido:
    """Un usuario pide libros: se descuenta el stock y se registra el pedido."""

    def __init__(
        self, uow: UnidadDeTrabajo, notificador: Notificador, ahora: Reloj = datetime.now
    ) -> None:
        self._uow = uow
        self._notificador = notificador
        self._ahora = ahora

    def ejecutar(self, cmd: CrearPedidoComando) -> Pedido:
        with self._uow as uow:
            usuario = uow.usuarios.obtener(cmd.usuario_id)
            if usuario is None:
                raise UsuarioNoEncontradoError(f"No existe el usuario {cmd.usuario_id}")

            libros = uow.libros.obtener_varios(cmd.lineas)
            # El dominio valida y descuenta (o lanza el error sin tocar nada)
            pedido = pedidos.crear_pedido(cmd.usuario_id, cmd.lineas, libros, fecha=self._ahora())

            for isbn in cmd.lineas:
                uow.libros.guardar(libros[isbn])
            uow.pedidos.agregar(pedido)
            uow.confirmar()
            guardado = _releer(uow, pedido)

        _avisar(self._notificador, usuario, *_aviso_pedido_creado(guardado))
        return guardado


class CambiarEstatusPedido:
    """Avanza un pedido (pagado, enviado) o lo cancela regresando el stock."""

    def __init__(self, uow: UnidadDeTrabajo, notificador: Notificador) -> None:
        self._uow = uow
        self._notificador = notificador

    def ejecutar(self, cmd: CambiarEstatusComando) -> Pedido:
        with self._uow as uow:
            pedido = uow.pedidos.obtener(cmd.pedido_id)
            if pedido is None:
                raise PedidoNoEncontradoError(f"No existe el pedido {cmd.pedido_id}")

            libros = uow.libros.obtener_varios(item.isbn for item in pedido.items)
            anterior = pedido.estatus
            pedidos.cambiar_estatus(pedido, cmd.estatus, libros)  # el dominio decide

            cambio = pedido.estatus != anterior  # cancelar dos veces no cambia nada
            if cambio:
                for libro in libros.values():
                    uow.libros.guardar(libro)
                uow.pedidos.guardar(pedido)
                uow.confirmar()
            guardado = _releer(uow, pedido)
            usuario = uow.usuarios.obtener(pedido.usuario_id) if cambio else None

        if usuario is not None:  # solo se avisa si algo cambió
            _avisar(self._notificador, usuario, *_aviso_cambio_estatus(guardado))
        return guardado


# ── Consultas ────────────────────────────────────────────────────────────────


class ObtenerPedido:
    """Un pedido por su id. PedidoNoEncontradoError si no existe."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, pedido_id: int) -> Pedido:
        with self._uow as uow:
            pedido = uow.pedidos.obtener(pedido_id)
        if pedido is None:
            raise PedidoNoEncontradoError(f"No existe el pedido {pedido_id}")
        return pedido


class ListarPedidos:
    """Todos los pedidos, o solo los de un estatus, del más antiguo al más nuevo."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, estatus: str | None = None) -> list[Pedido]:
        with self._uow as uow:
            return uow.pedidos.listar(estatus)


class PedidosDeUsuario:
    """Los pedidos de un usuario. UsuarioNoEncontradoError si el usuario no existe."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, usuario_id: int) -> list[Pedido]:
        with self._uow as uow:
            if uow.usuarios.obtener(usuario_id) is None:
                raise UsuarioNoEncontradoError(f"No existe el usuario {usuario_id}")
            return uow.pedidos.de_usuario(usuario_id)


# ── Avisos ───────────────────────────────────────────────────────────────────

_TEXTO_ESTATUS = {
    "pagado": "Recibimos tu pago. Pronto enviaremos tus libros.",
    "enviado": "Tus libros ya van en camino.",
    "cancelado": "Tu pedido fue cancelado y los libros regresaron al inventario.",
}


def _aviso_pedido_creado(pedido: Pedido) -> tuple[str, str]:
    """(asunto, mensaje) del aviso de pedido nuevo."""
    lineas = "\n".join(
        f"- {item.titulo} x{item.cantidad}: ${item.subtotal:.2f}" for item in pedido.items
    )
    mensaje = f"Tu pedido quedó registrado.\n{lineas}\nTotal: ${pedido.total:.2f}"
    return f"Recibimos tu pedido #{pedido.id}", mensaje


def _aviso_cambio_estatus(pedido: Pedido) -> tuple[str, str]:
    """(asunto, mensaje) del aviso de cambio de estatus."""
    return f"Tu pedido #{pedido.id} ahora está {pedido.estatus}", _TEXTO_ESTATUS[pedido.estatus]


def _avisar(notificador: Notificador, usuario: Usuario, asunto: str, mensaje: str) -> None:
    """Envía el aviso. Si falla, solo lo registra: el pedido ya quedó guardado."""
    try:
        notificador.enviar(usuario.email, asunto, mensaje)
    except ServicioExternoError as e:
        log.warning("No se pudo avisar a %s (%s): %s", usuario.email, asunto, e)


def _releer(uow: UnidadDeTrabajo, pedido: Pedido) -> Pedido:
    """El pedido tal como quedó guardado (con id y en el formato del repositorio)."""
    assert pedido.id is not None  # agregar() ya le asignó uno
    guardado = uow.pedidos.obtener(pedido.id)
    assert guardado is not None
    return guardado
