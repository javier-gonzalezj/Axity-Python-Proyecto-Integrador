"""Registro, inicio de sesión y cuenta propia: /auth."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from libreria.api import seguridad
from libreria.api.dependencies import (
    AutenticarDep,
    CambiarPasswordDep,
    RegistrarUsuarioDep,
    UsuarioActualDep,
)
from libreria.api.schemas import PasswordUpdate, Token, UsuarioCreate, UsuarioRead
from libreria.aplicacion.casos_uso import CambiarPasswordComando, RegistrarUsuarioComando
from libreria.dominio.excepciones import CredencialesInvalidasError
from libreria.dominio.modelos import Usuario

router = APIRouter(prefix="/auth", tags=["autenticación"])


@router.post(
    "/registro",
    response_model=UsuarioRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una cuenta de cliente",
    responses={409: {"description": "Ya existe un usuario con ese email"}},
)
def registrarse(datos: UsuarioCreate, caso: RegistrarUsuarioDep) -> Usuario:
    # Email repetido -> EmailDuplicadoError -> 409 (ver app.py)
    comando = RegistrarUsuarioComando(
        nombre=datos.nombre,
        email=datos.email,
        telefono=datos.telefono,
        password=datos.password,
        rol="cliente",  # registrarse nunca da permisos de admin
    )
    return caso.ejecutar(comando)


@router.post(
    "/token",
    response_model=Token,
    summary="Iniciar sesión",
    responses={401: {"description": "Email o contraseña incorrectos"}},
)
def iniciar_sesion(
    formulario: Annotated[OAuth2PasswordRequestForm, Depends()], caso: AutenticarDep
) -> Token:
    """Recibe un formulario (no JSON) con `username` y `password`, como pide OAuth2.

    En `username` va el email. Esto es lo que usa el botón "Authorize" de /docs.
    """
    try:
        usuario = caso.ejecutar(formulario.username, formulario.password)
    except CredencialesInvalidasError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, str(e), headers={"WWW-Authenticate": "Bearer"}
        ) from None
    assert usuario.id is not None  # viene de la base
    # El caso de uso decide SI las credenciales valen; el token es cosa de la API
    return Token(
        access_token=seguridad.crear_token(usuario.id),
        expira_en=seguridad.MINUTOS_VALIDEZ * 60,
    )


@router.get("/yo", response_model=UsuarioRead, summary="Mi cuenta")
def mi_cuenta(actual: UsuarioActualDep) -> Usuario:
    return actual


@router.put(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cambiar mi contraseña",
    responses={400: {"description": "La contraseña actual no es correcta"}},
)
def cambiar_password(
    cambio: PasswordUpdate, actual: UsuarioActualDep, caso: CambiarPasswordDep
) -> None:
    assert actual.id is not None
    # Contraseña actual incorrecta -> PasswordIncorrectaError -> 400 (ver app.py)
    caso.ejecutar(
        CambiarPasswordComando(usuario_id=actual.id, actual=cambio.actual, nueva=cambio.nueva)
    )
