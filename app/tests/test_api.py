import datetime
import os

from django.contrib.auth.models import User
from guardian.shortcuts import assign_perm, get_objects_for_user
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_jwt.settings import api_settings

from app import pending_actions
from app.api.pagination import PageNumberPaginationWithPageSize
from app.models import Project, Task
from app.plugins.signals import processing_node_removed
from app.tests.utils import catch_signal
from nodeodm import status_codes
from nodeodm.models import ProcessingNode
from .classes import BootTestCase
from webodm import settings


class TestApi(BootTestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_project_pagination_exposes_configured_page_size(self):
        client = APIClient()
        client.login(username="testuser", password="test1234")

        original_page_size = PageNumberPaginationWithPageSize.page_size
        PageNumberPaginationWithPageSize.page_size = 1
        try:
            res = client.get('/api/projects/?page=1')
        finally:
            PageNumberPaginationWithPageSize.page_size = original_page_size

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['page_size'], 1)
        self.assertEqual(len(res.data['results']), 1)

    def test_projects_and_tasks(self):
        client = APIClient()

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

        # Forbidden without credentials
        res = client.get('/api/projects/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        client.login(username="testuser", password="test1234")
        res = client.get('/api/projects/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) > 0)

        res = client.get('/api/projects/?page=1')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data['results']) > 0)

        # Can sort
        res = client.get('/api/projects/?ordering=-created_at&page=1')
        last_project = Project.objects.filter(owner=user).latest('created_at')
        self.assertTrue(res.data["results"][0]['id'] == last_project.id)

        res = client.get('/api/projects/{}/'.format(project.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        res = client.get('/api/projects/dasjkldas/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        res = client.get('/api/projects/{}/'.format(other_project.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Can filter
        res = client.get('/api/projects/?name=999&page=1')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data["results"]) == 0)

        # Cannot list somebody else's project without permission
        res = client.get('/api/projects/?id={}&page=1'.format(other_project.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data["results"]) == 0)

        # Can access individual project
        res = client.get('/api/projects/{}/'.format(project.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["id"] == project.id)

        # Cannot access project for which we have no access to
        res = client.get('/api/projects/{}/'.format(other_project.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Can create project, but owner cannot be set
        res = client.post('/api/projects/', {'name': 'test', 'description': 'test descr'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Project.objects.get(pk=res.data['id']).owner.id == user.id)

        # Cannot leave name empty
        res = client.post('/api/projects/', {'description': 'test descr'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


        # Create some tasks
        task = Task.objects.create(project=project)
        task2 = Task.objects.create(project=project, created_at=task.created_at + datetime.timedelta(0, 1))
        other_task = Task.objects.create(project=other_project)

        # Can list project tasks to a project we have access to
        res = client.get('/api/projects/{}/tasks/'.format(project.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) == 2)

        # Can sort
        res = client.get('/api/projects/{}/tasks/?ordering=created_at'.format(project.id))
        self.assertTrue(res.data[0]['id'] == str(task.id))
        self.assertTrue(res.data[1]['id'] == str(task2.id))

        res = client.get('/api/projects/{}/tasks/?ordering=-created_at'.format(project.id))
        self.assertTrue(res.data[0]['id'] == str(task2.id))
        self.assertTrue(res.data[1]['id'] == str(task.id))

        # Cannot list project tasks for a project we don't have access to
        res = client.get('/api/projects/{}/tasks/'.format(other_project.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Cannot list project tasks for a project that doesn't exist
        res = client.get('/api/projects/999/tasks/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Can list task details for a task belonging to a project we have access to
        res = client.get('/api/projects/{}/tasks/{}/'.format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["id"] == str(task.id))

        # images_count field exists
        self.assertTrue(res.data["images_count"] == 0)

        # can_rerun_from field exists, should be an empty list at this point
        self.assertTrue(len(res.data["can_rerun_from"]) == 0)

        # Get console output
        res = client.get('/api/projects/{}/tasks/{}/output/'.format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data == "")

        data_path = task.data_path()
        if not os.path.exists(data_path):
            os.makedirs(data_path, exist_ok=True)

        task.console.reset("line1\nline2\nline3")
        task.save()

        res = client.get('/api/projects/{}/tasks/{}/output/'.format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, task.console.output())

        # Console output with line num
        res = client.get('/api/projects/{}/tasks/{}/output/?line=2'.format(project.id, task.id))
        self.assertEqual(res.data, "line3")

        # Console output with line num out of bounds
        res = client.get('/api/projects/{}/tasks/{}/output/?line=3'.format(project.id, task.id))
        self.assertEqual(res.data, "")
        res = client.get('/api/projects/{}/tasks/{}/output/?line=-1'.format(project.id, task.id))
        self.assertEqual(res.data, task.console.output())

        # Console output with limit
        res = client.get('/api/projects/{}/tasks/{}/output/?line=0&limit=2'.format(project.id, task.id))
        self.assertEqual(res.data, "line1\nline2")

        # Console output with negative limit
        res = client.get('/api/projects/{}/tasks/{}/output/?line=0&limit=-2'.format(project.id, task.id))
        self.assertEqual(res.data, "line2\nline3")
        
        # Console output json/raw format
        res = client.get('/api/projects/{}/tasks/{}/output/?line=0&limit=-2&f=json'.format(project.id, task.id))
        j = res.json()
        self.assertEqual(j['lines'][0], "line2")
        self.assertEqual(j['lines'][1], "line3")
        self.assertEqual(j['count'], 3)

        res = client.get('/api/projects/{}/tasks/{}/output/?line=0&limit=-2&f=raw'.format(project.id, task.id))
        self.assertEqual(res.content.decode("utf-8"), "line2\nline3")

        # Cannot list task details for a task belonging to a project we don't have access to
        res = client.get('/api/projects/{}/tasks/{}/'.format(other_project.id, other_task.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # As above, but by trying to trick the API by using a project we have access to
        res = client.get('/api/projects/{}/tasks/{}/'.format(project.id, other_task.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Cannot duplicate a project we have no access to
        res = client.post('/api/projects/{}/duplicate/'.format(other_project.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Can duplicate a project we have access to
        res = client.post('/api/projects/{}/duplicate/'.format(project.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data.get('success'))
        new_project_id = res.data['project']['id']
        self.assertNotEqual(new_project_id, project.id)

        # Tasks have been duplicated
        duplicated_project = Project.objects.get(pk=new_project_id)
        self.assertEqual(project.task_set.count(), duplicated_project.task_set.count())

        # Cannot access task details for a task that doesn't exist
        res = client.get('/api/projects/{}/tasks/4004d1e9-ed2c-4983-8b93-fc7577ee6d89/'.format(project.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Cannot access task details for a malformed task id
        res = client.get('/api/projects/{}/tasks/0/'.format(project.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Can update a task
        res = client.patch('/api/projects/{}/tasks/{}/'.format(project.id, task.id), {'name': 'updated!'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Verify the task has been updated
        res = client.get('/api/projects/{}/tasks/{}/'.format(project.id, task.id))
        self.assertTrue(res.data["name"] == "updated!")

        # Cannot update a task we have no access to
        res = client.patch('/api/projects/{}/tasks/{}/'.format(other_project.id, other_task.id), {'name': 'updated!'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Can cancel a task for which we have permission
        self.assertTrue(task.pending_action is None)
        res = client.post('/api/projects/{}/tasks/{}/cancel/'.format(project.id, task.id))
        self.assertTrue(res.data["success"])
        task.refresh_from_db()

        # Task should have been canceled
        self.assertTrue(task.last_error is None)
        self.assertEqual(task.status, status_codes.CANCELED)

        res = client.post('/api/projects/{}/tasks/{}/restart/'.format(project.id, task.id))
        self.assertTrue(res.data["success"])
        task.refresh_from_db()

        # Task should have failed to be restarted
        self.assertTrue("has no processing node" in task.last_error)

        # Cannot cancel, restart, delete, compact a task for which we don't have permission
        for action in ['cancel', 'remove', 'restart', 'compact']:
            res = client.post('/api/projects/{}/tasks/{}/{}/'.format(other_project.id, other_task.id, action))
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Can compact
        self.assertFalse(task.compacted)
        res = client.post('/api/projects/{}/tasks/{}/compact/'.format(project.id, task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertTrue(task.compacted)

        # Can delete
        res = client.post('/api/projects/{}/tasks/{}/remove/'.format(project.id, task.id))
        self.assertTrue(res.data["success"])
        self.assertFalse(Task.objects.filter(id=task.id).exists())

        task = Task.objects.create(project=project)
        temp_project = Project.objects.create(owner=user)

        # We have permissions to do anything on a project that we own
        res = client.get('/api/projects/{}/'.format(project.id))
        for perm in ['delete', 'change', 'view', 'add']:
            self.assertTrue(perm in res.data['permissions'])

        # Can delete project that we we own
        res = client.delete('/api/projects/{}/'.format(temp_project.id))
        self.assertTrue(res.status_code == status.HTTP_204_NO_CONTENT)
        self.assertTrue(Project.objects.filter(id=temp_project.id).count() == 0) # Really deleted

        # Cannot delete a project we don't own
        other_temp_project = Project.objects.create(owner=other_user)
        res = client.delete('/api/projects/{}/'.format(other_temp_project.id))
        self.assertTrue(res.status_code == status.HTTP_404_NOT_FOUND)

        assign_perm('view_project', user, other_temp_project)

        # We have view permissions only
        res = client.get('/api/projects/{}/'.format(other_temp_project.id))
        self.assertTrue('view' in res.data['permissions'])
        for perm in ['delete', 'change', 'add']:
            self.assertFalse(perm in res.data['permissions'])

        # Can delete a project for which we just have view permissions
        # (we will just remove our read permissions without deleting the project)
        res = client.delete('/api/projects/{}/'.format(other_temp_project.id))
        self.assertTrue(res.status_code == status.HTTP_204_NO_CONTENT)
        
        # Project still exists
        self.assertTrue(Project.objects.filter(id=other_temp_project.id).count() == 1)

        # We just can't access it
        res = client.get('/api/projects/{}/'.format(other_temp_project.id))
        self.assertTrue(res.status_code == status.HTTP_404_NOT_FOUND)

        # A user cannot reassign a task to a
        # project for which he/she has no permissions
        res = client.patch('/api/projects/{}/tasks/{}/'.format(project.id, task.id), {'project': other_project.id},
                           format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # A user cannot reassign a task to a
        # project for which he/she has no permissions (using uppercase)
        res = client.patch('/api/projects/{}/tasks/{}/'.format(project.id, task.id), {'PROJECT': other_project.id},
                           format='json')

        # Request went through, but no changes were applied
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertTrue(task.project.id == project.id)

        # A user cannot update a task's read only fields
        self.assertTrue(task.pending_action != 0)
        res = client.patch('/api/projects/{}/tasks/{}/'.format(project.id, task.id), {
                'processing_time': 1234,
                'status': -99,
                'last_error': 'yo!',
                'created_at': 0,
                'pending_action': 0,
                'can_rerun_from': ['abc']
            }, format='json')

        # Operation should fail without errors, but nothing has changed in the DB
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertTrue(task.processing_time != 1234)
        self.assertTrue(task.status != -99)
        self.assertTrue(task.last_error != 'yo!')
        self.assertTrue(task.created_at != 0)
        self.assertTrue(task.pending_action != 0)
        self.assertTrue(len(res.data['can_rerun_from']) == 0)

    def test_processingnodes(self):
        client = APIClient()

        pnode = ProcessingNode.objects.create(
                hostname="localhost",
                port=999
            )

        another_pnode = ProcessingNode.objects.create(
            hostname="localhost",
            port=998
        )

        # Cannot list processing nodes as guest
        res = client.get('/api/processingnodes/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        res = client.get('/api/processingnodes/{}/'.format(pnode.id))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Cannot get options as guest
        res = client.get('/api/processingnodes/options/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        client.login(username="testuser", password="test1234")

        # Cannot list processing nodes, unless permissions have been granted
        res = client.get('/api/processingnodes/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) == 0)

        user = User.objects.get(username="testuser")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_perm('view_processingnode', pnode))
        assign_perm('view_processingnode', user, pnode)
        self.assertTrue(user.has_perm('view_processingnode', pnode))

        # Now we can list processing nodes as normal user
        res = client.get('/api/processingnodes/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) == 1)
        self.assertTrue(res.data[0]["hostname"] == "localhost")

        # Can use filters
        res = client.get('/api/processingnodes/?id={}'.format(pnode.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) == 1)

        res = client.get('/api/processingnodes/?id={}'.format(another_pnode.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) == 0)

        # Can filter nodes with valid options
        res = client.get('/api/processingnodes/?has_available_options=true')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) == 0)

        res = client.get('/api/processingnodes/?has_available_options=false')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) == 1)
        self.assertTrue(res.data[0]['hostname'] == 'localhost')


        # Can get single processing node as normal user
        res = client.get('/api/processingnodes/{}/'.format(pnode.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["hostname"] == "localhost")

        # Verify online field exists
        self.assertTrue("online" in res.data)

        # Should be set to false
        self.assertFalse(res.data['online'])

        # Verify max images field
        self.assertTrue("max_images" in res.data)

        # Verify engine version
        self.assertTrue("engine_version" in res.data)

        # Verify engine
        self.assertTrue("engine" in res.data)

        # label should be hostname:port (since no label is set)
        self.assertEqual(res.data['label'], pnode.hostname + ":" + str(pnode.port))

        # If we update the label, the label is used instead
        pnode.label = "Test"
        pnode.save()

        res = client.get('/api/processingnodes/{}/'.format(pnode.id))
        self.assertEqual(res.data['label'], "Test")

        # Cannot delete a processing node as normal user
        res = client.delete('/api/processingnodes/{}/'.format(pnode.id))
        self.assertTrue(res.status_code, status.HTTP_403_FORBIDDEN)

        # Cannot create a processing node as normal user
        res = client.post('/api/processingnodes/', {'hostname': 'localhost', 'port':'1000'})
        self.assertTrue(res.status_code, status.HTTP_403_FORBIDDEN)

        client.login(username="testsuperuser", password="test1234")

        # Can delete a processing node as super user
        # and a signal is sent when a processing node is deleted
        with catch_signal(processing_node_removed) as h1:
            res = client.delete('/api/processingnodes/{}/'.format(pnode.id))
            self.assertTrue(res.status_code, status.HTTP_200_OK)
        h1.assert_called_once_with(sender=ProcessingNode, processing_node_id=pnode.id, signal=processing_node_removed)

        # Can create a processing node as super user
        res = client.post('/api/processingnodes/', {'hostname': 'localhost', 'port':'1000'})
        self.assertTrue(res.status_code, status.HTTP_200_OK)

        # Verify node has been created
        res = client.get('/api/processingnodes/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) == 2)
        self.assertTrue(res.data[1]["port"] == 1000)

        # Test available_options intersection
        # (with normal user)
        client.login(username="testuser", password="test1234")
        user = User.objects.get(username="testuser")
        self.assertFalse(user.is_superuser)

        p1 = ProcessingNode.objects.create(hostname="invalid-host", port=11223,
                                           last_refreshed=timezone.now(),
                                           available_options=[{'name': 'a'}, {'name': 'b'}])
        p2 = ProcessingNode.objects.create(hostname="invalid-host-2", port=11223,
                                           last_refreshed=timezone.now(),
                                           available_options=[{'name': 'a'}, {'name': 'c'}])
        p3 = ProcessingNode.objects.create(hostname="invalid-host-3", port=11223,
                                           last_refreshed=timezone.now(),
                                           available_options=[{'name': 'd'}])
        p4 = ProcessingNode.objects.create(hostname="invalid-host-4", port=11223,
                                           last_refreshed=timezone.now() - datetime.timedelta(minutes=settings.NODE_OFFLINE_MINUTES * 2),
                                           available_options=[{'name': 'd'}]) # offline

        assign_perm('view_processingnode', user, p1)
        assign_perm('view_processingnode', user, p2)
        assign_perm('view_processingnode', user, p4)
        self.assertFalse(user.has_perm('view_processingnode', p3))

        nodes_available = get_objects_for_user(user, 'view_processingnode', ProcessingNode, accept_global_perms=False).exclude(available_options=dict())
        self.assertTrue(len(nodes_available) == 3)

        res = client.get('/api/processingnodes/options/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) == 1)
        self.assertTrue(res.data[0]['name'] == 'a')

        # Test optimistic mode
        self.assertFalse(p4.is_online())

        settings.NODE_OPTIMISTIC_MODE = True

        self.assertTrue(p4.is_online())
        res = client.get('/api/processingnodes/')
        self.assertEqual(len(res.data), 3)
        for nodes in res.data:
            self.assertTrue(nodes['online'])

        settings.NODE_OPTIMISTIC_MODE = False

    def test_token_auth(self):
        client = APIClient()

        pnode = ProcessingNode.objects.create(
            hostname="localhost",
            port=999
        )

        # Cannot access resources
        res = client.get('/api/processingnodes/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Cannot generate token with invalid credentials
        res = client.post('/api/token-auth/', {
            'username': 'testuser',
            'password': 'wrongpwd'
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Can generate token with valid credentials
        res = client.post('/api/token-auth/', {
            'username': 'testuser',
            'password': 'test1234'
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        token = res.data['token']
        self.assertTrue(len(token) > 0)

        # Can access resources by passing token via querystring
        res = client.get('/api/processingnodes/?jwt={}'.format(token))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Can access resources by passing token via header
        client = APIClient(HTTP_AUTHORIZATION="{0} {1}".format(api_settings.JWT_AUTH_HEADER_PREFIX, token))
        res = client.get('/api/processingnodes/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
