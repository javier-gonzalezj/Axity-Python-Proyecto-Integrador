"""Endpoints de clientes: /usuarios.

Permisos:
    listar, crear y cambiar rol     solo admin
    ver, modificar, borrar, pedidos el propio usuario o un admin
Para registrarse sin ser admin está POST /auth/registro.
"""

from fastapi import APIRouter, Depends, status

from libreria.api.dependencies import (
    ActualizarUsuarioDep,
    AdminDep,
    CambiarRolDep,
    EliminarUsuarioDep,
    ListarUsuariosDep,
    PaginacionDep,
    PedidosDeUsuarioDep,
    RegistrarUsuarioDep,
    Respuestas,
    UsuarioAutorizadoDep,
    UsuarioDep,
    requiere_admin,
)
from libreria.api.schemas import (
    PedidoRead,
    RolUpdate,
    UsuarioAdminCreate,
    UsuarioRead,
    UsuarioUpdate,
)
from libreria.aplicacion.casos_uso import (
    ActualizarUsuarioComando,
    CambiarRolComando,
    RegistrarUsuarioComando,
)
from libreria.dominio.modelos import Usuario
from libreria.dominio.pedidos import Pedido

router = APIRouter(
    prefix="/usuarios",
    tags=["usuarios"],
    responses={401: {"description": "No autenticado"}, 403: {"description": "Sin permiso"}},
)

_EMAIL_REPETIDO: Respuestas = {409: {"description": "Ya existe un usuario con ese email"}}
_NO_ENCONTRADO: Respuestas = {404: {"description": "Usuario no encontrado"}}


@router.get(
    "/",
    response_model=list[UsuarioRead],
    summary="Listar usuarios",
    dependencies=[Depends(requiere_admin)],
)
def listar_usuarios(caso: ListarUsuariosDep, pagina: PaginacionDep) -> list[Usuario]:
    return pagina.aplicar(caso.ejecutar())


@router.post(
    "/",
    response_model=UsuarioRead,
    status_code=status.HTTP_201_CREATED,
    summary="Dar de alta un usuario (con cualquier rol)",
    dependencies=[Depends(requiere_admin)],
    responses=_EMAIL_REPETIDO,
)
def crear_usuario(datos: UsuarioAdminCreate, caso: RegistrarUsuarioDep) -> Usuario:
    # Email repetido -> EmailDuplicadoError -> 409 (ver app.py)
    comando = RegistrarUsuarioComando(
        nombre=datos.nombre,
        email=datos.email,
        telefono=datos.telefono,
        password=datos.password,
        rol=datos.rol,
    )
    return caso.ejecutar(comando)


@router.get(
    "/{usuario_id}",
    response_model=UsuarioRead,
    summary="Obtener un usuario",
    responses=_NO_ENCONTRADO,
)
def obtener_usuario(usuario: UsuarioAutorizadoDep) -> Usuario:
    return usuario


@router.patch(
    "/{usuario_id}",
    response_model=UsuarioRead,
    summary="Modificar nombre, email o teléfono",
    responses={**_NO_ENCONTRADO, **_EMAIL_REPETIDO},
)
def actualizar_usuario(
    usuario: UsuarioAutorizadoDep, cambios: UsuarioUpdate, caso: ActualizarUsuarioDep
) -> Usuario:
    assert usuario.id is not None  # viene de la base, siempre tiene id
    comando = ActualizarUsuarioComando(
        usuario_id=usuario.id, **cambios.model_dump(exclude_none=True)
    )
    return caso.ejecutar(comando)


@router.put(
    "/{usuario_id}/rol",
    response_model=UsuarioRead,
    summary="Cambiar el rol de un usuario",
    responses=_NO_ENCONTRADO,
)
def cambiar_rol(
    admin: AdminDep, usuario: UsuarioDep, cambio: RolUpdate, caso: CambiarRolDep
) -> Usuario:
    assert usuario.id is not None and admin.id is not None
    # Quitarse el propio rol de admin -> CambioDeRolInvalidoError -> 409 (ver app.py)
    comando = CambiarRolComando(solicitante_id=admin.id, usuario_id=usuario.id, rol=cambio.rol)
    return caso.ejecutar(comando)


@router.delete(
    "/{usuario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un usuario sin pedidos",
    responses={**_NO_ENCONTRADO, 409: {"description": "El usuario tiene pedidos"}},
)
def eliminar_usuario(usuario: UsuarioAutorizadoDep, caso: EliminarUsuarioDep) -> None:
    assert usuario.id is not None
    caso.ejecutar(usuario.id)  # tiene pedidos -> RegistroEnUsoError -> 409 (ver app.py)


@router.get(
    "/{usuario_id}/pedidos",
    response_model=list[PedidoRead],
    summary="Pedidos de un usuario",
    responses=_NO_ENCONTRADO,
)
def pedidos_de_usuario(usuario: UsuarioAutorizadoDep, caso: PedidosDeUsuarioDep) -> list[Pedido]:
    assert usuario.id is not None
    return caso.ejecutar(usuario.id)
