"""Pruebas de ARQUITECTURA: las dependencias entre capas apuntan hacia adentro.

    api, consola, analitica   (presentación y herramientas)
              │
              ▼
      infraestructura         (adaptadores: SQLAlchemy, archivos, HTTP, Argon2)
              │
              ▼
         aplicacion           (casos de uso y puertos)
              │
              ▼
           dominio            (reglas del negocio)

Una capa puede importar las de abajo, nunca las de arriba. Si alguien escribe
`from libreria.infraestructura import basedatos` dentro de un caso de uso, esta
prueba falla y dice en qué archivo y línea.

Se revisa el código con `ast` (sin ejecutarlo): se leen los `import` y
`from ... import` de cada archivo.
"""

import ast
from pathlib import Path

import pytest

PAQUETE = Path(__file__).parent.parent / "src" / "libreria"

# Qué capas del proyecto puede importar cada capa
PERMITIDAS: dict[str, set[str]] = {
    "dominio": {"dominio"},
    "aplicacion": {"dominio", "aplicacion"},
    "infraestructura": {"dominio", "aplicacion", "infraestructura"},
    "api": {"dominio", "aplicacion", "infraestructura", "api"},
    "consola": {"dominio", "aplicacion", "infraestructura", "consola"},
    "analitica": {"dominio", "aplicacion", "infraestructura", "analitica"},
}

# Bibliotecas técnicas que el núcleo (dominio y aplicación) no debe conocer
TECNICAS = {"sqlalchemy", "fastapi", "starlette", "httpx", "pwdlib", "jwt", "sklearn", "pandas"}


def _importados(archivo: Path) -> list[tuple[int, str]]:
    """(línea, módulo) de cada import del archivo."""
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    modulos: list[tuple[int, str]] = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.extend((nodo.lineno, alias.name) for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            if nodo.module == "libreria":  # from libreria import dominio
                modulos.extend((nodo.lineno, f"libreria.{a.name}") for a in nodo.names)
            else:
                modulos.append((nodo.lineno, nodo.module))
    return modulos


def _archivos(capa: str) -> list[Path]:
    return sorted((PAQUETE / capa).rglob("*.py"))


def test_todo_el_codigo_esta_en_una_capa() -> None:
    sueltos = [p.name for p in PAQUETE.glob("*.py") if p.name != "__init__.py"]
    assert sueltos == [], f"Módulos fuera de las capas: {sueltos}"
    capas = {p.name for p in PAQUETE.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert capas == set(PERMITIDAS)


@pytest.mark.parametrize("capa", sorted(PERMITIDAS))
def test_cada_capa_solo_importa_las_de_abajo(capa: str) -> None:
    violaciones = []
    for archivo in _archivos(capa):
        for linea, modulo in _importados(archivo):
            partes = modulo.split(".")
            if partes[0] == "libreria" and len(partes) > 1 and partes[1] not in PERMITIDAS[capa]:
                ruta = archivo.relative_to(PAQUETE)
                violaciones.append(f"{ruta}:{linea} importa {modulo}")
    assert violaciones == [], "\n".join(violaciones)


@pytest.mark.parametrize("capa", ["dominio", "aplicacion"])
def test_el_nucleo_no_conoce_bibliotecas_tecnicas(capa: str) -> None:
    violaciones = [
        f"{archivo.relative_to(PAQUETE)}:{linea} importa {modulo}"
        for archivo in _archivos(capa)
        for linea, modulo in _importados(archivo)
        if modulo.split(".")[0] in TECNICAS
    ]
    assert violaciones == [], "\n".join(violaciones)


def test_los_routers_no_tocan_la_base_de_datos() -> None:
    """Los endpoints solo hablan con casos de uso (vía api/dependencies.py)."""
    violaciones = [
        f"{archivo.relative_to(PAQUETE)}:{linea} importa {modulo}"
        for archivo in sorted((PAQUETE / "api" / "routers").glob("*.py"))
        for linea, modulo in _importados(archivo)
        if modulo.startswith(("libreria.infraestructura", "sqlalchemy"))
    ]
    assert violaciones == [], "\n".join(violaciones)
