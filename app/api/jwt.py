# Partially derived from djangorestframework-jwt 1.11.0
# MIT

import datetime
import jwt
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils.translation import gettext as _
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .authentication import jwt_payload, jwt_encode, jwt_decode, jwt_user, JWT_REFRESH_EXPIRATION_DELTA


class JSONWebTokenSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    impersonate = serializers.CharField(required=False)

    def validate(self, attrs):
        credentials = {
            'username': attrs.get('username'),
            'password': attrs.get('password')
        }

        if all(credentials.values()):
            user = authenticate(**credentials)
            if user:
                if not user.is_active:
                    msg = _('User account is disabled.')
                    raise serializers.ValidationError(msg)

                if attrs.get('impersonate'):
                    if not user.is_superuser:
                        raise serializers.ValidationError(_('Cannot impersonate, user is not superuser.'))
                    try:
                        impersonated = User.objects.get(username=attrs.get('impersonate'))
                        if not impersonated.is_active:
                            msg = _('User account is disabled.')
                            raise serializers.ValidationError(msg)
                        
                        return {
                            'token': jwt_encode(jwt_payload(impersonated)),
                            'user': impersonated
                        }
                    except:
                        msg = _('Unable to log in with provided credentials.')
                        raise serializers.ValidationError({'non_field_errors': msg, 'impersonate': "Invalid"})
                else:
                    return {
                        'token': jwt_encode(jwt_payload(user)),
                        'user': user
                    }
            else:
                raise serializers.ValidationError(_('Unable to log in with provided credentials.'))
        else:
            raise serializers.ValidationError(_('Must include "username" and "password".'))


class RefreshJSONWebTokenSerializer(serializers.Serializer):
    token = serializers.CharField()

    def validate(self, attrs):
        try:
            payload = jwt_decode(attrs['token'])
        except jwt.ExpiredSignatureError:
            raise serializers.ValidationError(_('Signature has expired.'))
        except jwt.DecodeError:
            raise serializers.ValidationError(_('Error decoding signature.'))
        user = jwt_user(payload, serializers.ValidationError)

        orig_iat = payload.get('orig_iat')
        if not orig_iat:
            raise serializers.ValidationError(_('orig_iat field is required.'))
        if datetime.datetime.now(datetime.timezone.utc).timestamp() > orig_iat + JWT_REFRESH_EXPIRATION_DELTA.total_seconds():
            raise serializers.ValidationError(_('Refresh has expired.'))

        new_payload = jwt_payload(user)
        new_payload['orig_iat'] = orig_iat
        return {
            'token': jwt_encode(new_payload),
            'user': user
        }


class JSONWebTokenAPIView(APIView):
    permission_classes = ()
    authentication_classes = ()
    serializer_class = None

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request, 'view': self})
        if serializer.is_valid():
            return Response({'token': serializer.validated_data['token']})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ObtainJSONWebToken(JSONWebTokenAPIView):
    """
    API View that receives a POST with a user's username and password
    and an optional impersonate parameter (admin only)

    Returns a JSON Web Token that can be used for authenticated requests.
    """
    serializer_class = JSONWebTokenSerializer


class RefreshJSONWebToken(JSONWebTokenAPIView):
    serializer_class = RefreshJSONWebTokenSerializer


obtain_jwt_token = ObtainJSONWebToken.as_view()
refresh_jwt_token = RefreshJSONWebToken.as_view()
