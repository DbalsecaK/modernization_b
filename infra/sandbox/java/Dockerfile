# Sandbox image of the Java Spring Boot pack (spec 15.5, ADR-0010): Temurin 21 and the pack's libraries in /opt/lib,
# downloaded at build time because the sandbox runs without network. Generated code is compiled with javac and its
# tests run with the JUnit console launcher; nothing is written outside the /work tmpfs. Base images pinned by digest.
# PostgreSQL runs inside the same container for the equivalence check (plan M4 step 11): on loopback only, with its
# data in /work, started and stopped by the script of each run.
FROM maven@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320 AS libraries
COPY pom.xml /pack/pom.xml
RUN mvn -q -B -f /pack/pom.xml dependency:copy-dependencies -DoutputDirectory=/opt/lib -DincludeScope=test
# JaCoCo for the coverage of the target under the golden master (M29, ADR-0049): apart from /opt/lib so it never
# joins the classpath of the generated code.
RUN mvn -q -B dependency:copy -Dartifact=org.jacoco:org.jacoco.agent:0.8.13:jar:runtime -DoutputDirectory=/opt/coverage \
 && mvn -q -B dependency:copy -Dartifact=org.jacoco:org.jacoco.cli:0.8.13:jar:nodeps -DoutputDirectory=/opt/coverage \
 && mv /opt/coverage/org.jacoco.agent-0.8.13-runtime.jar /opt/coverage/jacocoagent.jar \
 && mv /opt/coverage/org.jacoco.cli-0.8.13-nodeps.jar /opt/coverage/jacococli.jar

FROM eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get -o Acquire::Retries=5 update \
 && apt-get -o Acquire::Retries=5 install -y --no-install-recommends postgresql \
 && rm -rf /var/lib/apt/lists/* \
 && ln -s "/usr/lib/postgresql/$(ls /usr/lib/postgresql | sort -n | tail -1)/bin" /opt/pgbin
COPY --from=libraries /opt/lib /opt/lib
COPY --from=libraries /opt/coverage /opt/coverage
ENV JAVA_TOOL_OPTIONS="-Xss1m -XX:+UseSerialGC" CLASSPATH_LIBS=/opt/lib/* PATH=/opt/pgbin:$PATH
LABEL org.opencontainers.image.title="nexti-sandbox-java" org.opencontainers.image.description="Sandbox for the Java Spring Boot pack"
