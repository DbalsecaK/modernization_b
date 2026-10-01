# Sandbox image of the Java Spring Boot pack with Oracle (spec 15.5, ADR-0021): Oracle Database Free 23ai with a
# pre-initialized database, and on top of it Temurin 21 and the pack's libraries (with the Oracle JDBC driver) in
# /opt/lib, downloaded at build time because the sandbox runs without network. The script of each run starts the
# database, compiles and tests the generated code, runs the equivalence harness and stops the database.
# The sandbox runs it as the image's unprivileged `oracle` user, on a network of its own with no route out and with
# the container's writable layer (Oracle writes its data files in place). Base images pinned by digest.
FROM maven@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320 AS libraries
COPY pom.xml /pack/pom.xml
RUN mvn -q -B -f /pack/pom.xml dependency:copy-dependencies -DoutputDirectory=/opt/lib -DincludeScope=test

FROM eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026 AS jdk

FROM gvenzl/oracle-free@sha256:f5ff19033860d662c821cb04eb10483fa94f14f78eae252d054291ea07028093
COPY --from=jdk /opt/java/openjdk /opt/java/openjdk
COPY --from=libraries /opt/lib /opt/lib
# Sandbox-only credentials of a throwaway database: the container never has network to the outside.
ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:$PATH \
    CLASSPATH_LIBS=/opt/lib/* \
    JAVA_TOOL_OPTIONS="-Xss1m -XX:+UseSerialGC" \
    ORACLE_PASSWORD=Nexti_Sandbox_1 \
    APP_USER=nexti \
    APP_USER_PASSWORD=Nexti_Sandbox_1
# The sandbox runs its own script, which starts the database itself (/opt/oracle/container-entrypoint.sh).
ENTRYPOINT []
CMD ["sh"]
LABEL org.opencontainers.image.title="nexti-sandbox-java-oracle" org.opencontainers.image.description="Sandbox for the Java Spring Boot pack with Oracle"
