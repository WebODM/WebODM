from django.contrib.auth.models import User
from django.contrib.auth import login
from rest_framework.views import APIView
from rest_framework import exceptions, permissions, parsers
from rest_framework.response import Response
from app.auth.backends import get_user_from_external_auth_response, cluster_mismatch
import requests
from django.utils.translation import gettext as _
from webodm import settings

class ExternalTokenAuth(APIView):
    permission_classes = (permissions.AllowAny,)
    parser_classes = (parsers.JSONParser, parsers.FormParser,)

    def post(self, request):
        # This should never happen
        if settings.EXTERNAL_AUTH_ENDPOINT == '':
            return Response({'error': 'EXTERNAL_AUTH_ENDPOINT not set'})

        token = request.COOKIES.get('external_access_token', '')
        if token == '':
            return Response({'error': 'external_access_token cookie not set'})

        try:
            r = requests.post(settings.EXTERNAL_AUTH_ENDPOINT, headers={
                'Authorization': "Bearer %s" % token 
            })
            res = r.json()
            if res.get('user_id') is not None:
                user = get_user_from_external_auth_response(res)
                if user is not None:
                    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                    return Response({'redirect': '/'})
                elif cluster_mismatch(res) and settings.CLUSTER_URL != '':
                    return Response({'redirect': settings.CLUSTER_URL % res['cluster_id']})
                else:
                    return Response({'error': _('Invalid credentials')})
            else:
                return Response({'error': res.get('message', 'Invalid external server response')})
        except Exception as e:
            return Response({'error': str(e)})

