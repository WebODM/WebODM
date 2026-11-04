import os
import time
from worker.celery import app as celery
import logging
import json

import requests
from PIL import Image
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient
from app.plugins.signals import task_completed
from app.tests.classes import BootTransactionTestCase
from app.models import Project, Task
from nodeodm.models import ProcessingNode
from guardian.shortcuts import assign_perm
from nodeodm import status_codes

import worker
from worker.tasks import TestSafeAsyncResult

from .utils import start_processing_node, clear_test_media_root, catch_signal

# We need to test in a TransactionTestCase because
# task processing happens on a separate thread, and normal TestCases
# do not commit changes to the DB, so spawning a new thread will show no
# data in it.
from webodm import settings
logger = logging.getLogger('app.logger')

DELAY = 2  # time to sleep for during process launch, background processing, etc.

class TestApiTask(BootTransactionTestCase):
    def setUp(self):
        super().setUp()

    def tearDown(self):
        clear_test_media_root()

    def test_exports(self):
        client = APIClient()

        with start_processing_node():
            user = User.objects.get(username="testuser")
            self.assertFalse(user.is_superuser)

            other_user = User.objects.get(username="testuser2")

            project = Project.objects.create(
                owner=user,
                name="test project"
            )
            other_project = Project.objects.create(
                owner=other_user,
                name="another test project"
            )

            # Start processing node

            # Create processing node
            pnode = ProcessingNode.objects.create(hostname="localhost", port=11223)
            assign_perm('view_processingnode', user, pnode)
            assign_perm('view_processingnode', other_user, pnode)

            other_pnode = ProcessingNode.objects.create(hostname="localhost", port=11224)
            assign_perm('view_processingnode', other_user, other_pnode)
            
            # task creation via file upload
            image1 = open("app/fixtures/tiny_drone_image.jpg", 'rb')
            image2 = open("app/fixtures/tiny_drone_image_2.jpg", 'rb')

            client.login(username="testuser", password="test1234")

            # Attempt to create a task with a processing node we have no access to
            res = client.post("/api/projects/{}/tasks/".format(project.id), {
                'images': [image1, image2],
                'name': 'test task',
                'processing_node': other_pnode.id
            }, format="multipart")
            self.assertTrue(res.status_code == status.HTTP_400_BAD_REQUEST)
            image1.seek(0)
            image2.seek(0)

            # Normal case with images[], name and processing node parameter
            res = client.post("/api/projects/{}/tasks/".format(project.id), {
                'images': [image1, image2],
                'name': 'test task',
                'processing_node': pnode.id
            }, format="multipart")
            self.assertTrue(res.status_code == status.HTTP_201_CREATED)
            image1.close()
            image2.close()

            # Should have returned the id of the newly created task
            task = Task.objects.latest('created_at')
            test_proj = "+proj=tmerc +lat_0=39.75527777777778 +lon_0=-104.8980555555556 +k=1.00025403 +x_0=182880.3657607315 +y_0=121920.2438404877 +ellps=GRS80 +units=us-ft +no_defs326"

            params = [
                ('orthophoto', {'formula': 'NDVI', 'bands': 'RGN'}, status.HTTP_200_OK),
                ('dsm', {'epsg': 4326}, status.HTTP_200_OK),
                ('dtm', {'epsg': 4326}, status.HTTP_200_OK),
                ('georeferenced_model', {'epsg': 4326}, status.HTTP_200_OK),
                ('georeferenced_model', {'epsg': 4326, 'resample': 2.5}, status.HTTP_200_OK)
            ]

            # Cannot export stuff
            for p in params:
                asset_type, data, _ = p
                res = client.post("/api/projects/{}/tasks/{}/{}/export".format(project.id, task.id, asset_type), data)
                self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

            # Assign invalid processing node to task via API
            res = client.patch("/api/projects/{}/tasks/{}/".format(project.id, task.id), {
                'processing_node': other_pnode.id
            })
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

            # Assign processing node to task via API
            res = client.patch("/api/projects/{}/tasks/{}/".format(project.id, task.id), {
                'processing_node': pnode.id
            })
            self.assertEqual(res.status_code, status.HTTP_200_OK)

            retry_count = 0
            while task.status != status_codes.COMPLETED:
                worker.tasks.process_pending_tasks()
                time.sleep(DELAY)
                task.refresh_from_db()
                retry_count += 1
                if retry_count > 10:
                    break

            self.assertEqual(task.status, status_codes.COMPLETED)

            # Can export stuff (basic)
            for p in params:
                asset_type, data, exp_status = p
                res = client.post("/api/projects/{}/tasks/{}/{}/export".format(project.id, task.id, asset_type), data)
                self.assertEqual(res.status_code, exp_status)
                reply = json.loads(res.content.decode("utf-8"))
                self.assertTrue("celery_task_id" in reply)
                celery_task_id = reply["celery_task_id"]

            # More exhaustive export testing
            params = [
                ('orthophoto', {}, True, ".tif", status.HTTP_200_OK),
                ('orthophoto', {'format': 'gtiff'}, True, ".tif", status.HTTP_200_OK),
                ('orthophoto', {'format': 'gtiff-rgb', 'rescale': "10,100"}, False, ".tif", status.HTTP_200_OK),
                ('orthophoto', {'format': 'laz'}, False, ".tif", status.HTTP_400_BAD_REQUEST),
                ('orthophoto', {'format': 'jpg', 'epsg': 4326}, False, ".jpg", status.HTTP_200_OK),
                ('orthophoto', {'format': 'jpg', 'proj': test_proj}, False, ".jpg", status.HTTP_200_OK),
                ('orthophoto', {'format': 'jpg', 'epsg': 4326, 'rescale': '10,200'}, False, ".jpg", status.HTTP_200_OK),
                ('orthophoto', {'format': 'png'}, False, ".png", status.HTTP_200_OK),
                ('orthophoto', {'format': 'kmz'}, False, ".kmz", status.HTTP_200_OK),
                
                ('orthophoto', {'formula': 'NDVI'}, False, "-NDVI.tif", status.HTTP_400_BAD_REQUEST),
                ('orthophoto', {'bands': 'RGN'}, False, "-NDVI.tif", status.HTTP_400_BAD_REQUEST),
                ('orthophoto', {'bands': 'RGN', 'formula': 'NDVI'}, False, "-NDVI.tif", status.HTTP_200_OK),
                
                ('dsm', {'format': 'gtiff'}, True, ".tif", status.HTTP_200_OK),
                ('dsm', {'epsg': 4326}, False, ".tif", status.HTTP_200_OK),
                ('dsm', {'format': 'jpg', 'epsg': 4326}, False, ".jpg", status.HTTP_200_OK),
                ('dsm', {'format': 'jpg', 'proj': test_proj}, False, ".jpg", status.HTTP_200_OK),
                ('dsm', {'format': 'jpg', 'color_map': 'jet', 'hillshade': 0, 'epsg': 3857}, False, ".jpg", status.HTTP_200_OK),
                ('dsm', {'epsg': 4326, 'format': 'jpg'}, False, ".jpg", status.HTTP_200_OK),
                ('dsm', {'epsg': 4326, 'format': 'gtiff-rgb'}, False, ".tif", status.HTTP_200_OK),
                ('dsm', {'format': 'kmz'}, False, ".kmz", status.HTTP_200_OK),
                ('dsm', {'color_map': 'viridis', 'hillshade': 2, 'format': 'png'}, False, ".png", status.HTTP_200_OK),
                ('dsm', {'rescale': 'invalid-but-works-cuz-gtiff'}, True, ".tif", status.HTTP_200_OK),
                
                ('dsm', {'epsg': 'invalid'}, False, ".tif", status.HTTP_400_BAD_REQUEST),
                ('dsm', {'format': 'invalid'}, False, ".tif", status.HTTP_400_BAD_REQUEST),
                ('dsm', {'hillshade': 'invalid'}, False, ".tif", status.HTTP_400_BAD_REQUEST),
                ('dsm', {'color_map': 'invalid'}, False, ".tif", status.HTTP_400_BAD_REQUEST),
                ('dsm', {'format': 'gtiff-rgb', 'rescale': 'invalid'}, False, ".tif", status.HTTP_400_BAD_REQUEST),
                ('dsm', {'format': 'las'}, False, ".tif", status.HTTP_400_BAD_REQUEST),
                
                ('dtm', {'format': 'gtiff'}, True, ".tif", status.HTTP_200_OK),
                ('dtm', {'epsg': 4326}, False, ".tif", status.HTTP_200_OK),
                ('dtm', {'proj': test_proj}, False, ".tif", status.HTTP_200_OK),

                ('georeferenced_model', {}, True, ".laz", status.HTTP_200_OK),
                ('georeferenced_model', {'format': 'las'}, False, ".las", status.HTTP_200_OK),
                ('georeferenced_model', {'format': 'ply'}, False, ".ply", status.HTTP_200_OK),
                ('georeferenced_model', {'format': 'csv'}, False, ".csv", status.HTTP_200_OK),
                ('georeferenced_model', {'format': 'las', 'epsg': 4326}, False, ".las", status.HTTP_200_OK),
                ('georeferenced_model', {'format': 'las', 'proj': test_proj}, False, ".las", status.HTTP_200_OK),

                ('georeferenced_model', {'format': 'tif'}, False, ".laz", status.HTTP_400_BAD_REQUEST),
            ]

            def testExport(crop = False):
                for p in params:
                    asset_type, data, shortcut_link, extension, exp_status = p
                    
                    # When cropping, there should never be shortcut links
                    if shortcut_link and crop:
                        shortcut_link = False
                    
                    logger.info("Testing {}".format(p))
                    res = client.post("/api/projects/{}/tasks/{}/{}/export".format(project.id, task.id, asset_type), data)
                    self.assertEqual(res.status_code, exp_status)

                    reply = json.loads(res.content.decode("utf-8"))

                    if res.status_code == status.HTTP_200_OK:
                        self.assertTrue("filename" in reply)
                        self.assertEqual(reply["filename"], "test-task-" + asset_type + extension)

                        if shortcut_link:
                            self.assertFalse("celery_task_id" in reply)
                            self.assertTrue("url" in reply)

                            # Can download
                            res = client.get(reply["url"])
                            self.assertEqual(res.status_code, status.HTTP_200_OK)
                        else:
                            self.assertTrue("celery_task_id" in reply)
                            self.assertFalse("url" in reply)

                            cres = TestSafeAsyncResult(celery_task_id)
                            c = 0
                            while not cres.ready():
                                time.sleep(0.2)
                                c += 1
                                if c > 50:
                                    self.assertTrue(False)
                                    break
                            
                            res = client.get("/api/workers/get/{}?filename={}".format(celery_task_id, reply["filename"]))
                            self.assertEqual(res.status_code, status.HTTP_200_OK)
                            self.assertEqual(res.headers['content-disposition'], 'attachment; filename={}'.format(reply["filename"]))
                    else:
                        self.assertTrue(len(reply[0]) > 0) # Error message

            # Test without crop
            testExport()

            # Set crop

            crop_geojson = {"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-91.99424117803576,46.84230591442068],[-91.99366182088853,46.84228940253027],[-91.99393808841705,46.84257010397711],[-91.99424117803576,46.84230591442068]]]}}
            res = client.patch("/api/projects/{}/tasks/{}/".format(project.id, task.id), {
                'crop': crop_geojson
            }, format="json")
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            task.refresh_from_db()
            self.assertTrue(task.crop is not None)

            # Test with crop
            testExport(crop=True)