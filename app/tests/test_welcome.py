from django.contrib.auth.models import User
from django.test import Client

from app.models import Project
from .classes import BootTestCase


class TestWelcome(BootTestCase):

    def setUp(self):
        Project.objects.all().delete()

        # Start with no users
        User.objects.all().delete()

    def tearDown(self):
        pass

    def test_first_screen(self):
        c = Client()

        # User points the browser to the website
        res = c.get('/', follow=True)

        # User is redirected to the welcome page
        self.assertRedirects(res, '/welcome/')

        # The welcome page is being rendered by the correct template
        self.assertTemplateUsed(res, 'app/welcome.html')

        # User cannot create an admin user without password
        res = c.post('/welcome/', data={
            'username': 'testadminuser',
            'password': ''}, follow=True)
        self.assertFormError(res.context['firstuserform'], 'password', 'This field is required.')
        self.assertTrue(User.objects.count() == 0, 'No users were created')

        # User can create admin user
        res = c.post('/welcome/', data={
            'username': 'testadminuser',
            'password': 'testadminpass'}, follow=True)
        self.assertTrue(User.objects.count() == 1, 'A user was created')

        # User was created
        user = User.objects.get(username='testadminuser')
        self.assertTrue(user.is_superuser, 'The user is a superuser')
        self.assertTrue(user.is_staff, 'The user is a staff member')

        # Redirect to the dashboard happens
        self.assertRedirects(res, '/dashboard/')

        # User is automatically logged-in
        self.assertTrue(res.context['user'].is_authenticated)

        # After a super admin is created, the welcome page is no longer accessible
        res = c.get('/welcome/', follow=True)
        self.assertRedirects(res, '/dashboard/')

        # We cannot create another superuser
        res = c.post('/welcome/', data={
            'username': 'testadminuser2',
            'password': 'testadminpass2'}, follow=True)
        self.assertRedirects(res, '/dashboard/')

        self.assertTrue(User.objects.filter(username='testadminuser2').count() == 0, 'No users were created')

        # If we log-out and try to access the welcome page, we should get the login page
        c.logout()
        res = c.get('/welcome/', follow=True)
        self.assertRedirects(res, '/login/')

        # We're not logged-in
        self.assertFalse(res.context['user'].is_authenticated)

        # We can log-in
        res = c.post('/login/', data={
            'username': 'testadminuser',
            'password': 'testadminpass'}, follow=True)
        self.assertTrue(res.context['user'].is_authenticated)
        self.assertRedirects(res, '/dashboard/')
