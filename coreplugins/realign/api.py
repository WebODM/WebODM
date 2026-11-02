import os
import datetime

from rest_framework import status, exceptions
from rest_framework.response import Response
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

from app.plugins.views import TaskView, GetTaskResult
from app.plugins.worker import run_function_async
from app.api.common import check_project_perms

from . import transform, store, corrections, pointcloud, contract


# Productos ráster 2D que el plugin puede realinear (comparten georreferenciación).
PRODUCT_ASSETS = {
    'orthophoto': 'orthophoto.tif',
    'dsm': 'dsm.tif',
    'dtm': 'dtm.tif',
}


def available_products(task):
    """Productos ráster 2D presentes en la tarea (FR-016), por sus *extent* en BD."""
    extents = {
        'orthophoto': task.orthophoto_extent,
        'dsm': task.dsm_extent,
        'dtm': task.dtm_extent,
    }
    return [name for name, ext in extents.items() if ext is not None]


def _now():
    return datetime.datetime.utcnow().isoformat() + 'Z'


def _out_dir(pk):
    return contract.corrected_dir(pk)


def _stored_corrected_paths(pk):
    return (store.get_state(pk) or {}).get('corrected_paths') or {}


def _corrected_path(pk, product_type):
    """Ruta del corregido. Manda la que registró el pipeline al aplicar —la misma que usan el
    contrato y `corrected_available`—: los corregidos generados antes de que existiera
    `realign_data` siguen en la carpeta antigua, y calcular la ruta aquí por separado hacía que el
    estado dijera 'aplicado' mientras los tiles respondían 404."""
    return (_stored_corrected_paths(pk).get(product_type)
            or os.path.join(_out_dir(pk), '{}.tif'.format(product_type)))


def _remove_corrected(pk):
    # Los registrados en el estado (estén donde estén) más lo que haya en la carpeta actual.
    paths = set(_stored_corrected_paths(pk).values())
    d = _out_dir(pk)
    if os.path.isdir(d):
        paths.update(os.path.join(d, f) for f in os.listdir(d) if f.endswith('.tif'))
    for path in paths:
        if path.endswith('.tif') and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _abort_apply(state):
    """Cancela la aplicación en curso, si la hay.

    El pipeline consulta `should_cancel` entre productos y durante el remuestreo de cada uno, así
    que para de verdad en vez de seguir ocupando un worker hasta terminar un trabajo que ya nadie
    quiere. Se cancela también desde el backend y no solo desde el panel que lanzó la aplicación,
    para que sirva desde otra pestaña o navegador.
    """
    state = state or {}
    if state.get('state') == 'applying' and state.get('celery_task_id'):
        _abort_celery_task(state['celery_task_id'])


def _validate_points(raw):
    """Valida y normaliza la lista de pares de puntos. Devuelve (points, error)."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, _('El campo "points" debe ser una lista.')
    points = []
    for p in raw:
        try:
            s, t = p['source'], p['target']
            slat, slng = float(s['lat']), float(s['lng'])
            tlat, tlng = float(t['lat']), float(t['lng'])
        except (KeyError, TypeError, ValueError):
            return None, _('Cada par debe tener source y target con lat/lng numéricos.')
        if not (-90 <= slat <= 90 and -90 <= tlat <= 90 and -180 <= slng <= 180 and -180 <= tlng <= 180):
            return None, _('Coordenadas fuera de rango.')
        points.append({
            'id': p.get('id'),
            'source': {'lat': slat, 'lng': slng},
            'target': {'lat': tlat, 'lng': tlng},
            'enabled': p.get('enabled', True),
        })
    return points, None


def _fit_for_task(task, points, use_scale=True):
    enabled = [p for p in points if p.get('enabled', True)]
    return transform.similarity_from_latlng(enabled, task.epsg or 4326, use_scale=use_scale)


def _transform_dict(fit, epsg, use_scale):
    # Los valores (translation, cos/sin, scale) están en las unidades de este CRS proyectado;
    # se guarda el EPSG para poder reinterpretarlos (p. ej. reusarlos en la nube de puntos, FR-017).
    return {
        'crs': 'EPSG:{}'.format(epsg), 'use_scale': use_scale, 'scale': fit['scale'],
        'rotation_deg': fit['rotation_deg'], 'translation': {'x': fit['tx'], 'y': fit['ty']},
        'cos': fit['cos'], 'sin': fit['sin'], 'n_points': fit['n'], 'rmse_m': fit['rmse'],
        'degenerate': fit['degenerate'],
    }


def _use_scale_from_request(request, state):
    # Si el body no trae 'use_scale', se conserva el último valor persistido; si nunca hubo uno,
    # el default es True (preserva el comportamiento con el que se creó el estado — FR-020, D9).
    prev = ((state or {}).get('transform') or {}).get('use_scale', True)
    return bool(request.data.get('use_scale', prev))


def _points_with_residuals(points, fit):
    res = fit.get('residuals', [])
    enabled_idx = 0
    out = []
    for p in points:
        r = None
        if p.get('enabled', True) and not fit['degenerate'] and enabled_idx < len(res):
            r = res[enabled_idx]
            enabled_idx += 1
        out.append(dict(p, residual_m=r))
    return out


def _state_response(task, pk):
    products = available_products(task)
    state = store.get_state(pk)
    if state is None:
        return {
            'state': 'previewing', 'points': [], 'transform': None,
            'products': products, 'corrected_available': False,
            'pointcloud': _pointcloud_state_response(task, pk),
        }
    corrected = state.get('corrected_paths') or {}
    corrected_available = (state.get('state') == 'applied'
                           and any(os.path.isfile(p) for p in corrected.values()))
    return {
        'state': state.get('state', 'previewing'),
        'points': state.get('points', []),
        'transform': state.get('transform'),
        'products': products,
        'corrected_available': corrected_available,
        'updated_at': state.get('updated_at'),
        # Un fallo del pipeline solo vivía en el resultado de Celery, que se pierde al recargar:
        # así el panel puede decir por qué no hay productos corregidos.
        'error': state.get('error'),
        'pointcloud': _pointcloud_state_response(task, pk),
    }


class RealignState(TaskView):
    """Estado de realineación de una tarea (FR-012, FR-013, FR-016)."""

    def get(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        return Response(_state_response(task, pk), status=status.HTTP_200_OK)

    def put(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))

        points, err = _validate_points(request.data.get('points'))
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)

        state = store.get_state(pk) or {}
        _abort_apply(state)
        use_scale = _use_scale_from_request(request, state)
        fit = _fit_for_task(task, points, use_scale)
        # Editar puntos vuelve a estado de previsualización (los corregidos previos se
        # regenerarán desde el original al volver a aplicar — FR-010).
        state.update({
            'state': 'previewing',
            'points': _points_with_residuals(points, fit),
            'transform': _transform_dict(fit, task.epsg or 4326, use_scale),
            'products': available_products(task),
            'updated_at': _now(),
        })
        store.set_state(pk, state)
        return Response(_state_response(task, pk), status=status.HTTP_200_OK)

    def delete(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))
        _remove_corrected(pk)
        _discard_pointcloud(pk)
        store.del_state(pk)
        return Response({'ok': True}, status=status.HTTP_200_OK)


class RealignApply(TaskView):
    """Genera los productos corregidos de forma asíncrona (FR-008, FR-010, FR-014, FR-015)."""

    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))

        points, err = _validate_points(request.data.get('points'))
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)
        state = store.get_state(pk) or {}
        if points is None or len(points) == 0:
            points = state.get('points', [])

        enabled = [p for p in points if p.get('enabled', True)]
        if len(enabled) < 1:
            return Response({'error': _('Se necesita al menos un par de puntos para aplicar.')},
                            status=status.HTTP_400_BAD_REQUEST)

        use_scale = _use_scale_from_request(request, state)
        fit = _fit_for_task(task, points, use_scale)
        if fit['degenerate']:
            return Response({'error': _('Los puntos no permiten calcular la transformación (coincidentes o insuficientes).')},
                            status=status.HTTP_400_BAD_REQUEST)

        products = available_products(task)
        if not products:
            return Response({'error': _('La tarea no tiene productos ráster 2D para realinear.')},
                            status=status.HTTP_400_BAD_REQUEST)

        product_list = [{'type': t, 'src': os.path.abspath(task.get_asset_download_path(PRODUCT_ASSETS[t]))}
                        for t in products]
        T = {'scale': fit['scale'], 'cos': fit['cos'], 'sin': fit['sin'], 'tx': fit['tx'], 'ty': fit['ty']}

        state.update({
            'state': 'applying',
            'points': _points_with_residuals(points, fit),
            'transform': _transform_dict(fit, task.epsg or 4326, use_scale),
            'products': products,
            'updated_at': _now(),
        })
        store.set_state(pk, state)

        # `with_cancel` para que Revertir pueda parar el remuestreo en marcha, y no solo
        # descartar su resultado cuando por fin termine.
        async_result = run_function_async(
            corrections.run_correction_pipeline,
            str(pk), product_list, _out_dir(pk), T, request.user.id,
            with_progress=True, with_cancel=True,
        )
        # Bajo CELERY_TASK_ALWAYS_EAGER (tests) el pipeline ya terminó y escribió su propio
        # estado final: solo se adjunta el id si seguimos en el 'applying' que dejamos arriba.
        current = store.get_state(pk) or {}
        if current.get('state') == 'applying':
            current['celery_task_id'] = async_result.task_id
            store.set_state(pk, current)
        return Response({'celery_task_id': async_result.task_id}, status=status.HTTP_200_OK)


class RealignRevert(TaskView):
    """Revierte al estado original, conservando los originales (FR-011, FR-014)."""

    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))
        # Parar primero: si la aplicación sigue en marcha, borrar los corregidos antes de
        # cancelarla solo serviría para que el pipeline los volviera a escribir detrás.
        _abort_apply(store.get_state(pk))
        _remove_corrected(pk)
        _discard_pointcloud(pk)
        # Relectura obligatoria: `_discard_pointcloud` acaba de reescribir el documento sin su
        # clave `pointcloud`, y guardar una copia leída antes la resucitaría.
        state = store.get_state(pk) or {}
        state.update({'state': 'reverted', 'corrected_paths': {}, 'celery_task_id': None,
                      'error': None, 'updated_at': _now()})
        store.set_state(pk, state)
        return Response({'state': 'reverted'}, status=status.HTTP_200_OK)


class RealignStatus(GetTaskResult):
    """Sondeo del pipeline asíncrono de aplicar (patrón GetTaskResult del framework)."""
    pass


class RealignTiles(TaskView):
    """Tiles PNG del producto corregido, servidos por el plugin (D5, FR-008)."""

    def get(self, request, pk=None, type=None, z=None, x=None, y=None, ext=None):
        task = self.get_and_check_task(request, pk)
        path = _corrected_path(pk, type)
        if not os.path.isfile(path):
            raise exceptions.NotFound()

        from rio_tiler.io import COGReader
        from rio_tiler.errors import TileOutsideBounds, InvalidColorMapName
        from rio_tiler.profiles import img_profiles
        from rio_tiler.colormap import cmap as colormap

        z, x, y = int(z), int(x), int(y)

        # Mismo esquema que el tiler del core (app/api/tiler.py): las capas del frontend usan
        # tileSize 512 y piden z+1 en la URL; con size=512 se compensa restando 1 al zoom.
        tilesize = request.query_params.get('size') or 256
        try:
            tilesize = int(tilesize)
            if tilesize not in (256, 512):
                raise ValueError()
        except ValueError:
            raise exceptions.ValidationError(_("Parámetro size inválido"))
        if tilesize == 512:
            z -= 1

        # El core adjunta color_map/rescale a la URL de la capa original (Map.jsx: viridis +
        # rescale con min/max reales para dsm/dtm) y redirectCoreLayer los preserva al
        # redirigir — se honran aquí para que el corregido se vea igual que el original.
        default_color_map = None if type == 'orthophoto' else 'gray'
        color_map_name = request.query_params.get('color_map') or default_color_map
        cmap_obj = None
        if color_map_name:
            try:
                cmap_obj = colormap.get(color_map_name)
            except InvalidColorMapName:
                raise exceptions.ValidationError(_("Parámetro color_map inválido"))

        rescale_param = request.query_params.get('rescale')
        if rescale_param:
            try:
                rescale = [float(v) for v in rescale_param.split(',')]
            except ValueError:
                raise exceptions.ValidationError(_("Parámetro rescale inválido"))
        else:
            rescale = [0, 255] if type == 'orthophoto' else [0, 1000]

        options = img_profiles.get('png', {})

        try:
            with COGReader(path) as src:
                if not src.tile_exists(z, x, y):
                    raise exceptions.NotFound(_("Fuera de límites"))
                nodata = 0 if type == 'orthophoto' else None
                tile = src.tile(x, y, z, tilesize=tilesize, nodata=nodata)
                img = tile.post_process(in_range=(rescale,))
                render_kwargs = {'img_format': 'PNG', **options}
                if cmap_obj is not None:
                    render_kwargs['colormap'] = cmap_obj
                return HttpResponse(img.render(**render_kwargs), content_type='image/png')
        except TileOutsideBounds:
            raise exceptions.NotFound(_("Fuera de límites"))


class RealignTileJson(TaskView):
    """TileJSON del producto corregido (bounds leídos del COG corregido)."""

    def get(self, request, pk=None, type=None):
        task = self.get_and_check_task(request, pk)
        path = _corrected_path(pk, type)
        if not os.path.isfile(path):
            raise exceptions.NotFound()

        from rio_tiler.io import COGReader

        with COGReader(path) as src:
            minzoom, maxzoom = src.minzoom, src.maxzoom
            # rio-tiler 2.1.x expone COGReader.bounds ya en EPSG:4326 ([w, s, e, n]).
            bounds = list(src.bounds)

        tile_url = '/api/plugins/realign/task/{}/realign/tiles/{}/{{z}}/{{x}}/{{y}}.png'.format(pk, type)
        return Response({
            'tilejson': '2.1.0',
            'name': 'realign_{}'.format(type),
            'version': '1.0.0',
            'scheme': 'xyz',
            'tiles': [tile_url],
            'minzoom': minzoom,
            'maxzoom': maxzoom + 3,
            'bounds': bounds,
        })


class RealignDownload(TaskView):
    """Descarga del GeoTIFF corregido desde el directorio persistente del plugin."""

    def get(self, request, pk=None, type=None):
        from app.api.tasks import download_file_response
        task = self.get_and_check_task(request, pk)
        path = _corrected_path(pk, type)
        if not os.path.isfile(path):
            raise exceptions.NotFound()
        return download_file_response(request, path, 'attachment',
                                      download_filename='{}_realigned.tif'.format(type))


# --- Nube de puntos (003-realign-pointcloud) --------------------------------------------------

POINTCLOUD_ASSET = 'georeferenced_model.laz'

POINTCLOUD_REASON_MESSAGES = {
    'no_pointcloud': _('La tarea no tiene nube de puntos.'),
    'not_applied': _('Aplica primero la realineación (no solo la previsualización) antes de generar la nube corregida.'),
    'scale_enabled': _('La corrección de nube solo está disponible en modo rígido. Destilda "Usar escala", vuelve a aplicar la realineación y repite la generación.'),
    'already_running': _('Ya hay una generación de nube en curso para esta tarea.'),
    'pdal_missing': _('No se encontró PDAL en el servidor: no se puede generar la nube corregida.'),
}


def _pointcloud_files(pk):
    d = _out_dir(pk)
    return [os.path.join(d, name) for name in
            ('pointcloud.laz', 'pointcloud.tmp.laz', 'pointcloud_pipeline.json')]


def _remove_pointcloud_files(pk):
    # Igual que con los rásteres: la ruta registrada puede ser de la carpeta antigua.
    stored = (store.get_pointcloud_state(pk) or {}).get('path')
    for p in _pointcloud_files(pk) + ([stored] if stored else []):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


def _abort_celery_task(celery_task_id):
    from worker.tasks import TestSafeAsyncResult
    res = TestSafeAsyncResult(celery_task_id)
    if not res.ready():
        res.backend.store_result(celery_task_id, result=None, state="ABORTED", traceback=None)


def _discard_pointcloud(pk):
    """Cancela una generación en curso (si la hay), borra los archivos y el estado (FR-013, FR-015)."""
    pc = store.get_pointcloud_state(pk)
    if pc and pc.get('status') == 'running' and pc.get('celery_task_id'):
        _abort_celery_task(pc['celery_task_id'])
    _remove_pointcloud_files(pk)
    store.del_pointcloud_state(pk)


def _pointcloud_eligibility(task, pk):
    """Las tres condiciones de elegibilidad (D9 de research.md) más la exclusión mutua de una
    segunda generación simultánea. Se revalida siempre en el backend (FR-004, FR-005, FR-015,
    FR-017), sin confiar en que la UI ya las haya comprobado.
    """
    if POINTCLOUD_ASSET not in (task.available_assets or []):
        return False, 'no_pointcloud'

    # Mejor decirlo antes de lanzar nada que dejar que el worker falle a mitad de camino.
    if pointcloud.pdal_command()[0] is None:
        return False, 'pdal_missing'

    state = store.get_state(pk) or {}
    if state.get('state') != 'applied':
        return False, 'not_applied'

    transform_ = state.get('transform') or {}
    if transform_.get('use_scale', True):
        return False, 'scale_enabled'

    pc = store.get_pointcloud_state(pk)
    if pc and pc.get('status') == 'running':
        return False, 'already_running'

    return True, None


def _flat_transform(stored_transform):
    """Convierte el `transform` persistido (forma de `_transform_dict`, con `translation:
    {x,y}` anidado) a la forma plana (`cos`/`sin`/`tx`/`ty`) que usan `pointcloud.py` y
    `corrections.py` (mismo `T` que `RealignApply.post` arma a partir de `fit`, no del
    documento persistido)."""
    t = stored_transform or {}
    translation = t.get('translation') or {}
    return {
        'cos': t.get('cos', 1.0),
        'sin': t.get('sin', 0.0),
        'tx': translation.get('x', 0.0),
        'ty': translation.get('y', 0.0),
        'use_scale': t.get('use_scale', True),
        'n_points': t.get('n_points'),
    }


def _pointcloud_state_response(task, pk):
    pc = store.get_pointcloud_state(pk)
    state = store.get_state(pk) or {}
    current_transform = state.get('transform') or {}

    if pc is None:
        pc_status, stale, available = 'absent', False, False
        point_count = size_bytes = generated_at = error = celery_task_id = None
    else:
        pc_status = pc.get('status', 'absent')
        current_fp = pointcloud.compute_fingerprint(_flat_transform(current_transform)) if current_transform else None
        stale = (pc_status == 'ready') and not pointcloud.fingerprint_matches(pc.get('fingerprint'), current_fp)
        available = (pc_status == 'ready') and not stale
        point_count = pc.get('point_count')
        size_bytes = pc.get('size_bytes')
        generated_at = pc.get('generated_at')
        error = pc.get('error')
        celery_task_id = pc.get('celery_task_id')

    eligible, reason = _pointcloud_eligibility(task, pk)
    return {
        'status': pc_status,
        'stale': stale,
        'available': available,
        'point_count': point_count,
        'size_bytes': size_bytes,
        'generated_at': generated_at,
        'celery_task_id': celery_task_id,
        'error': error,
        'eligible': eligible,
        'ineligible_reason': reason,
    }


class RealignPointCloud(TaskView):
    """Generar / descartar la nube de puntos corregida (FR-001 a FR-007, FR-009, FR-013 a FR-017)."""

    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))

        eligible, reason = _pointcloud_eligibility(task, pk)
        if not eligible:
            return Response({'error': POINTCLOUD_REASON_MESSAGES[reason], 'reason': reason},
                            status=status.HTTP_400_BAD_REQUEST)

        state = store.get_state(pk) or {}
        transform_ = _flat_transform(state.get('transform'))
        src_path = os.path.abspath(task.get_asset_download_path(POINTCLOUD_ASSET))
        out_dir = _out_dir(pk)

        pc_state = {
            'status': 'running', 'path': None, 'fingerprint': None, 'celery_task_id': None,
            'point_count': None, 'size_bytes': None, 'source_size_bytes': None, 'error': None,
            'generated_at': None, 'generated_by': None, 'updated_at': _now(),
        }
        store.set_pointcloud_state(pk, pc_state)

        async_result = run_function_async(
            pointcloud.run_pointcloud_correction,
            str(pk), src_path, out_dir, transform_, request.user.id,
            with_progress=True, with_cancel=True,
        )
        # `run_function_async` corre síncrono bajo CELERY_TASK_ALWAYS_EAGER=True (tests):
        # para cuando volvemos aquí, `run_pointcloud_correction` ya pudo haber terminado y
        # escrito su propio estado final ('ready'/'error'). Solo adjuntamos el celery_task_id
        # si el estado sigue siendo el 'running' que dejamos antes de lanzar el async —de lo
        # contrario pisaríamos el resultado ya persistido con datos obsoletos.
        current = store.get_pointcloud_state(pk)
        if current is not None and current.get('status') == 'running' and current.get('celery_task_id') is None:
            current['celery_task_id'] = async_result.task_id
            store.set_pointcloud_state(pk, current)

        return Response({'celery_task_id': async_result.task_id, 'status': 'running'},
                        status=status.HTTP_200_OK)

    def delete(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))
        _discard_pointcloud(pk)
        return Response({'status': 'absent'}, status=status.HTTP_200_OK)


class RealignPointCloudDownload(TaskView):
    """Descarga del LAZ corregido desde el directorio persistente del plugin (D5, FR-010, FR-011)."""

    def get(self, request, pk=None):
        from app.api.tasks import download_file_response
        task = self.get_and_check_task(request, pk)

        pc = store.get_pointcloud_state(pk)
        if pc is None or pc.get('status') != 'ready':
            raise exceptions.NotFound()

        state = store.get_state(pk) or {}
        current_fp = pointcloud.compute_fingerprint(_flat_transform(state.get('transform')))
        if not pointcloud.fingerprint_matches(pc.get('fingerprint'), current_fp):
            raise exceptions.NotFound()

        path = pc.get('path')
        if not path or not os.path.isfile(path):
            raise exceptions.NotFound()

        return download_file_response(request, path, 'attachment',
                                      download_filename='{}_realigned.laz'.format(task.name or pk))
