# Realign

Plugin para realinear los productos ráster 2D de una tarea (ortofoto, DSM, DTM) a partir de pares
de puntos, aplicando una similitud y regenerando los corregidos sin tocar los originales; incluye
la generación de la nube de puntos corregida. Documentación de diseño en
[`specs/002-realign-products/`](https://github.com/obedmacallums/WebODM/tree/master/specs/002-realign-products) y
[`specs/003-realign-pointcloud/`](https://github.com/obedmacallums/WebODM/tree/master/specs/003-realign-pointcloud).

## Instalación

En WebODM 3.2.5 o posterior: **Administración → Plugins → Load Plugin (.zip)**, elegir
`realign-<versión>.zip` y activarlo. El zip ya trae el frontend compilado (`public/build`), así
que funciona también donde WebODM no puede compilar plugins, como la app de escritorio de Windows.

El botón aparece en la esquina superior derecha del **mapa 2D de una sola tarea** que tenga
ortofoto, DSM o DTM.

- Para actualizar, se sube el zip nuevo con la opción de actualizar y se reinicia WebODM. Los
  productos corregidos se guardan en `media/plugins/realign_data/`, fuera de la carpeta del
  plugin, así que sobreviven a la actualización.
- La nube de puntos corregida necesita PDAL. Viene con la imagen Docker de WebODM y, en la app de
  Windows, dentro de ODX (el plugin lo busca ahí). Si no está, el panel lo indica y los rásteres
  siguen funcionando.

## Generar el zip

Las herramientas están en [`packaging/`](packaging/). Con Node instalado:

```bash
cd coreplugins/realign/packaging
npm install
npm run dist        # compila ../public/build y crea dist/realign-<versión>.zip
```

La compilación necesita el código fuente de un WebODM, porque el panel incluye
`webodm/components/ErrorMessage`, `Workers` y `gettext`. Se usa el del propio repo; si no está,
se busca en `WEBODM_DIR`, en la app de Windows (`C:/WebODM/resources/app/apps/WebODM`) o en
`/webodm`. Después de tocar el JSX o el SCSS hay que volver a ejecutar `npm run dist`.
`public/build` no se versiona: dentro de este repo lo compila WebODM al arrancar.

## Contrato para otros plugins

`CONTRACT_VERSION = 1`. Un consumidor **no importa este paquete directamente**: lo obtiene por el
framework de plugins, que es lo que permite degradar con elegancia si `realign` está ausente o
deshabilitado.

```python
from app.plugins.functions import get_plugin_by_name

plugin = get_plugin_by_name("realign")
corrected = {}
if plugin is not None and getattr(plugin, "contract_version", None) and plugin.contract_version() <= 1:
    corrected = plugin.corrected_rasters(task_id)

# {'orthophoto': '/ruta.tif', 'dsm': ..., 'dtm': ...} con solo los que existen ahora mismo
```

Métodos públicos de la clase `Plugin` (delegan en `contract.py`; ningún otro atributo forma parte
del contrato):

| Método | Devuelve |
|---|---|
| `contract_version()` | `1` |
| `corrected_rasters(task_id)` | Rutas de los productos corregidos **que existen en disco**. Diccionario vacío si la tarea no tiene realineación aplicada, si se revirtió, o si los archivos ya no están. |

Se comprueban las dos cosas —estado `applied` **y** presencia real del archivo— porque son
independientes: un borrado manual del directorio de plugins deja el estado intacto, y un consumidor
que se fiara solo del estado abriría una ruta inexistente dentro del worker, lejos de donde se
podría explicar. Ninguno comprueba permisos: el consumidor ya resolvió el acceso a la tarea.

Lo consume [`road`](../road/README.md) para ofrecer la variante realineada del modelo de elevación.
Detalle en
[`005-road-metrics/contracts/consumed-contracts.md`](../../specs/005-road-metrics/contracts/consumed-contracts.md).

## Tests

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.realign.tests
```
