# Sandbox image of the Java Spring Boot pack (spec 15.5, ADR-0010): Temurin 21 and the pack's libraries in /opt/lib,
# downloaded at build time because the sandbox runs without network. Generated code is compiled with javac and its
# tests run with the JUnit console launcher; nothing is written outside the /work tmpfs. Base images pinned by digest.
FROM maven@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320 AS libraries
COPY pom.xml /pack/pom.xml
RUN mvn -q -B -f /pack/pom.xml dependency:copy-dependencies -DoutputDirectory=/opt/lib -DincludeScope=test

FROM eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026
COPY --from=libraries /opt/lib /opt/lib
ENV JAVA_TOOL_OPTIONS="-Xss1m -XX:+UseSerialGC" CLASSPATH_LIBS=/opt/lib/*
LABEL org.opencontainers.image.title="nexti-sandbox-java" org.opencontainers.image.description="Sandbox for the Java Spring Boot pack"
