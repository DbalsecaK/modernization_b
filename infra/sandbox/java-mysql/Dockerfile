# Sandbox image of the Java Spring Boot pack with MySQL (spec 15.5, ADR-0027): MySQL Community Server 8.4 and, on top
# of it, Temurin 21 and the pack's libraries (with MySQL Connector/J) in /opt/lib, downloaded at build time because the
# sandbox runs without network. The script of each run initializes a throwaway database in the /work tmpfs, starts
# MySQL on loopback only, compiles and tests the generated code, runs the equivalence harness and stops the database.
# Unlike Oracle it needs none of the exceptions of ADR-0021: no network (loopback only), read-only root, user nobody.
# Base images pinned by digest; the JDK is copied from its official image (no package mirrors at build time).
FROM maven@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320 AS libraries
COPY pom.xml /pack/pom.xml
RUN mvn -q -B -f /pack/pom.xml dependency:copy-dependencies -DoutputDirectory=/opt/lib -DincludeScope=test

FROM eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026 AS jdk

# mysql:8.4 (8.4.11, Oracle Linux 9)
FROM mysql@sha256:6ea90827b1100f8f2ae306a539f86d2c264a26ed435a2a9f75551dd5c3aeb242
COPY --from=jdk /opt/java/openjdk /opt/java/openjdk
COPY --from=libraries /opt/lib /opt/lib
ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:$PATH \
    CLASSPATH_LIBS=/opt/lib/* \
    JAVA_TOOL_OPTIONS="-Xss1m -XX:+UseSerialGC" \
    TZ=UTC
# The sandbox runs its own script, which initializes and starts the database itself (mysqld --initialize-insecure).
ENTRYPOINT []
CMD ["sh"]
LABEL org.opencontainers.image.title="nexti-sandbox-java-mysql" org.opencontainers.image.description="Sandbox for the Java Spring Boot pack with MySQL"
