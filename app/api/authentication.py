# Partially derived from djangorestframework-jwt 1.11.0 (https://github.com/jpadilla/django-rest-framework-jwt)
# MIT

import datetime
import jwt
from django.conf import settings
from django.contrib.auth.models import User
from django.utils.translation import gettext as _
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

JWT_AUTH_HEADER_PREFIX = 'JWT'
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_DELTA = settings.JWT_AUTH.get('JWT_EXPIRATION_DELTA', datetime.timedelta(seconds=300))
JWT_REFRESH_EXPIRATION_DELTA = settings.JWT_AUTH.get('JWT_REFRESH_EXPIRATION_DELTA', datetime.timedelta(days=7))
JWT_ALLOW_REFRESH = settings.JWT_AUTH.get('JWT_ALLOW_REFRESH', False)


def jwt_payload(user):
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        'user_id': user.pk,
        'username': user.get_username(),
        'exp': now + JWT_EXPIRATION_DELTA,
        'email': user.email,
    }
    if JWT_ALLOW_REFRESH:
        payload['orig_iat'] = int(now.timestamp())
    return payload


def jwt_encode(payload):
    return jwt.encode(payload, settings.SECRET_KEY, JWT_ALGORITHM)


def jwt_decode(token):
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])


def jwt_user(payload, error):
    username = payload.get('username')
    if not username:
        raise error(_('Invalid payload.'))
    try:
        user = User.objects.get_by_natural_key(username)
    except User.DoesNotExist:
        raise error(_('Invalid signature.'))
    if not user.is_active:
        raise error(_('User account is disabled.'))
    return user


class JSONWebTokenAuthentication(BaseAuthentication):
    www_authenticate_realm = 'api'

    def get_jwt_value(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != JWT_AUTH_HEADER_PREFIX.lower().encode():
            return None
        if len(auth) == 1:
            raise exceptions.AuthenticationFailed(_('Invalid Authorization header. No credentials provided.'))
        if len(auth) > 2:
            raise exceptions.AuthenticationFailed(_('Invalid Authorization header. Credentials string should not contain spaces.'))
        return auth[1]

    def authenticate(self, request):
        jwt_value = self.get_jwt_value(request)
        if jwt_value is None:
            return None
        try:
            payload = jwt_decode(jwt_value)
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed(_('Signature has expired.'))
        except jwt.DecodeError:
            raise exceptions.AuthenticationFailed(_('Error decoding signature.'))
        except jwt.InvalidTokenError:
            raise exceptions.AuthenticationFailed()
        return (jwt_user(payload, exceptions.AuthenticationFailed), jwt_value)

    def authenticate_header(self, request):
        return '{0} realm="{1}"'.format(JWT_AUTH_HEADER_PREFIX, self.www_authenticate_realm)


class JSONWebTokenAuthenticationQS(JSONWebTokenAuthentication):
    def get_jwt_value(self, request):
        return request.query_params.get('jwt')
