import json

from django.test import Client
from django.contrib.auth.models import User
from rest_framework import status

from app.models import Basemap, Project, Task
from .classes import BootTestCase


class TestBasemap(BootTestCase):
    def setUp(self):
        pass

    def test_basemap(self):
        # There should be 4 basemaps by default
        self.assertEqual(Basemap.objects.all().count(), 4)
        self.assertTrue(
            Basemap.objects.filter(label='SWISSIMAGE (swisstopo)').exists()
        )

        Basemap.objects.all().delete()
        Basemap.invalidate_cache()

        # Test get_cached_basemaps, default handling

        b1 = Basemap.objects.create(
            default=True,
            type='tms',
            url='//tiles-a/{z}/{x}/{y}.png',
            label='A',
            maxzoom=20,
            minzoom=0,
        )

        b2 = Basemap.objects.create(
            default=True,
            type='tms',
            url='//tiles-b/{z}/{x}/{y}.png',
            label='B',
            maxzoom=20,
            minzoom=0,
        )

        b1.refresh_from_db()
        b2.refresh_from_db()

        self.assertFalse(b1.default)
        self.assertTrue(b2.default)
        self.assertEqual(Basemap.objects.filter(default=True).count(), 1)

        basemaps = Basemap.get_cached_basemaps()

        self.assertEqual(len(basemaps), 2)
        self.assertEqual(basemaps[0]['label'], 'B')
        self.assertEqual(basemaps[1]['label'], 'A')

        b1.label = 'C'
        b1.save()
        cached = Basemap.get_cached_basemaps()

        self.assertEqual(cached[0]['label'], 'B')
        self.assertEqual(cached[1]['label'], 'C')

        b1.delete()
        cached = Basemap.get_cached_basemaps()
        self.assertEqual(len(cached), 1)

        # Make sure basemaps param is sent to Map component

        client = Client()
        client.login(username='testuser', password='test1234')

        project = Project.objects.create(
            owner=User.objects.get(username='testuser'), 
            name='Test Project'
        )
        task = Task.objects.create(
            project=project,
            name="Test task",
            public=True
        )
        
        for url in ['/map/project/{}/'.format(project.id),
                   '/public/task/{}/map/'.format(task.id),
                   '/dashboard/']:
            response = client.get(url)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            params = dict(response.context['params'])
            basemaps = json.loads(params['basemaps'])
            self.assertTrue(any(bm['label'] == 'B' for bm in basemaps))
        
        # Cannot access admin endpoint as user
        response = client.get('/admin/app/basemap/')
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        # Can access admin endpoint as admin
        client.login(username='testsuperuser', password='test1234')
        response = client.get('/admin/app/basemap/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
