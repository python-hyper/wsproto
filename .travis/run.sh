#!/bin/bash

set -e
set -x

mkdir empty
cd empty

INSTALLDIR=$(python -c "import os, wsproto; print(os.path.dirname(wsproto.__file__))")
pytest --cov=$INSTALLDIR --cov-config=../.coveragerc ../test/

codecov
