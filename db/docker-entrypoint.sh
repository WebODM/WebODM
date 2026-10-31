#!/usr/bin/env bash
set -Eeo pipefail

VOLUME_DIR=/var/lib/postgresql/data
export PGDATA="$VOLUME_DIR/$PG_MAJOR"

if [ "$(id -u)" = '0' ]; then
	mkdir -p "$VOLUME_DIR" /var/run/postgresql
	find "$VOLUME_DIR" \! -user postgres -exec chown postgres '{}' +
	find /var/run/postgresql \! -user postgres -exec chown postgres '{}' +
	chmod 775 /var/run/postgresql || :
	exec gosu postgres "$BASH_SOURCE" "$@"
fi

init_cluster() {
	echo "Initializing new PostgreSQL $PG_MAJOR cluster in $PGDATA"
	mkdir -p "$PGDATA"
	chmod 700 "$PGDATA"
	initdb --username=postgres --pwfile=<(echo "$POSTGRES_PASSWORD") --encoding=UTF8 --locale=en_US.UTF-8 -D "$PGDATA" > /dev/null
	echo "host all all $POSTGRES_ALLOW_HOST $POSTGRES_HOST_AUTH_METHOD" >> "$PGDATA/pg_hba.conf"

	pg_ctl -D "$PGDATA" -o "-c listen_addresses=''" -w start > /dev/null
	for f in /docker-entrypoint-initdb.d/*.sql; do
		echo "Running $f"
		psql -v ON_ERROR_STOP=1 --username postgres --no-password -f "$f" > /dev/null
	done
	pg_ctl -D "$PGDATA" -m fast -w stop > /dev/null
	echo "PostgreSQL init process complete; ready for start up."
}

if [ "${1:0:1}" = '-' ]; then
	set -- postgres "$@"
fi

if [ "$1" = 'postgres' ]; then
	if [ -s "$VOLUME_DIR/PG_VERSION" ] && [ ! -s "$PGDATA/PG_VERSION" ]; then
		db-upgrade-9-to-18
		if [ -d "$VOLUME_DIR/backup-9.5" ]; then
			echo "NOTICE: a backup of the pre-upgrade PostgreSQL 9.5 database is kept in the database volume (backup-9.5). It can be deleted once you are satisfied with the upgrade."
		fi
	fi

	if [ ! -s "$PGDATA/PG_VERSION" ]; then
		init_cluster
	else
		echo "PostgreSQL $PG_MAJOR database directory appears to contain a database; Skipping initialization"
	fi
	chmod 700 "$PGDATA" || :

fi

if [ "$1" = "postgres" ]; then
	set -- "$@" -c log_checkpoints=off
fi

exec "$@"
