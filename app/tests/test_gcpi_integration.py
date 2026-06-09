from django.test import Client
from rest_framework import status

from app.models import Basemap
from .classes import BootTestCase


class TestGcpiIntegration(BootTestCase):
    def test_gcpi_receives_admin_basemaps(self):
        Basemap.invalidate_cache()
        client = Client()
        self.assertTrue(client.login(username='testuser', password='test1234'))

        response = client.get('/plugins/posm-gcpi/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertContains(response, 'window.__webodmGcpiConfig')
        self.assertContains(response, 'swisstopo')
        self.assertContains(response, 'Ground Control Point Interface')
