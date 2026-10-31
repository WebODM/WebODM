import os
from datetime import timedelta, datetime

import requests
from django.test import TestCase
import time
from django.utils import timezone
from os import path

from pyodx import Node
from pyodx.exceptions import NodeConnectionError, NodeServerError, NodeResponseError
from webodm import settings
from app.tests.utils import start_processing_node
from .models import ProcessingNode
from . import status_codes

current_dir = path.dirname(path.realpath(__file__))


class TestClientApi(TestCase):
    fixtures = ['test_processingnodes', ]

    @classmethod
    def setUpClass(cls):
        super(TestClientApi, cls).setUpClass()

    @classmethod
    def tearDownClass(cls):
        super(TestClientApi, cls).tearDownClass()


    def setUp(self):
        self.api_client = Node("localhost", 11223)

    def tearDown(self):
        pass

    def test_offline_api(self):
        api = Node("offline-host", 3000)
        self.assertRaises(NodeConnectionError, api.info)
        self.assertRaises(NodeConnectionError, api.options)

    def test_info(self):
        with start_processing_node():
            info = self.api_client.info()
            self.assertTrue(isinstance(info.version, str), "Found version string")
            self.assertTrue(isinstance(info.task_queue_count, int), "Found task queue count")
            self.assertTrue(info.max_images is None, "Found task max images")

    def test_options(self):
        with start_processing_node():
            options = self.api_client.options()
            self.assertTrue(len(options) > 0, "Found options")

    def test_online_processing_node(self):
        with start_processing_node():
            online_node = ProcessingNode.objects.get(pk=1)
            self.assertTrue(str(online_node) == "localhost:11223", "Formatting string works")
            self.assertTrue(online_node.last_refreshed == None, "Last refreshed not yet set")
            self.assertTrue(len(online_node.available_options) == 0, "Available options not yet set")
            self.assertTrue(online_node.api_version == "", "API version is not set")

            self.assertTrue(online_node.update_node_info(), "Could update info")
            self.assertTrue(online_node.last_refreshed is not None, "Last refreshed is set")
            self.assertTrue(len(online_node.available_options) > 0, "Available options are set")
            self.assertTrue(online_node.api_version != "", "API version is set")
            self.assertTrue(online_node.max_images is None, "No max images limit is set")
            
            self.assertTrue(isinstance(online_node.get_available_options_json(), str), "Available options json works")
            self.assertTrue(isinstance(online_node.get_available_options_json(pretty=True), str), "Available options json works with pretty")


    def test_offline_processing_node(self):
        offline_node = ProcessingNode.objects.get(pk=2)
        self.assertFalse(offline_node.update_node_info(), "Could not update info (offline)")
        self.assertTrue(offline_node.api_version == "", "API version is not set")

    def test_auto_update_node_info(self):
        with start_processing_node():
            online_node = ProcessingNode.objects.create(hostname="localhost", port=11223)
            self.assertTrue(online_node.last_refreshed != None, "Last refreshed info is here (update_node_info() was called)")

    def test_client_api_and_task_methods(self):
        def wait_for_status(api, uuid, status, num_retries = 10, error_description = "Failed to wait for status"):
            retries = 0
            while True:
                try:
                    task_info = api.get_task(uuid).info()
                    if task_info.status.value == status:
                        return True
                except (NodeServerError, NodeResponseError):
                    pass

                time.sleep(0.5)
                retries += 1
                if retries >= num_retries:
                    self.assertTrue(False, error_description)
                    return False

        with start_processing_node():
            api = Node("localhost", 11223)
            online_node = ProcessingNode.objects.get(pk=1)

            # Can call info(), options()
            self.assertTrue(type(api.info().version) == str)
            self.assertTrue(len(api.options()) > 0)
            
            # Can call new_task()
            import glob
            res = api.create_task(
                    glob.glob("nodeodm/fixtures/test_images/*.JPG"), 
                    {'force-ccd': 6.16},
                    "test")
            uuid = res.uuid
            self.assertTrue(uuid != None)

            # Can call task_info()
            task = api.get_task(uuid)
            task_info = task.info()
            self.assertTrue(isinstance(task_info.date_created, datetime))
            self.assertTrue(isinstance(task_info.uuid, str))

            # Can download assets?
            # Here we are waiting for the task to be completed
            wait_for_status(api, uuid, status_codes.COMPLETED, 10, "Could not download assets")
            asset = api.get_task(uuid).download_zip(settings.MEDIA_TMP)
            self.assertTrue(os.path.exists(asset))

            # task_output
            self.assertTrue(isinstance(api.get_task(uuid).output(0), list))
            self.assertTrue(isinstance(online_node.get_task_console_output(uuid, 0), list))

            self.assertRaises(NodeResponseError, online_node.get_task_console_output, "wrong-uuid", 0)

            # Can restart task
            self.assertTrue(online_node.restart_task(uuid))
            self.assertRaises(NodeResponseError, online_node.restart_task, "wrong-uuid")

            wait_for_status(api, uuid, status_codes.COMPLETED, 10, "Could not restart task")

            # Can restart task by passing options
            self.assertTrue(online_node.restart_task(uuid, [{'name': 'mesh-size', 'value': 12345},
                                                            {'name': 'invalid', 'value': True}]))
            wait_for_status(api, uuid, status_codes.COMPLETED, 10, "Could not restart task with options")

            # Verify that options have been updated after restarting the task
            task_info = api.get_task(uuid).info()
            self.assertEqual(len(task_info.options), 4) # pc-ept, cog, gltf have been added
            self.assertTrue(task_info.options[0]['name'] == 'mesh-size')
            self.assertTrue(task_info.options[0]['value'] == 12345)

            # Can cancel task (should work even if we completed the task)
            self.assertTrue(online_node.cancel_task(uuid))
            self.assertRaises(NodeResponseError, online_node.cancel_task, "wrong-uuid")

            # Wait for task to be canceled
            wait_for_status(api, uuid, status_codes.CANCELED, 5, "Could not remove task")
            self.assertTrue(online_node.remove_task(uuid))
            self.assertRaises(NodeResponseError, online_node.remove_task, "wrong-uuid")

            # Cannot delete task again
            self.assertRaises(NodeResponseError, online_node.remove_task, uuid)

            # Task has been deleted
            self.assertRaises(NodeResponseError, online_node.get_task_info, uuid)

            # Test URL building for HTTPS
            sslApi = Node("localhost", 443, 'abc')
            self.assertEqual(sslApi.url('/info'), 'https://localhost/info?token=abc')

    def test_find_best_available_node_and_is_online(self):
        with start_processing_node():
            # Fixtures are all offline
            self.assertTrue(ProcessingNode.find_best_available_node() is None)

            # Bring one online
            pnode = ProcessingNode.objects.get(pk=1)
            self.assertFalse(pnode.is_online())

            pnode.last_refreshed = timezone.now()
            pnode.queue_count = 2
            pnode.save()

            self.assertTrue(pnode.is_online())
            self.assertTrue(ProcessingNode.find_best_available_node().id == pnode.id)

            # Bring another online with lower queue count
            another_pnode = ProcessingNode.objects.get(pk=2)
            another_pnode.last_refreshed = pnode.last_refreshed
            another_pnode.queue_count = 1
            another_pnode.save()

            self.assertTrue(ProcessingNode.find_best_available_node().id == another_pnode.id)

            # Bring it offline
            another_pnode.last_refreshed -= timedelta(minutes=settings.NODE_OFFLINE_MINUTES)
            another_pnode.save()
            self.assertFalse(another_pnode.is_online())

            # Best choice now is original processing node
            self.assertTrue(ProcessingNode.find_best_available_node().id == pnode.id)

    def test_token_auth(self):
        def wait_for_status(api, uuid, status, num_retries=10, error_description="Failed to wait for status"):
            retries = 0
            while True:
                try:
                    task_info = api.get_task(uuid).info()
                    if task_info.status.value == status:
                        return True
                except (NodeResponseError, NodeServerError):
                    pass

                time.sleep(0.5)
                retries += 1
                if retries >= num_retries:
                    self.assertTrue(False, error_description)
                    return False

        with start_processing_node(['--token', 'test_token']):
            api = Node("localhost", 11223, "test_token")
            online_node = ProcessingNode.objects.get(pk=3)

            self.assertTrue(online_node.update_node_info(), "Could update info")

            # Cannot call info(), options()  without tokens
            api.token = "invalid"
            self.assertRaises(NodeResponseError, api.info)
            self.assertRaises(NodeResponseError, api.options)

            # Cannot call create_task() without token
            import glob
            self.assertRaises(NodeResponseError, api.create_task, glob.glob("nodeodm/fixtures/test_images/*.JPG"))

            # Can call create_task() with token
            api.token = "test_token"
            res = api.create_task(
                glob.glob("nodeodm/fixtures/test_images/*.JPG"))
            uuid = res.uuid
            self.assertTrue(uuid != None)

            # Can call task_info() with token
            task_info = api.get_task(uuid).info()
            self.assertTrue(isinstance(task_info.date_created, datetime))

            # Cannot call task_info() without token
            api.token = "invalid"
            try:
                api.get_task(uuid).info()
            except NodeResponseError as e:
                self.assertTrue('token does not match' in str(e))

            # Here we are waiting for the task to be completed
            api.token = "test_token"
            wait_for_status(api, uuid, status_codes.COMPLETED, 10, "Could not download assets")

            # Cannot download assets without token
            api.token = "invalid"
            task = api.get_task(uuid)
            self.assertRaises(NodeResponseError, task.download_assets, settings.MEDIA_TMP)

            api.token = "test_token"
            asset_archive = task.download_zip(settings.MEDIA_TMP)
            self.assertTrue(os.path.exists(asset_archive))
            os.unlink(asset_archive)

            # Cannot get task output without token
            api.token = "invalid"
            self.assertRaises(NodeResponseError, task.output, 0)

            api.token = "test_token"
            res = task.output()
            self.assertTrue(isinstance(res, list))

            # Cannot restart task without token
            online_node.token = "invalid"
            self.assertRaises(NodeResponseError, online_node.restart_task, uuid)

            online_node.token = "test_token"
            self.assertTrue(online_node.restart_task(uuid))

            # Cannot cancel task without token
            online_node.token = "invalid"
            self.assertRaises(NodeResponseError, online_node.cancel_task, uuid)
            online_node.token = "test_token"
            self.assertTrue(online_node.cancel_task(uuid))

            # Wait for task to be canceled
            wait_for_status(api, uuid, status_codes.CANCELED, 5, "Could not cancel task")

            # Cannot delete task without token
            online_node.token = "invalid"
            self.assertRaises(NodeResponseError, online_node.remove_task, "invalid token")
            online_node.token = "test_token"
            self.assertTrue(online_node.remove_task(uuid))
