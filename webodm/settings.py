import os, sys, json

import datetime

from django.contrib.messages import constants as messages

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# For best practices
# See https://docs.djangoproject.com/en/1.10/howto/deployment/checklist/

try:
    from .secret_key import SECRET_KEY
except ImportError:
    if os.environ.get("WO_SECRET_KEY", "") != "":
        SECRET_KEY = os.environ.get("WO_SECRET_KEY")
    else:
        # This will be executed the first time Django runs
        # It generates a secret_key.py file that contains the SECRET_KEY
        from django.utils.crypto import get_random_string

        current_dir = os.path.abspath(os.path.dirname(__file__))
        chars = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'
        secret = get_random_string(50, chars)
        with open(os.path.join(current_dir, 'secret_key.py'), 'w') as f:
            f.write("SECRET_KEY='{}'".format(secret))
        SECRET_KEY=secret

        print("Generated secret key")

with open(os.path.join(BASE_DIR, 'package.json')) as package_file:
    data = json.load(package_file)
    VERSION = data['version']

TESTING = sys.argv[1:2] == ['test']
FLUSHING = sys.argv[1:2] == ['flush']
MIGRATING = sys.argv[1:2] == ['migrate']
WORKER_RUNNING = sys.argv[2:3] == ["worker"]

# SECURITY WARNING: don't run with debug turned on a public facing server!
DEBUG = os.environ.get('WO_DEBUG', 'YES') == 'YES' or TESTING
DEV = os.environ.get('WO_DEV', 'NO') == 'YES' and not TESTING
DEV_WATCH_PLUGINS = DEV and os.environ.get('WO_DEV_WATCH_PLUGINS', 'NO') == 'YES'
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = os.environ.get('WO_SSL', 'NO') == 'YES'
INTERNAL_IPS = ['127.0.0.1']

ALLOWED_HOSTS = ['*']

# Branding
APP_NAME = "WebODM"
APP_DEFAULT_LOGO = os.path.join('app', 'static', 'app', 'img', 'logo512.png')

# In single user mode, a default admin account is created and automatically
# used so that no login windows are displayed
SINGLE_USER_MODE = False

# Enable a mechanism to override DNS resolution
# in cases where the machine might have a misconfigured DNS
DNS_RESOLUTION_FALLBACK = None # ['8.8.8.8', '1.1.1.1'] # Google, Cloudflare

# URL to redirect to if there are no processing nodes when visiting the dashboard
PROCESSING_NODES_ONBOARDING = None

# Enable the /api/users endpoint which is used for autocompleting
# usernames when handling project permissions. This can be disabled
# for security reasons if you don't want to let authenticated users
# retrieve the user list. 
ENABLE_USERS_API = True

# Enable desktop mode. In desktop mode some styling changes
# are applied to make the application look nicer on desktop
# as well as disabling certain features (e.g. sharing)
DESKTOP_MODE = False

# Default CSS to add to theme
DEFAULT_THEME_CSS = ''

# Plugins never to load
PLUGINS_BLACKLIST = [
    #'measure',
]

# Serve media static files URLs even in production
FORCE_MEDIA_STATICFILES = False

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
    'django_filters',
    'guardian',
    'rest_framework',
    'rest_framework_nested',
    'drf_yasg',
    'webpack_loader',
    'corsheaders',
    'colorfield',
    'imagekit',
    'codemirror2',
    'app',
    'nodeodm',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.locale.LocaleMiddleware',
]

ROOT_URLCONF = 'webodm.urls'

WSGI_APPLICATION = 'webodm.wsgi.application'


# Database
# https://docs.djangoproject.com/en/1.10/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': os.environ.get('WO_DATABASE_ENGINE', 'django.contrib.gis.db.backends.postgis'),
        'NAME': os.environ.get('WO_DATABASE_NAME', 'webodm_dev'),
        'USER': os.environ.get('WO_DATABASE_USER', 'postgres'),
        'PASSWORD': os.environ.get('WO_DATABASE_PASSWORD', 'postgres'),
        'HOST': os.environ.get('WO_DATABASE_HOST', 'db'),
        'PORT': os.environ.get('WO_DATABASE_PORT', '5432'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/1.10/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
   {
       'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
   },
   {
       'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
   },
   {
       'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
   },
   {
       'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
   },
]

# Hook guardian
AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend', # this is default
    'guardian.backends.ObjectPermissionBackend',
    'app.auth.backends.ExternalBackend',
)

# Internationalization
# https://docs.djangoproject.com/en/1.10/topics/i18n/

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Etc/UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

LOCALE_PATHS = [
    os.path.join(BASE_DIR, 'locale')
]

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.10/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'build', 'static')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'app', 'static'),
]
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

# File Uploads
FILE_UPLOAD_MAX_MEMORY_SIZE = 4718592 # 4.5 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760 # 10 MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = None

FILE_UPLOAD_HANDLERS = [
    'django.core.files.uploadhandler.MemoryFileUploadHandler',
    'app.uploadhandler.TemporaryFileUploadHandler', # Ours doesn't keep file descriptors open by default
]

# Webpack
WEBPACK_LOADER = {
    'DEFAULT': {
        'BUNDLE_DIR_NAME': 'app/bundles/',
        'STATS_FILE': os.path.join(BASE_DIR, 'webpack-stats.json'),
    }
}


# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s'
        },
        'simple': {
            'format': '%(levelname)s %(message)s'
        },
    },
    'filters': {
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            # 'filters': ['require_debug_true'],
            'class': 'logging.StreamHandler',
            'formatter': 'simple'
        }
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'propagate': True,
            'level': 'WARNING',
        },
        'app.logger': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'apscheduler.executors.default': {
            'handlers': ['console'],
            'level': 'WARNING',
        }
    }
}


# Auth
LOGIN_REDIRECT_URL = '/dashboard/'
LOGIN_URL = '/login/'

# CORS (very relaxed settings, users might want to change this in production)
CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True
SESSION_COOKIE_SAMESITE = None

# File uploads
MEDIA_ROOT = os.path.join(BASE_DIR, 'app', 'media')
if TESTING:
    MEDIA_ROOT = os.path.join(BASE_DIR, 'app', 'media_test')
MEDIA_TMP = os.path.join(MEDIA_ROOT, 'tmp')
MEDIA_CACHE = os.path.join(MEDIA_ROOT, 'CACHE')

FILE_UPLOAD_TEMP_DIR = MEDIA_TMP

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'app', 'templates'),
            os.path.join(BASE_DIR, 'app', 'templates', 'app'),
            BASE_DIR,
            MEDIA_ROOT,
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'app.contexts.settings.load',
            ],
        },
    },
]

# Store flash messages in cookies
MESSAGE_STORAGE = 'django.contrib.messages.storage.cookie.CookieStorage'
MESSAGE_TAGS = {
    messages.ERROR: 'danger' # Bootstrap 3 compatibility
}

# REST setup
# Use Django's standard django.contrib.auth permissions (no anonymous usage)
REST_FRAMEWORK = {
  'DEFAULT_PERMISSION_CLASSES': [
    'rest_framework.permissions.DjangoObjectPermissions',
  ],
  'DEFAULT_FILTER_BACKENDS': [
    'rest_framework_guardian.filters.ObjectPermissionsFilter',
    'django_filters.rest_framework.DjangoFilterBackend',
    'rest_framework.filters.OrderingFilter',
  ],
  'DEFAULT_AUTHENTICATION_CLASSES': (
    'rest_framework.authentication.SessionAuthentication',
    'rest_framework.authentication.BasicAuthentication',
    'rest_framework_jwt.authentication.JSONWebTokenAuthentication',
    'app.api.authentication.JSONWebTokenAuthenticationQS',
  ),
  'PAGE_SIZE': 10,
  'DEFAULT_PAGINATION_CLASS': 'app.api.pagination.PageNumberPaginationWithPageSize',
}

JWT_AUTH = {
    'JWT_EXPIRATION_DELTA': datetime.timedelta(hours=6),
    'JWT_ALLOW_REFRESH': True,
}

# Celery
CELERY_BROKER_URL = os.environ.get('WO_BROKER', 'redis://localhost')
CELERY_RESULT_BACKEND = os.environ.get('WO_BROKER', 'redis://localhost')

CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_INCLUDE=['worker.tasks', 'app.plugins.worker']
CELERY_WORKER_REDIRECT_STDOUTS = False
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get('WO_BROKER', 'redis://localhost'),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}
if DEBUG and not TESTING:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }

# Number of minutes a processing node hasn't been seen 
# before it should be considered offline
NODE_OFFLINE_MINUTES = 5

# When turned on, updates nodes information only when necessary
# and assumes that all nodes are always online, avoiding polling
NODE_OPTIMISTIC_MODE = False

# Number of parallel connections for uploading/downloading to/from processing nodes
NODE_CONNECTIONS = 6

# URL to external auth endpoint
EXTERNAL_AUTH_ENDPOINT = ''

# OpenID Connect (OIDC) authentication
OIDC_AUTH_PROVIDERS = []

# OpenID Connect (IODC) list of authorized e-mails
# when set, rejects any user who's email does not match an entry (domain-wide matches supported)
# e.g. ["@myorg.com", "exactuser@otherorg.com"]
OIDC_AUTH_EMAILS = None

# When turned on, updates the user's profile information in WebODM from OIDC profile data
# Will additionally request the "profile" OIDC scope
OIDC_UPDATE_PROFILE = False

# List any custom OIDC scopes needed for custom claims
OIDC_CUSTOM_SCOPES = []

# OIDC Claims to check for automatic group assignments
# List the names of the OIDC claims to check, the values returned in those claims should
# be the names of the groups to be assigned
OIDC_GROUPS_CLAIMS = []

# Create any groups returned in the claims listed in OIDC_GROUPS_CLAIMS that don't exist
OIDC_CREATE_GROUPS = False

# List any manually managed groups other than 'Default' that you don't want OIDC users removed from
OIDC_IGNORE_GROUPS = []

# Enable cluster mode for this instance by setting an integer ID >= 1
CLUSTER_ID = None

# Set the Cluster URL pattern common to all servers in the cluster
# e.g. https://mycluster%s.mydomain
CLUSTER_URL = ''

# URL to a page where a user can reset the password
RESET_PASSWORD_LINK = ''

# Additional HTML code to add at the bottom of pages
HTML_AFTER_BODY = ''

# Number of hours before tasks are automatically deleted
# from an account that is exceeding a disk quota
QUOTA_EXCEEDED_GRACE_PERIOD = 8

# URL to call when an account is about to have some of its tasks removed
QUOTA_EXCEEDED_NOTIFY_URL = None

# Maximum number of processing nodes to show in "Processing Nodes" menus/dropdowns
UI_MAX_PROCESSING_NODES = None

# Number of hours before partial tasks
# are removed (or None to disable)
CLEANUP_PARTIAL_TASKS = 72

# Number of hours before empty projects
# are removed for users that have zero quotas
CLEANUP_EMPTY_PROJECTS = None

# Maximum number of threads that a worker should use for processing
WORKERS_MAX_THREADS = 2

# Maximum number of seconds a worker task should take before being terminated
WORKERS_MAX_TIME_LIMIT = None

# Username to log-in automatically if the user is anonymous
# (e.g. for a demo or read-only site)
AUTO_LOGIN_USER = None

# Link to GCP docs
GCP_DOCS_LINK = "https://docs.webodm.org/ground-control-points/#gcp-file-format"

# Link to general docs
DOCS_LINK = "https://docs.webodm.org"

# Link to task options docs
TASK_OPTIONS_DOCS_LINK = ""

# Whether to display onboarding instructions and 
# automatically create a first project on first login
DASHBOARD_ONBOARDING = True

if TESTING or FLUSHING:
    CELERY_TASK_ALWAYS_EAGER = True
    EXTERNAL_AUTH_ENDPOINT = 'http://0.0.0.0:5555/auth'

try:
    from .local_settings import *
except ImportError:
    pass

try:
    from .settings_override import *
except ImportError:
    pass
