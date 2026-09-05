import io
import json
import os
import shutil
import struct
import subprocess
import tempfile
import uuid
import zipfile

from PIL import Image
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from app.api.common import get_asset_download_filename
from app.models import Project, Task
from .classes import BootTestCase


class TestSplats(BootTestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_splats(self):
        user = User.objects.get(username="testuser")
        project = Project.objects.create(owner=user, name="test project")

        # Create a task and populate a minimal mock cameras.json, shots.geojson and a point cloud
        task = Task.objects.create(project=project)

        camera_id = "dji test 48 36 perspective 0.85"
        os.makedirs(task.assets_path("odm_georeferencing"), exist_ok=True)
        os.makedirs(task.assets_path("odm_report"), exist_ok=True)

        with open(task.get_asset_file_or_stream('cameras.json'), 'w') as f:
            json.dump({
                camera_id: {
                    'projection_type': 'perspective',
                    'width': 48, 'height': 36,
                    'focal': 0.85, 'k1': 0.01, 'k2': -0.002
                }
            }, f)

        images = ['tiny_drone_image.jpg', 'tiny_drone_image_2.jpg']
        with open(task.get_asset_file_or_stream('shots.geojson'), 'w') as f:
            json.dump({
                'type': 'FeatureCollection',
                'features': [{
                    'type': 'Feature',
                    'geometry': {'type': 'Point', 'coordinates': [0, 0, 0]},
                    'properties': {
                        'filename': image,
                        'camera': 'v2 ' + camera_id,
                        'translation': [10.5, 20.5, 30.0],
                        'rotation': [0.1, 0.2, 0.3]
                    }
                } for image in images]
            }, f)

        # Hard link the task's images from the fixtures
        fixtures_dir = os.path.join(os.path.dirname(__file__), '..', 'fixtures')
        for image in images:
            os.link(os.path.join(fixtures_dir, image), task.task_path(image))

        # Generate a small .laz point cloud with PDAL
        tmpdir = tempfile.mkdtemp()
        try:
            csv_file = os.path.join(tmpdir, 'points.csv')
            with open(csv_file, 'w') as f:
                f.write("X,Y,Z,Red,Green,Blue\n")
                for i in range(10):
                    f.write("{},{},{},{},{},{}\n".format(i * 2.0, i * 2.0, 10.0 + i, 255, 128, 0))
            pipeline_file = os.path.join(tmpdir, 'pipeline.json')
            with open(pipeline_file, 'w') as f:
                json.dump([
                    {'type': 'readers.text', 'filename': csv_file},
                    {'type': 'writers.las', 'filename': task.get_asset_file_or_stream('georeferenced_model.laz')}
                ], f)
            subprocess.run([shutil.which('pdal'), 'pipeline', pipeline_file], check=True)
        finally:
            shutil.rmtree(tmpdir)

        # Call update task assets fields so that they populate task.available_assets
        task.update_available_assets_field(commit=True)

        # Assert cameras.json, shots.geojson and georeferenced_model.laz are there
        task.refresh_from_db()
        for asset in ('cameras.json', 'shots.geojson', 'georeferenced_model.laz'):
            self.assertIn(asset, task.available_assets)

        # Login with user's API Client
        client = APIClient()
        client.login(username="testuser", password="test1234")

        # An export that has not been run should not be ready
        res = client.get("/api/projects/{}/tasks/{}/splats/download/{}".format(project.id, task.id, uuid.uuid4()))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # User should be able to call POST splats/download
        res = client.post("/api/projects/{}/tasks/{}/splats/download".format(project.id, task.id), {'image_size': 16})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        celery_task_id = res.data.get('celery_task_id')
        self.assertIsNotNone(celery_task_id)

        # User should be able to GET splats/download
        res = client.get("/api/projects/{}/tasks/{}/splats/download/{}".format(project.id, task.id, celery_task_id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Filename should match get_asset_download_filename(task, 'training.zip')
        filename = get_asset_download_filename(task, 'training.zip')
        self.assertEqual(res.get('Content-Disposition'), "attachment; filename={}".format(filename))

        # User should be able to GET splats/download with ?filename=override.zip
        res = client.get("/api/projects/{}/tasks/{}/splats/download/{}?filename=override.zip".format(project.id, task.id, celery_task_id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Filename should match override.zip
        self.assertEqual(res.get('Content-Disposition'), "attachment; filename=override.zip")

        # The resulting file is a valid .zip file and extracting it contains the proper COLMAP structure
        with zipfile.ZipFile(io.BytesIO(b''.join(res.streaming_content))) as z:
            self.assertIsNone(z.testzip())
            extract_dir = tempfile.mkdtemp()
            try:
                z.extractall(extract_dir)
                for f in ('cameras.bin', 'images.bin', 'points3D.bin'):
                    self.assertTrue(os.path.isfile(os.path.join(extract_dir, 'sparse', '0', f)))

                # Images have been resized to image_size
                for image in images:
                    with Image.open(os.path.join(extract_dir, 'images', image)) as im:
                        self.assertEqual(max(im.width, im.height), 16)
            finally:
                shutil.rmtree(extract_dir)

        # With image_size 0, images should keep their original size
        res = client.post("/api/projects/{}/tasks/{}/splats/download".format(project.id, task.id), {'image_size': 0})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        celery_task_id = res.data.get('celery_task_id')

        res = client.get("/api/projects/{}/tasks/{}/splats/download/{}".format(project.id, task.id, celery_task_id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        with zipfile.ZipFile(io.BytesIO(b''.join(res.streaming_content))) as z:
            extract_dir = tempfile.mkdtemp()
            try:
                z.extractall(extract_dir)
                for image in images:
                    with Image.open(os.path.join(extract_dir, 'images', image)) as im:
                        self.assertEqual((im.width, im.height), (48, 36))
            finally:
                shutil.rmtree(extract_dir)

        # Another user should not be able to call POST splats/download
        other_client = APIClient()
        res = other_client.post("/api/projects/{}/tasks/{}/splats/download".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Another user should not be able to call GET splats/download
        res = other_client.get("/api/projects/{}/tasks/{}/splats/download/{}".format(project.id, task.id, celery_task_id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Create a small gaussian splat mock file in .ply format
        def create_splat_ply(count=10):
            props = ['x', 'y', 'z', 'nx', 'ny', 'nz',
                     'f_dc_0', 'f_dc_1', 'f_dc_2'] + \
                    ['f_rest_{}'.format(i) for i in range(45)] + \
                    ['opacity', 'scale_0', 'scale_1', 'scale_2',
                     'rot_0', 'rot_1', 'rot_2', 'rot_3']
            buf = io.BytesIO()
            buf.write(("ply\n"
                       "format binary_little_endian 1.0\n"
                       "element vertex {}\n".format(count) +
                       "".join("property float {}\n".format(p) for p in props) +
                       "end_header\n").encode('ascii'))
            for i in range(count):
                values = [i * 0.1, i * 0.1, 0.0,       # position
                          0.0, 0.0, 0.0,               # normal
                          0.5, 0.5, 0.5]               # f_dc
                values += [0.0] * 45                   # f_rest
                values += [2.0,                        # opacity
                           -3.0, -3.0, -3.0,           # scale
                           1.0, 0.0, 0.0, 0.0]         # rotation
                buf.write(struct.pack('<62f', *values))
            buf.seek(0)
            buf.name = 'model.ply'
            return buf

        upload_url = "/api/projects/{}/tasks/{}/splats/upload".format(project.id, task.id)

        # A malformed .ply file is accepted for upload, but processing fails
        # and no splat model is created
        bad_ply = io.BytesIO(b"ply\nformat binary_little_endian 1.0\nelement vertex 100\nproperty float x\nend_header\ntruncated")
        bad_ply.name = 'model.ply'
        res = client.post(upload_url, {'file': bad_ply}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertIsNotNone(res.data.get('celery_task_id'))

        res = client.get("/api/workers/check/{}".format(res.data['celery_task_id']))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data.get('ready'))
        self.assertIsNotNone(res.data.get('error'))
        self.assertFalse(os.path.isfile(task.get_asset_file_or_stream('splats.rad')))
        task.refresh_from_db()
        self.assertNotIn('splats.rad', task.available_assets)

        size_before = task.size

        # Upload the splat model (the conversion via splat-tools runs eagerly)
        res = client.post(upload_url, {'file': create_splat_ply()}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertIsNotNone(res.data.get('celery_task_id'))

        # The converted model should have been created
        res = client.get("/api/workers/check/{}".format(res.data['celery_task_id']))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data.get('ready'))
        self.assertIsNone(res.data.get('error'))
        self.assertTrue(os.path.isfile(task.get_asset_file_or_stream('splats.rad')))
        task.refresh_from_db()
        self.assertIn('splats.rad', task.available_assets)

        # The task size should have increased
        self.assertGreater(task.size, size_before)

        # Files can be uploaded in chunks
        payload = b"a chunked mock rad model"
        chunks = [payload[0:8], payload[8:16], payload[16:]]
        for i, chunk in enumerate(chunks):
            buf = io.BytesIO(chunk)
            buf.name = 'model.rad'
            res = client.post(upload_url, {
                'file': buf,
                'dzuuid': 'test-chunked-upload',
                'dzchunkindex': i,
                'dzchunkbyteoffset': sum(len(c) for c in chunks[:i]),
                'dztotalchunkcount': len(chunks)
            }, format='multipart')
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertTrue(res.data['success'])

            if i < len(chunks) - 1:
                # Intermediate chunks return a partial response
                self.assertTrue(res.data.get('partial'))
            else:
                # The last chunk completes the upload
                self.assertFalse(res.data.get('partial'))
                self.assertIsNone(res.data.get('celery_task_id'))

        # The chunks have been reassembled
        with open(task.get_asset_file_or_stream('splats.rad'), 'rb') as f:
            self.assertEqual(f.read(), payload)

        # A .rad file is stored directly (no processing) and replaces the current model
        rad = io.BytesIO(b"mock rad model")
        rad.name = 'model.rad'
        res = client.post(upload_url, {'file': rad}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertIsNone(res.data.get('celery_task_id'))
        with open(task.get_asset_file_or_stream('splats.rad'), 'rb') as f:
            self.assertEqual(f.read(), b"mock rad model")
        task.refresh_from_db()
        self.assertIn('splats.rad', task.available_assets)

        # Can download splats.rad assets
        res = client.get("/api/projects/{}/tasks/{}/download/splats.rad".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsNone(res.get('Accept-Ranges'))

        # Range requests are supported on the raw asset path work
        res = client.get("/api/projects/{}/tasks/{}/assets/splats/model.rad".format(project.id, task.id), HTTP_RANGE='bytes=0-3')
        self.assertEqual(res.status_code, 206)
        self.assertEqual(b''.join(res.streaming_content), b"mock")

        rad_model = "/api/projects/{}/tasks/{}/assets/splats/model.rad".format(project.id, task.id)

        # Full responses advertise range support ("mock rad model" is 14 bytes)
        res = client.get(rad_model)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.get('Accept-Ranges'), 'bytes')
        self.assertEqual(res.get('Content-Length'), '14')

        # Range with an explicit start and end
        res = client.get(rad_model, HTTP_RANGE='bytes=5-7')
        self.assertEqual(res.status_code, 206)
        self.assertEqual(b''.join(res.streaming_content), b"rad")
        self.assertEqual(res.get('Content-Range'), 'bytes 5-7/14')
        self.assertEqual(res.get('Content-Length'), '3')

        # Open ended range
        res = client.get(rad_model, HTTP_RANGE='bytes=5-')
        self.assertEqual(res.status_code, 206)
        self.assertEqual(b''.join(res.streaming_content), b"rad model")
        self.assertEqual(res.get('Content-Range'), 'bytes 5-13/14')

        # The end of the range is clamped to the file size
        res = client.get(rad_model, HTTP_RANGE='bytes=10-9999')
        self.assertEqual(res.status_code, 206)
        self.assertEqual(b''.join(res.streaming_content), b"odel")
        self.assertEqual(res.get('Content-Range'), 'bytes 10-13/14')

        # A range starting past the end of the file is rejected
        res = client.get(rad_model, HTTP_RANGE='bytes=14-')
        self.assertEqual(res.status_code, 416)
        self.assertEqual(res.get('Content-Range'), 'bytes */14')

        # Suffix, multipart and malformed ranges are not supported (full response)
        for header in ('bytes=-5', 'bytes=0-3,5-7', 'garbage'):
            res = client.get(rad_model, HTTP_RANGE=header)
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertEqual(res.content, b"mock rad model")

        # Range requests are ignored for other assets
        res = client.get("/api/projects/{}/tasks/{}/assets/cameras.json".format(project.id, task.id), HTTP_RANGE='bytes=0-3')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsNone(res.get('Accept-Ranges'))

        # Reject non-splat files
        txt = io.BytesIO(b"hello")
        txt.name = 'notes.txt'
        res = client.post(upload_url, {'file': txt}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Cannot upload multiple files
        res = client.post(upload_url, {'file': [create_splat_ply(), create_splat_ply()]}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # No access from another user (upload)
        user2_client = APIClient()
        user2_client.login(username="testuser2", password="test1234")
        res = user2_client.post(upload_url, {'file': create_splat_ply()}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # No access from anonymous users (upload)
        res = other_client.post(upload_url, {'file': create_splat_ply()}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Cannot upload to a task without a point cloud
        task2 = Task.objects.create(project=project)
        res = client.post("/api/projects/{}/tasks/{}/splats/upload".format(project.id, task2.id),
                          {'file': create_splat_ply()}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        delete_url = "/api/projects/{}/tasks/{}/splats/delete".format(project.id, task.id)

        # No access from another user (delete)
        res = user2_client.post(delete_url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # No access from anonymous users (delete)
        res = other_client.post(delete_url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # User should be able to delete the splat model
        size_before_delete = task.size
        res = client.post(delete_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertFalse(os.path.isfile(task.get_asset_file_or_stream('splats.rad')))
        task.refresh_from_db()
        self.assertNotIn('splats.rad', task.available_assets)

        # The task size should have decreased
        self.assertLess(task.size, size_before_delete)

        # Cannot delete a model that no longer exists
        res = client.post(delete_url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
