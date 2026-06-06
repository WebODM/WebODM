ARG WEBODM_BASE_IMAGE=webodm/webodm_webapp
FROM ${WEBODM_BASE_IMAGE}

COPY custom/swisstopo/patch-swisstopo.js \
  /webodm/coreplugins/posm-gcpi/public/patch-swisstopo.js

RUN node /webodm/coreplugins/posm-gcpi/public/patch-swisstopo.js
