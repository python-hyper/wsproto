#!/bin/bash

set -e
set -x

if [ -d empty ]; then
	rm -fr empty
fi

mkdir empty
cd empty

INSTALLDIR=$(python -c "import os, wsproto; print(os.path.dirname(wsproto.__file__))")
pytest --cov=$INSTALLDIR --cov-config=../.coveragerc ../test/

codecov
