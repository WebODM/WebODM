#!/bin/bash
set -eo pipefail
__dirname=$(cd $(dirname "$0"); pwd -P)
cd "${__dirname}"


# Only execute if TEST_BUILD is set to true
if [[ ! -z ${TEST_BUILD+x} ]]; then
    cd external/NodeODM
    npm install
    echo "NodeODX is setup"
else
    echo "TEST_BUILD is not set"
fi
