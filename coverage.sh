#!/bin/sh

ENVIRONMENTS="py27 py36"

for environment in $ENVIRONMENTS; do
    env COVERAGE_FILE=".coverage.$environment" tox -e $environment
done

coverage combine
coverage report -m
