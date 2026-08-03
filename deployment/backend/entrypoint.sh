#!/bin/sh
set -eu

umask 077
data_root="${DATA_ROOT:-/data}"
install -d -m 0700 -o ngopilot -g ngopilot "$data_root"
chown -R ngopilot:ngopilot "$data_root"
exec gosu ngopilot "$@"
