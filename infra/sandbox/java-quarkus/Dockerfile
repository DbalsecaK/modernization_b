# Sandbox image of the Java pack with Quarkus (spec 15.5, ADR-0028): Temurin 21 and the Quarkus 3.40 LTS libraries
# (Quarkus REST with Jackson, Agroal, the PostgreSQL driver, ArC) in /opt/lib, downloaded at build time because the
# sandbox runs without network. Like nexti-sandbox-java, generated code is compiled with javac and its tests run with
# the JUnit console launcher (no Maven or Quarkus build at run time); nothing is written outside the /work tmpfs.
# PostgreSQL runs inside the same container for the equivalence check: on loopback only, with its data in /work,
# started and stopped by the script of each run. Base images pinned by digest; PostgreSQL comes from its official image
# and the JDK is copied from its official image (no package mirrors at build time).
FROM maven@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320 AS libraries
COPY pom.xml /pack/pom.xml
RUN mvn -q -B -f /pack/pom.xml dependency:copy-dependencies -DoutputDirectory=/opt/lib -DincludeScope=test

FROM eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026 AS jdk

# postgres:17.11 (Debian); initdb, pg_ctl and psql are already on its PATH (/usr/lib/postgresql/17/bin)
FROM postgres@sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f
COPY --from=jdk /opt/java/openjdk /opt/java/openjdk
COPY --from=libraries /opt/lib /opt/lib
ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/postgresql/17/bin \
    CLASSPATH_LIBS=/opt/lib/* \
    JAVA_TOOL_OPTIONS="-Xss1m -XX:+UseSerialGC"
# The sandbox runs its own script, which initializes and starts the database itself (initdb in /work).
ENTRYPOINT []
CMD ["sh"]
LABEL org.opencontainers.image.title="nexti-sandbox-java-quarkus" org.opencontainers.image.description="Sandbox for the Java pack with Quarkus"
