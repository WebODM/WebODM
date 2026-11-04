import os
import time
import shutil
import subprocess

import io
import requests
from django.contrib.auth.models import User
from guardian.shortcuts import remove_perm, assign_perm
from rest_framework import status
from rest_framework.test import APIClient

import worker
from app.cogeo import valid_cogeo
from app.models import Project
from app.models import Task
from app.tests.classes import BootTransactionTestCase
from app.tests.utils import clear_test_media_root, start_processing_node
from nodeodm import status_codes
from nodeodm.models import ProcessingNode
from webodm import settings


class TestApiTask(BootTransactionTestCase):
    def setUp(self):
        super().setUp()
        clear_test_media_root()

    def test_task(self):
        client = APIClient()

        with start_processing_node():
            user = User.objects.get(username="testuser")
            self.assertFalse(user.is_superuser)
            project = Project.objects.create(
                owner=user,
                name="test project"
            )

            image1 = open("app/fixtures/tiny_drone_image.jpg", 'rb')
            image2 = open("app/fixtures/tiny_drone_image_2.jpg", 'rb')

            # Create processing node
            pnode = ProcessingNode.objects.create(hostname="localhost", port=11223)
            assign_perm('view_processingnode', user, pnode)
            client.login(username="testuser", password="test1234")

            # Create task
            res = client.post("/api/projects/{}/tasks/".format(project.id), {
                'images': [image1, image2]
            }, format="multipart")
            image1.close()
            image2.close()
            task = Task.objects.get(id=res.data['id'])

            # Wait for completion
            c = 0
            while c < 10:
                worker.tasks.process_pending_tasks()
                task.refresh_from_db()
                if task.status == status_codes.COMPLETED:
                    break
                c += 1
                time.sleep(1)


            self.assertEqual(task.status, status_codes.COMPLETED)

            if not os.path.exists(settings.MEDIA_TMP):
                os.mkdir(settings.MEDIA_TMP)

            # EPT assets should be there
            res = client.get("/api/projects/{}/tasks/{}/assets/entwine_pointcloud/ept.json".format(project.id, task.id))
            self.assertEqual(res.status_code, status.HTTP_200_OK)

            # Try removing it
            shutil.rmtree(task.assets_path("entwine_pointcloud"))

            res = client.get("/api/projects/{}/tasks/{}/assets/entwine_pointcloud/ept.json".format(project.id, task.id))
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

            # Rebuild it
            self.assertTrue(task.check_ept())

            # EPT available again
            res = client.get("/api/projects/{}/tasks/{}/assets/entwine_pointcloud/ept.json".format(project.id, task.id))
            self.assertEqual(res.status_code, status.HTTP_200_OK)

            # Download task assets
            task_uuid = task.uuid
            res = client.get("/api/projects/{}/tasks/{}/download/all.zip".format(project.id, task.id))
            self.assertEqual(res.status_code, status.HTTP_200_OK)

            assets_path = os.path.join(settings.MEDIA_TMP, "all.zip")

            with open(assets_path, 'wb') as f:
                f.write(b''.join(res.streaming_content))

            remove_perm('change_project', user, project)

            assets_file = open(assets_path, 'rb')

            # Cannot import unless we have permission
            res = client.post("/api/projects/{}/tasks/import".format(project.id), {
                'file': [assets_file]
            }, format="multipart")
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

            assign_perm('change_project', user, project)

            # Import with file upload method
            assets_file.seek(0)
            res = client.post("/api/projects/{}/tasks/import".format(project.id), {
                'file': [assets_file]
            }, format="multipart")
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)
            assets_file.close()

            file_import_task = Task.objects.get(id=res.data['id'])
            # Wait for completion
            c = 0
            while c < 10:
                worker.tasks.process_pending_tasks()
                file_import_task.refresh_from_db()
                if file_import_task.status == status_codes.COMPLETED:
                    break
                c += 1
                time.sleep(1)

            self.assertEqual(file_import_task.import_url, "file://all.zip")
            self.assertEqual(file_import_task.images_count, 1)
            self.assertEqual(file_import_task.processing_node, None)
            self.assertEqual(file_import_task.auto_processing_node, False)

            # Can access assets
            res = client.get("/api/projects/{}/tasks/{}/assets/odm_orthophoto/odm_orthophoto.tif".format(project.id, file_import_task.id))
            self.assertEqual(res.status_code, status.HTTP_200_OK)

            self.assertTrue(valid_cogeo(file_import_task.assets_path(task.ASSETS_MAP["orthophoto.tif"])))
            self.assertTrue(valid_cogeo(file_import_task.assets_path(task.ASSETS_MAP["dsm.tif"])))
            self.assertTrue(valid_cogeo(file_import_task.assets_path(task.ASSETS_MAP["dtm.tif"])))

            # Set task public so we can download from it without auth
            file_import_task.public = True
            file_import_task.save()

            # Cannot import an invalid URL
            res = client.post("/api/projects/{}/tasks/import".format(project.id), {
                'url': "javascript:void(0)"
            })
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

            # Import with URL method
            assets_import_url = "http://{}:{}/task/{}/download/all.zip".format(pnode.hostname, pnode.port, task_uuid)
            res = client.post("/api/projects/{}/tasks/import".format(project.id), {
                'url': assets_import_url
            })
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)
            url_task = Task.objects.get(id=res.data['id'])

            # Wait for completion
            c = 0
            while c < 10:
                worker.tasks.process_pending_tasks()
                url_task.refresh_from_db()
                if url_task.status == status_codes.COMPLETED:
                    break
                c += 1
                time.sleep(1)

            self.assertEqual(url_task.import_url, assets_import_url)
            self.assertEqual(url_task.images_count, 1)

            # Import corrupted file
            assets_import_url = "http://{}:{}/task/{}/download/orthophoto.tif".format(pnode.hostname, pnode.port, task_uuid)
            res = client.post("/api/projects/{}/tasks/import".format(project.id), {
                'url': assets_import_url
            })
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)
            corrupted_task = Task.objects.get(id=res.data['id'])

            # Wait for completion
            c = 0
            while c < 10:
                worker.tasks.process_pending_tasks()
                corrupted_task.refresh_from_db()
                if corrupted_task.status == status_codes.FAILED:
                    break
                c += 1
                time.sleep(1)

            self.assertEqual(corrupted_task.status, status_codes.FAILED)
            self.assertTrue("Invalid" in corrupted_task.last_error)

            # Test chunked upload import
            assets_file = open(assets_path, 'rb')
            assets_size = os.path.getsize(assets_path)
            chunk_1_size = assets_size // 2
            chunk_1_path = os.path.join(os.path.dirname(assets_path), "1.zip")
            chunk_2_path = os.path.join(os.path.dirname(assets_path), "2.zip")
            with open(chunk_1_path, 'wb') as f:
                assets_file.seek(0)
                f.write(assets_file.read(chunk_1_size))
            with open(chunk_2_path, 'wb') as f:
                f.write(assets_file.read())
            
            chunk_1 = open(chunk_1_path, 'rb')
            chunk_2 = open(chunk_2_path, 'rb')
            assets_file.close()

            res = client.post("/api/projects/{}/tasks/import".format(project.id), {
                'file': [chunk_1],
                'dzuuid': 'abc-test',
                'dzchunkindex': 0,
                'dztotalchunkcount': 2,
                'dzchunkbyteoffset': 0,
                'public': True
            }, format="multipart")
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertTrue(res.data['uploaded'])
            chunk_1.close()
                
            res = client.post("/api/projects/{}/tasks/import".format(project.id), {
                'file': [chunk_2],
                'dzuuid': 'abc-test',
                'dzchunkindex': 1,
                'dztotalchunkcount': 2,
                'dzchunkbyteoffset': chunk_1_size,
                'public': True
            }, format="multipart")
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)
            chunk_2.close()

            file_import_task = Task.objects.get(id=res.data['id'])
            # Wait for completion
            c = 0
            while c < 10:
                worker.tasks.process_pending_tasks()
                file_import_task.refresh_from_db()
                if file_import_task.status == status_codes.COMPLETED:
                    break
                c += 1
                time.sleep(1)

            self.assertEqual(file_import_task.import_url, "file://all.zip")
            self.assertEqual(file_import_task.images_count, 1)
            self.assertTrue(file_import_task.public)

    def test_backup(self):
        client = APIClient()

        with start_processing_node():
            user = User.objects.get(username="testuser")
            self.assertFalse(user.is_superuser)
            project = Project.objects.create(
                owner=user,
                name="test backup"
            )

            image1 = open("app/fixtures/tiny_drone_image.jpg", 'rb')
            image2 = open("app/fixtures/tiny_drone_image_2.jpg", 'rb')

            # Create processing node
            pnode = ProcessingNode.objects.create(hostname="localhost", port=11223)
            assign_perm('view_processingnode', user, pnode)

            client.login(username="testuser", password="test1234")

            # Create task
            res = client.post("/api/projects/{}/tasks/".format(project.id), {
                'images': [image1, image2]
            }, format="multipart")
            image1.close()
            image2.close()
            task = Task.objects.get(id=res.data['id'])

            # Wait for completion
            c = 0
            while c < 10:
                worker.tasks.process_pending_tasks()
                task.refresh_from_db()
                if task.status == status_codes.COMPLETED:
                    break
                c += 1
                time.sleep(1)

            # Assign some fields
            task.name = "Backup test"
            task.potree_scene = {'saved': True}
            task.public = True
            task.crop = {"type":"Polygon","coordinates":[[[-91.99424117803576,46.84230591442068],[-91.99366182088853,46.84228940253027],[-91.99393808841705,46.84257010397711],[-91.99424117803576,46.84230591442068]]]}
            task.save()
            task.refresh_from_db()
            self.assertTrue(task.crop is not None)

            self.assertEqual(task.status, status_codes.COMPLETED)

            # Download task backup
            task_uuid = task.uuid
            res = client.get("/api/projects/{}/tasks/{}/backup".format(project.id, task.id))
            self.assertEqual(res.status_code, status.HTTP_200_OK)

            if not os.path.exists(settings.MEDIA_TMP):
                os.mkdir(settings.MEDIA_TMP)

            assets_path = os.path.join(settings.MEDIA_TMP, "backup.zip")

            with open(assets_path, 'wb') as f:
                f.write(b''.join(res.streaming_content))

            assets_file = open(assets_path, 'rb')

            # Import with file upload method
            res = client.post("/api/projects/{}/tasks/import".format(project.id), {
                'file': [assets_file]
            }, format="multipart")
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)
            assets_file.close()

            file_import_task = Task.objects.get(id=res.data['id'])
            # Wait for completion
            c = 0
            while c < 10:
                worker.tasks.process_pending_tasks()
                file_import_task.refresh_from_db()
                if file_import_task.status == status_codes.COMPLETED:
                    break
                c += 1
                time.sleep(1)

            self.assertEqual(file_import_task.import_url, "")
            self.assertEqual(file_import_task.images_count, 1)
            self.assertEqual(file_import_task.processing_node, None)
            self.assertEqual(file_import_task.auto_processing_node, False)
            self.assertEqual(file_import_task.name, "Backup test")
            self.assertTrue('saved' in file_import_task.potree_scene)
            self.assertEqual(file_import_task.public, True)
            self.assertEqual(file_import_task.crop, task.crop)
            
            # Can access assets
            res = client.get("/api/projects/{}/tasks/{}/assets/odm_orthophoto/odm_orthophoto.tif".format(project.id, file_import_task.id))
            self.assertEqual(res.status_code, status.HTTP_200_OK)

            self.assertTrue(valid_cogeo(file_import_task.assets_path(task.ASSETS_MAP["orthophoto.tif"])))
            self.assertTrue(valid_cogeo(file_import_task.assets_path(task.ASSETS_MAP["dsm.tif"])))
            self.assertTrue(valid_cogeo(file_import_task.assets_path(task.ASSETS_MAP["dtm.tif"])))

    def test_entwine_bin(self):
        entwine = shutil.which("entwine")
        self.assertTrue(entwine is not None)

        self.assertEqual(subprocess.run([entwine, "--help"]).returncode, 0)