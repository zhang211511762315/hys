"""Explicitly isolated MySQL fixtures only; never load production credentials."""
import os
import ipaddress
from .settings_test import *

if os.environ.get('OPTIMIZATION_MYSQL_TEST') != '1':
    raise RuntimeError('isolated MySQL test opt-in required')
port = int(os.environ['OPTIMIZATION_MYSQL_PORT'])
host = os.environ.get('OPTIMIZATION_MYSQL_HOST', '127.0.0.1')
if not ipaddress.ip_address(host).is_private:
    raise RuntimeError('isolated network address required')
if port < 1024 or port == 3306:
    raise RuntimeError('refusing a production-style database port')
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.mysql', 'HOST': host, 'PORT': port,
    'NAME': 'optimization_release', 'USER': 'root',
    'PASSWORD': os.environ['OPTIMIZATION_MYSQL_PASSWORD'],
    'OPTIONS': {'charset': 'utf8mb4', 'connect_timeout': 5},
    'TEST': {'NAME': 'optimization_test_release'},
}}
