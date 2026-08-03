#!/bin/sh
set -eu

umask 077
install -d -m 0700 -o ngopilot -g ngopilot "${DATA_ROOT:-/data}"
exec gosu ngopilot "$@"
