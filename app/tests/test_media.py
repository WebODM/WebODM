import io
import os
import shutil

from PIL import Image
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from app.models import Project, Task
from app.tests.classes import BootTestCase


class TestMedia(BootTestCase):
    def setUp(self):
        pass
    def tearDown(self):
        pass

    def test_media(self):
        user = User.objects.get(username="testuser")
        project = Project.objects.create(owner=user, name="media test")
        task = Task.objects.create(project=project)
        client = APIClient()
        client.login(username="testuser", password="test1234")
        other_client = APIClient()
        other_client.login(username="testuser2", password="test1234")
        url = "/api/projects/{}/tasks/{}/media".format(project.id, task.id)

        def create_test_image(w=100, h=100):
            buf = io.BytesIO()
            Image.new('RGB', (w, h), color='red').save(buf, format='JPEG')
            buf.seek(0)
            buf.name = 'a.jpg'
            return buf

        # Upload photo
        img = create_test_image()
        res = client.post("/api/projects/{}/tasks/{}/media/upload".format(project.id, task.id), {'file': img}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        task.refresh_from_db()
        self.assertEqual(len(task.media), 1)
        self.assertEqual(task.media[0]['type'], 'photo')

        # A retried chunk does not corrupt the upload
        data = create_test_image().getvalue()
        chunks = [data[0:64], data[64:128], data[128:]]
        for i in [0, 1, 1, 2]:
            buf = io.BytesIO(chunks[i])
            buf.name = 'retry.jpg'
            res = client.post("/api/projects/{}/tasks/{}/media/upload".format(project.id, task.id), {
                'file': buf,
                'dzuuid': 'test-chunk-retry',
                'dzchunkindex': i,
                'dzchunkbyteoffset': sum(len(c) for c in chunks[:i]),
                'dztotalchunkcount': len(chunks)
            }, format='multipart')
            self.assertEqual(res.status_code, status.HTTP_200_OK)
        with open(task.media_directory_path('retry.jpg'), 'rb') as f:
            self.assertEqual(f.read(), data)
        res = client.delete("/api/projects/{}/tasks/{}/media/manage/retry.jpg".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertEqual(len(task.media), 1)

        # Upload photo with bad filename
        img = create_test_image()
        img.name = 'test$%.jpg'
        res = client.post("/api/projects/{}/tasks/{}/media/upload".format(project.id, task.id), {'file': img}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertTrue('test$%.jpg' in res.data['uploaded'])
        self.assertEqual(res.data['added'][0]['filename'], 'test.jpg') # sanitized

        # Can delete using sanitized name
        res = client.delete("/api/projects/{}/tasks/{}/media/manage/test.jpg".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # No access from another user (upload)
        img2 = create_test_image()
        res = other_client.post("/api/projects/{}/tasks/{}/media/upload".format(project.id, task.id), {'file': img2}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Reject non-media
        txt = io.BytesIO(b"hello")
        txt.name = 'notes.txt'
        res = client.post("/api/projects/{}/tasks/{}/media/upload".format(project.id, task.id), {'file': txt}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertEqual(len(task.media), 1)

        # List media
        res = client.get("/api/projects/{}/tasks/{}/media/".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['filename'], 'a.jpg')
        self.assertEqual(res.data[0]['size'], len(img.getvalue()))
        
        # No access from another user (list)
        res = other_client.get("/api/projects/{}/tasks/{}/media/".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Media GeoJSON
        with open(os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'tiny_drone_image.jpg'), 'rb') as f:
            res = client.post("/api/projects/{}/tasks/{}/media/upload".format(project.id, task.id), {'file': f}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertEqual(len(task.media), 2)

        res = client.get("/api/projects/{}/tasks/{}/media.geojson".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['type'], 'FeatureCollection')
        self.assertEqual(len(res.data['features']), 1)
        coords = res.data['features'][0]['geometry']['coordinates']
        self.assertAlmostEqual(coords[0], -81.70550109, places=4)
        self.assertAlmostEqual(coords[1], 41.22636995, places=4)

        # No access from another user (geojson)
        res = other_client.get("/api/projects/{}/tasks/{}/media.geojson".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Patch description
        res = client.patch("/api/projects/{}/tasks/{}/media/manage/a.jpg".format(project.id, task.id), {'description': 'hello'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertEqual(task.media[0]['description'], 'hello')

        # No access from another user (patch)
        res = other_client.patch("/api/projects/{}/tasks/{}/media/manage/a.jpg".format(project.id, task.id), {'description': 'x'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Download

        # No access from another user (download)
        res = other_client.get("/api/projects/{}/tasks/{}/media/download/a.jpg".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        res = client.get("/api/projects/{}/tasks/{}/media/download/a.jpg".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('image/jpeg', res['Content-Type'])

        res = client.get("/api/projects/{}/tasks/{}/media/download/a.jpg".format(project.id, task.id), HTTP_RANGE='bytes=0-9')
        self.assertEqual(res.status_code, 206)
        self.assertEqual(res['Content-Length'], '10')

        # Thumbnail

        # No access from another user (thumbnail)
        res = other_client.get("/api/projects/{}/tasks/{}/media/thumbnail/a.jpg".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        res = client.get("/api/projects/{}/tasks/{}/media/thumbnail/a.jpg".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('image/jpeg', res['Content-Type'])

        res = client.get("/api/projects/{}/tasks/{}/media/thumbnail/a.jpg?size=10".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('image/jpeg', res['Content-Type'])
        img_response = Image.open(io.BytesIO(b''.join(res.streaming_content)))
        self.assertEqual(img_response.width, 10)

        # Delete media

        # No access from another user (delete)
        res = other_client.delete("/api/projects/{}/tasks/{}/media/manage/a.jpg".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Can't delete file that doesn't exist
        res = client.delete("/api/projects/{}/tasks/{}/media/manage/nonexistant.jpg".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        
        # Can delete
        media_dir = task.media_directory_path()
        filepath = os.path.join(media_dir, "a.jpg")
        self.assertTrue(os.path.isfile(filepath))

        res = client.delete("/api/projects/{}/tasks/{}/media/manage/a.jpg".format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(os.path.isfile(filepath))
        task.refresh_from_db()
        self.assertEqual(len(task.media), 1)
