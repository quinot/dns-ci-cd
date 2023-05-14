#! /bin/bash

SSH_USER=knotssh
RSYNCPARAMS="--itemize-changes --verbose --human-readable --times --checksum --recursive --delete --delete-excluded"

usage() {
    echo "Usage: $0 -b BUILD_DIR -s SERVER [zone [zone]...]" 1>&2
    exit 1

}

check() {
    if [ -z "$1" ]; then
        echo "$2 is not set" 1>&2
        exit 1
    fi
}

while getopts z:b:s: opt
do
  case $opt in
    z)
        ZONES_DIR="$OPTARG";;
    b)
        BUILD_DIR="$OPTARG";;
    s)
        SERVER="$OPTARG";;
  esac
done
shift `expr $OPTIND - 1`

check "$ZONES_DIR" "zones directory (-z)"
check "$BUILD_DIR" "build directory (-b)"
check "$SERVER" "server (-s)"
check "$SSH_PRIVATE_KEY" "SSH private key (\$SSH_PRIVATE_KEY)"

set -x
eval "$(ssh-agent -s)" > /dev/null 2>&1
trap "ssh-agent -k" EXIT
ssh-add <(echo "$SSH_PRIVATE_KEY") > /dev/null 2>&1

if [ ! -f ~/.ssh/config ]; then
    mkdir -p ~/.ssh
    echo -e "Host *\n\tStrictHostKeyChecking accept-new\n" > ~/.ssh/config
fi

# Push zone files

rsync $RSYNCPARAMS $BUILD_DIR/$ZONES_DIR/ "$SSH_USER"@"$SERVER":"$ZONES_DIR"/

# Reload

if [ $# = 0 ]; then
    # Reload server configuration and all zones

    ssh "$SSH_USER@$SERVER" "knotc reload"
else
    # Reload selected zones

    ssh "$SSH_USER@$SERVER" "knotc zone-reload $*"
fi

# Show status

ssh "$SSH_USER@$SERVER" "knotc zone-status"