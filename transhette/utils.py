from django.conf import settings
from transhette import settings as transhette_settings


def get_setting(name, default=None):
    return getattr(settings, name, getattr(transhette_settings, name, default))
