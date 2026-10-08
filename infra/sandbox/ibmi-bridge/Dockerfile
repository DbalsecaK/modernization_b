# The IBM i bridge (ADR-0053): JTOpen and the bridge, compiled at build time. The worker starts one container per
# golden master run with the request on stdin (credentials included, never in arguments or the environment); it is the
# only sandbox with network, because it must reach the customer's IBM i. Base images pinned by digest.
FROM maven@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320 AS build
COPY pom.xml /bridge/pom.xml
COPY src /bridge/src
RUN mvn -q -B -f /bridge/pom.xml package dependency:copy-dependencies -DoutputDirectory=/bridge/target/lib

FROM eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026
COPY --from=build /bridge/target/nexti-ibmi-bridge.jar /opt/bridge/bridge.jar
COPY --from=build /bridge/target/lib /opt/bridge/lib
USER 10001
ENTRYPOINT ["java", "-Xss1m", "-XX:+UseSerialGC", "-cp", "/opt/bridge/bridge.jar:/opt/bridge/lib/*", "dev.nexti.ibmi.Bridge"]
LABEL org.opencontainers.image.title="nexti-ibmi-bridge" org.opencontainers.image.description="Runs golden master cases of RPG programs on a customer's IBM i"
