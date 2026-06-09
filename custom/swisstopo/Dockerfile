ARG WEBODM_BASE_IMAGE=webodm/webodm_webapp
FROM ${WEBODM_BASE_IMAGE}

COPY custom/swisstopo/patch-swisstopo.js /webodm/coreplugins/posm-gcpi/public/patch-swisstopo.js
COPY coreplugins/posm-gcpi/plugin.py /webodm/coreplugins/posm-gcpi/plugin.py
COPY coreplugins/posm-gcpi/manifest.json /webodm/coreplugins/posm-gcpi/manifest.json
COPY coreplugins/posm-gcpi/templates/app.html /webodm/coreplugins/posm-gcpi/templates/app.html
COPY app/management/commands/basemaps.py /webodm/app/management/commands/basemaps.py
COPY app/migrations/0052_add_swissimage_basemap.py /webodm/app/migrations/0052_add_swissimage_basemap.py
COPY app/tests/test_basemap.py /webodm/app/tests/test_basemap.py
COPY app/tests/test_gcpi_integration.py /webodm/app/tests/test_gcpi_integration.py

RUN node /webodm/coreplugins/posm-gcpi/public/patch-swisstopo.js
