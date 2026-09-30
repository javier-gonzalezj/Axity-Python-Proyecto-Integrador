"""Tokens JWT de la API. No depende de FastAPI: son funciones normales.

Las contraseñas (hash y verificación) viven en infraestructura/passwords.py,
porque también las usan los casos de uso, no solo la API.

Configuración (variables de entorno):
    LIBRERIA_JWT_SECRETO   clave para firmar los tokens (mínimo 32 caracteres).
                           Si no existe, se genera una al azar al iniciar: sirve
                           para desarrollo, pero los tokens dejan de valer cada
                           vez que se reinicia el servidor.
    LIBRERIA_JWT_MINUTOS   minutos de validez de cada token (30 por defecto).

Para generar un secreto:  python -c "import secrets; print(secrets.token_urlsafe(48))"
"""

import logging
import os
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from libreria.dominio.excepciones import LibreriaError

log = logging.getLogger(__name__)

ALGORITMO = "HS256"
MINUTOS_VALIDEZ = int(os.environ.get("LIBRERIA_JWT_MINUTOS", "30"))


class TokenInvalidoError(LibreriaError):
    """El token está mal formado, caducó o su firma no coincide."""


def _leer_secreto() -> str:
    secreto = os.environ.get("LIBRERIA_JWT_SECRETO")
    if secreto is None:
        log.warning("LIBRERIA_JWT_SECRETO no está definido; se usa un secreto temporal")
        return secrets.token_urlsafe(48)
    if len(secreto) < 32:
        raise RuntimeError("LIBRERIA_JWT_SECRETO debe tener al menos 32 caracteres")
    return secreto


SECRETO = _leer_secreto()


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
def crear_token(usuario_id: int, minutos: int = MINUTOS_VALIDEZ) -> str:
    """Token firmado con el id del usuario (`sub`) y su caducidad (`exp`).

    El rol NO va en el token: se lee de la base en cada petición, así un cambio
    de rol surte efecto de inmediato.
    """
    ahora = datetime.now(UTC)
    datos = {
        "sub": str(usuario_id),  # el estándar pide que sub sea texto
        "iat": ahora,  # emitido en
        "exp": ahora + timedelta(minutes=minutos),  # caduca en
    }
    return jwt.encode(datos, SECRETO, algorithm=ALGORITMO)


def leer_token(token: str) -> int:
    """Verifica firma y caducidad y devuelve el id del usuario."""
    try:
        datos = jwt.decode(
            token,
            SECRETO,
            algorithms=[ALGORITMO],  # nunca confiar en el algoritmo que diga el token
            options={"require": ["sub", "exp"]},
        )
        return int(datos["sub"])
    except jwt.ExpiredSignatureError:
        raise TokenInvalidoError("El token caducó; inicia sesión de nuevo") from None
    except (jwt.InvalidTokenError, ValueError) as e:
        raise TokenInvalidoError("Token inválido") from e
