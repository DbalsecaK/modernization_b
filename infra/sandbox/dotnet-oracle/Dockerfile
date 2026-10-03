# Sandbox image of the .NET 10 pack with Oracle (spec 15.5, ADR-0031): Oracle Database Free 23ai with a pre-initialized
# database, and on top of it the .NET 10 SDK and the NuGet packages the generated projects use (with
# Oracle.ManagedDataAccess.Core), restored at build time in the SDK image because the sandbox runs without network.
# Nothing is installed from package mirrors: the SDK and the packages are copied from the SDK stage. The script of each
# run builds and tests the generated code, starts the database, runs the equivalence harness and stops the database.
# The sandbox runs it as the image's unprivileged `oracle` user, on a network of its own with no route out and with
# the container's writable layer (Oracle writes its data files in place), as for the Java image (ADR-0021).
# Base images pinned by digest.
FROM mcr.microsoft.com/dotnet/sdk:10.0@sha256:35d40304542c8689331f8cab17c65926cdf48fe711e289321d71924b230a7d29 AS sdk
ENV NUGET_PACKAGES=/opt/nuget DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
WORKDIR /opt/seed
COPY seed/ ./
RUN dotnet restore Seed.csproj && chmod -R a+rX /opt/nuget

FROM gvenzl/oracle-free@sha256:f5ff19033860d662c821cb04eb10483fa94f14f78eae252d054291ea07028093
COPY --from=sdk /usr/share/dotnet /usr/share/dotnet
COPY --from=sdk /opt/nuget /opt/nuget
# Oracle Linux 8 carries no ICU: .NET runs in invariant globalization (the harness formats with the invariant culture).
# Sandbox-only credentials of a throwaway database: the container never has network to the outside.
ENV PATH=/usr/share/dotnet:$PATH DOTNET_ROOT=/usr/share/dotnet NUGET_PACKAGES=/opt/nuget \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    DOTNET_GENERATE_ASPNET_CERTIFICATE=0 DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    ORACLE_PASSWORD=Nexti_Sandbox_1 \
    APP_USER=nexti \
    APP_USER_PASSWORD=Nexti_Sandbox_1
# The sandbox runs its own script, which starts the database itself (/opt/oracle/container-entrypoint.sh).
ENTRYPOINT []
CMD ["sh"]
LABEL org.opencontainers.image.title="nexti-sandbox-dotnet-oracle" org.opencontainers.image.description="Sandbox for the .NET 10 pack with Oracle"
