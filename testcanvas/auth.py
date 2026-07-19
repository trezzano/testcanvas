# myapp/auth.py
from rest_framework import authentication
from rest_framework import exceptions
from django.contrib.auth.models import User


class StaticTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if not auth_header:
            return None

        try:
            auth_type, token = auth_header.split(' ')
        except ValueError:
            raise exceptions.AuthenticationFailed('Invalid authorization header format')

        if auth_type.lower() != 'bearer':
            raise exceptions.AuthenticationFailed('Unsupported authorization type')

        # Check whether the token matches the one in your configuration
        if token != "secret-token-123":
            raise exceptions.AuthenticationFailed('Invalid token')

        # Return a dummy or system user for Django
        # (Make sure an active user exists in the DB, e.g. "mcp-bot")
        try:
            user = User.objects.get(username="mcp-bot")
        except User.DoesNotExist:
            user = User.objects.create_user(username="mcp-bot", is_active=True)

        return (user, None)