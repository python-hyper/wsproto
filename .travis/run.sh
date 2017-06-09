#!/bin/bash

set -e

# ${foo:-} means "$foo, unless that's undefined, in which case an empty string"
if [ -n "${PYPY_VERSION:-}" ]; then
    curl -Lo pypy.tar.bz2 https://bitbucket.org/squeaky/portable-pypy/downloads/${PYPY_VERSION}-linux_x86_64-portable.tar.bz2
    tar xaf pypy.tar.bz2
    # Something like:
    #   pypy-5.6-linux_x86_64-portable/bin/pypy
    #   pypy3.5-5.7.1-beta-linux_x86_64-portable/bin/pypy
    PYPY=$(echo pypy*/bin/pypy)
    $PYPY -m ensurepip
    $PYPY -m pip install virtualenv
    $PYPY -m virtualenv testenv
    # http://redsymbol.net/articles/unofficial-bash-strict-mode/#sourcing-nonconforming-document
    set +u
    source testenv/bin/activate
    set -u

    # Don't use wsaccel under PyPy
    WSACCEL=0
fi

if [ -z "${WSACCEL:-}" ]; then
    WSACCEL=1
fi

echo "Python version:"
python --version
echo "WSACCEL=$WSACCEL"

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
