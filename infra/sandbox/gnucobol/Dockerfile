# Sandbox image of the local COBOL/CICS engine (ADR-0056, point 7): GnuCOBOL compiles the customer's programs, the
# platform's substitutes stand in for the CICS services (maps, LINK/XCTL, syncpoints) and the VSAM files are
# GnuCOBOL indexed files. python3 runs the small helper that moves bytes between the cases and the programs; no
# network, no privileges, the root filesystem read-only, everything written under /work (tmpfs).
#
# debian:bookworm-slim, pinned by digest. GnuCOBOL 3.1.2 comes from the Debian repository at build time.
FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

RUN apt-get update \
 && apt-get install -y --no-install-recommends gnucobol3 libcob4 python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && cobc --version

ENV COB_LIBRARY_PATH=/work/bin \
    LANG=C.UTF-8
WORKDIR /work
USER nobody
