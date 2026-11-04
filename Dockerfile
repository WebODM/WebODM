# syntax=docker/dockerfile:1
FROM ubuntu:24.04 AS common
LABEL maintainer="Piero Toffanin <pt@masseranolabs.com>"

# Build-time variables
ARG DEBIAN_FRONTEND=noninteractive
ARG NODE_MAJOR=20
ARG PYTHON_VERSION=3.14
ARG RELEASE_CODENAME=noble
ARG WORKDIR=/webodm

# Run-time variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=$WORKDIR
ENV PROJ_LIB=/usr/share/proj
ENV NPM_CONFIG_AUDIT=false NPM_CONFIG_FUND=false NPM_CONFIG_UPDATE_NOTIFIER=false NPM_CONFIG_LOGLEVEL=error

#### Common setup ####

# Create and change into working directory
WORKDIR $WORKDIR

# Allow multi-line runs, break on errors and output commands for debugging.
# The following does not work in Podman unless you build in Docker
# compatibility mode: <https://github.com/containers/podman/issues/8477>
# You can manually prepend every RUN script with `set -ex` too.
SHELL ["sh", "-exc"]

RUN <<EOT
    # Common system configuration, should change very infrequently
    # Set timezone to UTC
    echo "UTC" > /etc/timezone
EOT

FROM common AS build

# Install Python deps -- install & remove cleanup build-only deps in the process
COPY requirements.txt ./

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    <<EOT
    # Build-time dependencies
    apt-get -qq update
    apt-get install -y --no-install-recommends curl ca-certificates gnupg cmake g++
    curl -fsSL 'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xf23c5a6cf475977595c89f51ba6932366a755776' | gpg --dearmor -o /etc/apt/trusted.gpg.d/deadsnakes.gpg
    echo "deb http://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu $RELEASE_CODENAME main" > /etc/apt/sources.list.d/deadsnakes.list
    curl -fsSL 'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x6b827c12c2d425e227edca75089ebe08314df160' | gpg --dearmor -o /etc/apt/trusted.gpg.d/ubuntugis.gpg
    echo "deb http://ppa.launchpadcontent.net/ubuntugis/ubuntugis-unstable/ubuntu $RELEASE_CODENAME main" > /etc/apt/sources.list.d/ubuntugis.list
    # Node.js deb source
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/nodesource.gpg
    echo "deb https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
    # Nginx deb source (official stable)
    curl -fsSL https://nginx.org/keys/nginx_signing.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/nginx.gpg
    echo "deb https://nginx.org/packages/ubuntu $RELEASE_CODENAME nginx" > /etc/apt/sources.list.d/nginx.list
    printf "Package: *\nPin: origin nginx.org\nPin: release o=nginx\nPin-Priority: 900\n" > /etc/apt/preferences.d/99nginx
    # Update package list
    apt-get update
    # Install common deps, starting with NodeJS
    apt-get -qq install -y nodejs
    # Python, GDAL, PDAL, nginx, letsencrypt, psql
    apt-get install -y --no-install-recommends \
        python$PYTHON_VERSION python$PYTHON_VERSION-venv python$PYTHON_VERSION-dev build-essential git libproj-dev proj-bin gdal-bin pdal libpdal-dev \
        libgdal-dev nginx certbot gettext-base cron postgresql-client gettext tzdata
    # Create virtualenv
    python$PYTHON_VERSION -m venv $WORKDIR/venv
    # Build entwine
    mkdir /staging && cd /staging
    git clone -b webodm https://github.com/WebODM/entwine && cd entwine
    mkdir build && cd build
    cmake .. -DWITH_TESTS=OFF -DWITH_ZSTD=OFF -DCMAKE_INSTALL_PREFIX=/staging/entwine/build/install
    make -j6
    make install
    cd /webodm
EOT

# Modify PATH to prioritize venv, effectively activating venv
ENV PATH="$WORKDIR/venv/bin:$PATH"

RUN --mount=type=cache,target=/root/.cache/pip \
    <<EOT
    # Install Python dependencies
    # Install pip
    pip install -U pip==26.0.1 setuptools==80.9.0 wheel==0.46.3
    # Install Python requirements, including correct Python GDAL bindings.
    # rasterio and pyproj are compiled against the system GDAL/PROJ
    pip install -r requirements.txt --no-binary rasterio,pyproj
    pip install gdal[numpy]=="$(gdal-config --version).*" --no-build-isolation
    # Cleanup build
    find $WORKDIR/venv/lib -type f \( -name '*.pyx' -o -name '*.pxd' -o -name '*.pxi' -o -name '*.c' -o -name '*.cpp' \) -delete
    rm -rf /tmp/* /var/tmp/*
EOT

# Install project Node dependencies
COPY package.json ./
RUN --mount=type=cache,target=/root/.npm \
    <<EOT
    npm install
    # Install webpack, webpack CLI
    npm install -g webpack@5.89.0 webpack-cli@5.1.4
EOT

# Copy remaining files
COPY . ./

# Defining this here allows for caching of previous layers.
ARG TEST_BUILD

RUN <<EOT
    # Final build steps (in one roll to prevent too many layers).
    # Setup cron
    chmod 0644 ./nginx/crontab
    ln -s ./nginx/crontab /var/spool/cron/crontabs/root
    # NodeODX setup
    chmod +x ./nginx/letsencrypt-autogen.sh
    ./nodeodm/setup.sh
    ./nodeodm/cleanup.sh
    # Run webpack build, Django setup and final cleanup
    webpack --mode production
    # Django setup
    python manage.py collectstatic --noinput
    python manage.py rebuildplugins
    python manage.py translate build --safe
    # Install ffmpeg
    python /webodm/app/scripts/install_ffmpeg.py
    # Remove stale temp files
    rm -rf /tmp/* /var/tmp/*
    # Remove auto-generated secret key (happens on import of settings when none is defined)
    rm /webodm/webodm/secret_key.py
EOT

FROM common AS app

# Modify PATH to prioritize venv, effectively activating venv
ENV PATH="$WORKDIR/venv/bin:$PATH"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=cache,target=/root/.npm \
    <<EOT
    # Run-time dependencies
    apt-get -qq update
    apt-get install -y --no-install-recommends curl ca-certificates gnupg
    curl -fsSL 'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xf23c5a6cf475977595c89f51ba6932366a755776' | gpg --dearmor -o /etc/apt/trusted.gpg.d/deadsnakes.gpg
    echo "deb http://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu $RELEASE_CODENAME main" > /etc/apt/sources.list.d/deadsnakes.list
    curl -fsSL 'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x6b827c12c2d425e227edca75089ebe08314df160' | gpg --dearmor -o /etc/apt/trusted.gpg.d/ubuntugis.gpg
    echo "deb http://ppa.launchpadcontent.net/ubuntugis/ubuntugis-unstable/ubuntu $RELEASE_CODENAME main" > /etc/apt/sources.list.d/ubuntugis.list
    # Node.js deb source
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/nodesource.gpg
    echo "deb https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
    # Nginx deb source (official stable)
    curl -fsSL https://nginx.org/keys/nginx_signing.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/nginx.gpg
    echo "deb https://nginx.org/packages/ubuntu $RELEASE_CODENAME nginx" > /etc/apt/sources.list.d/nginx.list
    printf "Package: *\nPin: origin nginx.org\nPin: release o=nginx\nPin-Priority: 900\n" > /etc/apt/preferences.d/99nginx
    # Update package list
    apt-get update
    # Install common deps, starting with NodeJS
    apt-get -qq install -y nodejs
    # Python, GDAL, PDAL, nginx, letsencrypt, psql, git, exiftool
    apt-get install -y --no-install-recommends \
        python$PYTHON_VERSION gdal-bin pdal \
        nginx certbot logrotate gettext-base cron postgresql-client gettext tzdata git exiftool
    # Install webpack, webpack CLI
    npm install -g webpack@5.89.0 webpack-cli@5.1.4
    # Install splat-tools
    curl -fsSL "https://github.com/uav4geo/Splat-Tools/releases/download/v1.0.3/splat-tools-1.0.3-$(uname -m)-linux.tar.gz" | tar -xz -C /usr/bin --strip-components=1 "splat-tools-1.0.3-$(uname -m)-linux/splat-tools" && /usr/bin/splat-tools --version
    # Cleanup of build requirements
    apt-get autoremove -y
    apt-get clean
    rm -rf /var/lib/apt/lists/*
    # Remove stale temp files
    rm -rf /tmp/* /var/tmp/*
EOT

COPY --from=build /staging/entwine/build/install/bin/entwine /usr/bin/entwine
COPY --from=build /staging/entwine/build/install/lib/libentwine* /usr/lib/
COPY --from=build /usr/bin/ffmpeg /usr/bin/ffmpeg
COPY --from=build $WORKDIR ./

VOLUME /webodm/app/media
