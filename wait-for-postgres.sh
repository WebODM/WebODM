#!/bin/bash

set -e

host="$1"
shift
cmd="$@"

if ! psql -h "$host" -U "postgres" -c '\q' >/dev/null 2>&1; then
  >&2 echo "Waiting for Postgres..."
  until psql -h "$host" -U "postgres" -c '\q' >/dev/null 2>&1; do
    sleep 0.5
  done
fi

>&2 echo "Postgres is up"
exec $cmd
