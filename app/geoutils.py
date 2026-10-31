import math
import os
import rasterio.warp
import numpy as np
from rasterio.crs import CRS
from rasterio.warp import transform, transform_bounds
from osgeo import osr, gdal
from functools import lru_cache
osr.DontUseExceptions()

SUPPORTED_UNITS = ["m", "ft", "US survey foot"]
UNIT_TO_M = {
    "m": 1.0,
    "ft": 0.3048,
    "US survey foot": 1200.0 / 3937.0,
}

def get_rtc_offset(task):
    # Relative-to-center coordinates. [0, 0] if not available
    coords_files = [
        task.assets_path("odm_georeferencing", "coords.txt"),
        task.assets_path("odm_georeferencing", "odm_georeferencing_model_geo.txt"),
    ]

    for cf in coords_files:
        if not os.path.isfile(cf):
            continue
        try:
            with open(cf) as f:
                lines = f.read().split("\n")
            if len(lines) >= 2:
                x, y = [float(v) for v in lines[1].split(" ")[:2]]
                return [x, y]
        except (IOError, ValueError, IndexError):
            pass

    return [0, 0]


def polygon_ring(geom):
    if not isinstance(geom, dict) or geom.get('type') != 'Polygon':
        return None
    coords = geom.get('coordinates')
    if not isinstance(coords, list) or len(coords) == 0:
        return None
    ring = coords[0]
    if not isinstance(ring, list) or len(ring) < 4:
        return None
    try:
        return [[float(p[0]), float(p[1])] for p in ring]
    except (TypeError, ValueError, IndexError):
        return None

def polygon_from_ring(ring):
    if len(ring) > 0 and ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    return {'type': 'Polygon', 'coordinates': [ring]}

def segments_intersect(a, b, c, d):
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 0) - (v < 0)
    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    return o1 != o2 and o3 != o4

def polygon_valid(geom):
    ring = polygon_ring(geom)
    if ring is None:
        return False
    if ring[0] != ring[-1]:
        return False
    for x, y in ring:
        if not math.isfinite(x) or not math.isfinite(y):
            return False
    if polygon_area(geom) <= 0:
        return False

    edges = [(ring[i], ring[i + 1]) for i in range(len(ring) - 1)]
    n = len(edges)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if segments_intersect(edges[i][0], edges[i][1], edges[j][0], edges[j][1]):
                return False
    return True

def polygon_area(geom):
    ring = polygon_ring(geom)
    if ring is None:
        return 0.0
    area = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0

def polygon_bbox(geom):
    ring = polygon_ring(geom)
    if ring is None:
        return None
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (min(xs), min(ys), max(xs), max(ys))

def bbox_intersects(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]

def bbox_to_polygon(bbox):
    w, s, e, n = bbox
    return polygon_from_ring([[w, s], [w, n], [e, n], [e, s], [w, s]])

def polygon_clip_bbox(geom, bbox):
    ring = polygon_ring(geom)
    if ring is None:
        return None
    if ring[0] == ring[-1]:
        ring = ring[:-1]

    minx, miny, maxx, maxy = bbox
    edges = [
        (lambda p: p[0] >= minx, lambda a, b: [minx, a[1] + (b[1] - a[1]) * (minx - a[0]) / (b[0] - a[0])]),
        (lambda p: p[0] <= maxx, lambda a, b: [maxx, a[1] + (b[1] - a[1]) * (maxx - a[0]) / (b[0] - a[0])]),
        (lambda p: p[1] >= miny, lambda a, b: [a[0] + (b[0] - a[0]) * (miny - a[1]) / (b[1] - a[1]), miny]),
        (lambda p: p[1] <= maxy, lambda a, b: [a[0] + (b[0] - a[0]) * (maxy - a[1]) / (b[1] - a[1]), maxy]),
    ]

    for inside, intersect in edges:
        if len(ring) == 0:
            return None
        out = []
        prev = ring[-1]
        for cur in ring:
            if inside(cur):
                if not inside(prev):
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(intersect(prev, cur))
            prev = cur
        ring = out

    if len(ring) < 3:
        return None

    poly = polygon_from_ring(ring)
    if polygon_area(poly) <= 0:
        return None
    return poly

def polygon_to_wkt(geom):
    ring = polygon_ring(geom)
    if ring is None:
        return None
    return "POLYGON ((%s))" % ", ".join("%s %s" % (x, y) for x, y in ring)

def geom_transform_wkt_bbox(geom, dataset, bbox_crs="geographic", wkt_crs="raster"):
    """
    :param geom GeoJSON Polygon dict (EPSG:4326)
    :param dataset rasterio dataset | path to raster
    :param bbox_crs CRS of bbox (geographic --> lat/lon | projected --> north/east | raster --> pixels)
    :param wkt_crs CRS of WKT (raster --> pixels | projected --> north/east)
    :return (WKT, bbox)
    """
    ring = polygon_ring(geom)
    if ring is None:
        raise ValueError("Geometry must be a polygon")
    
    close_ds = False
    if isinstance(dataset, str):
        dataset = rasterio.open(dataset, 'r')
        close_ds = True
    
    try:
        if not dataset.crs:
            raise ValueError("Dataset must have a CRS")

        xs, ys = zip(*ring)
        tx, ty = rasterio.warp.transform(CRS.from_epsg(4326), dataset.crs, xs, ys)
        raster_coords = [dataset.index(x, y, op=np.round) for x, y in zip(tx, ty)]

        if bbox_crs == 'geographic':
            minx = min(xs)
            maxx = max(xs)
            miny = min(ys)
            maxy = max(ys)
        elif bbox_crs == 'projected':
            minx = min(tx)
            maxx = max(tx)
            miny = min(ty)
            maxy = max(ty)
        elif bbox_crs == 'raster':
            coords = np.array(raster_coords)
            px = coords[:, 1]
            py = coords[:, 0]
            minx = px.min()
            maxx = px.max()
            miny = py.min()
            maxy = py.max()
        else:
            raise ValueError("Invalid bbox_crs")

        if wkt_crs == "raster":
            out = ", ".join(f"{x} {y}" for y, x in raster_coords)
        elif wkt_crs == "projected":
            out = ", ".join(f"{x} {y}" for x, y in zip(tx, ty))
        else:
            raise ValueError("Invalid wkt_crs")
        
        wkt = f"POLYGON (({out}))"
        return wkt, (minx, miny, maxx, maxy)
    finally:
        if close_ds:
            dataset.close()

def geom_transform(geom, target_srs):
    ring = polygon_ring(geom)
    if ring is None:
        raise ValueError("Geometry must be a polygon")

    xs, ys = zip(*ring)

    if isinstance(target_srs, int):
        srs = CRS.from_epsg(target_srs)
    elif isinstance(target_srs, str):
        srs = CRS.from_wkt(target_srs)

    tx, ty = rasterio.warp.transform(CRS.from_epsg(4326), srs, xs, ys)
    return list(zip(tx, ty))


def epsg_from_wkt(wkt):
    srs = osr.SpatialReference()
    if srs.ImportFromWkt(wkt) != 0:
        return None
    
    epsg = srs.GetAuthorityCode(None)
    if epsg is not None:
        return None

    # Try to get the 2D component
    if srs.IsCompound():
        if srs.DemoteTo2D() != 0:
            return None

    epsg = srs.GetAuthorityCode(None)
    if epsg is not None:
        return epsg


def get_raster_bounds_geojson(raster_path, target_srs="EPSG:4326"):
    with rasterio.open(raster_path) as src:
        if src.crs is None:
            return None

        left, bottom, right, top = src.bounds
        w, s, e, n = transform_bounds(
            src.crs, 
            target_srs, 
            left, bottom, right, top
        )

        return bbox_to_polygon((w, s, e, n))

@lru_cache(maxsize=1000)
def get_srs_name_units_from_epsg_or_wkt(epsg, wkt):
    if epsg is None and wkt is None:
        return {'name': '', 'units': 'm'}
    
    srs = osr.SpatialReference()

    if epsg is not None:
        if srs.ImportFromEPSG(epsg) != 0:
            return {'name': '', 'units': 'm'}
    
    if wkt is not None:
        if srs.ImportFromWkt(wkt) != 0:
            return {'name': '', 'units': 'm'}

    name = srs.GetAttrValue("PROJCS")
    if name is None:
        name = srs.GetAttrValue("GEOGCS")
    
    if name is None:
        return {'name': '', 'units': 'm'}
    
    if name == "unknown" and wkt is not None:
        try:
            proj = srs.ExportToProj4()
            if proj is not None and proj != "":
                name = proj
        except:
            pass
    
    units = srs.GetAttrValue('UNIT')
    if units is None:
        units = 'm'  # Default to meters
    elif units not in SUPPORTED_UNITS:
        units = 'm' # Unsupported

    return {'name': name, 'units': units}

def get_rasterio_to_meters_factor(rasterio_ds):
    if isinstance(rasterio_ds, str):
        with rasterio.open(rasterio_ds, 'r') as ds:
            return get_rasterio_to_meters_factor(ds)

    units = rasterio_ds.units
    if len(units) >= 1:
        unit = units[0]
        if unit is not None and unit != "" and unit in SUPPORTED_UNITS:
            return UNIT_TO_M.get(unit, 1.0)
    return 1.0

def utm_crs_from_lonlat(lon, lat):
    utm_zone = (int(math.floor((lon + 180.0) / 6.0)) % 60) + 1
    epsg = 32600 + utm_zone if lat >= 0 else 32700 + utm_zone
    return CRS.from_epsg(4326), CRS.from_epsg(epsg)

def utm_transformers_from_lonlat(lon, lat):
    source_srs, target_srs = utm_crs_from_lonlat(lon, lat)

    def ll_to_utm(lon, lat, alt=0.0):
        return [p[0] for p in transform(source_srs, target_srs, [lon], [lat])] + [alt]

    def utm_to_ll(x, y, alt=0.0):
        return [p[0] for p in transform(target_srs, source_srs, [x], [y])] + [alt]

    return ll_to_utm, utm_to_ll