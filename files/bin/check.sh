#! /bin/bash

usage() {
    echo "Usage: $0  [-Z ZONES_DIR] [-C CONFIG_DIR] [-c CONFIG_FILE]" 1>&2
    exit 1
}

check_config() {
    knotc -c $1 conf-check
}

check_zones() {
    for zone in $1/*.zone; do
        kzonecheck $zone
    done
}

while getopts Z:C:c: opt
do
  case $opt in
    Z)
        ZONES_DIR="$OPTARG";;
    C)
        CONFIG_DIR="$OPTARG";;
    c)
        CONFIG_FILE="$OPTARG";;
    *)
        usage;;
  esac
done
shift `expr $OPTIND - 1`

if [ "$#" != 0 ]; then
    usage
fi

set -ex

if [ -n "$ZONES_DIR" ]; then
    shopt -s nullglob
    check_zones "$ZONES_DIR"
fi

if [ -n "$CONFIG_DIR" ]; then
    check_config $CONFIG_DIR/${CONFIG_FILE:-knot.conf}
fi