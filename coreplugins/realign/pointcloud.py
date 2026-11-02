"""Pipeline de corrección de la nube de puntos (research.md D1-D9), ejecutado en el worker.

Aplica a ``georeferenced_model.laz`` exactamente la misma transformación horizontal (traslación
+ rotación) que ``corrections.py`` aplica a los rásteres, con la fila Z en identidad — las
elevaciones quedan bit a bit intactas (D2, FR-003). Usa el CLI ``pdal`` (ya en la imagen, cero
dependencias nuevas — los bindings ``python-pdal`` no están instalados y no hacen falta) invocado
por ``subprocess`` con un pipeline ``readers.las -> filters.transformation -> writers.las`` (D1).
"""

import json
import os
import shutil
import subprocess
import sys
import time

# Menor que el paso de cuantización del LAZ (típicamente >= 0.001 m): dos huellas con una
# diferencia menor se consideran "el mismo ajuste" (D8, data-model.md).
FINGERPRINT_TOLERANCE = 1e-4

# Rango representable por una dimensión LAS de 4 bytes con signo.
_INT32_MAX = 2 ** 31 - 1


class PointCloudTransformError(Exception):
    """La transformación no se puede aplicar a esta nube (p. ej. desbordaría la precisión LAS)."""
    pass


def build_transformation_matrix(transform):
    """Matriz 4x4 *row-major* (string, formato que espera ``filters.transformation``) a partir de
    ``cos``/``sin``/``tx``/``ty``, con la fila Z en identidad (D2).

    ``transform`` es el dict persistido en ``TaskRealignment`` (mismos parámetros que
    ``corrections.py`` usa para los rásteres). El campo ``scale`` se ignora deliberadamente: esta
    feature solo opera sobre transformaciones en modo rígido (FR-004).
    """
    cos, sin = transform['cos'], transform['sin']
    tx, ty = transform['tx'], transform['ty']
    rows = [
        [cos, -sin, 0.0, tx],
        [sin, cos, 0.0, ty],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    return " ".join(repr(float(v)) for row in rows for v in row)


def pdal_command():
    """Ejecutable de ``pdal`` y entorno con el que lanzarlo: ``(exe, env)``.

    En Docker y en instalaciones nativas está en el PATH (``env`` es ``None``: el heredado). La
    app de escritorio de Windows no lo pone en el PATH del worker, pero lo trae dentro de ODX y
    solo arranca con las DLL de GDAL de ese mismo ODX: se reproduce el entorno de su
    ``win32env.bat``. Devuelve ``(None, None)`` si no hay ``pdal`` en ningún lado.
    """
    exe = shutil.which('pdal')
    if exe:
        return exe, None

    # <app>/apps/python39/python.exe -> <app>/apps/ODX
    odx = os.path.join(os.path.dirname(os.path.dirname(sys.executable)), 'ODX')
    bin_dir = os.path.join(odx, 'SuperBuild', 'install', 'bin')
    exe = os.path.join(bin_dir, 'pdal.exe')
    if not os.path.isfile(exe):
        return None, None

    site_packages = os.path.join(odx, 'venv', 'Lib', 'site-packages')
    gdal_dir = os.path.join(site_packages, 'osgeo')
    env = dict(os.environ)
    env.update({
        'PATH': os.pathsep.join([gdal_dir, bin_dir, env.get('PATH', '')]),
        'PDAL_DRIVER_PATH': bin_dir,
        'GDAL_DATA': os.path.join(gdal_dir, 'data', 'gdal'),
        'PROJ_LIB': os.path.join(site_packages, 'rasterio', 'proj_data'),
    })
    return exe, env


def _pdal_output(args):
    exe, env = pdal_command()
    if exe is None:
        raise FileNotFoundError("No se encontró el ejecutable de PDAL")
    return subprocess.check_output([exe] + args, env=env)


def read_las_summary(las_path):
    """Lee el resumen de la cabecera (bounds, num_points) sin recorrer los puntos."""
    out = _pdal_output(['info', '--summary', las_path])
    return json.loads(out.decode('utf-8'))['summary']


def read_las_metadata(las_path):
    """Lee la cabecera completa (scale_*, offset_z, dataformat_id, SRS, ...)."""
    out = _pdal_output(['info', '--metadata', las_path])
    return json.loads(out.decode('utf-8'))['metadata']


def _apply_xy(cos, sin, tx, ty, x, y):
    return cos * x - sin * y + tx, sin * x + cos * y + ty


def _safe_should_cancel(should_cancel):
    """Invoca ``should_cancel`` tolerando que falle (p. ej. ``RuntimeError: Cannot retrieve
    result with task_always_eager enabled`` — la implementación de ``should_cancel`` en
    ``app/plugins/worker.py`` consulta el backend de resultados de Celery, que no está
    disponible en modo eager/tests). Un chequeo de cancelación que falla no debe abortar un
    pipeline por lo demás sano: se trata como "no cancelado" y se reintenta en la próxima
    iteración.
    """
    if should_cancel is None:
        return False
    try:
        return bool(should_cancel())
    except Exception:
        return False


def compute_safe_offsets(bounds, transform, scale_x, scale_y):
    """Offsets XY seguros para el resultado, calculados de las 4 esquinas del bbox transformado
    (sin leer los puntos). Evita el desborde del entero de 4 bytes de LAS que ocurre si se
    heredan los offsets originales sobre una transformación que aleja las coordenadas del origen
    (research.md D3). Lanza ``PointCloudTransformError`` si ni el offset óptimo evita el desborde.
    """
    cos, sin = transform['cos'], transform['sin']
    tx, ty = transform['tx'], transform['ty']

    corners = [
        (bounds['minx'], bounds['miny']),
        (bounds['minx'], bounds['maxy']),
        (bounds['maxx'], bounds['miny']),
        (bounds['maxx'], bounds['maxy']),
    ]
    xs, ys = [], []
    for x, y in corners:
        px, py = _apply_xy(cos, sin, tx, ty, x, y)
        xs.append(px)
        ys.append(py)

    offset_x = round((min(xs) + max(xs)) / 2)
    offset_y = round((min(ys) + max(ys)) / 2)

    _check_int32_range(xs, offset_x, scale_x, 'X')
    _check_int32_range(ys, offset_y, scale_y, 'Y')

    return offset_x, offset_y


def _check_int32_range(values, offset, scale, dim_name):
    if not scale:
        return
    for v in (min(values), max(values)):
        if abs((v - offset) / scale) > _INT32_MAX:
            raise PointCloudTransformError(
                "La transformación desplaza la coordenada {} fuera del rango representable "
                "con la precisión ({}) de la nube original.".format(dim_name, scale))


def compute_fingerprint(transform):
    """Huella de la transformación vigente (research.md D8): identifica con qué ajuste se generó
    un resultado, para detectar cuándo deja de corresponder al ajuste actual (FR-012).
    """
    return {
        'cos': round(float(transform.get('cos', 1.0)), 9),
        'sin': round(float(transform.get('sin', 0.0)), 9),
        'tx': round(float(transform.get('tx', 0.0)), 4),
        'ty': round(float(transform.get('ty', 0.0)), 4),
        'use_scale': bool(transform.get('use_scale', True)),
        'n_points': transform.get('n_points'),
    }


def fingerprint_matches(a, b):
    """Compara dos huellas con la tolerancia de ``FINGERPRINT_TOLERANCE`` (D8)."""
    if not a or not b:
        return False
    if a.get('use_scale') != b.get('use_scale'):
        return False
    if a.get('n_points') != b.get('n_points'):
        return False
    for key in ('cos', 'sin', 'tx', 'ty'):
        av, bv = a.get(key) or 0.0, b.get(key) or 0.0
        if abs(av - bv) > FINGERPRINT_TOLERANCE:
            return False
    return True


def run_pointcloud_correction(task_id, src_path, out_dir, transform, applied_by=None,
                               progress_callback=None, should_cancel=None):
    """Función de worker: genera el LAZ corregido y marca el estado como ``ready`` (o ``error``).

    IMPORTANTE — debe ser **self-contained**: WebODM ejecuta esta función reejecutando su código
    fuente en un namespace vacío (``app/plugins/worker.py: eval_async``), sin los globals del
    módulo. Por eso los imports van **dentro** y son **absolutos**, y las funciones auxiliares del
    módulo se acceden vía ``pointcloud.*`` — mismo patrón que ``corrections.py:
    run_correction_pipeline`` (incluido el import que funciona como zip o como coreplugin).
    """
    import datetime
    import json
    import os
    import subprocess
    import time
    import app.plugins
    try:
        from plugins.realign import pointcloud, store
    except ImportError:
        from coreplugins.realign import pointcloud, store

    def _now():
        return datetime.datetime.utcnow().isoformat() + 'Z'

    def _still_running():
        """El estado sigue siendo el 'running' que dejó el request que nos lanzó.

        Un DELETE (descartar) borra estado y archivos de forma síncrona mientras esto corre, y
        `should_cancel` solo se consulta mientras vive el proceso de pdal: sin esta comprobación,
        lo que se escriba después resucitaría un resultado que el usuario ya descartó.
        """
        state = store.get_pointcloud_state(task_id)
        return bool(state) and state.get('status') == 'running'

    def _fail(message, tmp_path=None, pipeline_path=None):
        for p in (tmp_path, pipeline_path):
            if p and os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        if not _still_running():
            return {'discarded': True}
        state = store.get_pointcloud_state(task_id) or {}
        state.update({'status': 'error', 'error': message, 'celery_task_id': None, 'updated_at': _now()})
        store.set_pointcloud_state(task_id, state)
        return {'error': message}

    os.makedirs(out_dir, exist_ok=True)
    final_path = os.path.join(out_dir, 'pointcloud.laz')
    tmp_path = os.path.join(out_dir, 'pointcloud.tmp.laz')
    pipeline_path = os.path.join(out_dir, 'pointcloud_pipeline.json')

    # Limpia restos de una ejecución previa interrumpida antes de empezar.
    for p in (tmp_path, pipeline_path):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass

    try:
        summary = pointcloud.read_las_summary(src_path)
        metadata = pointcloud.read_las_metadata(src_path)
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as e:
        return _fail("No se pudo leer la nube de puntos original: {}".format(e))

    source_size = os.path.getsize(src_path)

    try:
        offset_x, offset_y = pointcloud.compute_safe_offsets(
            summary['bounds'], transform,
            metadata.get('scale_x', 0.01), metadata.get('scale_y', 0.01))
    except pointcloud.PointCloudTransformError as e:
        return _fail(str(e))

    matrix = pointcloud.build_transformation_matrix(transform)
    pipeline = {
        "pipeline": [
            {"type": "readers.las", "filename": src_path},
            {"type": "filters.transformation", "matrix": matrix},
            {"type": "writers.las", "filename": tmp_path, "compression": "LASZIP",
             "forward": "all", "offset_x": str(offset_x), "offset_y": str(offset_y)},
        ]
    }
    with open(pipeline_path, 'w') as f:
        json.dump(pipeline, f)

    pdal_exe, pdal_env = pointcloud.pdal_command()
    if pdal_exe is None:
        return _fail("No se encontró el ejecutable de PDAL.", pipeline_path=pipeline_path)
    proc = subprocess.Popen([pdal_exe, 'pipeline', pipeline_path],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=pdal_env)

    while proc.poll() is None:
        if pointcloud._safe_should_cancel(should_cancel):
            # should_cancel() solo se vuelve True vía RealignPointCloud.delete (D del
            # contrato), que ya deja el estado en "absent" y borra los archivos de forma
            # síncrona en el propio request. No se reescribe el store aquí: hacerlo dejaría
            # una ventana de carrera donde este bucle "resucita" un estado 'error' después de
            # que el DELETE ya lo dejó en 'absent'. Solo queda limpiar lo que este proceso
            # generó.
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            for p in (tmp_path, pipeline_path):
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            return {'error': 'canceled'}

        if progress_callback is not None:
            current = os.path.getsize(tmp_path) if os.path.isfile(tmp_path) else 0
            pct = min(99.0, 100.0 * current / source_size) if source_size else 0.0
            progress_callback("Transformando la nube de puntos", pct)

        time.sleep(2)

    out, err = proc.communicate()
    if proc.returncode != 0:
        msg = err.decode('utf-8', 'replace').strip() if err else 'pdal terminó con error'
        return _fail("Error al ejecutar pdal: {}".format(msg), tmp_path, pipeline_path)

    if os.path.isfile(pipeline_path):
        try:
            os.remove(pipeline_path)
        except OSError:
            pass

    if not os.path.isfile(tmp_path):
        return _fail("El pipeline terminó sin generar el archivo esperado.")

    if not _still_running():
        # Descartado entre que pdal terminó y este punto: no se publica el resultado ni se deja
        # el .laz recién escrito, que ya nadie espera.
        for p in (tmp_path, final_path):
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return {'discarded': True}

    os.replace(tmp_path, final_path)

    state = store.get_pointcloud_state(task_id) or {}
    state.update({
        'status': 'ready',
        'path': final_path,
        'fingerprint': pointcloud.compute_fingerprint(transform),
        'celery_task_id': None,
        'point_count': summary.get('num_points'),
        'size_bytes': os.path.getsize(final_path),
        'source_size_bytes': source_size,
        'error': None,
        'generated_at': _now(),
        'generated_by': applied_by,
        'updated_at': _now(),
    })
    store.set_pointcloud_state(task_id, state)

    return {'status': 'ready', 'path': final_path, 'point_count': summary.get('num_points')}
