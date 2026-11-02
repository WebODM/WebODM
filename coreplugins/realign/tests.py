import os
import shutil
import tempfile
import unittest

from django.contrib.auth.models import User
from django.contrib.gis.geos import Polygon
from guardian.shortcuts import assign_perm
from rest_framework import status
from rest_framework.test import APIClient

from app.models import Project, Task
from app.tests.classes import BootTestCase
from nodeodm import status_codes

from . import transform, corrections, pointcloud, store, contract

TEST_EXTENT = Polygon.from_bbox([-82.8325, 27.9578, -82.8310, 27.9593])
POINTCLOUD_ASSET_KEY = 'georeferenced_model.laz'
# Pares de puntos de control de ejemplo (cerca de Tampa, UTM 17N / EPSG:32617).
POINTS_OK = [
    {'id': 1, 'source': {'lat': 27.9580, 'lng': -82.8320}, 'target': {'lat': 27.9581, 'lng': -82.8319}, 'enabled': True},
    {'id': 2, 'source': {'lat': 27.9590, 'lng': -82.8315}, 'target': {'lat': 27.9591, 'lng': -82.8314}, 'enabled': True},
    {'id': 3, 'source': {'lat': 27.9585, 'lng': -82.8312}, 'target': {'lat': 27.9586, 'lng': -82.8311}, 'enabled': True},
]
POINTS_DEGENERATE = [
    {'id': 1, 'source': {'lat': 27.9585, 'lng': -82.8318}, 'target': {'lat': 27.9586, 'lng': -82.8317}, 'enabled': True},
    {'id': 2, 'source': {'lat': 27.9585, 'lng': -82.8318}, 'target': {'lat': 27.9590, 'lng': -82.8310}, 'enabled': True},
]


class RealignStateTest(BootTestCase):
    """Tests de los endpoints de realineación (US1–US4)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _project(self, name="Realign test project"):
        owner = User.objects.get(username="testuser")
        return Project.objects.create(owner=owner, name=name)

    def _task(self, project, **kwargs):
        defaults = dict(project=project, status=status_codes.COMPLETED,
                        available_assets=["orthophoto.tif"], orthophoto_extent=TEST_EXTENT, epsg=32617)
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def _url(self, task, suffix="state"):
        return "/api/plugins/realign/task/{}/realign/{}".format(task.id, suffix)

    # --- US1 -----------------------------------------------------------------

    def test_state_lists_available_2d_products(self):
        task = self._task(self._project(), available_assets=["orthophoto.tif", "dsm.tif"], dsm_extent=TEST_EXTENT)
        self.client.login(username="testuser", password="test1234")
        res = self.client.get(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("orthophoto", res.data["products"])
        self.assertIn("dsm", res.data["products"])
        self.assertNotIn("dtm", res.data["products"])
        self.assertEqual(res.data["state"], "previewing")
        self.assertFalse(res.data["corrected_available"])

    def test_state_no_2d_products(self):
        task = self._task(self._project("no rasters"), available_assets=["georeferenced_model.laz"],
                          orthophoto_extent=None)
        self.client.login(username="testuser", password="test1234")
        res = self.client.get(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["products"], [])

    def test_state_permission_denied(self):
        task = self._task(self._project())
        self.client.login(username="testuser2", password="test1234")
        res = self.client.get(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # --- US4: persistencia (FR-012, FR-013) ----------------------------------

    def test_put_state_persists_points_with_residuals(self):
        task = self._task(self._project())
        self.client.login(username="testuser", password="test1234")
        res = self.client.put(self._url(task), {'points': POINTS_OK}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['points']), 3)
        self.assertIn('residual_m', res.data['points'][0])
        self.assertIsNotNone(res.data['transform'])
        self.assertFalse(res.data['transform']['degenerate'])
        # El transform registra el CRS en el que viven sus valores (task.epsg).
        self.assertEqual(res.data['transform']['crs'], 'EPSG:32617')

        # Recuperación idéntica en un GET posterior (otra "sesión").
        res2 = self.client.get(self._url(task))
        self.assertEqual(len(res2.data['points']), 3)
        self.assertEqual(res2.data['state'], 'previewing')

    def test_put_state_use_scale_default_and_persistence(self):
        """T049 — use_scale por defecto True; se persiste y se conserva si se omite en llamadas
        posteriores (FR-018/FR-020)."""
        task = self._task(self._project())
        self.client.login(username="testuser", password="test1234")

        # Sin use_scale en el body → default True.
        res = self.client.put(self._url(task), {'points': POINTS_OK}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['transform']['use_scale'])
        scale_with = res.data['transform']['scale']

        # use_scale=False → transformación rígida (scale exactamente 1.0), y distinta de la anterior.
        res2 = self.client.put(self._url(task), {'points': POINTS_OK, 'use_scale': False}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertFalse(res2.data['transform']['use_scale'])
        self.assertEqual(res2.data['transform']['scale'], 1.0)
        self.assertNotEqual(scale_with, 1.0)

        # Se omite use_scale en la siguiente llamada → se conserva el último persistido (False).
        res3 = self.client.put(self._url(task), {'points': POINTS_OK}, format='json')
        self.assertFalse(res3.data['transform']['use_scale'])

        # GET refleja el mismo valor persistido.
        res4 = self.client.get(self._url(task))
        self.assertFalse(res4.data['transform']['use_scale'])

    def test_apply_uses_requested_use_scale(self):
        """T049 — POST apply acepta use_scale y lo refleja en la transformación persistida."""
        task = self._task(self._project())
        self.client.login(username="testuser", password="test1234")
        res = self.client.post(self._url(task, "apply"), {'points': POINTS_OK, 'use_scale': False}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        state_res = self.client.get(self._url(task))
        self.assertFalse(state_res.data['transform']['use_scale'])
        self.assertEqual(state_res.data['transform']['scale'], 1.0)

    def test_put_state_requires_change_project(self):
        project = self._project()
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        task = self._task(project)
        self.client.login(username="testuser2", password="test1234")
        res = self.client.put(self._url(task), {'points': POINTS_OK}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # --- US2: aplicar (FR-014, FR-015) ---------------------------------------

    def test_apply_requires_change_project(self):
        project = self._project()
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        task = self._task(project)
        self.client.login(username="testuser2", password="test1234")
        res = self.client.post(self._url(task, "apply"), {'points': POINTS_OK}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_apply_insufficient_points(self):
        task = self._task(self._project())
        self.client.login(username="testuser", password="test1234")
        res = self.client.post(self._url(task, "apply"), {'points': []}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_apply_degenerate_points(self):
        task = self._task(self._project())
        self.client.login(username="testuser", password="test1234")
        res = self.client.post(self._url(task, "apply"), {'points': POINTS_DEGENERATE}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # --- US3: revertir (FR-011, FR-014) --------------------------------------

    def test_revert_requires_change_project(self):
        project = self._project()
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        task = self._task(project)
        self.client.login(username="testuser2", password="test1234")
        res = self.client.post(self._url(task, "revert"))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_revert_sets_state(self):
        task = self._task(self._project())
        self.client.login(username="testuser", password="test1234")
        self.client.put(self._url(task), {'points': POINTS_OK}, format='json')
        res = self.client.post(self._url(task, "revert"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['state'], 'reverted')
        res2 = self.client.get(self._url(task))
        self.assertEqual(res2.data['state'], 'reverted')

    def test_pipeline_self_contained_under_eval_async(self):
        """El worker reejecuta el source en un namespace vacío (app/plugins/worker.py:
        eval_async). Verifica que run_correction_pipeline es self-contained: sin imports
        relativos ni referencias a globals del módulo (regresión del bug de 'apply')."""
        import inspect
        from . import corrections, store

        tmp = tempfile.mkdtemp(prefix="realign_worker_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        src = os.path.join(tmp, "orthophoto.tif")
        _make_synthetic_raster(src)
        out_dir = os.path.join(tmp, "out")

        task_id = "eval-model-task"
        T = {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 100.0, 'ty': -50.0}
        products = [{'type': 'orthophoto', 'src': src}]

        # El pipeline solo publica su resultado si el documento sigue en el 'applying' que dejó
        # el request al lanzarlo; se siembra igual que en producción.
        store.set_state(task_id, {'state': 'applying'})

        # Ejecutar tal cual lo hace el worker: source → compile → eval en ns vacío.
        source = inspect.getsource(corrections.run_correction_pipeline)
        ns = {}
        exec(compile(source, 'file', 'exec'), ns, ns)
        result = ns['run_correction_pipeline'](task_id, products, out_dir, T, None)

        self.assertIn('orthophoto', result['corrected'])
        self.assertTrue(os.path.isfile(os.path.join(out_dir, 'orthophoto.tif')))
        st = store.get_state(task_id)
        self.assertEqual(st['state'], 'applied')
        self.assertIn('orthophoto', st['corrected_paths'])

    def test_tilejson_of_corrected_product(self):
        """El tilejson del corregido debe responder 200 con bounds en EPSG:4326.
        (Regresión: usaba COGReader.crs, inexistente en rio-tiler 2.1 → 500 → el frontend
        nunca cambiaba de capa y 'se veía igual')."""
        from . import corrections

        task = self._task(self._project())
        out_dir = contract.corrected_dir(task.id)
        self.addCleanup(shutil.rmtree, out_dir, ignore_errors=True)
        os.makedirs(out_dir, exist_ok=True)
        tmp_src = os.path.join(out_dir, '_src.tif')
        _make_synthetic_raster(tmp_src, bands=3)
        corrections.apply_similarity_to_raster(
            tmp_src, os.path.join(out_dir, 'orthophoto.tif'),
            {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 0.0, 'ty': 0.0}, 'near')

        self.client.login(username="testuser", password="test1234")
        res = self.client.get(self._url(task, "tilejson/orthophoto"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['bounds']), 4)
        self.assertTrue(all(isinstance(v, (int, float)) for v in res.data['bounds']))
        self.assertTrue(res.data['tiles'][0].endswith('{z}/{x}/{y}.png'))

        # Esquema del core (Map.jsx TILESIZE=512): la capa pide z+1 en la URL con size=512 y el
        # tiler compensa restando 1 (regresión: se ignoraba size → 404 masivo → ortofoto invisible).
        import math
        w, s, e, n = res.data['bounds']
        lat, lng, zoom = (s + n) / 2.0, (w + e) / 2.0, 16
        ntiles = 2 ** zoom
        tx = int((lng + 180.0) / 360.0 * ntiles)
        lr = math.radians(lat)
        ty = int((1.0 - math.log(math.tan(lr) + 1.0 / math.cos(lr)) / math.pi) / 2.0 * ntiles)
        base = self._url(task, "tiles/orthophoto/{}/{}/{}.png")
        r256 = self.client.get(base.format(zoom, tx, ty))
        self.assertEqual(r256.status_code, status.HTTP_200_OK)
        # Con size=512, el mismo tile se pide con z+1 y las MISMAS coordenadas de grilla z.
        r512 = self.client.get(base.format(zoom + 1, tx, ty) + "?size=512")
        self.assertEqual(r512.status_code, status.HTTP_200_OK)
        self.assertEqual(r512['Content-Type'], 'image/png')

    def test_tiles_follow_the_path_recorded_when_applying(self):
        """Los corregidos generados antes de `realign_data` siguen en la carpeta antigua y el
        estado registra esa ruta. (Regresión: el estado decía 'aplicado' —el archivo existía—
        pero los tiles calculaban la ruta nueva y respondían 404, dejando la ortofoto sin mover)."""
        from . import corrections

        task = self._task(self._project())
        legacy_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, legacy_dir, ignore_errors=True)
        tmp_src = os.path.join(legacy_dir, '_src.tif')
        _make_synthetic_raster(tmp_src, bands=3)
        legacy_path = os.path.join(legacy_dir, 'orthophoto.tif')
        corrections.apply_similarity_to_raster(
            tmp_src, legacy_path, {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 0.0, 'ty': 0.0}, 'near')
        store.set_state(str(task.id), {'state': 'applied', 'corrected_paths': {'orthophoto': legacy_path}})

        self.client.login(username="testuser", password="test1234")
        self.assertTrue(self.client.get(self._url(task, "state")).data['corrected_available'])
        res = self.client.get(self._url(task, "tilejson/orthophoto"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Revertir borra el corregido registrado aunque no esté en la carpeta actual.
        self.client.post(self._url(task, "revert"))
        self.assertFalse(os.path.isfile(legacy_path))

    def test_dsm_tile_honors_color_map_and_rescale(self):
        """El tile de dsm/dtm debe usar el color_map/rescale de la URL (los que el core
        adjunta a la capa original: viridis + min/max reales), no el gris fijo anterior.
        (Regresión: se ignoraban esos parámetros y el DSM/DTM corregido se veía plano/gris
        en vez de igual al original)."""
        from . import corrections

        task = self._task(self._project())
        out_dir = contract.corrected_dir(task.id)
        self.addCleanup(shutil.rmtree, out_dir, ignore_errors=True)
        os.makedirs(out_dir, exist_ok=True)
        tmp_src = os.path.join(out_dir, '_dsm_src.tif')
        _make_synthetic_raster(tmp_src, bands=1)
        corrections.apply_similarity_to_raster(
            tmp_src, os.path.join(out_dir, 'dsm.tif'),
            {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 0.0, 'ty': 0.0}, 'near')

        self.client.login(username="testuser", password="test1234")
        res = self.client.get(self._url(task, "tilejson/dsm"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        import math
        w, s, e, n = res.data['bounds']
        lat, lng, zoom = (s + n) / 2.0, (w + e) / 2.0, 16
        ntiles = 2 ** zoom
        tx = int((lng + 180.0) / 360.0 * ntiles)
        lr = math.radians(lat)
        ty = int((1.0 - math.log(math.tan(lr) + 1.0 / math.cos(lr)) / math.pi) / 2.0 * ntiles)
        base = self._url(task, "tiles/dsm/{}/{}/{}.png".format(zoom, tx, ty))

        # Sin parámetros: cae al comportamiento previo (gray, 0-1000) — no debe romperse.
        r_default = self.client.get(base)
        self.assertEqual(r_default.status_code, status.HTTP_200_OK)
        self.assertEqual(r_default['Content-Type'], 'image/png')

        # Con los parámetros que el core adjunta a la capa original: deben honrarse.
        r_viridis = self.client.get(base + "?color_map=viridis&rescale=0,255")
        self.assertEqual(r_viridis.status_code, status.HTTP_200_OK)
        self.assertEqual(r_viridis['Content-Type'], 'image/png')
        # El color_map cambia la salida (gray vs viridis no pueden ser idénticos para data no nula).
        self.assertNotEqual(r_default.content, r_viridis.content)

        # color_map inválido → 400, no 500.
        r_bad = self.client.get(base + "?color_map=not_a_real_colormap")
        self.assertEqual(r_bad.status_code, status.HTTP_400_BAD_REQUEST)


class RealignTransformTest(unittest.TestCase):
    """Paridad de transform.fit_similarity con los mismos casos que similarity.js (T022)."""

    def test_translation_only(self):
        r = transform.fit_similarity([(0, 0, 10, 5)])
        self.assertAlmostEqual(r['scale'], 1.0)
        self.assertAlmostEqual(r['rotation_deg'], 0.0)
        self.assertAlmostEqual(r['tx'], 10.0)
        self.assertAlmostEqual(r['ty'], 5.0)
        self.assertAlmostEqual(r['rmse'], 0.0)

    def test_known_similarity_recovered(self):
        import math
        T = dict(scale=2.0, cos=math.cos(math.pi / 2), sin=math.sin(math.pi / 2), tx=100.0, ty=50.0)
        srcs = [(0, 0), (10, 0), (0, 10), (7, 3), (-5, 8)]
        pairs = []
        for x, y in srcs:
            qx, qy = transform.apply_similarity(T, x, y)
            pairs.append((x, y, qx, qy))
        r = transform.fit_similarity(pairs)
        self.assertAlmostEqual(r['scale'], 2.0, places=6)
        self.assertAlmostEqual(r['rotation_deg'], 90.0, places=6)
        self.assertAlmostEqual(r['tx'], 100.0, places=5)
        self.assertAlmostEqual(r['ty'], 50.0, places=5)
        self.assertLess(r['rmse'], 1e-6)

    def test_degenerate_coincident_sources(self):
        r = transform.fit_similarity([(0, 0, 1, 1), (0, 0, 2, 2)])
        self.assertTrue(r['degenerate'])
        self.assertFalse(r['ok'])

    def test_rigid_mode_fixes_scale_to_one(self):
        """T048 — use_scale=False: escala fija en 1.0, misma rotación que con escala (D9,
        el numerador a/b no depende de la normalización), traslación distinta y RMSE real
        (forzar escala=1 sobre datos con escala verdadera 2.0 no es un ajuste perfecto)."""
        import math
        T = dict(scale=2.0, cos=math.cos(math.pi / 2), sin=math.sin(math.pi / 2), tx=100.0, ty=50.0)
        srcs = [(0, 0), (10, 0), (0, 10), (7, 3), (-5, 8)]
        pairs = []
        for x, y in srcs:
            qx, qy = transform.apply_similarity(T, x, y)
            pairs.append((x, y, qx, qy))

        r_scale = transform.fit_similarity(pairs, use_scale=True)
        r_rigid = transform.fit_similarity(pairs, use_scale=False)

        self.assertAlmostEqual(r_scale['scale'], 2.0, places=6)
        self.assertLess(r_scale['rmse'], 1e-6)

        self.assertAlmostEqual(r_rigid['scale'], 1.0, places=9)
        self.assertAlmostEqual(r_rigid['rotation_deg'], r_scale['rotation_deg'], places=6)
        self.assertAlmostEqual(r_rigid['tx'], 95.8, places=5)
        self.assertAlmostEqual(r_rigid['ty'], 52.4, places=5)
        self.assertGreater(r_rigid['rmse'], 1.0)

    def test_rigid_mode_single_point_unaffected(self):
        r = transform.fit_similarity([(0, 0, 10, 5)], use_scale=False)
        self.assertAlmostEqual(r['scale'], 1.0)
        self.assertAlmostEqual(r['rotation_deg'], 0.0)
        self.assertAlmostEqual(r['tx'], 10.0)
        self.assertAlmostEqual(r['ty'], 5.0)

    def test_rigid_mode_degenerate_coincident_sources(self):
        r = transform.fit_similarity([(0, 0, 1, 1), (0, 0, 2, 2)], use_scale=False)
        self.assertTrue(r['degenerate'])
        self.assertFalse(r['ok'])


def _make_synthetic_raster(path, bands=1):
    from osgeo import gdal, osr
    size = 64
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, size, size, bands, gdal.GDT_Byte)
    ds.SetGeoTransform((500000.0, 1.0, 0, 5000000.0, 0, -1.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    ds.SetProjection(srs.ExportToWkt())
    import numpy as np
    for b in range(1, bands + 1):
        ds.GetRasterBand(b).WriteArray(np.full((size, size), 128, dtype=np.uint8))
    ds.FlushCache()
    ds = None


def _make_synthetic_pointcloud(path, count=500,
                                bounds=((500000.0, 500050.0), (5000000.0, 5000050.0), (100.0, 110.0)),
                                scale=0.001, epsg=32633):
    """Genera un LAZ sintético con `pdal`/`readers.faux` (research.md D10) — sin binarios
    versionados en el repo."""
    import json
    import subprocess

    bx, by, bz = bounds
    pipeline = {
        "pipeline": [
            {"type": "readers.faux", "mode": "random", "count": count,
             "bounds": "([{},{}],[{},{}],[{},{}])".format(bx[0], bx[1], by[0], by[1], bz[0], bz[1])},
            {"type": "writers.las", "filename": path, "compression": "LASZIP",
             "a_srs": "EPSG:{}".format(epsg),
             "scale_x": scale, "scale_y": scale, "scale_z": scale,
             "offset_x": (bx[0] + bx[1]) / 2, "offset_y": (by[0] + by[1]) / 2, "offset_z": (bz[0] + bz[1]) / 2},
        ]
    }
    pipeline_path = path + ".pipeline.json"
    with open(pipeline_path, 'w') as f:
        json.dump(pipeline, f)
    try:
        subprocess.run(['pdal', 'pipeline', pipeline_path], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    finally:
        if os.path.isfile(pipeline_path):
            os.remove(pipeline_path)


def _export_xyz(las_path):
    """Exporta X,Y,Z con precisión completa (no la del JSON de `pdal info`) para comparar
    resultados punto a punto en los tests (D2/D3)."""
    import csv
    import json
    import subprocess

    csv_path = las_path + ".xyz.csv"
    pipeline = {"pipeline": [
        {"type": "readers.las", "filename": las_path},
        {"type": "writers.text", "filename": csv_path, "order": "X,Y,Z",
         "keep_unspecified": "false", "precision": 9},
    ]}
    pipeline_path = csv_path + ".json"
    with open(pipeline_path, 'w') as f:
        json.dump(pipeline, f)
    try:
        subprocess.run(['pdal', 'pipeline', pipeline_path], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with open(csv_path) as f:
            rows = [(float(r['X']), float(r['Y']), float(r['Z'])) for r in csv.DictReader(f)]
    finally:
        for p in (pipeline_path, csv_path):
            if os.path.isfile(p):
                os.remove(p)
    return rows


class RealignPointCloudMathTest(unittest.TestCase):
    """Matriz, offsets seguros y huella de la transformación (T009, research.md D2/D3/D8)."""

    def test_build_transformation_matrix_z_identity_and_ignores_scale(self):
        T = {'cos': 0.8660254037844387, 'sin': 0.5, 'tx': 10.0, 'ty': -5.0, 'scale': 2.0}
        values = [float(v) for v in pointcloud.build_transformation_matrix(T).split()]
        self.assertEqual(len(values), 16)
        self.assertEqual(values[8:12], [0.0, 0.0, 1.0, 0.0])   # fila Z: identidad (D2, FR-003)
        self.assertEqual(values[12:16], [0.0, 0.0, 0.0, 1.0])  # fila homogénea
        self.assertAlmostEqual(values[0], T['cos'])
        self.assertAlmostEqual(values[1], -T['sin'])
        self.assertAlmostEqual(values[3], T['tx'])
        self.assertAlmostEqual(values[4], T['sin'])
        self.assertAlmostEqual(values[5], T['cos'])
        self.assertAlmostEqual(values[7], T['ty'])

    def test_compute_safe_offsets_centers_on_transformed_bbox(self):
        bounds = {'minx': 0.0, 'maxx': 100.0, 'miny': 0.0, 'maxy': 100.0}
        T = {'cos': 1.0, 'sin': 0.0, 'tx': 1000.0, 'ty': -1000.0}
        ox, oy = pointcloud.compute_safe_offsets(bounds, T, 0.001, 0.001)
        # Sin rotación, las 4 esquinas transformadas caen en [1000,1100]x[-1000,-900];
        # el centro esperado es (1050, -950), no el offset original heredado (D3).
        self.assertEqual(ox, 1050)
        self.assertEqual(oy, -950)

    def test_compute_safe_offsets_rejects_int32_overflow(self):
        # bbox de 600 km de ancho con precisión de 0.1 mm: ni el offset óptimo (centrado)
        # evita que las esquinas excedan el rango representable por un int32 (D3).
        bounds = {'minx': 0.0, 'maxx': 600000.0, 'miny': 0.0, 'maxy': 10.0}
        T = {'cos': 1.0, 'sin': 0.0, 'tx': 0.0, 'ty': 0.0}
        with self.assertRaises(pointcloud.PointCloudTransformError):
            pointcloud.compute_safe_offsets(bounds, T, 0.0001, 0.0001)

    def test_fingerprint_matches_identical_transform(self):
        T = {'cos': 0.999, 'sin': 0.01, 'tx': 100.1234, 'ty': -50.5678, 'use_scale': False, 'n_points': 3}
        self.assertTrue(pointcloud.fingerprint_matches(
            pointcloud.compute_fingerprint(T), pointcloud.compute_fingerprint(dict(T))))

    def test_fingerprint_mismatch_on_translation_change(self):
        T1 = {'cos': 0.999, 'sin': 0.01, 'tx': 100.0, 'ty': -50.0, 'use_scale': False, 'n_points': 3}
        T2 = dict(T1, tx=105.0)
        self.assertFalse(pointcloud.fingerprint_matches(
            pointcloud.compute_fingerprint(T1), pointcloud.compute_fingerprint(T2)))

    def test_fingerprint_mismatch_on_scale_mode_change(self):
        """Reaplicar con escala habilitada invalida una nube generada en modo rígido (US2-AS3)."""
        T1 = {'cos': 1.0, 'sin': 0.0, 'tx': 0.0, 'ty': 0.0, 'use_scale': False, 'n_points': 2}
        T2 = dict(T1, use_scale=True)
        self.assertFalse(pointcloud.fingerprint_matches(
            pointcloud.compute_fingerprint(T1), pointcloud.compute_fingerprint(T2)))

    def test_fingerprint_none_never_matches(self):
        self.assertFalse(pointcloud.fingerprint_matches(None, {'cos': 1.0}))
        self.assertFalse(pointcloud.fingerprint_matches({'cos': 1.0}, None))


class RealignPointCloudPipelineTest(unittest.TestCase):
    """Pipeline PDAL end-to-end sobre un LAZ sintético (T010, research.md D2/D3/D4/D8)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="realign_pc_")
        self.src = os.path.join(self.tmp, "georeferenced_model.laz")
        _make_synthetic_pointcloud(self.src)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_correction_preserves_point_count_z_and_header(self):
        out_dir = os.path.join(self.tmp, "out")
        T = {'cos': 0.9998476951563913, 'sin': 0.01745240643728351, 'tx': 12.3, 'ty': -7.8,
             'use_scale': False, 'n_points': 3}

        orig_summary = pointcloud.read_las_summary(self.src)
        orig_meta = pointcloud.read_las_metadata(self.src)

        # El pipeline solo publica si el estado sigue siendo el 'running' que dejó el request
        # (su ausencia es justo lo que deja un "Descartar"); se siembra como en producción.
        store.set_pointcloud_state("test-task-pc1", {'status': 'running'})
        result = pointcloud.run_pointcloud_correction("test-task-pc1", self.src, out_dir, T)
        self.assertEqual(result.get('status'), 'ready', result)

        out_path = os.path.join(out_dir, 'pointcloud.laz')
        self.assertTrue(os.path.isfile(out_path))
        self.assertFalse(os.path.isfile(os.path.join(out_dir, 'pointcloud.tmp.laz')))

        new_summary = pointcloud.read_las_summary(out_path)
        new_meta = pointcloud.read_las_metadata(out_path)

        self.assertEqual(new_summary['num_points'], orig_summary['num_points'])
        # Cabecera preservada: escala/offset_z/formato/versión/SRS (D3, FR-008).
        self.assertEqual(new_meta['scale_x'], orig_meta['scale_x'])
        self.assertEqual(new_meta['scale_y'], orig_meta['scale_y'])
        self.assertEqual(new_meta['scale_z'], orig_meta['scale_z'])
        self.assertEqual(new_meta['offset_z'], orig_meta['offset_z'])
        self.assertEqual(new_meta['dataformat_id'], orig_meta['dataformat_id'])
        self.assertEqual(new_meta['minor_version'], orig_meta['minor_version'])
        self.assertIn('32633', new_meta.get('spatialreference', ''))

        # Z intacta y XY coherente con lo esperado, punto a punto — no basta con comparar
        # bounds de `pdal info --summary`, que redondea la salida JSON con precisión variable
        # (mismo valor real puede imprimirse con distinta cantidad de decimales). Se exporta a
        # texto con precisión completa y se compara cada punto (D2/D3, FR-003, SC-002).
        src_rows = _export_xyz(self.src)
        out_rows = _export_xyz(out_path)
        self.assertEqual(len(src_rows), len(out_rows))
        cos, sin, tx, ty = T['cos'], T['sin'], T['tx'], T['ty']
        max_dz = 0.0
        max_dxy = 0.0
        for (sx, sy, sz), (ox, oy, oz) in zip(src_rows, out_rows):
            max_dz = max(max_dz, abs(sz - oz))
            ex = cos * sx - sin * sy + tx
            ey = sin * sx + cos * sy + ty
            max_dxy = max(max_dxy, abs(ex - ox), abs(ey - oy))
        self.assertEqual(max_dz, 0.0)
        self.assertLess(max_dxy, orig_meta['scale_x'])  # dentro de un paso de cuantización

        state = store.get_pointcloud_state("test-task-pc1")
        self.assertEqual(state['status'], 'ready')
        self.assertEqual(state['point_count'], orig_summary['num_points'])
        self.assertIsNotNone(state['fingerprint'])

    def test_cancellation_before_launch_reports_canceled_without_files(self):
        out_dir = os.path.join(self.tmp, "out_cancel")
        T = {'cos': 1.0, 'sin': 0.0, 'tx': 0.0, 'ty': 0.0, 'use_scale': False, 'n_points': 1}
        result = pointcloud.run_pointcloud_correction(
            "test-task-cancel", self.src, out_dir, T, should_cancel=lambda: True)
        self.assertEqual(result.get('error'), 'canceled')
        self.assertFalse(os.path.isfile(os.path.join(out_dir, 'pointcloud.tmp.laz')))
        self.assertFalse(os.path.isfile(os.path.join(out_dir, 'pointcloud.laz')))

    def test_self_contained_under_eval_async(self):
        """Mismo patrón que corrections.py: el worker reejecuta el source en un namespace
        vacío (app/plugins/worker.py: eval_async) — sin imports relativos ni globals del
        módulo (regresión del bug de 'apply')."""
        import inspect
        source = inspect.getsource(pointcloud.run_pointcloud_correction)
        ns = {}
        exec(compile(source, 'file', 'exec'), ns, ns)
        out_dir = os.path.join(self.tmp, "out_eval")
        T = {'cos': 1.0, 'sin': 0.0, 'tx': 0.0, 'ty': 0.0, 'use_scale': False, 'n_points': 1}
        store.set_pointcloud_state("eval-pc-task", {'status': 'running'})
        result = ns['run_pointcloud_correction']("eval-pc-task", self.src, out_dir, T)
        self.assertEqual(result.get('status'), 'ready')
        self.assertTrue(os.path.isfile(os.path.join(out_dir, 'pointcloud.laz')))


class RealignPointCloudApiTest(BootTestCase):
    """Contrato de la API de nube de puntos (T011, T017, T018, T023-T025)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _project(self, name="Realign pointcloud API test project"):
        owner = User.objects.get(username="testuser")
        return Project.objects.create(owner=owner, name=name)

    def _task(self, project, **kwargs):
        defaults = dict(project=project, status=status_codes.COMPLETED,
                        available_assets=["orthophoto.tif", POINTCLOUD_ASSET_KEY],
                        orthophoto_extent=TEST_EXTENT, epsg=32617)
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def _url(self, task, suffix="pointcloud"):
        return "/api/plugins/realign/task/{}/realign/{}".format(task.id, suffix)

    def _seed_assets(self, task):
        ortho_path = task.get_asset_download_path('orthophoto.tif')
        os.makedirs(os.path.dirname(ortho_path), exist_ok=True)
        _make_synthetic_raster(ortho_path)
        laz_path = task.get_asset_download_path(POINTCLOUD_ASSET_KEY)
        os.makedirs(os.path.dirname(laz_path), exist_ok=True)
        _make_synthetic_pointcloud(laz_path)
        self.addCleanup(shutil.rmtree, task.task_path(), ignore_errors=True)

    def _apply(self, task, use_scale):
        self.client.login(username="testuser", password="test1234")
        res = self.client.post("/api/plugins/realign/task/{}/realign/apply".format(task.id),
                               {'points': POINTS_OK, 'use_scale': use_scale}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        # CELERY_TASK_ALWAYS_EAGER=True en tests (webodm/settings.py): la corrección de
        # rásteres ya corrió de forma síncrona dentro del POST anterior.
        state = self.client.get("/api/plugins/realign/task/{}/realign/state".format(task.id))
        self.assertEqual(state.data['state'], 'applied', state.data)

    # --- T017: las cuatro causas de inelegibilidad ---------------------------

    def test_post_pointcloud_rejects_task_without_pointcloud_asset(self):
        task = self._task(self._project(), available_assets=["orthophoto.tif"])
        self._seed_assets(task)  # solo para tener orthophoto real; el asset de nube no está declarado
        self._apply(task, use_scale=False)
        res = self.client.post(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['reason'], 'no_pointcloud')

    def test_post_pointcloud_rejects_when_not_applied(self):
        task = self._task(self._project())
        self._seed_assets(task)
        self.client.login(username="testuser", password="test1234")
        res = self.client.post(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['reason'], 'not_applied')

    def test_post_pointcloud_rejects_when_scale_enabled(self):
        task = self._task(self._project())
        self._seed_assets(task)
        self._apply(task, use_scale=True)
        res = self.client.post(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['reason'], 'scale_enabled')

    def test_post_pointcloud_rejects_when_already_running(self):
        task = self._task(self._project())
        self._seed_assets(task)
        self._apply(task, use_scale=False)
        store.set_pointcloud_state(task.id, {'status': 'running', 'celery_task_id': 'fake-id'})
        res = self.client.post(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['reason'], 'already_running')

    # --- T011: happy path ------------------------------------------------------

    def test_post_pointcloud_happy_path_completes_and_downloads(self):
        task = self._task(self._project())
        self._seed_assets(task)
        self._apply(task, use_scale=False)

        res = self.client.post(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertIn('celery_task_id', res.data)

        # El sondeo real de progreso pasa por el endpoint genérico del framework
        # (contracts/api.md) — se confirma que responde, pero no se afirma `ready` aquí:
        # `TestSafeAsyncResult` en tests es `MockAsyncResult` (worker/celery.py), que solo ve
        # resultados registrados explícitamente vía `.set()`/`store_result()`; `eval_async`
        # (el mecanismo detrás de `run_function_async`, usado por todo el framework de
        # plugins) nunca lo hace, así que ningún test de este repo verifica ese endpoint tras
        # un pipeline de plugin. La finalización real (CELERY_TASK_ALWAYS_EAGER=True en tests
        # ya ejecutó el pipeline de forma síncrona dentro del POST anterior) se verifica por
        # el canal autoritativo: el propio estado persistido del plugin.
        check = self.client.get('/api/workers/check/{}'.format(res.data['celery_task_id']))
        self.assertEqual(check.status_code, status.HTTP_200_OK)

        state = self.client.get("/api/plugins/realign/task/{}/realign/state".format(task.id))
        pc = state.data['pointcloud']
        self.assertEqual(pc['status'], 'ready')
        self.assertTrue(pc['available'])
        self.assertFalse(pc['stale'])
        self.assertGreater(pc['point_count'], 0)

        download = self.client.get(self._url(task, "pointcloud/download"))
        self.assertEqual(download.status_code, status.HTTP_200_OK)
        self.assertGreater(len(b"".join(download.streaming_content)) if download.streaming else len(download.content), 0)

    def test_post_pointcloud_requires_change_project(self):
        project = self._project()
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        task = self._task(project)
        self._seed_assets(task)
        self._apply(task, use_scale=False)
        self.client.logout()
        self.client.login(username="testuser2", password="test1234")
        res = self.client.post(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # --- T018: obsolescencia por cambio de modo de escala (US2-AS3) ----------

    def test_pointcloud_becomes_stale_after_reapplying_with_scale(self):
        task = self._task(self._project())
        self._seed_assets(task)
        self._apply(task, use_scale=False)
        res = self.client.post(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        state = self.client.get("/api/plugins/realign/task/{}/realign/state".format(task.id))
        self.assertTrue(state.data['pointcloud']['available'])

        # Reaplicar con escala habilitada invalida la nube ya generada.
        self._apply(task, use_scale=True)
        state2 = self.client.get("/api/plugins/realign/task/{}/realign/state".format(task.id))
        pc2 = state2.data['pointcloud']
        self.assertEqual(pc2['status'], 'ready')  # el archivo sigue registrado...
        self.assertTrue(pc2['stale'])             # ...pero ya no corresponde al ajuste vigente
        self.assertFalse(pc2['available'])
        self.assertEqual(pc2['ineligible_reason'], 'scale_enabled')

    # --- T023: cancelar / descartar -------------------------------------------

    def test_delete_pointcloud_cancels_running_and_cleans_tmp(self):

        task = self._task(self._project())
        self._seed_assets(task)
        self._apply(task, use_scale=False)

        out_dir = contract.corrected_dir(task.id)
        os.makedirs(out_dir, exist_ok=True)
        tmp_path = os.path.join(out_dir, 'pointcloud.tmp.laz')
        with open(tmp_path, 'wb') as f:
            f.write(b'not a real laz, just simulating a generation in progress')
        store.set_pointcloud_state(task.id, {'status': 'running', 'celery_task_id': 'fake-id'})

        res = self.client.delete(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'absent')
        self.assertFalse(os.path.isfile(tmp_path))
        self.assertIsNone(store.get_pointcloud_state(task.id))

    def test_delete_pointcloud_requires_change_project(self):
        project = self._project()
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        task = self._task(project)
        self.client.login(username="testuser2", password="test1234")
        res = self.client.delete(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # --- T024: Revertir descarta la nube --------------------------------------

    def test_revert_discards_pointcloud(self):
        task = self._task(self._project())
        self._seed_assets(task)
        self._apply(task, use_scale=False)
        res = self.client.post(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        pc = store.get_pointcloud_state(task.id)
        self.assertEqual(pc['status'], 'ready')
        self.assertTrue(os.path.isfile(pc['path']))
        laz_path = pc['path']

        self.client.post("/api/plugins/realign/task/{}/realign/revert".format(task.id))

        self.assertIsNone(store.get_pointcloud_state(task.id))
        self.assertFalse(os.path.isfile(laz_path))

    # --- T025: reanudar el sondeo tras recargar -------------------------------

    def test_state_exposes_running_celery_task_id_for_resume(self):
        task = self._task(self._project())
        self._seed_assets(task)
        self._apply(task, use_scale=False)
        store.set_pointcloud_state(task.id, {'status': 'running', 'celery_task_id': 'resume-me'})

        res = self.client.get("/api/plugins/realign/task/{}/realign/state".format(task.id))
        self.assertEqual(res.data['pointcloud']['status'], 'running')
        self.assertEqual(res.data['pointcloud']['celery_task_id'], 'resume-me')

    # --- FR-017: sin nube de puntos --------------------------------------------

    def test_state_reports_no_pointcloud_reason_when_absent(self):
        task = self._task(self._project(), available_assets=["orthophoto.tif"])
        self.client.login(username="testuser", password="test1234")
        res = self.client.get("/api/plugins/realign/task/{}/realign/state".format(task.id))
        pc = res.data['pointcloud']
        self.assertEqual(pc['status'], 'absent')
        self.assertFalse(pc['eligible'])
        self.assertEqual(pc['ineligible_reason'], 'no_pointcloud')


class RealignCorrectionsTest(unittest.TestCase):
    """Pipeline GDAL: aplica una similitud conocida y verifica el COG corregido (T023, FR-009)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="realign_corr_")
        self.src = os.path.join(self.tmp, "orthophoto.tif")
        _make_synthetic_raster(self.src)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_translation_shifts_origin_and_keeps_north_up(self):
        from osgeo import gdal
        orig_gt = gdal.Open(self.src).GetGeoTransform()

        out = os.path.join(self.tmp, "orthophoto_corr.tif")
        T = {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 100.0, 'ty': -50.0}
        corrections.apply_similarity_to_raster(self.src, out, T, resampling='near')

        self.assertTrue(os.path.isfile(out))
        out_gt = gdal.Open(out).GetGeoTransform()
        # Origen desplazado por (tx, ty); north-up (sin términos de rotación).
        self.assertAlmostEqual(out_gt[0], orig_gt[0] + 100.0, places=3)
        self.assertAlmostEqual(out_gt[3], orig_gt[3] - 50.0, places=3)
        self.assertAlmostEqual(out_gt[2], 0.0, places=6)
        self.assertAlmostEqual(out_gt[4], 0.0, places=6)

        # El original no cambió (FR-009).
        self.assertEqual(gdal.Open(self.src).GetGeoTransform(), orig_gt)

    def test_compose_geotransform_translation(self):
        gt = (500000.0, 1.0, 0.0, 5000000.0, 0.0, -1.0)
        T = {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 10.0, 'ty': 20.0}
        new_gt = corrections.compose_geotransform(gt, T)
        self.assertAlmostEqual(new_gt[0], 500010.0)
        self.assertAlmostEqual(new_gt[3], 5000020.0)
        self.assertAlmostEqual(new_gt[1], 1.0)
        self.assertAlmostEqual(new_gt[5], -1.0)


# --- Los pipelines de worker frente a decisiones posteriores del usuario ------------------------

class WorkerRespectsLaterUserActionTest(BootTestCase):
    """Ninguno de los dos pipelines es interrumpible a mitad de camino: el de rásteres se lanza
    sin cancelación y el de nube solo consulta `should_cancel` mientras vive el proceso de pdal.
    Como el usuario puede revertir o descartar mientras tanto, el resultado que llega tarde no
    debe pisar lo que él decidió después.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _task(self):
        project = Project.objects.create(owner=User.objects.get(username="testuser"),
                                         name="realign worker race")
        task = Task.objects.create(project=project, status=status_codes.COMPLETED,
                                   available_assets=["orthophoto.tif"],
                                   orthophoto_extent=TEST_EXTENT, epsg=32617)
        ortho = task.get_asset_download_path('orthophoto.tif')
        os.makedirs(os.path.dirname(ortho), exist_ok=True)
        _make_synthetic_raster(ortho)
        self.addCleanup(shutil.rmtree, task.task_path(), ignore_errors=True)
        return task

    def _out_dir(self, task):
        from .api import _out_dir
        d = _out_dir(str(task.id))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def _products(self, task):
        return [{'type': 'orthophoto',
                 'src': os.path.abspath(task.get_asset_download_path('orthophoto.tif'))}]

    IDENTITY = {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 1.0, 'ty': 1.0}

    def test_revert_during_apply_is_not_undone_by_the_worker(self):
        task = self._task()
        self.client.login(username="testuser", password="test1234")
        url = "/api/plugins/realign/task/{}/realign".format(task.id)

        self.client.put(url + "/state", {'points': POINTS_OK, 'use_scale': False}, format='json')
        state = store.get_state(str(task.id))
        state['state'] = 'applying'
        store.set_state(str(task.id), state)

        # El usuario revierte mientras el pipeline sigue trabajando...
        self.assertEqual(self.client.post(url + "/revert").status_code, status.HTTP_200_OK)
        # ...y el worker termina después.
        out_dir = self._out_dir(task)
        result = corrections.run_correction_pipeline(
            str(task.id), self._products(task), out_dir, self.IDENTITY, None)

        self.assertTrue(result.get('discarded'), result)
        final = self.client.get(url + "/state").data
        self.assertEqual(final['state'], 'reverted', 'el worker resucitó lo que el usuario revirtió')
        self.assertFalse(final['corrected_available'])
        self.assertFalse(os.path.isfile(os.path.join(out_dir, 'orthophoto.tif')),
                         'quedó un corregido huérfano tras el revert')

    def test_apply_completing_normally_still_marks_applied(self):
        """La guarda no debe romper el camino feliz."""
        task = self._task()
        self.client.login(username="testuser", password="test1234")
        url = "/api/plugins/realign/task/{}/realign".format(task.id)
        self.client.put(url + "/state", {'points': POINTS_OK, 'use_scale': False}, format='json')
        state = store.get_state(str(task.id))
        state['state'] = 'applying'
        store.set_state(str(task.id), state)

        corrections.run_correction_pipeline(
            str(task.id), self._products(task), self._out_dir(task), self.IDENTITY, None)

        final = self.client.get(url + "/state").data
        self.assertEqual(final['state'], 'applied')
        self.assertTrue(final['corrected_available'])

    def test_failed_apply_reports_error_instead_of_staying_applying(self):
        task = self._task()
        self.client.login(username="testuser", password="test1234")
        url = "/api/plugins/realign/task/{}/realign".format(task.id)
        self.client.put(url + "/state", {'points': POINTS_OK, 'use_scale': False}, format='json')
        state = store.get_state(str(task.id))
        state['state'] = 'applying'
        store.set_state(str(task.id), state)

        broken = [{'type': 'orthophoto', 'src': '/no/existe/orthophoto.tif'}]
        result = corrections.run_correction_pipeline(
            str(task.id), broken, self._out_dir(task), self.IDENTITY, None)

        self.assertIn('error', result)
        final = self.client.get(url + "/state").data
        self.assertEqual(final['state'], 'error', 'el estado se quedó colgado en applying')
        self.assertTrue(final['error'], 'el motivo del fallo debe llegar al panel')
        self.assertFalse(final['corrected_available'])

    def test_discarded_pointcloud_is_not_republished_by_the_worker(self):
        """Mismo criterio en la nube: descartar mientras corre gana sobre el resultado tardío."""
        task = self._task()
        store.set_pointcloud_state(str(task.id), {'status': 'absent'})  # como tras un DELETE
        out_dir = self._out_dir(task)
        os.makedirs(out_dir, exist_ok=True)
        final_path = os.path.join(out_dir, 'pointcloud.laz')

        result = pointcloud.run_pointcloud_correction(
            str(task.id), '/no/existe.laz', out_dir,
            {'cos': 1.0, 'sin': 0.0, 'tx': 1.0, 'ty': 1.0, 'use_scale': False}, None)

        self.assertTrue(result.get('discarded'), result)
        self.assertEqual(store.get_pointcloud_state(str(task.id)).get('status'), 'absent',
                         'el worker reescribió un estado que el usuario ya había descartado')
        self.assertFalse(os.path.isfile(final_path))

    def test_cancel_stops_the_pipeline_and_leaves_nothing_behind(self):
        """Cancelar mientras se aplica: el pipeline para en cuanto lo consulta y no publica nada."""
        task = self._task()
        self.client.login(username="testuser", password="test1234")
        url = "/api/plugins/realign/task/{}/realign".format(task.id)
        self.client.put(url + "/state", {'points': POINTS_OK, 'use_scale': False}, format='json')
        state = store.get_state(str(task.id))
        state['state'] = 'applying'
        store.set_state(str(task.id), state)

        out_dir = self._out_dir(task)
        result = corrections.run_correction_pipeline(
            str(task.id), self._products(task), out_dir, self.IDENTITY, None,
            should_cancel=lambda: True)

        self.assertTrue(result.get('canceled'), result)
        self.assertFalse(os.path.isfile(os.path.join(out_dir, 'orthophoto.tif')),
                         'una aplicación cancelada no debe dejar productos a medias')
        self.assertEqual(store.get_state(str(task.id))['state'], 'applying',
                         'el estado lo resuelve el request que canceló, no el pipeline')

    def test_editing_points_aborts_a_running_apply(self):
        """Editar los puntos mientras se aplica también cancela: el trabajo en curso usa un
        ajuste que el usuario acaba de cambiar."""
        task = self._task()
        self.client.login(username="testuser", password="test1234")
        url = "/api/plugins/realign/task/{}/realign".format(task.id)
        self.client.put(url + "/state", {'points': POINTS_OK, 'use_scale': False}, format='json')
        state = store.get_state(str(task.id))
        state.update({'state': 'applying', 'celery_task_id': 'fake-task-id'})
        store.set_state(str(task.id), state)

        aborted = []
        from . import api
        original = api._abort_celery_task
        api._abort_celery_task = lambda tid: aborted.append(tid)
        self.addCleanup(setattr, api, '_abort_celery_task', original)

        res = self.client.put(url + "/state", {'points': POINTS_OK, 'use_scale': False}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(aborted, ['fake-task-id'], 'no se canceló la aplicación en curso')
        self.assertEqual(res.data['state'], 'previewing')

    def test_apply_reports_progress_while_resampling(self):
        """El panel muestra un spinner con el producto y el porcentaje: el dato sale del
        callback de progreso de gdalwarp, no de un contador por producto."""
        task = self._task()
        store.set_state(str(task.id), {'state': 'applying'})
        reports = []

        corrections.run_correction_pipeline(
            str(task.id), self._products(task), self._out_dir(task), self.IDENTITY, None,
            progress_callback=lambda status, progress: reports.append((status, progress)))

        self.assertTrue(reports, 'no se reportó ningún avance')
        self.assertTrue(all('orthophoto' in s for s, _p in reports), reports)
        percentages = [p for _s, p in reports]
        self.assertEqual(percentages, sorted(percentages), 'el avance retrocede: {}'.format(percentages))
        self.assertTrue(all(0 <= p <= 100 for p in percentages), percentages)

    def test_cancel_during_resampling_stops_the_warp(self):
        """Cancelar a mitad del remuestreo (no solo entre productos) aborta el warp en marcha."""
        task = self._task()
        store.set_state(str(task.id), {'state': 'applying'})
        out_dir = self._out_dir(task)

        # Deja pasar la comprobación previa al producto y cancela ya dentro de gdalwarp.
        calls = {'n': 0}

        def cancel_after_first_check():
            calls['n'] += 1
            return calls['n'] > 1

        result = corrections.run_correction_pipeline(
            str(task.id), self._products(task), out_dir, self.IDENTITY, None,
            should_cancel=cancel_after_first_check)

        self.assertTrue(result.get('canceled'), result)
        self.assertGreater(calls['n'], 1, 'la cancelación no llegó a consultarse dentro del warp')
        self.assertFalse(os.path.isfile(os.path.join(out_dir, 'orthophoto.tif')),
                         'un warp abortado no debe dejar el producto a medias')


class RealignContractTest(BootTestCase):
    """Contrato de consumo para otros plugins del fork (`contract.py`, `CONTRACT_VERSION = 1`).

    Lo consume `road` para ofrecer la variante realineada del DEM. Lo que se prueba aquí es que el
    contrato **no miente**: devolver una ruta que ya no existe haría que el consumidor la abriera
    dentro del worker y reventara allí, lejos de donde se podría explicar.
    """

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _task(self):
        project = Project.objects.create(owner=User.objects.get(username="testuser"),
                                         name="Realign contract project")
        return Task.objects.create(project=project, status=status_codes.COMPLETED,
                                   available_assets=["orthophoto.tif", "dsm.tif"],
                                   orthophoto_extent=TEST_EXTENT, dsm_extent=TEST_EXTENT,
                                   epsg=32617)

    def _write(self, name):
        path = os.path.join(self.tmp, name)
        with open(path, 'wb') as f:
            f.write(b'GeoTIFF de prueba')
        return path

    def test_version_is_exposed_through_the_plugin_class(self):
        from .plugin import Plugin
        plugin = Plugin()
        self.assertEqual(plugin.contract_version(), contract.CONTRACT_VERSION)
        self.assertEqual(contract.CONTRACT_VERSION, 1)

    def test_empty_without_any_realignment(self):
        task = self._task()
        self.assertEqual(contract.corrected_rasters(str(task.id)), {})

    def test_empty_while_still_previewing(self):
        task = self._task()
        store.set_state(str(task.id), {'state': 'previewing', 'corrected_paths': {}})
        self.assertEqual(contract.corrected_rasters(str(task.id)), {})

    def test_returns_the_paths_after_applying(self):
        task = self._task()
        paths = {'dsm': self._write('dsm.tif'), 'orthophoto': self._write('orthophoto.tif')}
        store.set_state(str(task.id), {'state': 'applied', 'corrected_paths': paths})

        corrected = contract.corrected_rasters(str(task.id))

        self.assertEqual(sorted(corrected), ['dsm', 'orthophoto'])
        self.assertEqual(corrected['dsm'], paths['dsm'])

    def test_empty_after_reverting(self):
        task = self._task()
        paths = {'dsm': self._write('dsm.tif')}
        store.set_state(str(task.id), {'state': 'applied', 'corrected_paths': paths})
        self.assertEqual(len(contract.corrected_rasters(str(task.id))), 1)

        store.set_state(str(task.id), {'state': 'reverted', 'corrected_paths': {}})
        self.assertEqual(contract.corrected_rasters(str(task.id)), {})

    def test_a_file_missing_from_disk_is_not_offered(self):
        # El estado y el disco son independientes: un borrado manual del directorio de plugins deja
        # el documento intacto, y fiarse solo del estado haría abrir una ruta inexistente.
        task = self._task()
        dsm = self._write('dsm.tif')
        store.set_state(str(task.id), {'state': 'applied',
                                       'corrected_paths': {'dsm': dsm, 'dtm': '/no/existe.tif'}})

        corrected = contract.corrected_rasters(str(task.id))

        self.assertEqual(sorted(corrected), ['dsm'])

    def test_applied_state_without_files_yields_nothing(self):
        task = self._task()
        store.set_state(str(task.id), {'state': 'applied',
                                       'corrected_paths': {'dsm': '/no/existe.tif'}})
        self.assertEqual(contract.corrected_rasters(str(task.id)), {})
