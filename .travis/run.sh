#!/bin/bash

set -e
set -x

install_wsproto() {
    pip install -U pip setuptools
    python setup.py sdist
    pip install dist/*
    if [ $WSACCEL -eq 1 ]; then
        pip install wsaccel
    fi
}

case "$MODE" in
    flake8)
        pip install flake8
        flake8 --max-complexity 12 wsproto
        ;;

    docs)
        # For autodoc
        install_wsproto
        pip install sphinx
        sphinx-build -nW -b html -d docs/build/doctrees docs/source docs/build/html
        ;;
    pytest)
        install_wsproto
        pip install -r test_requirements.txt

        # Prevent python from seeing our source tree, forcing it to use the
        # installed version
        mkdir empty
        cd empty/

        INSTALLDIR=$(python -c "import os, wsproto; print(os.path.dirname(wsproto.__file__))")
        pytest --cov=$INSTALLDIR --cov-config=../.coveragerc ../test/

        pip install codecov && codecov
        ;;

    autobahn)
        install_wsproto
        pip install coverage

        cd compliance/
        python run-autobahn-tests.py --cov "$SIDE"

        pip install codecov && codecov
        ;;

    *)
        echo "WTF?"
        exit 1
esac
