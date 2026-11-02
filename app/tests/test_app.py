from django.contrib.auth.models import User, Group
from django.test import Client
from rest_framework import status
from guardian.shortcuts import assign_perm
from nodeodm.models import ProcessingNode

from app.models import Project, Task
from app.models import Setting
from app.models import Theme
from webodm import settings
from .classes import BootTestCase
from django.core.exceptions import ValidationError

class TestApp(BootTestCase):
    fixtures = ['test_processingnodes', ]

    def setUp(self):
        self.credentials = {
            'username': 'testuser',
            'password': 'test1234',
            'email': 'test@mail.com'}

        # Create a test Group
        my_group, created = Group.objects.get_or_create(name='test_group')

        # Add user to test Group
        User.objects.get(pk=1).groups.add(my_group)

        # Add view permissions
        user = User.objects.get(username=self.credentials['username'])
        pns = ProcessingNode.objects.all()
        for pn in pns:
            assign_perm('view_processingnode', user, pn)

    def test_user_login(self):
        c = Client()
        # User points the browser to the landing page
        res = c.post('/', follow=True)

        # the user is not logged in
        self.assertFalse(res.context['user'].is_authenticated)
        # and is redirected to the login page
        self.assertRedirects(res, '/login/')

        # The login page is being rendered by the correct template
        self.assertTemplateUsed(res, 'registration/login.html')

        # asks the user to login using a set of valid credentials
        res = c.post('/login/', data=self.credentials, follow=True)

        # The system acknowledges him
        self.assertTrue(res.context['user'].is_authenticated)

        # and moves him at the dashboard
        self.assertTemplateUsed(res, 'app/dashboard.html')

    def test_views(self):
        c = Client()

        # Connecting to dashboard without auth redirects to /
        res = c.get('/dashboard/', follow=True)
        self.assertFalse(res.context['user'].is_authenticated)
        self.assertRedirects(res, '/login/?next=/dashboard/')

        res = c.get('/processingnode/1/', follow=True)
        self.assertRedirects(res, '/login/?next=/processingnode/1/')

        res = c.get('/map/project/1/', follow=True)
        self.assertRedirects(res, '/login/?next=/map/project/1/')

        res = c.get('/3d/project/1/task/1/', follow=True)
        self.assertRedirects(res, '/login/?next=/3d/project/1/task/1/')

        # Login
        c.post('/login/', data=self.credentials, follow=True)

        # We should have a project created from the dashboard
        self.assertTrue(Project.objects.count() >= 1)

        # Can access API page
        res = c.get('/api/')
        self.assertTrue(res.status_code == status.HTTP_200_OK)

        # We can access a processingnode view that exists
        res = c.get('/processingnode/1/')
        self.assertTrue(res.status_code == 200)
        self.assertTemplateUsed(res, 'app/processing_node.html')

        # We can access a processingnode that is offline
        # (and there's a warning message when we do that)
        res = c.get('/processingnode/2/')
        self.assertTrue(res.status_code == 200)
        self.assertTemplateUsed(res, 'app/processing_node.html')

        message = list(res.context['messages'])[0]
        self.assertEqual(message.tags, 'warning')
        self.assertTrue("offline" in message.message)

        # The menu should have 3 processing nodes
        res = c.get('/dashboard/', follow=True)
        self.assertEqual(res.content.decode("utf-8").count('href="/processingnode/'), 3)
        self.assertTemplateUsed(res, 'app/dashboard.html')

        # There should be an onboarding message
        self.assertTrue('To create a map, press the' in res.content.decode("utf-8"))

        # But not if we disable it
        settings.DASHBOARD_ONBOARDING = False
        res = c.get('/dashboard/', follow=True)
        self.assertFalse('To create a map, press the' in res.content.decode("utf-8"))
        settings.DASHBOARD_ONBOARDING  = True        

        # The API should return 3 nodes
        res = c.get('/api/processingnodes/')
        self.assertEqual(len(res.data), 3)

        # We can change that with a setting
        settings.UI_MAX_PROCESSING_NODES = 1

        res = c.get('/dashboard/', follow=True)
        self.assertEqual(res.content.decode("utf-8").count('href="/processingnode/'), 1)
        self.assertTemplateUsed(res, 'app/dashboard.html')

        # There's no og:graph tag (no thumb)
        self.assertEqual(res.content.decode("utf-8").count('<meta property="og:image"'), 0)
        

        res = c.get('/api/processingnodes/')
        self.assertEqual(len(res.data), 1)

        settings.UI_MAX_PROCESSING_NODES = None

        res = c.get('/processingnode/9999/')
        self.assertTrue(res.status_code == 404)

        res = c.get('/processingnode/abc/')
        self.assertTrue(res.status_code == 404)

        # /map/ and /3d/ views
        user = User.objects.get(username="testuser")
        other_user = User.objects.get(username="testuser2")

        project = Project.objects.create(owner=user)
        task = Task.objects.create(project=project)
        other_project = Project.objects.create(owner=other_user)
        other_task = Task.objects.create(project=other_project)

        # Cannot access a project that we have no access to, or that does not exist
        for project_id in [other_project.id, 99999]:
            res = c.get('/map/project/{}/'.format(project_id))
            self.assertTrue(res.status_code == status.HTTP_404_NOT_FOUND)

        # We can access a project that we have access to
        res = c.get('/map/project/{}/'.format(project.id))
        self.assertTrue(res.status_code == status.HTTP_200_OK)

        # 3D views need project and task parameters
        res = c.get('/3d/project/{}/'.format(project.id))
        self.assertTrue(res.status_code == status.HTTP_404_NOT_FOUND)

        # Cannot access a 3d view for a task we have no access to
        res = c.get('/3d/project/{}/task/{}/'.format(other_project.id, other_task.id))
        self.assertTrue(res.status_code == status.HTTP_404_NOT_FOUND)

        # Can access 3d view for task we have access to
        res = c.get('/3d/project/{}/task/{}/'.format(project.id, task.id))
        self.assertTrue(res.status_code == status.HTTP_200_OK)

        # Cannot access public URLs unless a task is shared
        def test_public_task_views(client, expectedStatus):
            res = client.get('/public/task/{}/map/'.format(task.id))
            self.assertTrue(res.status_code == expectedStatus)
            if expectedStatus == status.HTTP_200_OK:
                self.assertEqual(res.content.decode("utf-8").count('<meta property="og:image"'), 1)

            res = client.get('/public/task/{}/3d/'.format(task.id))
            self.assertTrue(res.status_code == expectedStatus)
            if expectedStatus == status.HTTP_200_OK:
                self.assertEqual(res.content.decode("utf-8").count('<meta property="og:image"'), 1)
            
            res = client.get('/public/task/{}/iframe/3d/'.format(task.id))
            self.assertTrue(res.status_code == expectedStatus)
            res = client.get('/public/task/{}/iframe/map/'.format(task.id))
            self.assertTrue(res.status_code == expectedStatus)
            res = client.get('/public/task/{}/json/'.format(task.id))
            self.assertTrue(res.status_code == expectedStatus)
        
        # Cannot access certain public URLs unless a project is shared
        def test_public_project_views(client, expectedStatus):
            if project.public_id is not None:
                res = client.get('/public/project/{}/map/'.format(project.public_id))
                self.assertTrue(res.status_code == expectedStatus)
                if expectedStatus == status.HTTP_200_OK:
                    self.assertEqual(res.content.decode("utf-8").count('<meta property="og:image"'), 0)
                res = client.get('/public/project/{}/iframe/map/'.format(project.public_id))
                self.assertTrue(res.status_code == expectedStatus)
                res = client.get('/api/projects/{}/tasks/{}/'.format(project.id, task.id))
                self.assertTrue(res.status_code == expectedStatus)

            
        test_public_task_views(c, status.HTTP_404_NOT_FOUND)
        test_public_project_views(c, status.HTTP_404_NOT_FOUND)

        # Project should not have a public_id
        self.assertTrue(project.public_id is None)

        # Share task
        task.public = True
        task.save()

        # Can now access task URLs even as anonymous user
        ac = Client()
        test_public_task_views(ac, status.HTTP_200_OK)

        # Set project to public
        project.public = True
        project.save()
        project.refresh_from_db()

        # There should be a public_id
        self.assertTrue(project.public_id is not None)

        # Can access project/task URLs even as anonymous user
        test_public_project_views(ac, status.HTTP_200_OK)
        test_public_task_views(ac, status.HTTP_200_OK)

        # Unshare a task
        task.public = False
        task.save()

        # We can still access project/task URLs
        test_public_project_views(ac, status.HTTP_200_OK)
        test_public_task_views(ac, status.HTTP_200_OK)

    def test_admin_views(self):
        c = Client()
        c.login(username='testsuperuser', password='test1234')

        settingId = Setting.objects.all()[0].id # During tests, sometimes this is != 1
        themeId = Theme.objects.all()[0].id # During tests, sometimes this is != 1

        # Can access admin menu items
        admin_menu_items = ['/admin/app/setting/{}/change/'.format(settingId),
                            '/admin/app/theme/{}/change/'.format(themeId),
                            '/admin/',
                            '/admin/app/plugin/',
                            '/admin/auth/user/',
                            '/admin/auth/group/',
                            ]

        for url in admin_menu_items:
            res = c.get(url)
            self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Cannot access dev tools (not in dev mode)
        settings.DEV = False
        self.assertEqual(c.get('/dev-tools/').status_code, status.HTTP_404_NOT_FOUND)
        settings.DEV = True
        
        # Can access in dev mode
        self.assertEqual(c.get('/dev-tools/').status_code, status.HTTP_200_OK)

        # Cannot access admin views as normal user
        c.logout()
        c.login(username='testuser', password='test1234')

        # Can never access dev tools as user, even in dev mode
        self.assertRedirects(c.get('/dev-tools/', follow=True), '/login/?next=/dev-tools/')
        settings.DEV = False

        for url in admin_menu_items:
            res = c.get(url, follow=True)
            self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


    def test_default_group(self):
        # It exists
        self.assertTrue(Group.objects.filter(name='Default').count() == 1)

        # Verify that all new users are assigned to default group
        u = User.objects.create_user(username="default_user")
        u.refresh_from_db()
        self.assertTrue(u.groups.filter(name='Default').count() == 1)

    def test_projects(self):
        # Get a normal user
        user = User.objects.get(username="testuser")
        self.assertFalse(user.is_superuser)

        # Create a new project
        p = Project.objects.create(owner=user, name="test")

        # Have the proper permissions been set?
        self.assertTrue(user.has_perm("view_project", p))
        self.assertTrue(user.has_perm("add_project", p))
        self.assertTrue(user.has_perm("change_project", p))
        self.assertTrue(user.has_perm("delete_project", p))

        # Get a superuser
        superUser = User.objects.get(username="testsuperuser")
        self.assertTrue(superUser.is_superuser)

        # He should also have permissions, although not explicitly set
        self.assertTrue(superUser.has_perm("delete_project", p))

        # Get another user
        anotherUser = User.objects.get(username="testuser2")
        self.assertFalse(anotherUser.is_superuser)

        # Should not have permission
        self.assertFalse(anotherUser.has_perm("delete_project", p))

    def test_tasks(self):
        # Create a new task
        p = Project.objects.create(owner=User.objects.get(username="testuser"), name="test")
        task = Task.objects.create(project=p)

        # Test options validation
        task.options = [{'name': 'test', 'value': 1}]
        self.assertTrue(task.save() is None)

        task.options = {'test': 1}
        self.assertRaises(ValidationError, task.save)

        task.options = [{'name': 'test', 'value': 1}, {"invalid": 1}]
        self.assertRaises(ValidationError, task.save)
