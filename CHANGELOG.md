# Historial de cambios

Los cambios más recientes van primero. Cada entrada describe el proyecto **en ese momento**: los nombres de archivo son los de entonces (desde "Arquitectura por capas", los módulos viven en carpetas por capa; por ejemplo, `pedidos.py` está hoy en `src/libreria/dominio/`).

## Auditoría de dependencias

- **`.github/workflows/auditoria.yml`**: `pip-audit` revisa las versiones de `poetry.lock` en cada push, en cada pull request y cada lunes. Falla si hay vulnerabilidades conocidas y guarda el reporte `auditoria-dependencias.json` como artefacto. La primera auditoría (30 de septiembre de 2026) no encontró vulnerabilidades en los 87 paquetes del proyecto.
- **`.github/dependabot.yml`**: pull requests semanales con versiones nuevas de las dependencias de Python y de las acciones del CI.
- **`pip-audit`** como dependencia de desarrollo (`poetry run pip-audit --skip-editable`). Se agregaron 18 paquetes de desarrollo a `poetry.lock`; ninguna versión existente cambió.
- **`requires-python = ">=3.13,<4.0"`** (antes `">=3.13"`): sin el límite superior, Poetry no podía instalar `pip-audit`, porque una de sus bibliotecas solo declara soporte hasta antes de Python 4.

## Docker, integración continua y extra `ml`

- **`Dockerfile` multistage** y **`.dockerignore`**: la etapa `builder` instala Poetry 2.5.1 (la versión que generó `poetry.lock`) y las dependencias de producción; la etapa final solo copia el entorno, las migraciones y `alembic.ini`, y corre con un usuario sin privilegios.
- **`.github/workflows/ci.yml`**: lint, formato y tipos; pruebas con cobertura; y construcción de la imagen con una prueba de humo.
- **`migraciones/env.py` respeta `LIBRERIA_URL_BD`**: antes Alembic siempre usaba la base de `alembic.ini` aunque la API usara otra.
- **Extra opcional `ml`**: scikit-learn, pandas y joblib salieron de las dependencias principales, porque solo las usa `analitica/prediccion.py`. Se instalan con `poetry install --all-extras`. `poetry.lock` se regeneró con Poetry 2.5.1 sin cambiar ninguna versión. Las bibliotecas de la imagen Docker bajaron de 347 MB a 88 MB. Si faltan, `prediccion.py` dice cómo instalarlas en lugar de lanzar un `ModuleNotFoundError` sin contexto.
- **README** reorganizado en tres archivos: `README.md`, este historial y `docs/detalles_tecnicos.md`.
- **Diagramas en Mermaid** (GitHub los dibuja al ver el archivo): arquitectura por capas en el README, y modelo de datos y estados de un pedido en `docs/detalles_tecnicos.md`.

## Arquitectura por capas y API sobre casos de uso

- **Carpetas por capa**: los módulos que estaban sueltos en `src/libreria/` pasan a `dominio/`, `aplicacion/`, `infraestructura/`, `consola/` y `analitica/` (la API ya estaba en `api/`). Cambian las rutas de los comandos (`python -m libreria.infraestructura.basedatos`, `python -m libreria.analitica.prediccion`, …) y el script `libreria` apunta a `libreria.consola.main:main`.
- **Todos los endpoints pasan por casos de uso**. Antes solo crear pedido, cambiar estatus y agregar libro lo hacían; los de usuarios, autenticación, reportes, editar/borrar libros y las consultas llamaban directo a `basedatos.py`. Casos de uso nuevos: `ActualizarLibro`, `EliminarLibro`, `ObtenerLibro`, `ListarLibros`, `RegistrarUsuario`, `Autenticar`, `CambiarPassword`, `ActualizarUsuario`, `CambiarRol`, `EliminarUsuario`, `AsegurarAdministrador`, `ObtenerUsuario`, `BuscarUsuarioPorEmail`, `ListarUsuarios`, `ObtenerPedido`, `ListarPedidos`, `PedidosDeUsuario`, `GastoPorUsuario` y `LibrosMasVendidos`. `casos_uso.py` se volvió el paquete `casos_uso/`, con un módulo por recurso.
- **Reglas que salieron de los routers**: email único, no quitarse el propio rol de admin, no borrar libros vendidos ni usuarios con pedidos, y la verificación de credenciales. Viven en los casos de uso, con excepciones nuevas (`EmailDuplicadoError`, `CambioDeRolInvalidoError`, `CredencialesInvalidasError`, `PasswordIncorrectaError`) que `app.py` traduce a HTTP. Las respuestas de la API no cambiaron.
- **Puertos ampliados**: los repositorios ganaron `listar`, `eliminar`, `buscar_por_email`, `de_usuario`, `incluyen_libro` y el manejo del hash de contraseña; `ConsultasVentas` (reportes) y `Hasher` (contraseñas) son nuevos. `LectorLibros` desacopla `ServicioCatalogo` del CSV: ahora recibe un `LectorCSV`.
- **`basedatos.py` solo tiene lo técnico**: tablas, motor, traducción filas ↔ dominio e `importar_catalogo`. Se quitaron las operaciones CRUD que duplicaban a los repositorios.
- **`Libro.con_cambios()`** (dominio): devuelve un libro nuevo con los campos cambiados y validados; lo usa `ActualizarLibro`.
- **Corrección**: `consola/main.py` calculaba mal la ruta de `data/` al quedar un nivel más adentro.
- **Pruebas nuevas**: `test_arquitectura.py`, `test_casos_uso_libros_usuarios.py` (con la unidad de trabajo en memoria y un `HasherFalso`) y más casos de contrato en `test_contrato_repositorios.py`. `test_crud.py` ahora prueba los casos de uso contra SQLite.

## Notificaciones al cliente (puerto Notificador)

Cuando se crea un pedido o cambia su estatus, el cliente recibe un aviso. El núcleo solo conoce el puerto `Notificador`; cómo viaja el aviso lo decide el adaptador.

- **Puerto `Notificador`** en `puertos.py`, con el método `enviar(destinatario, asunto, mensaje)`. Si no se puede entregar el aviso, lanza `ServicioExternoError`.
- **Adaptadores** en `notificadores.py` (nuevo):
  - `NotificadorHTTP`: hace un POST con JSON (`{"destinatario", "asunto", "mensaje"}`) a `LIBRERIA_URL_NOTIFICACIONES`. Solo reintenta si no se pudo conectar: si se agota el tiempo esperando la respuesta, el aviso pudo haber llegado y reintentar lo duplicaría. Los errores de `httpx` se traducen a `ServicioExternoError`.
  - `NotificadorRegistro`: escribe el aviso en el log. La API lo usa cuando no hay URL configurada.
  - `NotificadorEnMemoria`: guarda los avisos en una lista para las pruebas.
- **Casos de uso**: `CrearPedido` y `CambiarEstatusPedido` avisan DESPUÉS de confirmar y fuera de la transacción: nunca se avisa de algo que se revirtió, y cancelar dos veces no manda dos avisos. Si el aviso falla, el pedido ya quedó guardado: solo se registra una advertencia.
- **Raíz de composición**: `obtener_notificador()` en `api/dependencies.py` elige `NotificadorHTTP` o `NotificadorRegistro` según la variable de entorno.
- **Pruebas**: `test_contrato_notificador.py` corre el contrato con `[http]` (usando `httpx.MockTransport`, sin red), `[registro]` y `[memoria]`. `test_notificador_http.py` prueba la petición y los errores (4xx/5xx, sin conexión, tiempo agotado). `test_casos_uso.py` y `test_api.py` revisan qué avisos se envían.

## Casos de uso (paso 3)

La API dejó de orquestar para pedidos y altas de libros: traduce HTTP a un comando, llama a un caso de uso y traduce el resultado (o el error) a una respuesta.

- **`casos_uso.py`** (nuevo): `CrearPedido`, `CambiarEstatusPedido` y `AgregarLibro`, con sus comandos `CrearPedidoComando` y `CambiarEstatusComando`. Cada uno obtiene los datos a través de la `UnidadDeTrabajo`, deja las decisiones al dominio (`pedidos.py`, `Libro`) y confirma todo junto o nada. La fecha del pedido sale de un reloj inyectado (`ahora`), así que las pruebas pueden fijarla.
- **Raíz de composición de la API** en `api/dependencies.py`: `obtener_uow()` elige el adaptador (`UnidadDeTrabajoSQL`) y arma los casos de uso, que los routers piden ya listos (`CrearPedidoDep`, `CambiarEstatusDep`, `AgregarLibroDep`).
- **Routers de pedidos y libros**: ya no reciben la sesión de SQLAlchemy para crear pedidos, cambiar su estatus o agregar libros. La regla del ISBN repetido ya no vive en el router: el repositorio lanza `LibroDuplicadoError`, que `app.py` traduce a 409, como antes.
- **`basedatos.py` sin orquestación**: se quitaron `crear_pedido()`, `cambiar_estatus()`, `cancelar_pedido()` y `guardar_libro()`, que duplicaban lo que ahora hacen los casos de uso. Las pruebas que las usaban llaman a los casos de uso reales mediante atajos de `conftest.py`.
- **`tests/test_casos_uso.py`** (nuevo): prueba la orquestación con `UnidadDeTrabajoEnMemoria` (qué se guarda, cuántas veces se confirma y que un error no confirme nada), sin base de datos.

La API respondió igual que antes: los mismos códigos HTTP y los mismos datos.

## Pruebas de contrato (paso 4, adelantado al 3)

Una prueba de contrato es una sola batería de pruebas que corre contra TODAS las implementaciones de un puerto. Si todas pasan, las pruebas que usan la versión en memoria no mienten: la real se comporta igual.

- **Adaptadores en memoria** en `repositorios_memoria.py` (nuevo): `CatalogoEnMemoria` y `UnidadDeTrabajoEnMemoria` (con `LibrosEnMemoria`, `PedidosEnMemoria` y `UsuariosEnMemoria`). Guardan y devuelven copias, como un archivo o una base, y la unidad de trabajo confirma o revierte igual que la de SQL.
- **`tests/test_contrato_repositorios.py`** (antes `test_repositorios_sql.py`): las pruebas de los repositorios corren con `[sql]` y con `[memoria]` gracias a una fixture parametrizada. Se sumaron casos del contrato: los objetos leídos son copias independientes y cada pedido recibe un id distinto.
- **`tests/test_contrato_catalogo.py`** (nuevo): la misma batería para `CatalogoJSON` y `CatalogoEnMemoria`.
- **`test_servicios.py`** usa `RepositorioEspia`, un `CatalogoEnMemoria` que además cuenta los guardados. El falso anterior no pasaba el contrato: `guardar()` no guardaba nada y `cargar()` devolvía el mismo objeto, así que un cambio sin guardar aparecía como guardado.

## Puertos de la base de datos y unidad de trabajo (paso 2)

Segundo paso hacia la arquitectura hexagonal: el núcleo ya podía hablar con la base de datos sin conocer SQLAlchemy. En este paso solo las usaban sus pruebas; el paso 3 conectó la API a ellas.

- **Puertos nuevos** en `puertos.py`: `RepositorioLibros`, `RepositorioPedidos`, `RepositorioUsuarios` y `UnidadDeTrabajo`. Reciben y devuelven objetos del dominio, nunca filas ni sesiones.
- **Unidad de trabajo**: los repositorios nunca hacen commit. `with uow: ... uow.confirmar()` guarda todos los cambios juntos; si no se confirma o hay una excepción, al salir del `with` se revierte todo.
- **Adaptadores SQL** en `repositorios_sql.py` (nuevo): `LibrosSQL`, `PedidosSQL`, `UsuariosSQL` y `UnidadDeTrabajoSQL`. Reutilizan las tablas y las funciones de traducción de `basedatos.py` (`fila_a_libro`, `fila_a_pedido`, …), que pasaron a ser públicas. Los errores de SQLAlchemy se traducen a `PersistenciaError`.
- **`Usuario` y `Rol` pasan a `modelos.py`**, y `LibroNoEncontradoError`, `UsuarioNoEncontradoError`, `PedidoNoEncontradoError` y `RegistroEnUsoError` a `excepciones.py`. Así ni los puertos ni la API importan tipos desde la capa SQL.
- **`tests/test_repositorios_sql.py`**: pruebas de integración de los adaptadores con SQLite en memoria, incluida la garantía de "todo o nada" de la unidad de trabajo.

## Reglas de pedidos en el dominio (paso 1)

Las reglas de los pedidos vivían dentro de `basedatos.py`, mezcladas con SQLAlchemy. Pasaron al dominio, sin base de datos ni HTTP:

- **`pedidos.py`** (nuevo): las entidades `Pedido` y `PedidoItem`, el tipo `Estatus` y la tabla `TRANSICIONES` (pendiente → pagado → enviado, y cancelar desde pendiente o pagado). `crear_pedido()` valida todas las líneas antes de descontar stock (todo o nada), `Pedido.avanzar_a()` y `Pedido.cancelar()` cambian el estatus, y cancelar regresa los ejemplares al inventario.
- **`Libro.verificar_stock()`, `Libro.retirar()` y `Libro.reponer()`** (`modelos.py`): el inventario de un libro se modifica solo con estos métodos, que además mantienen `en_stock` sincronizado.
- **Excepciones de dominio** en `excepciones.py`: `PedidoInvalidoError`, `StockInsuficienteError` y `TransicionEstatusError`.
- **`basedatos.py` pasa a ser solo un adaptador**: carga las filas, las convierte en objetos del dominio, le deja las decisiones a `pedidos.py` y escribe el resultado en una transacción.
- **`tests/test_pedidos.py`** (nuevo): pruebas de dominio que corren en milisegundos, sin SQLite.

La API respondió exactamente igual que antes: los mismos códigos HTTP y los mismos mensajes.

## Patrones de diseño

- **Strategy en los filtros** (`catalogo.py`): cada criterio es una función `Libro -> bool` (`por_autor`, `por_genero`, `por_stock`, `por_precio_max`, `por_año_min`). `construir_filtros()` arma la lista según los criterios recibidos y `aplicar_filtros()` deja los libros que pasan todos. La consola y el endpoint `GET /libros` usan el mismo código, en lugar de repetir los filtros.
- **Decorador `@cache_temporal`** (`utilidades.py`): guarda el resultado de una función durante un tiempo, según sus argumentos, y descarta el que lleva más tiempo sin usarse cuando se llena. Los errores no se guardan.
- **Caché en `buscar_por_isbn`** (`buscador.py`): las búsquedas en Open Library se recuerdan 10 minutos (`SEGUNDOS_CACHE_ISBN`), así que repetir un ISBN no vuelve a usar la red. El ISBN se normaliza antes de consultar la caché (con o sin guiones es la misma entrada) y se devuelve una copia del resultado.
- **pre-commit**: `.pre-commit-config.yaml` se ajustó a que el repositorio git está en la carpeta `libreria`.

## Antes de estos cambios

Base de datos con SQLAlchemy y migraciones de Alembic (0001 esquema inicial, 0002 teléfono de usuario, 0003 autenticación), API web con FastAPI, autenticación JWT con roles y contraseñas Argon2, script `crear_admin`, predicción de best sellers con scikit-learn, descarga concurrente de portadas con `asyncio`, e importación desde CSV y exportación a JSON del catálogo de consola.
