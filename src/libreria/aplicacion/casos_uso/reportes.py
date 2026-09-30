"""Casos de uso de reportes de ventas (solo lectura).

Los cálculos (agrupar y sumar) los hace el adaptador de ConsultasVentas: con
SQL es una sola consulta con GROUP BY, mucho más rápido que traer todos los
pedidos a Python. Aquí solo se piden y se devuelven.
"""

from libreria.aplicacion.puertos import GastoUsuario, LibroVendido, UnidadDeTrabajo


class GastoPorUsuario:
    """Cuánto ha gastado cada usuario (sin contar cancelados), de mayor a menor."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self) -> list[GastoUsuario]:
        with self._uow as uow:
            return uow.ventas.gasto_por_usuario()


class LibrosMasVendidos:
    """Los libros con más ejemplares vendidos (sin contar cancelados)."""

    def __init__(self, uow: UnidadDeTrabajo) -> None:
        self._uow = uow

    def ejecutar(self, limite: int = 5) -> list[LibroVendido]:
        with self._uow as uow:
            return uow.ventas.libros_mas_vendidos(limite)
