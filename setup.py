#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import sys

try:
    from setuptools import setup
except ImportError:
    from distuitls.core import setup

# Get the version
version_regex = r'__version__ = ["\']([^"\']*)["\']'
with open('wsproto/__init__.py', 'r') as f:
    text = f.read()
    match = re.search(version_regex, text)

    if match:
        version = match.group(1)
    else:
        raise RuntimeError("No version number found!")

# Stealing this from Cory Benfield who stole it from Kenneth Reitz
if sys.argv[-1] == 'publish':
    os.system('python setup.py sdist upload')
    sys.exit()

packages = [
    'wsproto',
]

setup(
    name='wsproto',
    version=version,
    description='WebSockets state-machine based protocol implementation',
    author='Benno Rice',
    author_email='benno@jeamland.net',
    packages=packages,
    package_data={'': ['LICENSE', 'README.md']},
    package_dir={'wsproto': 'wsproto'},
    include_package_data=True,
    license='BSD License',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
    ],
    install_requires=[
        'h11 ~= 0.7.0',  # means: 0.7.x where x >= 0
    ],
)
