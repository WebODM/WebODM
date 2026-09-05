import json
import logging
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image
from zipstream.ng import ZipStream

from app.geoutils import get_rtc_offset

logger = logging.getLogger('app.logger')

# COLMAP camera model IDs
SIMPLE_PINHOLE = 0
PINHOLE = 1
SIMPLE_RADIAL = 2
RADIAL = 3
OPENCV = 4
OPENCV_FISHEYE = 5
FULL_OPENCV = 6

PLY_TYPES = {
    'int8': '<i1', 'char': '<i1',
    'uint8': '<u1', 'uchar': '<u1',
    'int16': '<i2', 'short': '<i2',
    'uint16': '<u2', 'ushort': '<u2',
    'int32': '<i4', 'int': '<i4',
    'uint32': '<u4', 'uint': '<u4',
    'int64': '<i8',
    'uint64': '<u8',
    'float32': '<f4', 'float': '<f4',
    'float64': '<f8', 'double': '<f8',
}

def normalize_camera_id(cam_id):
    # shots.geojson prefixes camera keys with a version tag (e.g. "v2 ")
    return re.sub(r'^v\d+\s+', '', cam_id.strip())


def compute_target_size(width, height, image_size):
    if image_size <= 0 or max(width, height) <= image_size:
        return width, height
    if width >= height:
        return image_size, max(1, int(round(height * image_size / float(width))))
    else:
        return max(1, int(round(width * image_size / float(height)))), image_size


def map_camera(cam, image_size):
    """
    Map an OpenSfM camera (cameras.json entry) to a COLMAP camera model
    """
    width = int(cam['width'])
    height = int(cam['height'])
    size = float(max(width, height))
    out_width, out_height = compute_target_size(width, height, image_size)
    sx = out_width / float(width)
    sy = out_height / float(height)

    projection = cam.get('projection_type', 'perspective').lower()

    def p(name):
        return float(cam.get(name, 0))

    fx = float(cam.get('focal_x', cam.get('focal', 0))) * size * sx
    fy = float(cam.get('focal_y', cam.get('focal', 0))) * size * sy
    f = (fx + fy) / 2.0
    cx = (width / 2.0 + p('c_x') * size) * sx
    cy = (height / 2.0 + p('c_y') * size) * sy

    if projection == 'perspective':
        model_id, params = RADIAL, [f, cx, cy, p('k1'), p('k2')]
    elif projection == 'brown':
        if p('k3') == 0:
            model_id, params = OPENCV, [fx, fy, cx, cy, p('k1'), p('k2'), p('p1'), p('p2')]
        else:
            model_id, params = FULL_OPENCV, [fx, fy, cx, cy, p('k1'), p('k2'), p('p1'), p('p2'), p('k3'), 0, 0, 0]
    elif projection == 'radial':
        model_id, params = RADIAL, [f, cx, cy, p('k1'), p('k2')]
    elif projection == 'simple_radial':
        model_id, params = SIMPLE_RADIAL, [f, cx, cy, p('k1')]
    elif projection in ('fisheye', 'fisheye_opencv', 'fisheye62', 'fisheye624'):
        # OpenSfM fisheye models use an equidistant projection like COLMAP's
        # OPENCV_FISHEYE; the higher order terms of fisheye62/fisheye624
        # (k5, k6, p1, p2, s0..s3) have no COLMAP equivalent and are dropped
        model_id, params = OPENCV_FISHEYE, [fx, fy, cx, cy, p('k1'), p('k2'), p('k3'), p('k4')]
    elif projection == 'dual':
        # Approximated using the perspective component only
        model_id, params = RADIAL, [f, cx, cy, p('k1'), p('k2')]
    else:
        # spherical/equirectangular have no COLMAP equivalent
        raise ValueError("Camera model '%s' cannot be exported to COLMAP" % projection)

    return {
        'model_id': model_id,
        'width': width,
        'height': height,
        'out_width': out_width,
        'out_height': out_height,
        'params': params
    }


def rodrigues(r):
    """
    Axis-angle rotation vector to (3x3 rotation matrix, [w, x, y, z] quaternion)
    """
    theta = math.sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2])
    if theta < 1e-12:
        return np.eye(3), [1.0, 0.0, 0.0, 0.0]

    axis = np.array(r) / theta
    K = np.array([[0.0, -axis[2], axis[1]],
                  [axis[2], 0.0, -axis[0]],
                  [-axis[1], axis[0], 0.0]])
    R = np.eye(3) + math.sin(theta) * K + (1.0 - math.cos(theta)) * K.dot(K)
    s = math.sin(theta / 2.0)
    q = [math.cos(theta / 2.0), axis[0] * s, axis[1] * s, axis[2] * s]
    return R, q


def write_cameras_bin(cameras):
    buf = [struct.pack('<Q', len(cameras))]
    for c in sorted(cameras.values(), key=lambda c: c['id']):
        buf.append(struct.pack('<iiQQ', c['id'], c['model_id'], c['out_width'], c['out_height']))
        buf.append(struct.pack('<%dd' % len(c['params']), *c['params']))
    return b''.join(buf)


def write_images_bin(shots):
    buf = [struct.pack('<Q', len(shots))]
    for s in shots:
        R, q = rodrigues(s['rotation'])
        t = -R.dot(np.array(s['center']))
        buf.append(struct.pack('<i', s['image_id']))
        buf.append(struct.pack('<7d', q[0], q[1], q[2], q[3], t[0], t[1], t[2]))
        buf.append(struct.pack('<i', s['camera_id']))
        buf.append(s['filename'].encode('utf-8') + b'\x00')
        buf.append(struct.pack('<Q', 0))  # no 2D points
    return b''.join(buf)


def parse_ply_header(f):
    if f.readline().strip() != b'ply':
        raise ValueError("Invalid PLY file")

    fmt = None
    count = 0
    props = []
    in_vertex = False
    i = 0

    while True:
        i += 1
        if i > 100:
            raise ValueError("Invalid PLY file (header too long)")
        line = f.readline()
        if not line:
            raise ValueError("Invalid PLY file (unexpected end of header)")
        line = line.strip()
        if line == b'end_header':
            break

        tokens = line.decode('ascii', 'ignore').split()
        if not tokens:
            continue
        if tokens[0] == 'format':
            fmt = tokens[1]
        elif tokens[0] == 'element':
            in_vertex = tokens[1] == 'vertex'
            if in_vertex:
                count = int(tokens[2])
        elif tokens[0] == 'property' and in_vertex:
            if tokens[1] == 'list':
                raise ValueError("Unsupported PLY (list property)")
            props.append((tokens[2], tokens[1]))

    if fmt != 'binary_little_endian':
        raise ValueError("Unsupported PLY format: %s" % fmt)

    return count, props


def load_scene(task, image_size):
    cameras_file = task.assets_path(task.ASSETS_MAP['cameras.json'])
    shots_file = task.assets_path(task.ASSETS_MAP['shots.geojson'])

    for f in (cameras_file, shots_file):
        if not os.path.isfile(f):
            raise FileNotFoundError("%s does not exist" % f)

    offset_x, offset_y = get_rtc_offset(task)

    with open(cameras_file) as f:
        cameras_json = json.load(f)
    with open(shots_file) as f:
        shots_geojson = json.load(f)

    cameras = {}
    for cam_id, cam in cameras_json.items():
        try:
            camera = map_camera(cam, image_size)
        except ValueError as e:
            logger.warning("Skipping camera %s: %s" % (cam_id, str(e)))
            continue
        camera['id'] = len(cameras) + 1
        cameras[normalize_camera_id(cam_id)] = camera

    if len(cameras) == 0:
        raise ValueError("Failed to export cameras")

    shots = []
    seen = set()
    for feat in shots_geojson.get('features', []):
        props = feat.get('properties', {})
        filename = props.get('filename')
        if not filename:
            continue
        
        camera = cameras.get(normalize_camera_id(props.get('camera', '')))
        if not camera:
            # Assume first
            camera = next(iter(cameras.values()))
                    
        filename = os.path.basename(filename)
        if filename in seen:
            continue
        seen.add(filename)

        translation = props['translation']
        shots.append({
            'image_id': len(shots) + 1,
            'camera_id': camera['id'],
            'camera': camera,
            'filename': filename,
            'rotation': [float(v) for v in props['rotation']],
            'center': [float(translation[0]) - offset_x,
                       float(translation[1]) - offset_y,
                       float(translation[2])]
        })

    if len(shots) == 0:
        raise ValueError("Failed to export shots")

    return cameras, shots, offset_x, offset_y


def resize_image(src, dst, camera):
    try:
        im = Image.open(src)
        fmt = im.format or 'JPEG'
        resample = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS
        im = im.resize((camera['out_width'], camera['out_height']), resample, reducing_gap=2)
        if fmt == 'JPEG' and im.mode not in ('RGB', 'L'):
            im = im.convert('RGB')
        im.save(dst, format=fmt, **({'quality': 95} if fmt == 'JPEG' else {}))
        im.close()
    except Exception as e:
        logger.warning("Cannot resize %s (%s), linking original" % (src, str(e)))
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy(src, dst)


def prepare_export(task, output_dir, image_size=0, progress_callback=None):
    last_progress = 0
    last_status = None

    def progress(status, perc):
        nonlocal last_progress, last_status
        if progress_callback is None:
            return
        if status != last_status or time.time() - last_progress >= 1:
            progress_callback(status, perc)
            last_progress = time.time()
            last_status = status

    cameras, shots, offset_x, offset_y = load_scene(task, image_size)
    laz_file = task.assets_path(task.ASSETS_MAP['georeferenced_model.laz'])

    # Only JPEG images are supported at this time
    for shot in shots:
        if os.path.splitext(shot['filename'])[1].lower() not in ('.jpg', '.jpeg'):
            raise ValueError("%s is not a JPEG image (only JPEG images are supported)" % shot['filename'])

    with open(os.path.join(output_dir, 'cameras.bin'), 'wb') as f:
        f.write(write_cameras_bin(cameras))
    with open(os.path.join(output_dir, 'images.bin'), 'wb') as f:
        f.write(write_images_bin(shots))

    images_dir = os.path.join(output_dir, 'images')
    export_images = []
    resize_queue = []
    pdal_bin = shutil.which("pdal")

    for shot in shots:
        try:
            image_file = task.get_image_path(shot['filename'])
        except Exception:
            continue
        if not os.path.isfile(image_file):
            continue

        camera = shot['camera']
        if image_size > 0 and (camera['out_width'] != camera['width'] or camera['out_height'] != camera['height']):
            resize_queue.append((image_file, shot))
            image_file = os.path.join(images_dir, shot['filename'])
        export_images.append({'name': shot['filename'], 'path': image_file})

    proc = None
    tmpdir = None
    try:
        if os.path.isfile(laz_file):
            sample = 0
            target_points = 125000
            try:
                p = subprocess.run([pdal_bin, 'info', '--summary', laz_file],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                summary = json.loads(p.stdout)['summary']
                bounds = summary['bounds']
                if summary['num_points'] > target_points:
                    area = (bounds['maxx'] - bounds['minx']) * (bounds['maxy'] - bounds['miny'])
                    sample = math.sqrt(area / (2.0 * target_points))
            except Exception as e:
                logger.warning("Cannot compute point cloud extent for %s (%s), skipping sampling" % (laz_file, str(e)))

            # Start sampling the point cloud; it will complete
            # while we resize the images
            tmpdir = tempfile.mkdtemp(prefix='splats_')
            ply_file = os.path.join(tmpdir, 'points.ply')
            cmd = [pdal_bin, 'translate', '-i', laz_file, '-o', ply_file]
            if sample > 0:
                cmd += ['sample', '--filters.sample.radius=%s' % sample]
            cmd += ['--writers.ply.storage_mode=little endian',
                    '--writers.ply.dims=X,Y,Z,Red,Green,Blue']
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        if resize_queue:
            os.makedirs(images_dir, exist_ok=True)
            for i, (image_file, shot) in enumerate(resize_queue):
                progress("Resizing images...", (i / len(resize_queue)) * 100)
                resize_image(image_file, os.path.join(images_dir, shot['filename']), shot['camera'])

        with open(os.path.join(output_dir, 'images.json'), 'w') as f:
            json.dump(export_images, f)

        if proc is None:
            # No point cloud available; write an empty points3D.bin
            with open(os.path.join(output_dir, 'points3D.bin'), 'wb') as f:
                f.write(struct.pack('<Q', 0))
            progress("Done", 100)
            return

        progress("Sampling point cloud...", 100)
        stderr = proc.communicate()[1]
        if proc.returncode != 0 or not os.path.isfile(ply_file):
            raise ValueError("pdal translate failed: %s" % stderr.decode('utf-8', 'ignore')[-512:])

        with open(ply_file, 'rb') as fin, open(os.path.join(output_dir, 'points3D.bin'), 'wb') as fout:
            count, props = parse_ply_header(fin)
            dt = np.dtype([(name, PLY_TYPES[t]) for name, t in props if t in PLY_TYPES])
            if len(dt) != len(props):
                raise ValueError("Unsupported PLY property types")

            names = {name.lower(): name for name, _ in props}
            for dim in ('x', 'y', 'z', 'red', 'green', 'blue'):
                if dim not in names:
                    raise ValueError("PLY file is missing the %s dimension" % dim)

            out_dt = np.dtype([('id', '<u8'), ('xyz', '<f8', (3, )), ('rgb', 'u1', (3, )),
                               ('error', '<f8'), ('track_len', '<u8')])

            fout.write(struct.pack('<Q', count))

            chunk_points = 65536
            point_id = 1
            is_16bit_rgb = None
            while point_id <= count:
                data = np.fromfile(fin, dtype=dt, count=min(chunk_points, count - point_id + 1))
                if data.shape[0] == 0:
                    raise ValueError("Truncated PLY file")

                out = np.zeros(data.shape[0], dtype=out_dt)
                out['id'] = np.arange(point_id, point_id + data.shape[0], dtype=np.uint64)
                out['xyz'][:, 0] = data[names['x']].astype(np.float64) - offset_x
                out['xyz'][:, 1] = data[names['y']].astype(np.float64) - offset_y
                out['xyz'][:, 2] = data[names['z']].astype(np.float64)
                rgb = np.stack([data[names[c]] for c in ('red', 'green', 'blue')], axis=1)
                if is_16bit_rgb is None:
                    # 16 bit color values need to be scaled down to 8 bit
                    is_16bit_rgb = rgb.dtype.itemsize > 1 and rgb.max(initial=0) > 255
                if is_16bit_rgb:
                    rgb = rgb.astype(np.uint32) >> 8
                out['rgb'] = rgb.astype(np.uint8)

                fout.write(out.tobytes())
                point_id += data.shape[0]

        progress("Done", 100)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


def export_zip(export_dir):
    with open(os.path.join(export_dir, 'images.json')) as f:
        export_images = json.load(f)

    zs = ZipStream(sized=True)
    zs.comment = "Generated by WebODM"

    for filename in ('cameras.bin', 'images.bin', 'points3D.bin'):
        bin_file = os.path.join(export_dir, filename)
        if not os.path.isfile(bin_file):
            raise FileNotFoundError("%s does not exist" % bin_file)
        zs.add_path(bin_file, 'sparse/0/' + filename)

    added = 0
    for image in export_images:
        if os.path.isfile(image['path']):
            zs.add_path(image['path'], 'images/' + image['name'])
            added += 1

    if added == 0:
        zs.add(None, 'images/')

    return zs
