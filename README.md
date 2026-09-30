# Proyecto: Librería

Programa de consola para administrar el catálogo de una librería: consultar, filtrar, agregar e importar libros, guardados en un archivo JSON.

Proyecto Integrador del curso **Axity Python**.

## Créditos

- Autor: [Javier González](https://github.com/javier-gonzalezj)
- Datos de libros y portadas: [Open Library](https://openlibrary.org), un proyecto de Internet Archive.

## Características

- **Catálogo paginado** con los datos de la librería, el total de libros y el valor del inventario.
- **Filtros** por autor, género, disponibilidad, precio máximo y año mínimo, con opción de exportar el resultado a JSON.
- **Captura de libros por consola** con autocompletado por ISBN: el programa consulta [Open Library](https://openlibrary.org) y sugiere título, autor, géneros, año y editorial (Enter acepta la sugerencia).
- **Descarga de portadas** por streaming a `data/portadas/<isbn>.jpg`, sin dejar archivos a medias si la conexión se corta.
- **Descarga concurrente de portadas** con `asyncio`, `httpx.AsyncClient` y un semáforo: baja las portadas faltantes de todo el catálogo, o las de los libros recién importados, varias a la vez.
- **Importación desde CSV** que reporta las filas con errores sin detener la carga.
- **Validación de datos** con modelos de [pydantic](https://docs.pydantic.dev).
- **Guardado seguro**: el catálogo se escribe en un archivo temporal y solo reemplaza al original si todo salió bien.
- **Registro (logging)** detallado en `logs/libreria.log`.
- **Base de datos con SQLAlchemy y migraciones con Alembic**: el catálogo, los usuarios y los pedidos viven en una base de datos. Las tablas se versionan en `migraciones/` (0001 esquema inicial, 0002 teléfono de usuario y la nueva 0003 autenticación).
- **API web con FastAPI** en `src/libreria/api/`: endpoints para libros, usuarios, pedidos y reportes, con documentación interactiva en `/docs`.
- **Autenticación con JWT**: registro e inicio de sesión (`/auth`), roles `cliente` y `admin`, y contraseñas guardadas como hash Argon2 (pwdlib).
- **Script para crear administradores**: `poetry run python -m libreria.api.crear_admin`.
- **Docker multistage** e **integración continua con GitHub Actions**: lint, tipos, pruebas y construcción de la imagen en cada push. Ver [Docker](#docker) e [Integración continua](#integración-continua-github-actions).
- **Arquitectura por capas** (dominio, aplicación, infraestructura y presentación), con una prueba automática que impide que las dependencias apunten en la dirección equivocada. Ver [Arquitectura](#arquitectura).
- **Predicción de best sellers** (`analitica/prediccion.py`): clasificador de scikit-learn que estima la probabilidad de que un libro se venda mucho, entrenado con ventas sintéticas (`analitica/datos_sinteticos.py`).
- **Pruebas**: nuevas pruebas de la API (`tests/test_api.py`) y de las migraciones.

Para ponerla en marcha:

```bash
poetry install
poetry run alembic upgrade head
poetry run python -m libreria.api.crear_admin
poetry run fastapi dev src/libreria/api/app.py
```

## Requisitos

- Python 3.13 o superior
- [Poetry](https://python-poetry.org) 2.x
- Conexión a internet (opcional: solo para el autocompletado por ISBN y las portadas; sin ella, la captura es manual)

## Instalación

```bash
git clone https://github.com/javier-gonzalezj/Axity-Python-Proyecto-Integrador
cd Axity-Python-Proyecto-Integrador
poetry install --all-extras
```

`--all-extras` instala también el extra opcional **`ml`** (scikit-learn, pandas y joblib), que solo usa el modelo de best sellers (`analitica/prediccion.py`) y sus pruebas. La API y la consola funcionan sin él: con un simple `poetry install` todo corre menos la predicción, que avisa qué falta instalar. La imagen Docker no lo incluye, y por eso pesa mucho menos.

Para activar las revisiones automáticas antes de cada commit:

```bash
poetry run pre-commit install
```

## Uso

```bash
poetry run libreria
```

Al iniciar se muestra el catálogo y después el menú:

```
═════════════ MENU ═════════════
  1. Filtrar libros
  2. Cargar archivo CSV
  3. Agregar un libro
  4. Ver catalogo completo
  5. Descargar portadas faltantes
  0. Salir
════════════════════════════════
```

### Agregar un libro (opción 3)

Al escribir el ISBN, el programa lo busca en Open Library y muestra los datos encontrados entre corchetes:

```
ISBN: 9780307474728
  🔎 Buscando el ISBN en Open Library...
  ✅ Encontrado: Cien años de soledad — Gabriel García Márquez
     Presiona Enter para aceptar el valor entre [corchetes] o escribe otro.
Título [Cien años de soledad]:
Nombre del autor [Gabriel García Márquez]:
Nacionalidad del autor: Colombiana
```

El precio, la cantidad disponible y la nacionalidad del autor siempre se capturan a mano. Si el libro no está en Open Library o no hay conexión, todos los campos se capturan manualmente.

> Open Library tiene menos libros en español, así que varios ISBN de editoriales mexicanas no aparecen. Los géneros que sugiere vienen en inglés.

### Base de datos (usuarios y pedidos)

Además del catálogo en JSON, el proyecto puede guardar libros, usuarios y pedidos en `data/libreria.db` (SQLite):

```
usuarios 1 ──< pedidos 1 ──< pedido_items >── 1 libros
```

Para crear la base y copiar el catálogo del JSON:

```bash
poetry run alembic upgrade head               # crea las tablas (aplica las migraciones)
poetry run python -m libreria.infraestructura.basedatos    # importa data/libreria.json a la base
```

Cada línea de pedido guarda el precio al momento de la compra, y crear un pedido es una sola transacción: si algún libro no tiene stock, no se guarda nada. Cancelar un pedido no lo borra: cambia su estatus y regresa los libros al inventario.

#### Operaciones (CRUD): casos de uso de `aplicacion/casos_uso/`

| Entidad | Crear | Leer | Actualizar | Eliminar |
|---|---|---|---|---|
| Libro | `AgregarLibro` | `ObtenerLibro`, `ListarLibros` (con filtros) | `ActualizarLibro` | `EliminarLibro` (solo si nunca se vendió) |
| Usuario | `RegistrarUsuario`, `AsegurarAdministrador` | `ObtenerUsuario`, `BuscarUsuarioPorEmail`, `ListarUsuarios` | `ActualizarUsuario`, `CambiarRol`, `CambiarPassword` | `EliminarUsuario` (solo si no tiene pedidos) |
| Pedido | `CrearPedido` | `ObtenerPedido`, `PedidosDeUsuario`, `ListarPedidos` | `CambiarEstatusPedido` | cancelar con `CambiarEstatusPedido` (no borra: cambia el estatus) |

Además: `Autenticar` (inicio de sesión) y los reportes `GastoPorUsuario` y `LibrosMasVendidos`. Todos se usan igual: se construyen con sus puertos y se llama a `ejecutar()`.

Un pedido avanza `pendiente → pagado → enviado`, y solo se puede cancelar antes de enviarse.

#### Migraciones con Alembic

Las clases `*DB` de `infraestructura/basedatos.py` definen las tablas. Cuando cambies alguna, genera una migración, revísala y aplícala:

```bash
poetry run alembic revision --autogenerate --rev-id 0004 -m "descripcion del cambio"
poetry run alembic upgrade head
```

`--rev-id` es el número de la nueva migración: el siguiente después de la última de `migraciones/versions/` (hoy la 0003, así que la próxima es 0004). Con `alembic history` puedes ver cuál es la última.

| Comando | Qué hace |
|---|---|
| `alembic current` | Versión actual de la base |
| `alembic history` | Lista de migraciones |
| `alembic downgrade -1` | Revierte la última migración |
| `alembic check` | Verifica que los modelos y las migraciones coincidan |

> `--autogenerate` no detecta que renombraste una columna: lo interpreta como borrar una y crear otra. Revisa siempre el archivo generado antes de aplicarlo.

### API web (FastAPI)

Los mismos casos de uso también están disponibles como API REST en `src/libreria/api/`. Para levantarla (después de `alembic upgrade head`):

```bash
poetry run fastapi dev src/libreria/api/app.py
```

y abre <http://127.0.0.1:8000/docs> para ver y probar todos los endpoints.

Antes de usarla por primera vez, crea un administrador (pide email, nombre y contraseña):

```bash
poetry run python -m libreria.api.crear_admin
```

El mismo comando sirve para darle contraseña a un usuario que ya existía antes de la migración 0003.

| Recurso | Endpoints | Quién puede |
|---|---|---|
| Autenticación | `POST /auth/registro`, `POST /auth/token` | Cualquiera |
| | `GET /auth/yo`, `PUT /auth/password` | Con sesión iniciada |
| Libros | `GET /libros/` (filtros `autor`, `genero`, `en_stock`, `precio_max`), `GET /libros/{isbn}` | Cualquiera |
| | `POST /libros/`, `PATCH/DELETE /libros/{isbn}` | Admin |
| Usuarios | `GET /usuarios/`, `POST /usuarios/`, `PUT /usuarios/{id}/rol` | Admin |
| | `GET/PATCH/DELETE /usuarios/{id}`, `GET /usuarios/{id}/pedidos` | El propio usuario o un admin |
| Pedidos | `POST /pedidos/` (queda a nombre de quien inició sesión) | Con sesión iniciada |
| | `GET /pedidos/{id}`, cancelar con `PATCH /pedidos/{id}/estatus` | El dueño o un admin |
| | `GET /pedidos/?estatus=`, marcar `pagado`/`enviado` | Admin |
| Reportes | `GET /reportes/usuarios`, `GET /reportes/mas-vendidos` | Admin |

Los listados aceptan `?saltar=` y `?limite=` (máximo 100).

#### Autenticación con JWT

1. `POST /auth/token` con un **formulario** (no JSON) con `username` (el email) y `password`. Responde un `access_token`.
2. Las demás peticiones mandan el encabezado `Authorization: Bearer <access_token>`.
3. En `/docs`, el botón **Authorize** hace estos dos pasos por ti.

El token solo guarda el id del usuario y su caducidad; el rol se lee de la base en cada petición, así que un cambio de rol surte efecto sin volver a iniciar sesión. Las contraseñas se guardan como hash Argon2, nunca en texto plano.

| Variable de entorno | Para qué | Por defecto |
|---|---|---|
| `LIBRERIA_JWT_SECRETO` | Clave para firmar los tokens (mínimo 32 caracteres) | Una al azar en cada arranque: los tokens dejan de servir al reiniciar |
| `LIBRERIA_JWT_MINUTOS` | Minutos de validez de cada token | 30 |
| `LIBRERIA_URL_NOTIFICACIONES` | URL a la que se envían (POST con JSON) los avisos de pedidos | Sin valor: los avisos solo se escriben en el log |
| `LIBRERIA_URL_BD` | Base de datos de la API **y** de las migraciones de Alembic (`migraciones/env.py` la lee también, para que nunca apunten a bases distintas) | `sqlite:///data/libreria.db` (en Docker, `sqlite:////app/data/libreria.db`) |

Para generar un secreto: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. No lo subas a git.

Cómo está organizada:

- **`routers/`**: un `APIRouter` por recurso, cada uno con su `prefix` y `tags`. Cada endpoint solo traduce HTTP ↔ caso de uso: arma el comando, llama a `ejecutar()` y devuelve el resultado. Ningún router importa la base de datos (lo verifica `tests/test_arquitectura.py`).
- **`dependencies.py`**: la raíz de composición. Elige los adaptadores (`UnidadDeTrabajoSQL`, `NotificadorHTTP`/`NotificadorRegistro`, `HasherArgon2`) y arma con ellos cada caso de uso (`ListarLibrosDep`, `CrearPedidoDep`, ...). También la sesión de base de datos (una por petición, con `yield`), la búsqueda de un libro/usuario/pedido que responde 404 si no existe, la paginación y la autenticación: `usuario_actual` (lee el token; 401), `requiere_admin` (403) y `usuario_autorizado`/`pedido_autorizado` (uno mismo o admin). Se aplican en tres niveles: como parámetro del endpoint, en el decorador (`dependencies=[...]`, libros) o en todo un router (pedidos y reportes).
- **`seguridad.py`**: creación y lectura de tokens (PyJWT). No depende de FastAPI. El hash de contraseñas (pwdlib + Argon2) está en `infraestructura/passwords.py`, porque también lo usan los casos de uso.
- **`schemas.py`**: esquemas pydantic de entrada (`Create`/`Update`) y salida (`Read`) con sus validaciones: formato de ISBN, año no futuro, géneros sin repetir, email en minúsculas, teléfono, al menos un campo en los `PATCH`, sin ISBN repetidos en un pedido, contraseñas de 8 a 128 caracteres con letras y números y sin espacios al inicio o al final.
- **`app.py`**: crea la app, incluye los routers y traduce las excepciones del dominio y de los casos de uso a códigos HTTP (404 no existe, 409 conflicto, 422 datos inválidos, 400 el resto).

### Importar desde CSV (opción 2)

El archivo debe estar en UTF-8 (en Excel: *Guardar como → CSV UTF-8*) y tener estas columnas:

| Columna | Obligatoria | Notas |
|---|---|---|
| `isbn` | Sí | No puede repetirse en el catálogo |
| `titulo` | Sí | |
| `autor` | Sí | Nombre del autor |
| `nacionalidad_autor` | No | Vacía por defecto |
| `genero` | Sí | Varios géneros separados por `;` |
| `año_publicacion` | Sí | Número entero |
| `precio` | Sí | Número, sin signo `$` |
| `cantidad_disponible` | Sí | Número entero |
| `editorial` | Sí | |
| `en_stock` | No | `sí`/`no`; si falta, se calcula con la cantidad |

Hay un ejemplo en [`data/ejemplos/libros_nuevos.csv`](data/ejemplos/libros_nuevos.csv).

Al terminar, el programa pregunta si quieres descargar de Open Library las portadas de los libros agregados (se descargan igual que en la opción 5).

### Descargar portadas faltantes (opción 5)

Busca los libros del catálogo que todavía no tienen su archivo en `data/portadas/` y descarga sus portadas **en paralelo**:

```
🖼️  Descargando 12 portada(s) (5 a la vez)... puede tardar un poco.

✅ 9 portada(s) descargada(s) en: data/portadas
ℹ️  2 libro(s) sin portada en Open Library:
   - 978-607-16-0001-1
   - 978-607-16-0002-8
⚠️  1 portada(s) no se pudieron descargar:
   - 978-0-14-044913-6: No se pudo descargar la portada: ...
```

Cómo funciona (`descargar_portadas()` en `buscador.py`):

- Cada ISBN es una corrutina que hace dos peticiones: la edición en `openlibrary.org` (para obtener el id de la portada) y la imagen en `covers.openlibrary.org`, por streaming y con archivo `.part` como en la opción 3.
- Todas las corrutinas comparten un `httpx.AsyncClient` por servidor, así que reutilizan las conexiones.
- Un `asyncio.Semaphore` deja pasar como máximo `MAX_DESCARGAS_SIMULTANEAS` (5) ISBN a la vez, para no saturar a Open Library.
- Se ejecutan con `asyncio.gather(..., return_exceptions=True)`: si un ISBN falla, los demás siguen y el error queda en el resumen. Un `TaskGroup` cancelaría todo al primer error.
- Los errores de red pasajeros se reintentan con `@reintentar_async` (en `utilidades.py`), que espera con `await asyncio.sleep()` para no congelar el event loop.
- El menú es síncrono, así que `main.py` lo ejecuta con `asyncio.run()`.

### Predicción de best sellers (machine learning)

Clasificador que estima la probabilidad de que un libro sea **best seller**. Como la base real todavía no tiene pedidos, se entrena con una base **aparte** de ventas sintéticas:

Requiere el extra opcional `ml` (`poetry install --all-extras`); ver [Instalación](#instalación).

```bash
# 1. Genera data/sintetico.db: 300 libros, 100 usuarios y 3000 pedidos inventados
poetry run python -m libreria.analitica.datos_sinteticos

# 2. Entrena, muestra las métricas y guarda data/modelo_best_seller.joblib
poetry run python -m libreria.analitica.prediccion entrenar

# 3. Probabilidad de cada libro del catálogo real (data/libreria.db)
poetry run python -m libreria.analitica.prediccion predecir
```

Opciones útiles: `--libros`, `--pedidos`, `--semilla` y `--reemplazar` en el generador; `--bd`, `--modelo` y `--percentil` en `prediccion`. El generador se niega a escribir en `data/libreria.db`, así que los datos inventados nunca se mezclan con los reales.

Cómo funciona:

- **Etiqueta** (`etiquetar()`): un libro es best seller si está en el 20% superior de unidades vendidas, sin contar pedidos cancelados. Un libro sin ventas nunca lo es.
- **Características**: precio, año, géneros, editorial y nacionalidad del autor, es decir, solo datos conocidos *antes* de vender. `cantidad_disponible` no se usa, porque baja justamente cuando el libro se vende (sería fuga de datos).
- **Pipeline** (`construir_modelo()`): un `ColumnTransformer` convierte los géneros en una columna 0/1 por género (`CountVectorizer`, sin distinguir mayúsculas) y la editorial y la nacionalidad con `OneHotEncoder(handle_unknown="ignore")`; después, un `RandomForestClassifier` con `class_weight="balanced"`, porque hay unos 4 libros "no" por cada "sí".
- **Evaluación** (`entrenar()`): separa 25% de los libros para prueba con `stratify`, reporta precision, recall, F1 y ROC AUC, y compara la exactitud contra decir siempre "no es best seller". Después vuelve a entrenar con todos los libros y ese es el modelo que se guarda.
- **Guardado** con joblib. ⚠️ joblib usa pickle: carga solo modelos que tú mismo entrenaste.

La tendencia de las ventas sintéticas está escrita a mano en `datos_sinteticos.popularidad()` (thrillers, fantasía y novelas baratas se venden más; poesía y ensayo, menos). Un modelo entrenado con esos datos solo aprende esa regla: sirve para practicar el flujo, no para decidir qué libros comprar. `importancias()` muestra qué rasgos usó el modelo para compararlos con la regla.

### Docker

El `Dockerfile` construye la imagen de la API en dos etapas (**multistage**):

| Etapa | Base | Qué hace | ¿Llega a la imagen final? |
|---|---|---|---|
| `builder` | `python:3.13-slim` | Instala Poetry 2.5.1 (la versión que generó `poetry.lock`), las dependencias de **producción** (`--only main`, sin el extra `ml`) en `/opt/venv` y el proyecto empaquetado como wheel | No |
| `runtime` | `python:3.13-slim` | Copia solo `/opt/venv`, `alembic.ini` y `migraciones/`; corre con el usuario `libreria` (no root) | Sí |

Así la imagen final no lleva Poetry, ruff, mypy, pytest, las pruebas, el código fuente suelto ni las bibliotecas de machine learning: las bibliotecas instaladas ocupan unos 88 MB en lugar de 347 MB. Al arrancar ejecuta `alembic upgrade head` y después `uvicorn`. `.dockerignore` deja fuera `data/`, `logs/`, `.env`, `.git` y los respaldos, para que ningún dato ni secreto termine dentro de la imagen.

```bash
docker build -t libreria-api .

# La base vive en ./data (volumen): sobrevive aunque borres el contenedor
docker run -d --name libreria -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -e LIBRERIA_JWT_SECRETO="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  libreria-api

# Tareas de una sola vez dentro del contenedor
docker exec -it libreria python -m libreria.api.crear_admin
docker exec libreria python -m libreria.infraestructura.basedatos   # importa data/libreria.json
```

Abre http://localhost:8000/docs. El contenedor tiene un `HEALTHCHECK` (`docker ps` muestra `healthy` cuando la API responde).

## Arquitectura

El código está organizado en capas. Cada capa solo puede importar las de abajo; nunca al revés:

```
  api/  consola/  analitica/     presentación y herramientas (HTTP, menú, ML)
            │
            ▼
     infraestructura/            adaptadores: SQLAlchemy, JSON/CSV, Open Library, HTTP, Argon2
            │
            ▼
       aplicacion/               casos de uso, ServicioCatalogo y puertos (Protocol)
            │
            ▼
        dominio/                 reglas del negocio: Libro, Pedido, catálogo, excepciones
```

- **Dominio**: no sabe que existen una base de datos, una API o archivos. Solo usa pydantic para validar.
- **Aplicación**: los casos de uso orquestan al dominio y hablan con el exterior solo a través de los **puertos** (`aplicacion/puertos.py`): `UnidadDeTrabajo` (con sus repositorios y `ConsultasVentas`), `Notificador`, `Hasher`, `RepositorioCatalogo` y `LectorLibros`.
- **Infraestructura**: los **adaptadores** que cumplen esos puertos. Para la base hay dos: SQL (`repositorios_sql.py`) y memoria (`repositorios_memoria.py`); las pruebas de contrato garantizan que se comportan igual.
- **Presentación**: la API y la consola eligen los adaptadores (raíz de composición: `api/dependencies.py` y `consola/main.py`), arman los casos de uso y traducen sus resultados a HTTP o a texto.

`tests/test_arquitectura.py` revisa los `import` de todos los módulos y falla si alguna dependencia apunta hacia arriba, si el núcleo (dominio o aplicación) importa una biblioteca técnica (SQLAlchemy, FastAPI, httpx...) o si un router toca la base de datos.

## Cambios recientes: Docker, integración continua y extra `ml`

- **`Dockerfile` multistage**, **`.dockerignore`** y **`.github/workflows/ci.yml`** (ver [Docker](#docker) e [Integración continua](#integración-continua-github-actions)).
- **`migraciones/env.py` respeta `LIBRERIA_URL_BD`**: antes Alembic siempre usaba la base de `alembic.ini` aunque la API usara otra.
- **Extra opcional `ml`**: scikit-learn, pandas y joblib salieron de las dependencias principales, porque solo las usa `analitica/prediccion.py`. Ahora se instalan con `poetry install --all-extras`. `poetry.lock` se regeneró con Poetry 2.5.1 sin cambiar ninguna versión. Si faltan, `prediccion.py` dice cómo instalarlas en lugar de lanzar un `ModuleNotFoundError` sin contexto.

## Cambios anteriores: arquitectura por capas y API sobre casos de uso

- **Carpetas por capa**: los módulos que estaban sueltos en `src/libreria/` pasan a `dominio/`, `aplicacion/`, `infraestructura/`, `consola/` y `analitica/` (la API ya estaba en `api/`). Cambian las rutas de los comandos: `python -m libreria.infraestructura.basedatos`, `python -m libreria.analitica.prediccion`, etc., y el script `libreria` apunta a `libreria.consola.main:main`.
- **Todos los endpoints pasan por casos de uso**. Antes solo crear pedido, cambiar estatus y agregar libro lo hacían; los de usuarios, autenticación, reportes, editar/borrar libros y las consultas llamaban directo a `basedatos.py`. Casos de uso nuevos: `ActualizarLibro`, `EliminarLibro`, `ObtenerLibro`, `ListarLibros`, `RegistrarUsuario`, `Autenticar`, `CambiarPassword`, `ActualizarUsuario`, `CambiarRol`, `EliminarUsuario`, `AsegurarAdministrador`, `ObtenerUsuario`, `BuscarUsuarioPorEmail`, `ListarUsuarios`, `ObtenerPedido`, `ListarPedidos`, `PedidosDeUsuario`, `GastoPorUsuario` y `LibrosMasVendidos`. `casos_uso.py` se volvió un paquete con un módulo por recurso.
- **Reglas que salieron de los routers**: email único, no quitarse el propio rol de admin, no borrar libros vendidos ni usuarios con pedidos y la verificación de credenciales viven ahora en los casos de uso, con excepciones nuevas (`EmailDuplicadoError`, `CambioDeRolInvalidoError`, `CredencialesInvalidasError`, `PasswordIncorrectaError`) que `app.py` traduce a HTTP. Las respuestas de la API no cambiaron.
- **Puertos ampliados**: los repositorios ganaron `listar`, `eliminar`, `buscar_por_email`, `de_usuario`, `incluyen_libro` y el manejo del hash de contraseña; `ConsultasVentas` (reportes) y `Hasher` (contraseñas) son nuevos. `LectorLibros` desacopla `ServicioCatalogo` del CSV: ahora recibe un `LectorCSV`.
- **`basedatos.py` solo tiene lo técnico**: tablas, motor, traducción filas ↔ dominio e `importar_catalogo`. Las operaciones CRUD que duplicaban a los repositorios se quitaron.
- **`Libro.con_cambios()`** (dominio): devuelve un libro nuevo con los campos cambiados y validados; lo usa `ActualizarLibro`.
- **Pruebas nuevas**: `test_arquitectura.py`, `test_casos_uso_libros_usuarios.py` (reglas y orquestación con la UoW en memoria y un `HasherFalso`) y más casos de contrato en `test_contrato_repositorios.py`. `test_crud.py` ahora prueba los casos de uso contra SQLite.

## Cambios anteriores: notificaciones al cliente (puerto Notificador)

Cuando se crea un pedido o cambia su estatus, el cliente recibe un aviso. El núcleo solo conoce el puerto `Notificador`; cómo viaja el aviso lo decide el adaptador.

- **Puerto `Notificador`** en `puertos.py`, con el método `enviar(destinatario, asunto, mensaje)`. Si no se puede entregar el aviso, lanza `ServicioExternoError`.
- **Adaptadores** en `notificadores.py` (nuevo):
  - `NotificadorHTTP`: hace un POST con JSON (`{"destinatario", "asunto", "mensaje"}`) a `LIBRERIA_URL_NOTIFICACIONES`. Solo reintenta si no se pudo conectar: si se agota el tiempo esperando la respuesta, el aviso pudo haber llegado, y reintentar lo duplicaría. Los errores de `httpx` se traducen a `ServicioExternoError`.
  - `NotificadorRegistro`: escribe el aviso en el log. La API lo usa cuando no hay URL configurada.
  - `NotificadorEnMemoria`: guarda los avisos en una lista para las pruebas.
- **Casos de uso**: `CrearPedido` y `CambiarEstatusPedido` avisan DESPUÉS de confirmar y fuera de la transacción: nunca se avisa de algo que se revirtió, y cancelar dos veces no manda dos avisos. Si el aviso falla, el pedido ya quedó guardado: solo se registra una advertencia.
- **Raíz de composición**: `obtener_notificador()` en `api/dependencies.py` elige `NotificadorHTTP` o `NotificadorRegistro` según la variable de entorno.
- **Pruebas**: `test_contrato_notificador.py` corre el contrato con `[http]` (usando `httpx.MockTransport`, sin red), `[registro]` y `[memoria]`. `test_notificador_http.py` prueba la petición y los errores (4xx/5xx, sin conexión, tiempo agotado). `test_casos_uso.py` y `test_api.py` revisan qué avisos se envían.

## Cambios anteriores: casos de uso (paso 3)

La API ya no orquesta nada: traduce HTTP a un comando, llama a un caso de uso y traduce el resultado (o el error) a una respuesta.

- **`casos_uso.py`** (nuevo): `CrearPedido`, `CambiarEstatusPedido` y `AgregarLibro`, con sus comandos `CrearPedidoComando` y `CambiarEstatusComando`. Cada uno obtiene los datos a través de la `UnidadDeTrabajo`, deja las decisiones al dominio (`pedidos.py`, `Libro`) y confirma todo junto o nada. La fecha del pedido sale de un reloj inyectado (`ahora`), así que las pruebas pueden fijarla.
- **Raíz de composición de la API** en `api/dependencies.py`: `obtener_uow()` elige el adaptador (`UnidadDeTrabajoSQL`) y arma los casos de uso, que los routers piden ya listos (`CrearPedidoDep`, `CambiarEstatusDep`, `AgregarLibroDep`).
- **Routers de pedidos y libros**: ya no reciben la sesión de SQLAlchemy para crear pedidos, cambiar su estatus o agregar libros. La regla del ISBN repetido ya no vive en el router: el repositorio lanza `LibroDuplicadoError`, que `app.py` traduce a 409, como antes.
- **`basedatos.py` sin orquestación**: se quitaron `crear_pedido()`, `cambiar_estatus()`, `cancelar_pedido()` y `guardar_libro()`, que duplicaban lo que ahora hacen los casos de uso. Las pruebas que las usaban llaman a los casos de uso reales mediante atajos de `conftest.py`.
- **`tests/test_casos_uso.py`** (nuevo): prueba la orquestación con `UnidadDeTrabajoEnMemoria` (qué se guarda, cuántas veces se confirma y que un error no confirme nada), sin base de datos.

La API responde igual que antes: los mismos códigos HTTP y los mismos datos.

## Cambios anteriores: pruebas de contrato (paso 4, adelantado al 3)

Una prueba de contrato es una sola batería de pruebas que corre contra TODAS las implementaciones de un puerto. Si todas pasan, las pruebas que usan la versión en memoria no mienten: la real se comporta igual.

- **Adaptadores en memoria** en `repositorios_memoria.py` (nuevo): `CatalogoEnMemoria` y `UnidadDeTrabajoEnMemoria` (con `LibrosEnMemoria`, `PedidosEnMemoria` y `UsuariosEnMemoria`). Guardan y devuelven copias, como un archivo o una base, y la unidad de trabajo confirma o revierte igual que la de SQL.
- **`tests/test_contrato_repositorios.py`**: las pruebas de los repositorios (antes `test_repositorios_sql.py`) ahora corren con `[sql]` y con `[memoria]` gracias a una fixture parametrizada. Se sumaron casos del contrato: los objetos leídos son copias independientes y cada pedido recibe un id distinto.
- **`tests/test_contrato_catalogo.py`** (nuevo): la misma batería para `CatalogoJSON` y `CatalogoEnMemoria`.
- **`test_servicios.py`** usa ahora `RepositorioEspia`, un `CatalogoEnMemoria` que además cuenta los guardados. El falso anterior no pasaba el contrato: `guardar()` no guardaba nada y `cargar()` devolvía el mismo objeto, así que un cambio sin guardar aparecía como guardado.

## Cambios anteriores: puertos de la base de datos y unidad de trabajo (paso 2)

Segundo paso hacia la arquitectura hexagonal: el núcleo ya puede hablar con la base de datos sin conocer SQLAlchemy. Por ahora estas piezas solo las usan sus pruebas; el siguiente paso (casos de uso) conectará la API a ellas.

- **Puertos nuevos** en `puertos.py`: `RepositorioLibros`, `RepositorioPedidos`, `RepositorioUsuarios` y `UnidadDeTrabajo`. Reciben y devuelven objetos del dominio, nunca filas ni sesiones, y solo tienen los métodos que usarán los casos de uso de pedidos.
- **Unidad de trabajo**: los repositorios nunca hacen commit. `with uow: ... uow.confirmar()` guarda todos los cambios juntos; si no se confirma o hay una excepción, al salir del `with` se revierte todo.
- **Adaptadores SQL** en `repositorios_sql.py` (nuevo): `LibrosSQL`, `PedidosSQL`, `UsuariosSQL` y `UnidadDeTrabajoSQL`. Reutilizan las tablas y las funciones de traducción de `basedatos.py` (`fila_a_libro`, `fila_a_pedido`, ...), que ahora son públicas. Los errores de SQLAlchemy se traducen a `PersistenciaError`.
- **`Usuario` y `Rol` pasan a `modelos.py`**, y los errores `LibroNoEncontradoError`, `UsuarioNoEncontradoError`, `PedidoNoEncontradoError` y `RegistroEnUsoError` pasan a `excepciones.py`. Así ni los puertos ni la API importan tipos desde la capa SQL.
- **`tests/test_repositorios_sql.py`** (hoy `test_contrato_repositorios.py`): pruebas de integración de los adaptadores con SQLite en memoria, incluida la garantía de "todo o nada" de la unidad de trabajo.

## Cambios anteriores: reglas de pedidos en el dominio (paso 1)

Las reglas de los pedidos vivían dentro de `basedatos.py`, mezcladas con SQLAlchemy. Ahora viven en el dominio, sin base de datos ni HTTP:

- **`pedidos.py`** (nuevo): las entidades `Pedido` y `PedidoItem`, el tipo `Estatus` y la tabla `TRANSICIONES` (pendiente → pagado → enviado, y cancelar desde pendiente o pagado). `crear_pedido()` valida todas las líneas antes de descontar stock (todo o nada), `Pedido.avanzar_a()` y `Pedido.cancelar()` cambian el estatus, y cancelar regresa los ejemplares al inventario.
- **`Libro.verificar_stock()`, `Libro.retirar()` y `Libro.reponer()`** (`modelos.py`): el inventario de un libro se modifica solo con estos métodos, que además mantienen `en_stock` sincronizado.
- **Excepciones de dominio** en `excepciones.py`: `PedidoInvalidoError`, `StockInsuficienteError` y `TransicionEstatusError`.
- **`basedatos.py` ahora es solo un adaptador**: carga las filas, las convierte en objetos del dominio, le deja las decisiones a `pedidos.py` y escribe el resultado en una transacción.
- **`tests/test_pedidos.py`** (nuevo): pruebas de dominio que corren en milisegundos, sin SQLite.

La API responde exactamente igual que antes: los mismos códigos HTTP y los mismos mensajes.

## Cambios anteriores: patrones de diseño

- **Strategy en los filtros** (`catalogo.py`): cada criterio es una función `Libro -> bool` (`por_autor`, `por_genero`, `por_stock`, `por_precio_max`, `por_año_min`). `construir_filtros()` arma la lista según los criterios recibidos y `aplicar_filtros()` deja los libros que pasan todos. La consola y el endpoint `GET /libros` usan ahora el mismo código, en lugar de repetir los filtros.
- **Decorador `@cache_temporal`** (`utilidades.py`): guarda el resultado de una función durante un tiempo, según sus argumentos, y descarta el que lleva más tiempo sin usarse cuando se llena. Los errores no se guardan.
- **Caché en `buscar_por_isbn`** (`buscador.py`): las búsquedas en Open Library se recuerdan 10 minutos (`SEGUNDOS_CACHE_ISBN`), así que repetir un ISBN no vuelve a usar la red. El ISBN se normaliza antes de consultar la caché (con o sin guiones es la misma entrada) y se devuelve una copia del resultado.
- **pre-commit**: `.pre-commit-config.yaml` se ajustó a que el repositorio git está en la carpeta `libreria`.

## Estructura del proyecto

```
libreria/
├── data/
│   ├── libreria.json          # catálogo principal
│   ├── libreria.db            # base SQLite (ignorada por git; se crea con alembic)
│   ├── sintetico.db           # ventas inventadas para entrenar (ignorada por git)
│   ├── modelo_best_seller.joblib  # modelo entrenado (ignorado por git)
│   ├── ejemplos/              # CSV de ejemplo para importar
│   ├── exportaciones/         # resultados de filtros exportados (ignorado por git)
│   └── portadas/              # portadas descargadas (ignorado por git)
├── logs/                      # archivo de log (ignorado por git)
├── migraciones/               # migraciones de Alembic
│   ├── env.py
│   └── versions/              # 0001_esquema_inicial, 0002_telefono_usuario, 0003_autenticacion
├── src/libreria/
│   ├── dominio/               # CAPA DE DOMINIO: reglas del negocio, sin base de datos ni HTTP
│   │   ├── modelos.py         # Libro (con su inventario), Autor, Usuario, Rol
│   │   ├── pedidos.py         # Pedido, estatus, stock y cancelación
│   │   ├── catalogo.py        # reglas del catálogo: agregar y filtrar (estrategias de filtrado)
│   │   └── excepciones.py     # jerarquía de errores del proyecto
│   ├── aplicacion/            # CAPA DE APLICACIÓN: orquesta al dominio a través de puertos
│   │   ├── puertos.py         # puertos (Protocol): repositorios, UoW, ventas, notificador, hasher...
│   │   ├── casos_uso/         # un caso de uso por acción: pedidos.py, libros.py, usuarios.py, reportes.py
│   │   └── servicios.py       # ServicioCatalogo: el catálogo JSON de la consola
│   ├── infraestructura/       # CAPA DE INFRAESTRUCTURA: adaptadores de los puertos
│   │   ├── basedatos.py       # tablas SQLAlchemy, motor y traducción filas <-> dominio
│   │   ├── repositorios_sql.py      # repositorios, ventas y unidad de trabajo con SQLAlchemy
│   │   ├── repositorios_memoria.py  # los mismos adaptadores en memoria (para pruebas)
│   │   ├── notificadores.py   # Notificador: HTTP, registro (log) y memoria
│   │   ├── passwords.py       # Hasher con Argon2 (pwdlib)
│   │   ├── almacenamiento.py  # lectura y escritura del catálogo JSON
│   │   ├── intercambio.py     # LectorCSV y exportar JSON
│   │   ├── buscador.py        # Open Library (con caché) y descarga de portadas (también async)
│   │   ├── registro.py        # configuración del logging
│   │   └── utilidades.py      # reintentos, caché temporal, escritura atómica, cronómetro
│   ├── api/                   # PRESENTACIÓN WEB (FastAPI)
│   │   ├── app.py             # crea la app, incluye routers, errores -> HTTP
│   │   ├── dependencies.py    # raíz de composición: adaptadores y casos de uso; paginación, permisos
│   │   ├── schemas.py         # esquemas de entrada y salida con validaciones
│   │   ├── seguridad.py       # tokens JWT
│   │   ├── crear_admin.py     # crea el primer administrador desde la consola
│   │   └── routers/           # auth.py, libros.py, usuarios.py, pedidos.py, reportes.py
│   ├── consola/               # PRESENTACIÓN DE CONSOLA
│   │   ├── main.py            # punto de entrada y menú (raíz de composición de la consola)
│   │   ├── captura.py         # entrada de datos por consola
│   │   └── vista.py           # salida por consola
│   └── analitica/             # HERRAMIENTAS DE ANÁLISIS (programas por lotes)
│       ├── datos_sinteticos.py  # genera libros y pedidos inventados para practicar ML
│       └── prediccion.py      # clasificador de best sellers (pandas + scikit-learn)
├── tests/
│   ├── conftest.py            # fixtures: base SQLite en memoria y caché de ISBN limpia por prueba
│   ├── test_buscador.py       # Open Library simulado y caché de búsquedas
│   ├── test_filtros.py        # estrategias de filtrado del catálogo
│   ├── test_pedidos.py        # reglas de pedidos e inventario, sin base de datos
│   ├── test_casos_uso.py      # orquestación de los casos de uso de pedidos con la UoW en memoria
│   ├── test_casos_uso_libros_usuarios.py  # casos de uso de libros, usuarios, auth y reportes
│   ├── test_arquitectura.py   # las dependencias entre capas apuntan hacia adentro
│   ├── test_servicios.py      # ServicioCatalogo con repositorios falsos
│   ├── test_cache.py          # decorador @cache_temporal (con reloj falso)
│   ├── test_portadas_concurrentes.py  # descarga en lote (async), semáforo y @reintentar_async
│   ├── test_basedatos.py      # pedidos y reportes
│   ├── test_contrato_repositorios.py  # contrato de la base: [sql] y [memoria]
│   ├── test_contrato_catalogo.py  # contrato del catálogo: [json] y [memoria]
│   ├── test_contrato_notificador.py  # contrato del notificador: [http], [registro] y [memoria]
│   ├── test_notificador_http.py  # petición, errores y reintentos del notificador HTTP
│   ├── test_crud.py           # casos de uso CRUD contra SQLite en memoria
│   ├── test_api.py            # endpoints, login, tokens y permisos con TestClient
│   ├── test_migraciones.py    # upgrade/downgrade de Alembic en memoria
│   ├── test_datos_sinteticos.py  # generador reproducible y protección de la base real
│   └── test_prediccion.py     # etiqueta, entrenamiento, predicción y guardado del modelo
├── .github/workflows/ci.yml   # integración continua (GitHub Actions)
├── Dockerfile                 # imagen multistage de la API
├── .dockerignore              # lo que no entra a la imagen
├── alembic.ini
└── pyproject.toml
```

## Desarrollo

### Pruebas

```bash
poetry run pytest
```

`test_arquitectura.py` revisa que cada capa solo importe las de abajo. `test_pedidos.py` prueba las reglas de pedidos directamente sobre objetos del dominio: no necesita base de datos. `test_casos_uso.py` y `test_casos_uso_libros_usuarios.py` prueban los casos de uso con `UnidadDeTrabajoEnMemoria` (y un `HasherFalso` en lugar de Argon2, que es lento a propósito); `test_crud.py` corre los mismos casos de uso contra SQLite. Los archivos `test_contrato_*.py` son pruebas de contrato: la misma batería corre contra el adaptador real y contra el de memoria (en la salida aparecen como `[sql]`/`[json]` y `[memoria]`), usando solo lo que promete el puerto. Las pruebas de `basedatos.py` usan una base SQLite en memoria, así que no tocan `data/libreria.db`. `test_migraciones.py` aplica y revierte las migraciones de Alembic sobre una base en memoria y verifica que coincidan con los modelos (lo mismo que `alembic check`). `test_api.py` prueba los endpoints con `TestClient` y reemplaza la sesión de base de datos por una en memoria con `app.dependency_overrides`. Las pruebas de `buscador.py` usan `httpx.MockTransport` para simular las respuestas de Open Library, así que no necesitan conexión a internet. `test_portadas_concurrentes.py` usa el mismo `MockTransport` con `httpx.AsyncClient` y ejecuta cada corrutina con `asyncio.run()`, así que no necesita plugins extra de pytest. Una de sus pruebas simula una red lenta para comprobar que el semáforo nunca deja más descargas simultáneas de las permitidas. `test_cache.py` simula el paso del tiempo con un reloj falso, así las pruebas de caducidad no esperan de verdad; `conftest.py` limpia la caché de ISBN antes de cada prueba. `test_prediccion.py` genera ventas sintéticas con semilla fija y entrena el modelo una sola vez para todo el archivo (fixture con `scope="module"`); comprueba, entre otras cosas, que el modelo supera claramente al azar y que las existencias no cambian la predicción.

### Calidad del código

| Herramienta | Comando | Qué revisa |
|---|---|---|
| [ruff](https://docs.astral.sh/ruff/) | `poetry run ruff check` | Estilo, errores comunes y orden de imports |
| ruff format | `poetry run ruff format` | Formato del código |
| [mypy](https://mypy-lang.org) | `poetry run mypy` | Tipos, en modo estricto |

Las tres se ejecutan automáticamente en cada commit con [pre-commit](https://pre-commit.com). Para correrlas sobre todo el proyecto:

```bash
poetry run pre-commit run --all-files
```

### Integración continua (GitHub Actions)

`.github/workflows/ci.yml` corre en cada push a `master`/`main`, en cada pull request y a mano (botón **Run workflow** en la pestaña **Actions**). Tiene tres trabajos:

| Trabajo | Qué hace | Depende de |
|---|---|---|
| **Lint, formato y tipos** | `ruff check`, `ruff format --check` y `mypy` (con `--all-extras`, para revisar también `prediccion.py`) | — |
| **Pruebas** | `pytest` con cobertura; el reporte `coverage.xml` queda como artefacto descargable | — |
| **Imagen Docker** | Construye la imagen, la levanta y hace una prueba de humo: espera a que `/docs` responda, que `/libros/` devuelva `[]` en una base nueva y que `/reportes/usuarios` sin token dé 401 | Los dos anteriores |

Los dos primeros corren en paralelo. Si algo falla, el commit o el pull request aparece en rojo y el trabajo de Docker no se ejecuta. A diferencia de pre-commit, que corre en tu máquina y se puede saltar, el CI corre siempre en GitHub e incluye las pruebas.

## Dependencias principales

- [pydantic](https://docs.pydantic.dev): validación de los datos de cada libro.
- [httpx](https://www.python-httpx.org): consultas HTTP a Open Library y descarga de portadas.
- [SQLAlchemy](https://www.sqlalchemy.org): acceso a la base de datos SQLite (ORM).
- [Alembic](https://alembic.sqlalchemy.org): migraciones del esquema de la base.
- [FastAPI](https://fastapi.tiangolo.com): API web con documentación automática (OpenAPI).
- [PyJWT](https://pyjwt.readthedocs.io): creación y verificación de tokens JWT.
- [pwdlib](https://frankie567.github.io/pwdlib/): hash de contraseñas con Argon2.
- [pandas](https://pandas.pydata.org): tablas de datos para preparar el entrenamiento.
- [scikit-learn](https://scikit-learn.org): clasificador de best sellers.
- [joblib](https://joblib.readthedocs.io): guardar y cargar el modelo entrenado.

