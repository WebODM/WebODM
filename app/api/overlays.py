import os
import re
import json
import gzip
import math
import time
import shutil
import subprocess
import tempfile

from django.core.files.uploadedfile import InMemoryUploadedFile
from django.http import FileResponse, HttpResponse
from django.utils.translation import gettext_lazy as _
from rest_framework import status, exceptions, parsers
from rest_framework.response import Response

from app.api.tasks import flatten_files, TaskNestedView
from webodm import settings

MAX_OVERLAY_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

def sanitize_overlay_id(name):
    overlay_id = re.sub(r'[^0-9a-zA-Z-_]+', '', str(name).replace(' ', '-'))
    overlay_id = re.sub(r'-[-]+', '-', overlay_id)[:64]
    if overlay_id == '':
        overlay_id = 'overlay'
    return overlay_id


def check_overlay_write_perms(request, task):
    if task.check_public_edit():
        if not request.user.has_perm("app.change_project", task.project):
            raise exceptions.NotFound()


def overlay_files(task, overlay_id):
    if overlay_id is None or not re.match(r'^[0-9a-zA-Z-_]+$', overlay_id):
        raise exceptions.ValidationError(detail=_("Invalid overlay ID"))
    return task.overlays_path(overlay_id + ".json"), task.overlays_path(overlay_id + ".geojson.gz")


def write_overlay_geojson(path, geojson):
    atomic_write(path, gzip.compress(json.dumps(geojson).encode('utf-8')))


def read_overlay_geojson(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def atomic_write(path, data):
    # Atomic write via rename
    if isinstance(data, str):
        data = data.encode('utf-8')
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.isfile(tmp):
            os.unlink(tmp)


def feature_layer_name(feature):
    props = feature.get('properties') or {}
    return str(props.get('Layer', "0"))


class TaskOverlaysSync(TaskNestedView):
    parser_classes = (parsers.MultiPartParser, parsers.FormParser)

    def post(self, request, pk=None, project_pk=None):
        """
        Store an overlay (GeoJSON file + metadata)
        """
        task = self.get_and_check_task(request, pk)
        check_overlay_write_perms(request, task)

        files = flatten_files(request.FILES)
        if len(files) != 1:
            raise exceptions.ValidationError(detail=_("Missing file"))
        file = files[0]
        if file.size > MAX_OVERLAY_FILE_SIZE:
            raise exceptions.ValidationError(detail=_("%(file)s is bigger than %(size)s MB.") % {'file': file.name, 'size': int(MAX_OVERLAY_FILE_SIZE / 1024 / 1024)})

        name = request.data.get('name', '')
        try:
            meta = json.loads(request.data.get('meta', '{}'))
            if not isinstance(meta, dict):
                raise ValueError()
        except (ValueError, json.JSONDecodeError):
            raise exceptions.ValidationError(detail=_("Invalid overlay metadata"))

        try:
            if isinstance(file, InMemoryUploadedFile):
                geojson = json.load(file)
            else:
                with open(file.temporary_file_path(), 'r', encoding='utf-8') as f:
                    geojson = json.load(f)
            if not isinstance(geojson, dict) or geojson.get('type') != 'FeatureCollection':
                raise ValueError()
        except (ValueError, json.JSONDecodeError):
            raise exceptions.ValidationError(detail=_("Invalid GeoJSON"))

        overlay_id = request.data.get('id')
        if not overlay_id:
            overlay_id = sanitize_overlay_id(name)
            candidate_id = overlay_id
            i = 2
            while os.path.isfile(overlay_files(task, candidate_id)[0]):
                candidate_id = "{}-{}".format(overlay_id, i)
                i += 1
            overlay_id = candidate_id

        stamp = int(time.time() * 1000)

        sidecar_path, geojson_path = overlay_files(task, overlay_id)
        os.makedirs(task.overlays_path(), exist_ok=True)
        write_overlay_geojson(geojson_path, geojson)
        atomic_write(sidecar_path, json.dumps({'name': name, 'stamp': stamp, 'meta': meta}))

        task.update_size(commit=True)

        return Response({'id': overlay_id, 'stamp': stamp}, status=status.HTTP_200_OK)


class TaskOverlay(TaskNestedView):
    def get(self, request, pk=None, project_pk=None, overlay_id=None):
        """
        Download an overlay's GeoJSON
        """
        task = self.get_and_check_task(request, pk)
        _, geojson_path = overlay_files(task, overlay_id)
        if not os.path.isfile(geojson_path):
            raise exceptions.NotFound()

        # Stored gzipped; serve the compressed bytes directly
        if 'gzip' in request.META.get('HTTP_ACCEPT_ENCODING', ''):
            response = FileResponse(open(geojson_path, 'rb'), content_type='application/json')
            response['Content-Encoding'] = 'gzip'
            return response
        else:
            with open(geojson_path, 'rb') as f:
                return HttpResponse(gzip.decompress(f.read()), content_type='application/json')

    def patch(self, request, pk=None, project_pk=None, overlay_id=None):
        """
        Update an overlay's metadata
        """
        task = self.get_and_check_task(request, pk)
        check_overlay_write_perms(request, task)

        sidecar_path, geojson_path = overlay_files(task, overlay_id)
        if not os.path.isfile(sidecar_path):
            raise exceptions.NotFound()

        body = request.data

        try:
            with open(sidecar_path, 'r', encoding='utf-8') as f:
                sidecar = json.load(f)
        except (IOError, json.JSONDecodeError):
            sidecar = {'name': '', 'stamp': 0, 'meta': {}}

        try:
            stamp = int(body.get('stamp', int(time.time() * 1000)))
        except (TypeError, ValueError):
            raise exceptions.ValidationError(detail=_("Invalid overlay metadata"))

        if sidecar.get('stamp', 0) >= stamp:
            return Response({'updated': False}, status=status.HTTP_200_OK)

        if 'name' in body:
            sidecar['name'] = str(body['name'])
        if 'meta' in body and isinstance(body['meta'], dict):
            sidecar['meta'] = body['meta']
        sidecar['stamp'] = stamp

        remove_layer = body.get('removeLayer')
        if remove_layer is not None and os.path.isfile(geojson_path):
            try:
                geojson = read_overlay_geojson(geojson_path)
            except (IOError, OSError, json.JSONDecodeError):
                raise exceptions.ValidationError(detail=_("Invalid GeoJSON"))
            geojson['features'] = [f for f in geojson.get('features', []) if feature_layer_name(f) != str(remove_layer)]
            write_overlay_geojson(geojson_path, geojson)
            task.update_size(commit=True)

        atomic_write(sidecar_path, json.dumps(sidecar))

        return Response({'updated': True, 'stamp': stamp}, status=status.HTTP_200_OK)

    def delete(self, request, pk=None, project_pk=None, overlay_id=None):
        """
        Delete an overlay
        """
        task = self.get_and_check_task(request, pk)
        check_overlay_write_perms(request, task)

        sidecar_path, geojson_path = overlay_files(task, overlay_id)
        found = False
        for p in (sidecar_path, geojson_path):
            if os.path.isfile(p):
                os.unlink(p)
                found = True
        if not found:
            raise exceptions.NotFound()

        # Don't leave empty folders behind
        d = task.overlays_path()
        if os.path.isdir(d) and len(os.listdir(d)) == 0:
            try:
                os.rmdir(d)
            except OSError:
                pass

        task.update_size(commit=True)

        return Response(status=status.HTTP_204_NO_CONTENT)


class TaskOverlayConvert(TaskNestedView):
    parser_classes = (parsers.MultiPartParser, parsers.FormParser)

    def post(self, request, pk=None, project_pk=None):
        """
        Convert an uploaded DXF file or zipped shapefile to GeoJSON
        """
        task = self.get_and_check_task(request, pk)

        files = flatten_files(request.FILES)
        if len(files) != 1:
            raise exceptions.ValidationError(detail=_("Missing file"))

        file = files[0]
        is_dxf = file.name.lower().endswith(".dxf")
        is_zip = file.name.lower().endswith(".zip")
        if not is_dxf and not is_zip:
            raise exceptions.ValidationError(detail=_("Not a DXF or zipped shapefile: %(file)s") % {'file': file.name})
        if file.size > MAX_OVERLAY_FILE_SIZE:
            raise exceptions.ValidationError(detail=_("%(file)s is bigger than %(size)s MB.") % {'file': file.name, 'size': int(MAX_OVERLAY_FILE_SIZE / 1024 / 1024)})

        epsg = request.data.get('epsg')
        if epsg is None and is_dxf:
            epsg = task.epsg
        if epsg is not None:
            try:
                epsg = int(epsg)
            except (TypeError, ValueError):
                raise exceptions.ValidationError(detail=_("Invalid EPSG code"))
        elif is_dxf:
            raise exceptions.ValidationError(detail=_("Invalid EPSG code"))

        ogr2ogr_bin = shutil.which("ogr2ogr")
        if ogr2ogr_bin is None:
            return Response({'error': "Cannot find ogr2ogr"}, status=status.HTTP_400_BAD_REQUEST)

        tmpdir = tempfile.mkdtemp('_overlay', dir=settings.MEDIA_TMP)
        try:
            infile = os.path.join(tmpdir, "input.dxf" if is_dxf else "input.zip")
            with open(infile, 'wb') as fd:
                if isinstance(file, InMemoryUploadedFile):
                    for chunk in file.chunks():
                        fd.write(chunk)
                else:
                    with open(file.temporary_file_path(), 'rb') as f:
                        shutil.copyfileobj(f, fd)

            src = infile if is_dxf else "/vsizip/{}".format(infile)
            args = [ogr2ogr_bin, "-f", "GeoJSON", "-t_srs", "EPSG:4326"]
            if epsg is not None:
                args += ["-s_srs", "EPSG:{}".format(epsg)]

            args += ['--config', 'DXF_ENCODING', 'UTF-8']
            args += ['--config', 'DXF_3D_EXTENSIBLE_MODE', 'YES']
            args += ["-if", "DXF" if is_dxf else "ESRI Shapefile"]
            
            outfile = os.path.join(tmpdir, "output.geojson")
            p = subprocess.Popen(args + [outfile, src],
                                 cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            if p.returncode != 0:
                return Response({'error': _("Cannot convert %(file)s: %(reason)s") % {'file': file.name, 'reason': err.decode('utf-8').strip()}},
                                status=status.HTTP_400_BAD_REQUEST)

            try:
                with open(outfile, 'r', encoding='utf-8') as f:
                    geojson = json.load(f)
            except (IOError, json.JSONDecodeError):
                return Response({'error': _("Cannot convert %(file)s: %(reason)s") % {'file': file.name, 'reason': "invalid output"}},
                                status=status.HTTP_400_BAD_REQUEST)

            return Response(geojson, status=status.HTTP_200_OK)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


def overlayStamp(request, **kwargs):
    return HttpResponse(json.dumps({'stamp': int(time.time() * 1000)}), content_type="application/json")
