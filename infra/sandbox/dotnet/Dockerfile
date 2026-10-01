# Sandbox image of the .NET 10 pack (spec 15.5, ADR-0017): the .NET 10 SDK on SQL Server 2025 (Ubuntu 22.04). The
# sandbox runs without network, as nobody, with a read-only root: the NuGet packages the generated projects use are
# restored here, at build time, with the exact versions of nexti_pack_dotnet; SQL Server's system databases are
# prepared here once and copied to a tmpfs by each run, which starts SQL Server only for the equivalence harness.
# The SDK is copied from the official SDK image (no apt mirrors needed). Base images pinned by digest.
FROM mcr.microsoft.com/dotnet/sdk:10.0@sha256:35d40304542c8689331f8cab17c65926cdf48fe711e289321d71924b230a7d29 AS sdk

FROM mcr.microsoft.com/mssql/server:2025-RTM-ubuntu-22.04@sha256:54b23ca766287dab5f6f55162923325f07cdec6ccb42108f37c55c87e7688ebd
USER root
COPY --from=sdk /usr/share/dotnet /usr/share/dotnet
# The SA password only exists inside a sandbox without network; it protects nothing outside it.
ENV PATH="/usr/share/dotnet:/opt/mssql-tools18/bin:${PATH}" DOTNET_ROOT=/usr/share/dotnet \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=0 \
    NUGET_PACKAGES=/opt/nuget ACCEPT_EULA=Y MSSQL_PID=Developer MSSQL_SA_PASSWORD=Nexti-Sandbox-Only-1

# sqlservr carries a file capability (cap_net_bind_service); the sandbox forbids gaining privileges, so a copy
# without it is what runs. Then the system databases are created once and kept as a seed.
RUN cp /opt/mssql/bin/sqlservr /tmp/sqlservr && mv /tmp/sqlservr /opt/mssql/bin/sqlservr && chmod 755 /opt/mssql/bin/sqlservr \
 && (/opt/mssql/bin/sqlservr > /tmp/sql.log 2>&1 &) \
 && for i in $(seq 1 180); do grep -q "now ready for client connections" /tmp/sql.log && break; sleep 1; done \
 && sqlcmd -S 127.0.0.1,1433 -U sa -P "$MSSQL_SA_PASSWORD" -C -l 30 -Q "SHUTDOWN WITH NOWAIT" > /dev/null || true \
 && sleep 5 && cp -r /var/opt/mssql /opt/mssql-seed && chmod -R a+rwX /opt/mssql-seed && rm -f /tmp/sql.log

WORKDIR /opt/seed
COPY seed/ ./
RUN dotnet restore Seed.csproj && chmod -R a+rX /opt/nuget && rm -rf /opt/seed/obj /root/.nuget/v3-cache

LABEL org.opencontainers.image.title="nexti-sandbox-dotnet" org.opencontainers.image.description="Sandbox for the .NET 10 pack"
