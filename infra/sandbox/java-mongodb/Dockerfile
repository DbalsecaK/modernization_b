# Sandbox image of the Java Spring Boot pack with MongoDB (spec 15.5, ADR-0029): MongoDB Community Server 8.0 and, on
# top of it, Temurin 21 and the pack's libraries (with the official MongoDB Java sync driver) in /opt/lib, downloaded
# at build time because the sandbox runs without network. The script of each run starts a throwaway mongod in the /work
# tmpfs as a single-node replica set (transactions need one) on loopback only, compiles and tests the generated code,
# runs the MongoDB equivalence harness and stops the server. Like MySQL it needs none of the exceptions of ADR-0021:
# no network (loopback only), read-only root, user nobody.
# Base images pinned by digest; the JDK is copied from its official image (no package mirrors at build time).
FROM maven@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320 AS libraries
COPY pom.xml /pack/pom.xml
RUN mvn -q -B -f /pack/pom.xml dependency:copy-dependencies -DoutputDirectory=/opt/lib -DincludeScope=test

FROM eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026 AS jdk

# mongo:8.0 (8.0.32, Ubuntu 24.04)
FROM mongo@sha256:d0d926f94df099bff534b7ee5b5986458131a22489dfff8664509af0c1e2ca9c
COPY --from=jdk /opt/java/openjdk /opt/java/openjdk
COPY --from=libraries /opt/lib /opt/lib
ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:$PATH \
    CLASSPATH_LIBS=/opt/lib/* \
    JAVA_TOOL_OPTIONS="-Xss1m -XX:+UseSerialGC" \
    TZ=UTC
# The sandbox runs its own script, which starts mongod itself and initiates the replica set from the harness.
ENTRYPOINT []
CMD ["sh"]
LABEL org.opencontainers.image.title="nexti-sandbox-java-mongodb" org.opencontainers.image.description="Sandbox for the Java Spring Boot pack with MongoDB"
