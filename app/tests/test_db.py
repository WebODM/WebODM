from app.geoutils import bbox_to_polygon

from .classes import BootTestCase
from app.models import Task, Project

class TestApi(BootTestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_db(self):
        task = Task.objects.create(project=Project.objects.latest("created_at"),
                                   orthophoto_extent=bbox_to_polygon([1, 2, 3, 4]))
        task.refresh_from_db()
        self.assertEqual(task.orthophoto_extent['type'], 'Polygon')
        self.assertEqual(task.get_extent(), (1, 2, 3, 4))
