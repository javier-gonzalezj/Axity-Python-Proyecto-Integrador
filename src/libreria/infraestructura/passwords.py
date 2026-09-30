"""Adaptador del puerto Hasher con Argon2 (biblioteca pwdlib).

Argon2 es lento a propósito, para que adivinar contraseñas por fuerza bruta
sea caro aunque alguien robe la base de datos.
"""

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()

# Hash de una contraseña cualquiera. Cuando el email no existe se verifica contra
# este, para que la respuesta tarde lo mismo y no delate qué emails existen.
_HASH_FALSO = _hasher.hash("contraseña-que-nadie-usa")


def hashear_password(password: str) -> str:
    return _hasher.hash(password)


def verificar_password(password: str, password_hash: str | None) -> bool:
    """True si la contraseña coincide. Con hash None (usuario inexistente o sin
    contraseña) siempre es False, pero tarda lo mismo que una verificación real."""
    if password_hash is None:
        _hasher.verify(password, _HASH_FALSO)
        return False
    return _hasher.verify(password, password_hash)


class HasherArgon2:
    """Adaptador de Hasher (ver aplicacion/puertos.py)."""

    def hashear(self, password: str) -> str:
        return hashear_password(password)

    def verificar(self, password: str, password_hash: str | None) -> bool:
        return verificar_password(password, password_hash)
