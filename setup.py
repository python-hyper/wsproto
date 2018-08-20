#!/usr/bin/env python

import os
import re
import sys

from setuptools import setup, find_packages

PROJECT_ROOT = os.path.dirname(__file__)

with open(os.path.join(PROJECT_ROOT, 'README.rst')) as file_:
    long_description = file_.read()

# Get the version
version_regex = r'__version__ = ["\']([^"\']*)["\']'
with open(os.path.join(PROJECT_ROOT, 'wsproto/__init__.py')) as file_:
    text = file_.read()
    match = re.search(version_regex, text)

    if match:
        version = match.group(1)
    else:
        raise RuntimeError("No version number found!")

# Stealing this from Cory Benfield who stole it from Kenneth Reitz
if sys.argv[-1] == 'publish':
    os.system('python setup.py sdist upload')
    sys.exit()

setup(
    name='wsproto',
    version=version,
    description='WebSockets state-machine based protocol implementation',
    long_description=long_description,
    author='Benno Rice',
    author_email='benno@jeamland.net',
    url='https://github.com/python-hyper/wsproto/',
    packages=find_packages(),
    package_data={'': ['LICENSE', 'README.rst']},
    package_dir={'wsproto': 'wsproto'},
    include_package_data=True,
    license='MIT',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
    ],
    install_requires=[
        'h11 ~= 0.8.1',  # means: 0.8.x where x >= 1
    ],
    extras_require={
        ':python_version == "2.7"':
            ['enum34>=1.0.4, <2'],
    }
)
