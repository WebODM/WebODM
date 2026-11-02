"""Pipeline de corrección de rásteres (D4 de research.md), ejecutado en el worker.

Para cada producto ráster 2D disponible se compone la nueva geotransformación afín
``GT_new = S ∘ GT_orig`` (bakea la similitud como geotransform rotado, sin remuestrear) y luego
se remuestrea con ``gdalwarp`` a un COG north-up estándar. Siempre se parte del asset
**original** de la tarea (FR-010) y los originales nunca se tocan (FR-009).

Cero dependencias nuevas: usa los bindings ``osgeo.gdal`` ya presentes en la imagen.
"""

import os
import datetime

# Remuestreo por tipo de producto: bilineal para la ortofoto, vecino más cercano para DEM.
RESAMPLING = {'orthophoto': 'bilinear', 'dsm': 'near', 'dtm': 'near'}


def compose_geotransform(gt, T):
    """Devuelve la geotransformación resultante de aplicar la similitud T sobre ``gt``.

    ``gt`` es la 6-tupla de GDAL (pixel→mundo). T = {scale, cos, sin, tx, ty} (mundo→mundo).
    Como ambas son afines, el resultado es la composición ``S ∘ GT``.
    """
    s, c, sn, tx, ty = T['scale'], T['cos'], T['sin'], T['tx'], T['ty']
    return (
        s * (c * gt[0] - sn * gt[3]) + tx,
        s * (c * gt[1] - sn * gt[4]),
        s * (c * gt[2] - sn * gt[5]),
        s * (sn * gt[0] + c * gt[3]) + ty,
        s * (sn * gt[1] + c * gt[4]),
        s * (sn * gt[2] + c * gt[5]),
    )


class Canceled(Exception):
    """El usuario canceló la aplicación mientras el remuestreo estaba en marcha."""
    pass


def apply_similarity_to_raster(src_path, out_path, T, resampling='bilinear', should_cancel=None,
                               on_progress=None):
    """Aplica la similitud T al ráster ``src_path`` y escribe un COG north-up en ``out_path``.

    ``should_cancel`` (opcional) se consulta durante el remuestreo: ``gdalwarp`` es la parte
    larga y sin esto una cancelación no se notaba hasta que el producto entero estaba escrito.
    Lanza ``Canceled`` si se pide parar. ``on_progress(fraccion)`` recibe el avance del propio
    remuestreo (0..1), que es de donde sale el porcentaje que ve el usuario.
    """
    from osgeo import gdal
    gdal.UseExceptions()

    src = gdal.Open(src_path)
    if src is None:
        raise RuntimeError("No se pudo abrir el ráster: {}".format(src_path))
    new_gt = compose_geotransform(src.GetGeoTransform(), T)

    # VRT liviano que referencia la fuente con el geotransform rotado (sin copiar píxeles).
    vrt_path = out_path + ".vrt"
    vrt = gdal.Translate(vrt_path, src, format='VRT')
    vrt.SetGeoTransform(new_gt)
    vrt.FlushCache()
    vrt = None
    src = None

    # Devolver 0 desde el callback de progreso aborta el warp: es el único punto de parada que
    # ofrece GDAL, y el remuestreo es donde se va el tiempo de la aplicación.
    canceled = {'value': False}
    last_reported = {'pct': -1}

    def _progress(complete, message, data):
        if should_cancel is not None and should_cancel():
            canceled['value'] = True
            return 0
        if on_progress is not None:
            # GDAL llama a esto constantemente y cada reporte escribe en el backend de Celery:
            # se limita a saltos de 5 puntos.
            pct = int((complete or 0) * 100)
            if pct >= last_reported['pct'] + 5:
                last_reported['pct'] = pct
                on_progress(complete or 0)
        return 1

    warp_options = dict(format='COG', resampleAlg=resampling,
                        creationOptions=['COMPRESS=DEFLATE', 'BLOCKSIZE=512'])
    if should_cancel is not None or on_progress is not None:
        warp_options['callback'] = _progress

    try:
        gdal.Warp(out_path, vrt_path, options=gdal.WarpOptions(**warp_options))
    except Exception:
        # Un warp abortado desde el callback también sale por aquí; se distingue por la marca.
        if canceled['value']:
            raise Canceled()
        raise
    finally:
        try:
            os.remove(vrt_path)
        except OSError:
            pass
        if canceled['value'] and os.path.isfile(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass

    if canceled['value']:
        raise Canceled()
    return out_path


def run_correction_pipeline(task_id, products, out_dir, T, applied_by=None,
                            progress_callback=None, should_cancel=None):
    """Función de worker: genera los corregidos y marca el estado como ``applied``.

    ``products`` = [{'type': 'orthophoto', 'src': '/ruta/orthophoto.tif'}, ...].

    IMPORTANTE — debe ser **self-contained**: WebODM ejecuta esta función reejecutando su
    código fuente en un namespace vacío (``app/plugins/worker.py: eval_async`` hace
    ``eval(compile(source), ns, ns)`` con ``ns = {}``), sin los globals del módulo. Por eso
    todos los imports van **dentro** y son **absolutos**, y las funciones/constantes auxiliares
    se acceden a través del módulo importado (``corrections.*``) — nunca por nombre libre ni
    con imports relativos (``from . import ...``). Mismo patrón que ``coreplugins/viewshed``.

    El paquete cambia según cómo esté instalado: ``plugins.realign`` si se subió como zip
    (vive en ``MEDIA_ROOT/plugins``) o ``coreplugins.realign`` si viene con el código de WebODM.
    Importar ``app.plugins`` deja ``MEDIA_ROOT`` en ``sys.path``, que es lo que hace importable
    el primero.
    """
    import os
    import datetime
    import app.plugins
    try:
        from plugins.realign import corrections, store
    except ImportError:
        from coreplugins.realign import corrections, store

    def _now():
        return datetime.datetime.utcnow().isoformat() + 'Z'

    def _discard(paths):
        for path in paths:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _canceled():
        """Igual que en `pointcloud.py`: un chequeo de cancelación que falla (Celery en modo
        eager no tiene backend de resultados) no debe abortar un pipeline por lo demás sano."""
        if should_cancel is None:
            return False
        try:
            return bool(should_cancel())
        except Exception:
            return False

    os.makedirs(out_dir, exist_ok=True)

    corrected = {}
    try:
        total = len(products)
        for i, p in enumerate(products):
            if _canceled():
                raise corrections.Canceled()

            def _report(fraction, index=i, product=p['type']):
                # El avance combina el producto en curso y los ya hechos, para que la barra no
                # vuelva a cero en cada uno.
                progress_callback("Corrigiendo {}".format(product),
                                  100.0 * (index + fraction) / total)

            if progress_callback is not None:
                _report(0.0)
            out_path = os.path.join(out_dir, p['type'] + '.tif')
            corrections.apply_similarity_to_raster(
                p['src'], out_path, T, corrections.RESAMPLING.get(p['type'], 'bilinear'),
                should_cancel=_canceled,
                on_progress=_report if progress_callback is not None else None)
            corrected[p['type']] = out_path
    except corrections.Canceled:
        # Cancelado desde el panel (Revertir o editar puntos): se limpia lo generado y no se toca
        # el estado — el request que canceló ya dejó el suyo, y es posterior a este trabajo.
        _discard(corrected.values())
        return {'canceled': True}
    except Exception as e:
        # Sin esto el documento se quedaba en 'applying' para siempre: el fallo solo vivía en el
        # resultado de Celery, que se pierde al recargar la página.
        _discard(corrected.values())
        state = store.get_state(task_id) or {}
        if state.get('state') == 'applying':
            state.update({'state': 'error', 'error': str(e), 'corrected_paths': {},
                          'updated_at': _now()})
            store.set_state(task_id, state)
        return {'error': str(e)}

    state = store.get_state(task_id) or {}
    if state.get('state') != 'applying':
        # El usuario revirtió o volvió a editar los puntos mientras esto corría (este pipeline no
        # es cancelable, así que sigue hasta el final). Su decisión es posterior y gana: escribir
        # 'applied' aquí resucitaría una realineación que ya había descartado.
        _discard(corrected.values())
        return {'discarded': True, 'reason': state.get('state')}

    state['state'] = 'applied'
    state['corrected_paths'] = corrected
    state['error'] = None
    state['applied_at'] = _now()
    state['applied_by'] = applied_by
    store.set_state(task_id, state)

    return {'corrected': list(corrected.keys()), 'out_dir': out_dir}
