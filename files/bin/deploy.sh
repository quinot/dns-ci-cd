#! /bin/bash

RSYNCPARAMS="--out-format=%n --recursive --delete --delete-excluded"

usage() {
    echo "Usage: $0  [-Z ZONES_DIR] [-C CONFIG_DIR] [-D DEST_DIR] [USER@]SERVER" 1>&2
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

DEST_DIR=.
# Default: remote user home directory

while getopts Z:C:s: opt
do
  case $opt in
    Z)
        ZONES_DIR="$OPTARG";;
    C)
        CONFIG_DIR="$OPTARG";;
    D)
        DEST_DIR="$OPTARG";;
    *)
        usage;;
  esac
done
shift `expr $OPTIND - 1`

if [ "$#" != 1 ]; then
    usage
fi
DEST=$1

check() {
    if [ -z "$1" ]; then
        echo "$2 is not set" 1>&2
        exit 1
    fi
}

check "$DEST" "destination"
check "$SSH_PRIVATE_KEY" "SSH private key (\$SSH_PRIVATE_KEY)"

set -ex

eval "$(ssh-agent -s)" > /dev/null 2>&1
trap "ssh-agent -k" EXIT
ssh-add <(echo "$SSH_PRIVATE_KEY") > /dev/null 2>&1

if [ ! -f ~/.ssh/config ]; then
    mkdir -p ~/.ssh
    echo -e "Host *\n\tStrictHostKeyChecking accept-new\n" > ~/.ssh/config
fi

# Push zone files

updated_config=false
updated_zones=""
for file in rsync $RSYNCPARAMS $ZONES_DIR $CONFIG_DIR "$DEST":"$DEST_DIR/"; do
    case $file in
        $CONFIG_DIR/*) updated_config=true ;;
        $ZONES_DIR/*)  updated_zones="$updated_zones $(basename $file .zone)";;
    esac
done

# Reload

if $updated_config; then
    # Reload server configuration and all zones

    ssh "$DEST" "knotc reload"
else
    # Reload updated zones

    ssh "$DEST" "knotc zone-reload $updated_zones"
fi

# Show status

ssh "$DEST" "knotc zone-status"