"""Contrato de consumo para otros plugins del fork.

`realign` no exponía nada a sus hermanos: quien quisiera usar sus productos corregidos tenía que
reconstruir la ruta interna `get_plugins_persistent_path('realign', 'task_<pk>')/<tipo>.tif`, lo que
acopla al consumidor al almacenamiento de este plugin y lo rompe en silencio en cuanto cambie.

Aquí vive la superficie pública, mínima y versionada. `plugin.py` solo delega en estas funciones;
ningún otro atributo de la clase `Plugin` forma parte del contrato.
"""

import os

from . import store

CONTRACT_VERSION = 1

# Productos ráster 2D que este plugin corrige. Duplicado deliberado de `api.PRODUCT_ASSETS`: el
# contrato no puede depender de un módulo de vistas, que arrastra DRF y el tiler.
PRODUCT_TYPES = ('orthophoto', 'dsm', 'dtm')

# Los productos corregidos viven fuera de la carpeta del plugin. Instalado desde un zip,
# `media/plugins/realign` es el propio código, y actualizarlo desde el panel de administración
# reemplaza esa carpeta entera: con los datos dentro, cada actualización los borraba. WebODM
# ignora `realign_data` al buscar plugins porque no tiene `plugin.py`.
DATA_DIR = 'realign_data'


def corrected_dir(task_id):
    from app.plugins.functions import get_plugins_persistent_path
    return get_plugins_persistent_path(DATA_DIR, 'task_{}'.format(task_id))


def corrected_path(task_id, product_type):
    return os.path.join(corrected_dir(task_id), '{}.tif'.format(product_type))


def corrected_rasters(task_id):
    """`{'orthophoto': '/ruta.tif', 'dsm': ..., 'dtm': ...}` con **solo** los corregidos que
    existen en disco ahora mismo.

    Diccionario vacío si la tarea no tiene realineación aplicada, si se revirtió, o si los archivos
    ya no están. Se comprueban las dos cosas —estado `applied` **y** presencia real del archivo—
    porque son independientes: un borrado manual del directorio de plugins deja el estado intacto,
    y un consumidor que se fiara solo del estado abriría una ruta inexistente dentro del worker.

    No comprueba permisos: el consumidor ya resolvió el acceso a la tarea.
    """
    state = store.get_state(task_id) or {}
    if state.get('state') != 'applied':
        return {}

    paths = state.get('corrected_paths') or {}
    available = {}
    for product_type in PRODUCT_TYPES:
        path = paths.get(product_type) or corrected_path(task_id, product_type)
        if os.path.isfile(path):
            available[product_type] = path
    return available
