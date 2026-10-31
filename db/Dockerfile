# syntax=docker/dockerfile:1

# Stage 1: PostgreSQL 9.5 + PostGIS 2.3 (used only to read old data during upgrades)
FROM ubuntu:24.04 AS pg95
ARG DEBIAN_FRONTEND=noninteractive
ARG PG95_VERSION=9.5.25
ARG PG95_SHA256=b7a900932f5a1e439956436b10a587bd9ee7023424e5fa7e8c483bff3940c334
ARG PROJ4_VERSION=4.9.3
ARG PROJ4_SHA256=6984542fea333488de5c82eea58d699e4aff4b359200a9971537cd7e047185f7
ARG POSTGIS2_VERSION=2.3.2
ARG POSTGIS2_SHA256=e92e34c18f078a3d1a2503cd870efdc4fa9e134f0bcedbbbdb8b46b0e6af09e4

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates wget gcc g++ make file pkg-config \
        libreadline-dev zlib1g-dev libxml2-dev libgeos-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /staging
RUN wget -q https://github.com/WebODM/WebODM/releases/download/v1.9.2/postgresql-$PG95_VERSION.tar.gz && \
    echo "$PG95_SHA256  postgresql-$PG95_VERSION.tar.gz" | sha256sum -c && \
    tar -zxf postgresql-$PG95_VERSION.tar.gz && \
    cd postgresql-$PG95_VERSION && \
    ./configure --prefix=/usr/local/pgsql-9.5 --without-readline > /dev/null && \
    make -j$(nproc) > /dev/null && \
    make install > /dev/null

RUN wget -q https://download.osgeo.org/proj/proj-$PROJ4_VERSION.tar.gz && \
    echo "$PROJ4_SHA256  proj-$PROJ4_VERSION.tar.gz" | sha256sum -c && \
    tar -zxf proj-$PROJ4_VERSION.tar.gz && \
    cd proj-$PROJ4_VERSION && \
    ./configure --prefix=/usr/local/pgsql-9.5 --disable-static > /dev/null && \
    make -j$(nproc) > /dev/null && \
    make install > /dev/null

RUN wget -q https://github.com/WebODM/WebODM/releases/download/v1.9.2/postgis-$POSTGIS2_VERSION.tar.gz && \
    echo "$POSTGIS2_SHA256  postgis-$POSTGIS2_VERSION.tar.gz" | sha256sum -c && \
    tar -zxf postgis-$POSTGIS2_VERSION.tar.gz && \
    cd postgis-$POSTGIS2_VERSION && \
    LDFLAGS="-Wl,-rpath,/usr/local/pgsql-9.5/lib" ./configure \
        --with-pgconfig=/usr/local/pgsql-9.5/bin/pg_config \
        --with-projdir=/usr/local/pgsql-9.5 \
        --without-raster --without-json --without-topology --without-address-standardizer > /dev/null && \
    make -j$(nproc) > /dev/null && \
    make install > /dev/null && \
    rm -rf /usr/local/pgsql-9.5/include /usr/local/pgsql-9.5/lib/*.a /usr/local/pgsql-9.5/share/man

# Stage 2: PostgreSQL 18
FROM ubuntu:24.04 AS pg18
ARG DEBIAN_FRONTEND=noninteractive
ARG PG_VERSION=18.6
ARG PG_SHA256=555610c24d53e4316da5b7d3fc25c279d96856d5e0e23ee308c328c5fa881d9f

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates wget gcc make bzip2 bison flex perl libreadline-dev zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /staging
RUN wget -q https://ftp.postgresql.org/pub/source/v$PG_VERSION/postgresql-$PG_VERSION.tar.bz2 && \
    echo "$PG_SHA256  postgresql-$PG_VERSION.tar.bz2" | sha256sum -c && \
    tar -jxf postgresql-$PG_VERSION.tar.bz2 && \
    cd postgresql-$PG_VERSION && \
    ./configure --prefix=/usr/local/pgsql --without-icu > /dev/null && \
    make -j$(nproc) > /dev/null && \
    make install > /dev/null && \
    rm -rf /usr/local/pgsql/include /usr/local/pgsql/lib/*.a /usr/local/pgsql/lib/pkgconfig

RUN conf=/usr/local/pgsql/share/postgresql.conf.sample && \
    sed -ri "s/#autovacuum_max_workers = 3/autovacuum_max_workers = 6/" $conf && \
    sed -ri "s/#autovacuum_naptime = 1min/autovacuum_naptime = 15s/" $conf && \
    sed -ri "s/#autovacuum_vacuum_threshold = 50/autovacuum_vacuum_threshold = 25/" $conf && \
    sed -ri "s/#autovacuum_vacuum_scale_factor = 0.2/autovacuum_vacuum_scale_factor = 0.1/" $conf && \
    sed -ri "s/#autovacuum_analyze_threshold = 50/autovacuum_analyze_threshold = 10/" $conf && \
    sed -ri "s/#autovacuum_analyze_scale_factor = 0.1/autovacuum_analyze_scale_factor = 0.05/" $conf && \
    sed -ri "s/#autovacuum_vacuum_cost_limit = -1/autovacuum_vacuum_cost_limit = 1000/" $conf && \
    sed -ri "s!^#?(listen_addresses)\s*=\s*\S+.*!\1 = '*'!" $conf && \
    grep -q "^autovacuum_max_workers = 6" $conf && \
    grep -q "^listen_addresses = '*'" $conf

# Stage 3: runtime image
FROM ubuntu:24.04
LABEL maintainer="Piero Toffanin <pt@masseranolabs.com>"
ARG DEBIAN_FRONTEND=noninteractive

ENV POSTGRES_PASSWORD=postgres
ENV POSTGRES_HOST_AUTH_METHOD=trust
ENV POSTGRES_ALLOW_HOST=all
ENV PG_MAJOR=18
ENV LANG=en_US.utf8
ENV PATH=$PATH:/usr/local/pgsql/bin
ENV PGDATA=/var/lib/postgresql/data/18

RUN apt-get update && apt-get install -y --no-install-recommends \
        gosu locales zlib1g libreadline8t64 libxml2 libgeos-c1t64 && \
    rm -rf /var/lib/apt/lists/* && \
    localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8 && \
    groupadd -r postgres --gid=999 && \
    useradd -r -g postgres --uid=999 --home-dir=/var/lib/postgresql --shell=/bin/bash postgres && \
    mkdir -p /var/lib/postgresql/data /var/run/postgresql && \
    chown -R postgres:postgres /var/lib/postgresql /var/run/postgresql && \
    chmod 777 /var/lib/postgresql/data && \
    chmod 2777 /var/run/postgresql && \
    gosu nobody true

COPY --from=pg95 /usr/local/pgsql-9.5 /usr/local/pgsql-9.5
COPY --from=pg18 /usr/local/pgsql /usr/local/pgsql

RUN mkdir /docker-entrypoint-initdb.d
COPY init.sql /docker-entrypoint-initdb.d/init-db.sql
COPY docker-entrypoint.sh db-upgrade-9-to-18 /usr/local/bin/
RUN chmod 644 /docker-entrypoint-initdb.d/init-db.sql && \
    chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/db-upgrade-9-to-18 && \
    ln -s /usr/local/bin/docker-entrypoint.sh / && \
    postgres --version && \
    /usr/local/pgsql-9.5/bin/postgres --version

VOLUME /var/lib/postgresql/data
ENTRYPOINT ["docker-entrypoint.sh"]
STOPSIGNAL SIGINT
EXPOSE 5432
CMD ["postgres"]
