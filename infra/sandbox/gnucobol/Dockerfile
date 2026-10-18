# Sandbox image of the local COBOL/CICS engine (ADR-0056, point 7): GnuCOBOL compiles the customer's programs, the
# platform's substitutes stand in for the CICS services (maps, LINK/XCTL, syncpoints) and the VSAM files are
# GnuCOBOL indexed files. For programs with EXEC SQL (DB2), Open COBOL ESQL (ocesql) precompiles the SQL against
# PostgreSQL, which runs inside the same container on loopback with its data in /work. python3 runs the small helper
# that moves bytes between the cases and the programs; no network at run time, no privileges, the root filesystem
# read-only, everything written under /work (tmpfs).
#
# postgres:17.11 (Debian bookworm), pinned by digest; GnuCOBOL 3 from the Debian repository; ocesql built from its
# source at build time (the only moment with network).
FROM postgres@sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends gnucobol3 libcob4 libcob4-dev build-essential autoconf automake \
      libtool bison flex pkg-config libpq-dev git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# Open COBOL ESQL 1.4 (opensourcecobol/Open-COBOL-ESQL, Apache 2.0): the EXEC SQL precompiler and its runtime.
RUN git clone --depth 1 --branch v1.4 https://github.com/opensourcecobol/Open-COBOL-ESQL.git /tmp/ocesql \
 && cd /tmp/ocesql \
 && autoreconf -fi >/dev/null 2>&1 \
 && LIBPQ_CFLAGS="-I/usr/include/postgresql" LIBPQ_LIBS="-lpq" ./configure --prefix=/opt/ocesql >/dev/null \
 && make -j"$(nproc)" >/dev/null && make install >/dev/null && ls /opt/ocesql/bin /opt/ocesql/lib

FROM postgres@sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f
RUN apt-get update \
 && apt-get install -y --no-install-recommends gnucobol3 libcob4 python3 libpq5 \
 && rm -rf /var/lib/apt/lists/* \
 && cobc --version
COPY --from=build /opt/ocesql /opt/ocesql
ENV PATH=/opt/ocesql/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/postgresql/17/bin \
    COB_LIBRARY_PATH=/work/bin:/opt/ocesql/lib \
    LD_LIBRARY_PATH=/opt/ocesql/lib \
    LANG=C.UTF-8
WORKDIR /work
USER nobody
