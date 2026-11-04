import logging

import json
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from app.models import Project, Task
from app.tests.classes import BootTestCase
from app.geoutils import bbox_to_polygon

logger = logging.getLogger('app.logger')

class TestCrop(BootTestCase):
    def setUp(self):
        super().setUp()

    def test_crop(self):
        client = APIClient()
        client.login(username="testuser", password="test1234")

        user = User.objects.get(username="testuser")
        project = Project.objects.create(
            owner=user,
            name="test project",
        )

        t = Task.objects.create(project=project, name="test task", epsg=32615)
        self.assertTrue(t.crop is None)
        self.assertTrue(t.get_projected_crop() is None)

        crop_geojson = {"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-91.99424117803576,46.84230591442068],[-91.99366182088853,46.84228940253027],[-91.99393808841705,46.84257010397711],[-91.99424117803576,46.84230591442068]]]}}
        coords = crop_geojson["geometry"]["coordinates"][0]
        xs, ys = zip(*coords)
        bbox = [min(xs), min(ys), max(xs), max(ys)]
        bbox[2] -= 0.0001 # Move X
        bbox[3] -= 0.0001 # Move Y
        
        t.orthophoto_extent = bbox_to_polygon(bbox)
        t.save()

        # Cannot set a self-intersecting polygon
        # (should silently fail)
        crop_invalid = {"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-91.99406415224075,46.84238582215199],[-91.99387907981874,46.84261331845379],[-91.99374094605449,46.84243168841939],[-91.99411109089851,46.8425454365936],[-91.99406415224075,46.84238582215199]]]}}
        res = client.patch("/api/projects/{}/tasks/{}/".format(project.id, t.id), {
            'crop': crop_invalid
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        t.refresh_from_db()
        self.assertTrue(t.crop is None)

        # Can update with valid crop
        res = client.patch("/api/projects/{}/tasks/{}/".format(project.id, t.id), {
            'crop': crop_geojson
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        t.refresh_from_db()

        self.assertTrue(t.crop is not None)

        # It should have cropped the polygon to the orthophoto boundary
        for coord in t.crop['coordinates'][0]:
            self.assertTrue(coord[0] <= bbox[2])
            self.assertTrue(coord[0] >= bbox[0])
            self.assertTrue(coord[1] <= bbox[3])
            self.assertTrue(coord[1] >= bbox[1])
        
        self.assertTrue(t.get_model_display_params()['crop_projected'] is not None)
        self.assertTrue(t.get_model_display_params()['crop_projected'] is not None)
