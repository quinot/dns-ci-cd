#! /bin/bash

RSYNCPARAMS=" --out-format=%n --archive --checksum --recursive --delete"

usage() {
    echo "Usage: $0  [-Z ZONES_DIR] [-M MERGED_CONFIG_DIR] [USER@]SERVER" 1>&2
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

while getopts Z:M:s: opt
do
  case $opt in
    Z)
        ZONES_DIR="$OPTARG";;
    M)
        MERGED_CONFIG_DIR="$OPTARG";;
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

set -e

eval "$(ssh-agent -s)" > /dev/null 2>&1
trap "ssh-agent -k" EXIT
ssh-add <(echo "$SSH_PRIVATE_KEY") > /dev/null 2>&1

if [ ! -f ~/.ssh/config ]; then
    mkdir -p ~/.ssh
    echo -e "Host *\n\tStrictHostKeyChecking accept-new\n" > ~/.ssh/config
fi

# Push config

updated_config=$(rsync $RSYNCPARAMS -f "protect zones/" $MERGED_CONFIG_DIR/ "$DEST":/config/ | grep -v '/$' || true)
if [ -n "$updated_config" ]; then
    echo "Updated config files: $updated_config"
else
    echo "No config files updated"
fi

# Push zone files

for file in $(rsync $RSYNCPARAMS $ZONES_DIR/ "$DEST":/config/zones/); do
    case $file in
        *.zone) updated_zones="$updated_zones $(basename $file .zone)" ;;
    esac
done
if [ -n "$updated_zones" ]; then
    echo "Updated zones: $updated_zones"
else
    echo "No zones updated"
fi

# Reload

set +x

if [ -n "$updated_config" ]; then
    # Reload server configuration and all zones

    ssh "$DEST" "knotc reload"

elif [ -n "$updated_zones" ]; then
    # Reload updated zones

    ssh "$DEST" "knotc zone-reload $updated_zones"
fi

# Show status

ssh "$DEST" "knotc zone-status"
