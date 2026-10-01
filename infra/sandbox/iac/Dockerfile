# Sandbox image of the deployment pack (spec 8.4, ADR-0021): OpenTofu with the AWS, Azure and random providers
# downloaded at build time, so `tofu init` and `tofu validate` run in the sandbox without network and without cloud
# credentials. The providers are unpacked inside the image and are the only mirror: `tofu init` links to them, so
# nothing executable is written to the sandbox's noexec /work. The official OpenTofu image refuses to be a base
# (ONBUILD), so its binary is copied onto Alpine. Images pinned by digest.
FROM alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc
COPY --from=ghcr.io/opentofu/opentofu@sha256:0c3fd5d7f8901a5d4273504f2becae9df77e6fe570d68669d739534f622de57f /usr/local/bin/tofu /usr/local/bin/tofu
COPY providers.tf /opt/mirror-src/providers.tf
RUN cd /opt/mirror-src \
 && mkdir -p /opt/tofu-cache \
 && TF_PLUGIN_CACHE_DIR=/opt/tofu-cache tofu init -backend=false -input=false > /dev/null \
 && rm -rf .terraform .terraform.lock.hcl \
 && chmod -R a+rX /opt/tofu-cache
# The unpacked providers are the only source of providers.
COPY tofu.rc /opt/tofu.rc
ENV TF_CLI_CONFIG_FILE=/opt/tofu.rc TF_IN_AUTOMATION=1 CHECKPOINT_DISABLE=1
ENTRYPOINT []
CMD ["sh"]
LABEL org.opencontainers.image.title="nexti-sandbox-iac" org.opencontainers.image.description="Sandbox that validates the generated IaC"
