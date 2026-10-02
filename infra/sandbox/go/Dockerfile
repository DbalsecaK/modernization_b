# Sandbox image of the Go pack (spec 15.5, ADR-0029): the Go 1.26 toolchain and a module cache with the pack's
# libraries (shopspring/decimal, jackc/pgx/v5 and what they need), downloaded at build time because the sandbox runs
# without network. Builds resolve modules only from that cache (GOPROXY=off, GOFLAGS=-mod=mod); the build cache and
# the temporary files live in the /work tmpfs. PostgreSQL runs inside the same container for the equivalence check: on
# loopback only, with its data in /work, started and stopped by the script of each run. Base images pinned by digest;
# PostgreSQL comes from its official image and the toolchain is copied from the official Go image (no package mirrors
# at build time).

# golang:1.26 (Go 1.26.8, Debian)
FROM golang@sha256:0f063af2d465d8dcae54cce04278ada488b96f77b42449c8d071e47d016cc65a AS toolchain
ENV GOMODCACHE=/opt/gomodcache GOFLAGS=-mod=mod GOTOOLCHAIN=local CGO_ENABLED=0
COPY seed /seed
WORKDIR /seed
RUN go mod download all \
 && go build -o /dev/null . \
 && go vet . \
 && chmod -R a+rX /opt/gomodcache

# postgres:17.11 (Debian); initdb, pg_ctl and psql are already on its PATH (/usr/lib/postgresql/17/bin)
FROM postgres@sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f
COPY --from=toolchain /usr/local/go /usr/local/go
COPY --from=toolchain /opt/gomodcache /opt/gomodcache
ENV PATH=/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/postgresql/17/bin \
    GOTOOLCHAIN=local \
    GOFLAGS=-mod=mod \
    GOPROXY=off \
    GOSUMDB=off \
    GOMODCACHE=/opt/gomodcache \
    GOPATH=/work/go \
    GOCACHE=/work/gocache \
    GOTMPDIR=/work/tmp \
    CGO_ENABLED=0
# A warm build cache of the standard library and the libraries (same toolchain, path and settings as a run), which
# each run copies into /work so a build does not compile them again; the image itself stays read-only.
COPY seed /opt/go-seed
RUN cd /opt/go-seed \
 && GOCACHE=/opt/gocache GOPATH=/tmp/gopath GOTMPDIR= go build -o /dev/null . \
 && GOCACHE=/opt/gocache GOPATH=/tmp/gopath GOTMPDIR= go test -count=1 ./... > /dev/null \
 && GOCACHE=/opt/gocache GOPATH=/tmp/gopath GOTMPDIR= go build -o /dev/null testing net/http net/http/httptest \
    encoding/json database/sql context errors fmt strconv strings time encoding/hex \
 && rm -rf /tmp/gopath && chmod -R a+rX /opt/gocache
# The sandbox runs its own script, which initializes and starts the database itself (initdb in /work).
ENTRYPOINT []
CMD ["sh"]
LABEL org.opencontainers.image.title="nexti-sandbox-go" org.opencontainers.image.description="Sandbox for the Go pack"
