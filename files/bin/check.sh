#! /bin/bash

usage() {
    echo "Usage: $0  [-Z ZONES_DIR] [-C CONFIG_DIR [-C CONFIG_DIR]...] [-M MERGED_CONFIG_DIR] [-c CONFIG_FILE]" 1>&2
    exit 1
}

check_config() {
    knotc -c $1 conf-check
}

check_zones() {
    shopt -s nullglob
    for zone in $1/*.zone; do
        kzonecheck $zone
    done
}

CONFIG_DIRS=""
MERGED_CONFIG_DIR=merged-config
while getopts Z:C:M:c: opt
do
  case $opt in
    Z)
        ZONES_DIR="$OPTARG";;
    C)
        CONFIG_DIRS="$CONFIG_DIRS $OPTARG/";;
    M)
        MERGED_CONFIG_DIR="$OPTARG";;
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
    check_zones "$ZONES_DIR"
fi

if [ -n "$CONFIG_DIRS" ]; then
    rm -fr $MERGED_CONFIG_DIR
    mkdir $MERGED_CONFIG_DIR
    rsync -a $CONFIG_DIRS $MERGED_CONFIG_DIR
    check_config $MERGED_CONFIG_DIR/${CONFIG_FILE:-knot.conf}
fi