import os
import shutil
import json
import hashlib
import urllib.request

import sys
import time

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from rest_framework import status

from app.models import Plugin
from app.models import Project
from app.models import Task
from app.plugins import UserDataStore, enable_plugin
from app.plugins import get_plugin_by_name
from app.plugins import sync_plugin_db, get_plugins_persistent_path
from app.plugins.data_store import InvalidDataStoreValue
from app.plugins.pyutils import parse_requirements, compute_file_md5, requirements_installed
from .classes import BootTestCase


def fetch(url, timeout, retries=5):
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "WebODM"}), timeout=timeout) as r:
                return r.read()
        except Exception:
            if i == retries:
                raise
            time.sleep(2 ** i)


class TestPlugins(BootTestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_core_plugins(self):
        client = Client()

        # We cannot access public files core plugins (plugin is disabled)
        res = client.get('/plugins/test/file.txt')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Cannot access mount point (plugin is disabled)
        res = client.get('/plugins/test/app_mountpoint/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # No python packages have been installed (plugin is disabled)
        self.assertFalse(os.path.exists(get_plugins_persistent_path("test", "site-packages")))

        enable_plugin("test")

        # Python packages have been installed
        self.assertTrue(os.path.exists(get_plugins_persistent_path("test", "site-packages")))

        # We can access public files core plugins (without auth)
        res = client.get('/plugins/test/file.txt')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # We mounted an endpoint
        res = client.get('/plugins/test/app_mountpoint/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(res, 'coreplugins/test/templates/app.html')

        # Form was rendered correctly
        self.assertContains(res,
                            '<input type="text" name="testField" class="form-control" required id="id_testField" />',
                            count=1, status_code=200, html=True)

        # It uses regex properly
        res = client.get('/plugins/test/app_mountpoint/a')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Querying a page should show the included CSS/JS files
        client.login(username='testuser', password='test1234')
        res = client.get('/dashboard/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertContains(res, "<link href='/plugins/test/test.css' rel='stylesheet' type='text/css'>", html=True)
        self.assertContains(res, "<script src='/plugins/test/test.js'></script>", html=True)

        # And our menu entry
        self.assertContains(res, '<li><a href="/plugins/test/menu_url/"><i class="test-icon"></i> Test</a></li>', html=True)

        # A node_modules directory has been created as a result of npm install
        # because we have a package.json in the public director
        test_plugin = get_plugin_by_name("test")
        self.assertTrue(os.path.exists(test_plugin.get_path("public/node_modules")))

        # This is a persistent plugin
        self.assertTrue(test_plugin.is_persistent())

        # A webpack file and build directory have been created as a
        # result of the build_jsx_components directive
        self.assertTrue(os.path.exists(test_plugin.get_path("public/webpack.config.js")))
        self.assertTrue(os.path.exists(test_plugin.get_path("public/build")))
        self.assertTrue(os.path.exists(test_plugin.get_path("public/build/component.js")))

        # Test task view
        user = User.objects.get(username="testuser")
        project = Project.objects.get(owner=user)
        task = Task.objects.create(project=project, name="Test")
        client.logout()

        # Cannot see the task view without logging-in
        res = client.get('/plugins/test/task/{}/'.format(task.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        client.login(username='testuser', password='test1234')
        res = client.get('/plugins/test/task/{}/'.format(task.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertContains(res, str(task.id))

        # Test dynamic script
        res = client.get('/plugins/test/app_dynamic_script.js')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.content.decode('utf-8') == '') # Empty

        res = client.get('/plugins/test/app_dynamic_script.js?print=1')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.content.decode('utf-8') == "console.log('Hello WebODM');")  # Empty

        # Check that the plugins media dirs have been created
        self.assertTrue(os.path.exists(get_plugins_persistent_path()))
        self.assertTrue(os.path.exists(get_plugins_persistent_path("test", "site-packages")))
        self.assertEqual(get_plugins_persistent_path("test", "site-packages"), test_plugin.get_python_packages_path())

        # Check MD5 install has been created
        self.assertTrue(os.path.exists(test_plugin.get_python_packages_path("install_md5")))
        with open(test_plugin.get_python_packages_path("install_md5"), "r") as f:
            md5 = f.read().strip()
            self.assertTrue(len(md5) > 20)
            self.assertEqual(md5, compute_file_md5(test_plugin.get_path("requirements.txt")))

        self.assertTrue(requirements_installed(test_plugin.get_path("requirements.txt"), test_plugin.get_python_packages_path()))

        # Test python imports context
        self.assertFalse(test_plugin.get_python_packages_path() in sys.path)
        with test_plugin.python_imports():
            self.assertTrue(test_plugin.get_python_packages_path() in sys.path)
        self.assertFalse(test_plugin.get_python_packages_path() in sys.path)

        # Parse requirements test
        self.assertEqual(parse_requirements(test_plugin.get_path("requirements.txt"))[0], "pyodx")

        # Current plugin test
        self.assertEqual(test_plugin.get_current_plugin_test(), test_plugin)


    def test_plugin_datastore(self):
        enable_plugin("test")
        test_plugin = get_plugin_by_name("test")
        user = User.objects.get(username='testuser')
        other_user = User.objects.get(username='testuser2')

        uds = test_plugin.get_user_data_store(user)
        other_uds = test_plugin.get_user_data_store(other_user)
        gds = test_plugin.get_global_data_store()

        # No key
        self.assertFalse(uds.has_key('mykey'))

        # Default value works
        self.assertTrue(uds.get_string('mykey', 'default') == 'default')

        # Still no key should have been added
        self.assertFalse(uds.has_key('mykey'))

        # Add key
        (object, created) = uds.set_string('mykey', 'value')
        self.assertTrue(object.string_value == 'value')
        self.assertTrue(created)
        self.assertTrue(uds.has_key('mykey'))

        # Key is not visible in global datastore
        self.assertFalse(gds.has_key('mykey'))

        # Key is not visible in another user's data store
        self.assertFalse(other_uds.has_key('mykey'))

        # Key is not visible in another's plugin data store
        # for the same user
        other_puds = UserDataStore('test2', user)
        self.assertFalse(other_puds.has_key('mykey'))

        # Deleting a non-existing key return False
        self.assertFalse(uds.del_key('nonexistant'))

        # Deleting a valid key returns True
        self.assertTrue(uds.del_key('mykey'))
        self.assertFalse(uds.has_key('mykey'))

        # Various data types setter/getter work
        uds.set_int('myint', 5)
        self.assertTrue(uds.get_int('myint') == 5)

        uds.set_float('myfloat', 10.0)
        self.assertTrue(uds.get_float('myfloat', 50.0) == 10.0)

        uds.set_bool('mybool', True)
        self.assertTrue(uds.get_bool('mybool'))

        uds.set_json('myjson', {'test': 123})
        self.assertTrue('test' in uds.get_json('myjson'))

        # Invalid types
        self.assertRaises(InvalidDataStoreValue, uds.set_bool, 'invalidbool', 5)

    def test_toggle_plugins(self):
        c = Client()
        c.login(username='testuser', password='test1234')

        # Cannot toggle plugins as normal user
        res = c.get('/admin/app/plugin/test/disable/', follow=True)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        c.login(username='testsuperuser', password='test1234')

        enable_plugin("test")

        # Test plugin is enabled
        res = c.get('/admin/app/plugin/')
        self.assertContains(res, '<a class="button" href="#" disabled>Enable</a>')
        self.assertContains(res, "<script src='/plugins/test/test.js'></script>")

        self.assertContains(res, 'data-can-build="true"')
        self.assertContains(res, 'data-webodm-version="{}"'.format(settings.VERSION))
                
        # Disable
        res = c.get('/admin/app/plugin/test/disable/', follow=True)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Test active vs. non-active flag for get_plugin_by_name
        self.assertTrue(get_plugin_by_name("test") is None)
        self.assertFalse(get_plugin_by_name("test", only_active=False) is None)

        # Test plugin has been disabled
        self.assertContains(res, '<a class="button" href="#" disabled>Disable</a>')
        self.assertNotContains(res, "<script src='/plugins/test/test.js'></script>")

        # Re-enable
        res = c.get('/admin/app/plugin/test/enable/', follow=True)
        self.assertEqual(res.status_code, status.HTTP_200_OK)


    def test_plugin_functions(self):
        # Check db/fs syncing
        if os.path.exists('coreplugins/test_copy'):
            print("Removing plugins/test_copy")
            shutil.rmtree('coreplugins/test_copy')

        sync_plugin_db()
        self.assertTrue(Plugin.objects.filter(pk='test_copy').count() == 0)

        shutil.copytree('coreplugins/test', 'coreplugins/test_copy')

        sync_plugin_db()
        self.assertTrue(Plugin.objects.filter(pk='test_copy').count() == 1)

        shutil.rmtree('coreplugins/test_copy')
        sync_plugin_db()
        self.assertTrue(Plugin.objects.filter(pk='test_copy').count() == 0)

        # Get manifest works and parses JSON
        p = get_plugin_by_name("test", only_active=False)
        self.assertEqual(p.get_manifest()['author'], "Piero Toffanin")


    def test_plugin_loading(self):
        c = Client()

        plugin_file = open("app/fixtures/testabc_plugin.zip", 'rb')
        bad_dir_plugin_file = open("app/fixtures/bad_dir_plugin.zip", 'rb')
        missing_manifest_plugin_file = open("app/fixtures/missing_manifest_plugin.zip", 'rb')

        # Cannot upload new plugins anonymously
        res = c.post('/admin/app/plugin/actions/upload/', {'file': plugin_file}, follow=True)
        self.assertRedirects(res, '/login/?next=/admin/app/plugin/actions/upload/')
        self.assertFalse(os.path.exists(get_plugins_persistent_path("testabc")))
        plugin_file.seek(0)

        # Cannot upload plugins as a normal user
        c.login(username='testuser', password='test1234')
        res = c.post('/admin/app/plugin/actions/upload/', {'file': plugin_file}, follow=True)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(os.path.exists(get_plugins_persistent_path("testabc")))
        self.assertEqual(Plugin.objects.filter(pk='testabc').count(), 0)
        plugin_file.seek(0)

        # Can upload plugin as an admin
        c.login(username='testsuperuser', password='test1234')
        res = c.post('/admin/app/plugin/actions/upload/', {'file': plugin_file}, follow=True)
        self.assertRedirects(res, '/admin/app/plugin/')
        messages = list(res.context['messages'])
        self.assertTrue('installed successfully' in str(messages[0]))
        self.assertTrue(os.path.exists(get_plugins_persistent_path("testabc")))
        plugin_file.seek(0)

        # Plugin has been added to db
        self.assertEqual(Plugin.objects.filter(pk='testabc').count(), 1)

        # This is not a persistent plugin
        self.assertFalse(get_plugin_by_name('testabc').is_persistent())

        # Cannot upload the same plugin again (same name)
        res = c.post('/admin/app/plugin/actions/upload/', {'file': plugin_file}, follow=True)
        self.assertRedirects(res, '/admin/app/plugin/')
        messages = list(res.context['messages'])
        self.assertTrue('already exist' in str(messages[0]))
        plugin_file.seek(0)

        # Can access paths (while being logged in)
        res = c.get('/plugins/testabc/hello/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        res = c.get('/api/plugins/testabc/hello/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Can access public paths as logged-in, (per plugin directive)
        res = c.get('/plugins/testabc/file.txt')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Can install the dronedb plugin from the plugin repository
        repo = "https://plugins.webodm.org"
        index = json.loads(fetch(repo + "/index.json", 30))
        ddb = [p for p in index['plugins'] if p['id'] == 'dronedb'][0]
        ddb_zip = fetch(repo + ddb['url'], 60)
        self.assertEqual(hashlib.sha256(ddb_zip).hexdigest(), ddb['sha256'])

        res = c.post('/admin/app/plugin/actions/upload/', {
            'file': SimpleUploadedFile('dronedb.zip', ddb_zip, content_type='application/zip'),
            'sha256': ddb['sha256'],
            'json': '1'
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.json()['success'], res.json()['message'])
        self.assertEqual(Plugin.objects.filter(pk='dronedb').count(), 1)

        ddb_plugin = get_plugin_by_name('dronedb', only_active=False)
        self.assertFalse(ddb_plugin is None)

        res = c.get('/admin/app/plugin/dronedb/delete/', follow=True)
        self.assertRedirects(res, '/admin/app/plugin/')
        self.assertEqual(Plugin.objects.filter(pk='dronedb').count(), 0)
        self.assertFalse(os.path.exists(get_plugins_persistent_path("dronedb")))
        
        c.logout()

        # Can still access the paths as anonymous
        res = c.get('/plugins/testabc/hello/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        res = c.get('/api/plugins/testabc/hello/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # But not the public paths as anonymous (per plugin directive)
        res = c.get('/plugins/testabc/file.txt')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Cannot delete plugin as normal user
        c.login(username='testuser', password='test1234')
        res = c.get('/admin/app/plugin/testabc/delete/', follow=True)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Can delete plugin as admin
        c.login(username='testsuperuser', password='test1234')
        res = c.get('/admin/app/plugin/testabc/delete/', follow=True)
        self.assertRedirects(res, '/admin/app/plugin/')
        messages = list(res.context['messages'])

        # No errors
        self.assertEqual(len(messages), 0)

        # Directories have been removed
        self.assertFalse(os.path.exists(get_plugins_persistent_path("testabc")))

        # Cannot access the paths as anonymous
        res = c.get('/plugins/testabc/hello/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        res = c.get('/api/plugins/testabc/hello/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        res = c.get('/plugins/testabc/file.txt')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Try to add malformed plugins files
        res = c.post('/admin/app/plugin/actions/upload/', {'file': missing_manifest_plugin_file}, follow=True)
        self.assertRedirects(res, '/admin/app/plugin/')
        messages = list(res.context['messages'])
        self.assertTrue('Cannot load plugin' in str(messages[0]))
        self.assertFalse(os.path.exists(get_plugins_persistent_path("test123")))
        self.assertEqual(Plugin.objects.filter(pk='test123').count(), 0)
        missing_manifest_plugin_file.seek(0)

        res = c.post('/admin/app/plugin/actions/upload/', {'file': bad_dir_plugin_file}, follow=True)
        self.assertRedirects(res, '/admin/app/plugin/')
        messages = list(res.context['messages'])
        self.assertTrue('Cannot load plugin' in str(messages[0]))
        missing_manifest_plugin_file.seek(0)

        plugin_file.close()
        missing_manifest_plugin_file.close()
        bad_dir_plugin_file.close()

