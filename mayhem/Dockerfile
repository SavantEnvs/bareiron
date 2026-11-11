# syntax=docker/dockerfile:1.7
# Commit image for bareiron (a minimal Minecraft server): built on the org C/C++ base.
#   DOCKER_BUILDKIT=1 docker build -f mayhem/Dockerfile --build-arg COMMIT=$(git rev-parse HEAD) -t bareiron-commit:test .
FROM ghcr.io/savantenvs/base:20261023

ARG COMMIT
ARG REPO_URL
ARG SOURCE_DATE_EPOCH
ARG SANITIZER_FLAGS
ARG COVERAGE_FLAGS=
ARG MAYHEM_JOBS=

# bareiron needs include/registries.h and src/registries.c, which upstream generates from Mojang's
# 1.21.8 server.jar (data generator) by build_registries.js. They are produced once, here, from the
# pinned jar into /opt/toolchains/deps (SPEC §6.2 item 19) so build.sh never touches the network.
USER root
ARG MC_JAR_URL=https://piston-data.mojang.com/v1/objects/6bce4ef400e4efaa63a13d5e6f6b500be969ef81/server.jar
ARG MC_JAR_SHA256=2349d9a8f0d4be2c40e7692890ef46a4b07015e7955b075460d02793be7fbbe7
COPY build_registries.js /tmp/gen/build_registries.js
RUN { [ -z "$SOURCE_DATE_EPOCH" ] || repro-sources-list.sh; } \
 && apt-get update \
 && apt-get install -yq --no-install-recommends openjdk-21-jre-headless nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && d=/opt/toolchains/deps/minecraft-registries-1.21.8 \
 && mkdir -p "$d/src" "$d/include" /tmp/gen/notchian /tmp/gen/src /tmp/gen/include \
 && cd /tmp/gen/notchian \
 && curl -fsSL -o server.jar "$MC_JAR_URL" \
 && echo "${MC_JAR_SHA256}  server.jar" | sha256sum -c - \
 && java -DbundlerMainClass=net.minecraft.data.Main -jar server.jar --all >/dev/null \
 && cd /tmp/gen && node build_registries.js \
 && cp src/registries.c "$d/src/" && cp include/registries.h "$d/include/" \
 && chmod -R a+rX "$d" && rm -rf /tmp/gen

USER mayhem
WORKDIR /mayhem
COPY --chown=2000:2000 . /mayhem

RUN if [ -x /opt/mayhem/ccache/prefill ]; then /opt/mayhem/ccache/prefill bash mayhem/build.sh; \
    else bash mayhem/build.sh; fi

RUN if [ -f mayhem/test.sh ]; then bash mayhem/test.sh; else echo "no mayhem/test.sh — repo ships no functional tests"; fi

LABEL org.opencontainers.image.source="${REPO_URL}" \
      org.opencontainers.image.revision="${COMMIT}" \
      rlenv.tier="commit" \
      rlenv.source_date_epoch="${SOURCE_DATE_EPOCH}" \
      rlenv.user="mayhem"

USER mayhem
WORKDIR /mayhem
