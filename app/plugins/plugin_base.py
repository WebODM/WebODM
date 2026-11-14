import json
import logging, os, re, sys, subprocess
from urllib.parse import quote
from abc import ABC
from app.plugins import UserDataStore, GlobalDataStore
from app.plugins.functions import get_plugins_persistent_path
from contextlib import contextmanager

from app.plugins.pyutils import requirements_installed, compute_file_md5

logger = logging.getLogger('app.logger')

class PluginBase(ABC):
    def __init__(self):
        self.name = self.get_module_name().split(".")[-2]
        self.manifest = None

    def register(self):
        self.check_requirements()

    def check_requirements(self):
        """
        Check if Python requirements need to be installed
        """
        req_file = self.get_path("requirements.txt")
        if os.path.exists(req_file):
            reqs_installed =  requirements_installed(req_file, self.get_python_packages_path())

            md5_file = self.get_python_packages_path("install_md5")
            md5_mismatch = False
            req_md5 = compute_file_md5(req_file)

            if os.path.exists(md5_file):
                with open(md5_file, 'r') as f:
                    md5_mismatch = f.read().strip() != req_md5
            else:
                reqs_installed = False

            if not reqs_installed or md5_mismatch:
                logger.info("Installing requirements.txt for {}".format(self))

                if not os.path.exists(self.get_python_packages_path()):
                    os.makedirs(self.get_python_packages_path(), exist_ok=True)

                p = subprocess.Popen(['python', '-m', 'pip', 'install', '-U', '-r', 'requirements.txt',
                                  '--target', self.get_python_packages_path()],
                                     cwd=self.get_path())
                p.wait()

                # Verify
                if requirements_installed(self.get_path("requirements.txt"), self.get_python_packages_path()):
                    logger.info("Installed requirements.txt for {}".format(self))

                    # Write MD5
                    if req_md5:
                        with open(md5_file, 'w') as f:
                            f.write(req_md5)
                else:
                    logger.warning("Failed to install requirements.txt for {}".format(self))

    def enable(self):
        """
        Should be overriden by plugins to perform persistent setup and configuration
        (e.g., registering static files, initializing databse entries, or hooking
        into WebODM’s functionality). Called once, each time a plugin is enabled. If
        this method throws an exception, it will not be enabled by the system.
        :return: none
        """
        pass

    def disable(self):
        """
        Should be overriden by plugins to perform cleanup or other persistent tasks
        to restore the system to pre-enabled state (e.g., removing hooks, deleting
        temporary data, or restoring system state). Called once each time a plugin
        is disabled. If this method fails to complete or throws an exception, it will
        still be disabled by the system.
        :return: none
        """
        pass

    def get_persistent_path(self, *paths):
        return get_plugins_persistent_path(self.name, *paths)

    def get_python_packages_path(self, *paths):
        return self.get_persistent_path("site-packages", *paths)

    @contextmanager
    def python_imports(self):
        # Add python path
        sys.path.insert(0, self.get_python_packages_path())
        try:
            yield
        finally:
            # Remove python path
            sys.path.remove(self.get_python_packages_path())


    def get_path(self, *paths):
        """
        Gets the path of the directory of the plugin, optionally chained with paths
        :return: path
        """
        return os.path.join(os.path.dirname(sys.modules[self.get_module_name()].__file__), *paths)

    def get_name(self):
        """
        :return: Name of current module (reflects the directory in which this plugin is stored)
        """
        return self.name

    def get_user_data_store(self, user):
        """
        Helper function to instantiate a user data store associated
        with this plugin
        :return: UserDataStore
        """
        return UserDataStore(self.get_name(), user)

    def get_global_data_store(self):
        """
        Helper function to instantiate a user data store associated
        with this plugin
        :return: GlobalDataStore
        """
        return GlobalDataStore(self.get_name())

    def get_module_name(self):
        return self.__class__.__module__

    def get_version(self):
        version = str(self.get_manifest().get('version', ''))
        if re.fullmatch(r'[0-9.]+', version):
            return version
        return '0.0.1'

    def versioned_url(self, path):
        version = self.get_version()
        if not version:
            return self.public_url(path)
        return "{}?v={}".format(self.public_url(path), quote(version))

    def get_include_js_urls(self):
        return [self.versioned_url(js_file) for js_file in self.include_js_files()]

    def get_include_css_urls(self):
        return [self.versioned_url(css_file) for css_file in self.include_css_files()]

    def public_url(self, path):
        """
        :param path: unix-style path
        :return: Path that can be accessed via a URL (from the browser), relative to plugins/<yourplugin>/public
        """
        return "/plugins/{}/{}".format(self.get_name(), path)

    def is_persistent(self):
        """
        :return: whether this plugin is persistent (stored in the /plugins directory,
                instead of /app/media/plugins which are transient)
        """
        return ".." in os.path.relpath(self.get_path(), get_plugins_persistent_path())

    def template_path(self, path):
        """
        :param path: unix-style path
        :return: path used to reference Django templates for a plugin
        """
        if self.is_persistent():
            return "coreplugins/{}/templates/{}".format(self.get_name(), path)
        else:
            return "plugins/{}/templates/{}".format(self.get_name(), path)


    def path_exists(self, *path):
        return os.path.exists(self.get_path(os.path.join(*path)))

    def include_js_files(self):
        """
        Should be overriden by plugins to communicate
        which JS files should be included in the WebODM interface
        All paths are relative to a plugin's /public folder.
        """
        return []

    def include_css_files(self):
        """
        Should be overriden by plugins to communicate
        which CSS files should be included in the WebODM interface
        All paths are relative to a plugin's /public folder.
        """
        return []

    def build_jsx_components(self):
        """
        Experimental
        Should be overriden by plugins that want to automatically
        build JSX files.
        All paths are relative to a plugin's /public folder.
        """
        return []

    def requires_restart(self):
        """
        Whether the plugin requires an app restart to
        function properly
        """
        return len(self.root_mount_points()) > 0

    def main_menu(self):
        """
        Should be overriden by plugins that want to add
        items to the side menu.
        :return: [] of Menu objects
        """
        return []

    def root_mount_points(self):
        """
        Should be overriden by plugins that want to 
        add routes to the root view controller.
        CAUTION: this should be used sparingly, as
        routes could conflict with other plugins and
        future versions of WebODM might break the routes.
        It's recommended to use app_mount_points, unless
        you know what you are doing.
        :return: [] of MountPoint objects
        """
        return [] 

    def app_mount_points(self):
        """
        Should be overriden by plugins that want to connect
        custom Django views
        :return: [] of MountPoint objects
        """
        return []

    def api_mount_points(self):
        """
        Should be overriden by plugins that want to add
        new API mount points
        :return: [] of MountPoint objects
        """
        return []

    def serve_public_assets(self, request):
        """
        Should be overriden by plugins that want to control which users
        have access to the public assets. By default anyone can access them,
        including anonymous users.
        :param request: HTTP request
        :return: boolean (whether the plugin's public assets should be exposed for this request)
        """
        return True

    def get_dynamic_script(self, script_path, callback = None, **template_args):
        """
        Retrieves a view handler that serves a dynamic script from
        the plugin's directory. Dynamic scripts are normal Javascript
        files that optionally support Template variable substitution
        via ${vars}, computed on the server.
        :param script_path: path to script relative to plugin's directory.
        :param callback: optional callback. The callback can prevent the script from being returned if it returns False.
            If it returns a dictionary, the dictionary items are used for variable substitution.
        :param template_args: Parameters to use for variable substitution (unless a callback is specified)
        :return: Django view
        """
        from app.plugins import get_dynamic_script_handler
        return get_dynamic_script_handler(self.get_path(script_path), callback, **template_args)

    def get_manifest(self):
        # Lazy loading
        if self.manifest is not None: return self.manifest

        manifest_path = self.get_path("manifest.json")

        # Read manifest
        with open(manifest_path) as manifest_file:
            self.manifest = json.load(manifest_file)

        return self.manifest

    def __str__(self):
        return "[{}]".format(self.get_module_name())
