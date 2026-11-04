import time
import jwt
from django.contrib.auth.models import User, Group
from rest_framework import status
from rest_framework.test import APIClient
from app.api.authentication import JWT_AUTH_HEADER_PREFIX
from django.contrib.auth.hashers import check_password

from .classes import BootTestCase
from app.api.admin import UserSerializer, GroupSerializer
from app.models import Project


class TestApiAdmin(BootTestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_user(self):
        ##
        ## Super user operation
        ##
        client = APIClient()

        super_user_name  = 'testsuperuser'
        super_user_pass  = 'test1234'
        # Get token
        res = client.post('/api/token-auth/', {
            'username': super_user_name,
            'password': super_user_pass,
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        super_user_token = res.data['token']
        client = APIClient(HTTP_AUTHORIZATION="{0} {1}".format(JWT_AUTH_HEADER_PREFIX, super_user_token))

        # Can create (active) user
        res = client.post('/api/admin/users/', {'username': 'testuser999', 'email': 'testuser999@test.com', 'password': 'test999', 'is_active': True})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='testuser999')
        self.assertTrue(user != None)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)

        # Can get user
        created_user_id = user.id
        res = client.get('/api/admin/users/{}/'.format(created_user_id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['username'], user.username)
        self.assertEqual(res.data['email'], user.email)
        self.assertEqual(res.data['password'], user.password)
        self.assertTrue(check_password('test999', user.password))

        # Can update user
        res = client.put('/api/admin/users/{}/'.format(created_user_id), {'username': 'testuser888', 'email': 'testuser888@test.com', 'password': 'test888'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        user = User.objects.filter(id=created_user_id).first()
        self.assertTrue(user != None and (not user.is_superuser))
        res = client.get('/api/admin/users/{}/'.format(created_user_id)) # ReGet user
        self.assertEqual(res.data['username'], user.username)
        self.assertEqual(res.data['email'], user.email)
        self.assertEqual(res.data['password'], user.password)

        # Can find user by email
        res = client.get('/api/admin/users/?email=testuser888@test.com')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        result = res.data['results'][0]
        self.assertEqual(result['id'], user.id)
        self.assertEqual(result['username'], user.username)
        self.assertEqual(result['email'], 'testuser888@test.com')

        # Can delete user
        res = client.delete('/api/admin/users/{}/'.format(created_user_id))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        user = User.objects.filter(id=created_user_id).first()
        self.assertTrue(user is None)


        ##
        ## user operation
        ##
        client = APIClient()
        user_name  = 'testuser'
        user_pass  = 'test1234'
        # Get token
        res = client.post('/api/token-auth/', {
            'username': user_name,
            'password': user_pass,
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        user_token = res.data['token']
        client = APIClient(HTTP_AUTHORIZATION="{0} {1}".format(JWT_AUTH_HEADER_PREFIX, user_token))

        # Can't create user
        res = client.post('/api/admin/users/', {'username': 'testuser999', 'email': 'testuser999@test.com', 'password': 'test999', 'is_active': True})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        user = User.objects.filter(username='testuser999').first()
        self.assertTrue(user is None)

        user = User.objects.get(username=user_name)

        # Can't get user
        res = client.get('/api/admin/users/{}/'.format(user.id))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Can't update user
        res = client.put('/api/admin/users/{}/'.format(user.id), {'password': 'changed'})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Can't delete user
        res = client.delete('/api/admin/users/{}/'.format(user.id))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


    def test_group(self):
        ##
        ## Super user operaiton
        ##
        client = APIClient()

        super_user_name  = 'testsuperuser'
        super_user_pass  = 'test1234'
        # Get token
        res = client.post('/api/token-auth/', {
            'username': super_user_name,
            'password': super_user_pass,
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        super_user_token = res.data['token']
        client = APIClient(HTTP_AUTHORIZATION="{0} {1}".format(JWT_AUTH_HEADER_PREFIX, super_user_token))

        # Can create group
        res = client.post('/api/admin/groups/', {'name': 'Test', 'permissions': [53, 54]})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        group = Group.objects.get(name='Test')
        self.assertTrue(group != None)
        serializer = GroupSerializer(group)
        self.assertEqual([53, 54], serializer.data['permissions'])

        # Can get group
        created_group_id = group.id
        res = client.get('/api/admin/groups/{}/'.format(created_group_id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['name'], group.name)

        # Can update group 
        res = client.put('/api/admin/groups/{}/'.format(created_group_id), {'name': 'TestTest', 'permissions': [37, 38]})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        group = Group.objects.filter(id=created_group_id).first()
        self.assertTrue(group != None)
        serializer = GroupSerializer(group)
        res = client.get('/api/admin/groups/{}/'.format(created_group_id)) # ReGet group
        self.assertEqual('TestTest', serializer.data['name'])
        self.assertEqual([37, 38], serializer.data['permissions'])

        # Can find group by name
        res = client.get('/api/admin/groups/?name=TestTest')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        result = res.data['results'][0]
        self.assertEqual(result['id'], group.id)
        self.assertEqual(result['name'], 'TestTest')

        # Can delete group
        res = client.delete('/api/admin/groups/{}/'.format(created_group_id))
        self.assertTrue(res.status_code == status.HTTP_204_NO_CONTENT)
        group = Group.objects.filter(id=created_group_id).first()
        self.assertTrue(group is None)

        ##
        ## user operation
        ##
        client = APIClient()

        user_name  = 'testuser'
        user_pass  = 'test1234'
        # Get token
        res = client.post('/api/token-auth/', {
            'username': user_name,
            'password': user_pass,
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        user_token = res.data['token']
        client = APIClient(HTTP_AUTHORIZATION="{0} {1}".format(JWT_AUTH_HEADER_PREFIX, user_token))

        # Can't create group
        res = client.post('/api/admin/groups/', {'name': 'Test', 'permissions': [53, 54]})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        group = Group.objects.filter(name='Test').first()
        self.assertTrue(group is None)

        group = Group.objects.get(name='Default')

        # Can't get group
        res = client.get('/api/admin/groups/{}/'.format(group.id))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Can't update group
        res = client.put('/api/admin/groups/{}/'.format(group.id), {'name': 'TestTest', 'permissions': [37, 38]})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Can't delete group
        res = client.delete('/api/admin/groups/{}/'.format(group.id))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_profile(self):
        client = APIClient()
        client.login(username="testuser", password="test1234")

        user = User.objects.get(username="testuser")

        # Cannot list profiles (not admin)
        res = client.get('/api/admin/profiles/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        res = client.get('/api/admin/profiles/%s/' % user.id)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Cannot update quota deadlines
        res = client.post('/api/admin/profiles/%s/update_quota_deadline/' % user.id, data={'hours': 1})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        
        # Cannot read quota information
        res = client.get('/api/admin/profiles/%s/used_quota/' % user.id)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Admin can
        client.login(username="testsuperuser", password="test1234")

        res = client.get('/api/admin/profiles/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) > 0)

        res = client.get('/api/admin/profiles/%s/used_quota/' % user.id)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue('used' in res.data)
        self.assertTrue('total' in res.data)

        res = client.get('/api/admin/profiles/%s/' % user.id)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue('quota' in res.data)
        self.assertTrue('user' in res.data)

        # User is the primary key (not profile id)
        self.assertEqual(res.data['user'], user.id)
        
        # There should be no quota by default
        self.assertEqual(res.data['quota'], -1)

        # Try updating
        user.profile.quota = 10
        user.save()
        res = client.get('/api/admin/profiles/%s/' % user.id)
        self.assertEqual(res.data['quota'], 10)
        
        # Update quota deadlines

        self.assertTrue(user.profile.get_quota_deadline() is None)

        # Miss parameters
        res = client.post('/api/admin/profiles/%s/update_quota_deadline/' % user.id)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        res = client.post('/api/admin/profiles/%s/update_quota_deadline/' % user.id, data={'hours': 48})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue('deadline' in res.data and res.data['deadline'] > time.time() + 47*60*60)

        res = client.post('/api/admin/profiles/%s/update_quota_deadline/' % user.id, data={'hours': 0})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(abs(user.profile.get_quota_deadline() - time.time()) < 10)

    def test_refresh_token(self):
        client = APIClient()
        res = client.post('/api/token-auth/', {
            'username': "testuser",
            'password': "test1234",
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        token = res.data['token']

        time.sleep(2)

        res = client.post('/api/token-auth/refresh/', {
            'token': token
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertNotEqual(token, res.data['token'])
        self.assertEqual(jwt.decode(res.data['token'], options={'verify_signature': False}).get('username'), 'testuser')

    def test_impersonation(self):
        client = APIClient()
        
        # Create a test user to impersonate
        impersonated_user = User.objects.create_user(
            username='impersonateduser',
            password='test1234',
        )

        # Create a mock project for the impersonated user
        Project.objects.create(
            owner=impersonated_user,
            name='Impersonated Project'
        )
        
        # Regular user can get token, but can't impersonate
        user_name = 'testuser'
        user_pass = 'test1234'
        res = client.post('/api/token-auth/', {
            'username': user_name,
            'password': user_pass,
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        res = client.post('/api/token-auth/', {
            'username': user_name,
            'password': user_pass,
            'impersonate': 'impersonateduser'
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Super user can impersonate

        # Create a mock project for admin user
        Project.objects.create(
            owner=User.objects.get(username='testsuperuser'),
            name='Admin Project'
        )

        client = APIClient()
        res = client.post('/api/token-auth/', {
            'username': 'testsuperuser',
            'password': 'test1234',
            'impersonate': 'impersonateduser'
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        impersonated_token = res.data['token']
        
        # Use impersonated token to access projects
        # Projects should be filtered by impersonated user
        impersonated_client = APIClient(HTTP_AUTHORIZATION="{0} {1}".format(JWT_AUTH_HEADER_PREFIX, impersonated_token))
        
        res = impersonated_client.get('/api/projects/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
        # Verify the response contains only projects owned by impersonated user
        self.assertEqual(len(res.data), 1)
        self.assertTrue(res.data[0]['name'] == 'Impersonated Project')