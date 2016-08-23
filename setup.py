#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys

try:
    from setuptools import setup
except ImportError:
    from distuitls.core import setup

# Stealing this from Cory Benfield who stole it from Kenneth Reitz
if sys.argv[-1] == 'publish':
    os.system('python setup.py sdist upload')
    sys.exit()

packages = [
    'wsproto',
]

setup(
    name='wsproto',
    version='1.0.0',
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
        'Programming Language :: Python :: 3.5',
        'Programming Language :: python :: Implementation :: CPython',
    ],
    install_requires=[
        'h11==0.5.0',
    ],
)
