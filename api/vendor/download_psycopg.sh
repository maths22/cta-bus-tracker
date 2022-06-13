#!/usr/bin/env bash

cd $(dirname ${0})
rm -rf psycopg_binary*
mkdir -p tmp
pip download --only-binary=:all: --no-deps --platform manylinux_2_24_x86_64 --implementation cp --abi cp38 --dest tmp psycopg-binary==$1
unzip tmp/*.whl
rm -rf tmp