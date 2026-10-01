"""The Keycloak identity provider of a tenant's provider, built by code (ADR-0022): OIDC and SAML, linked to the
Organization by domain, the groups imported into `idp_groups`, the secret kept by Keycloak when not changed, and the
roles the groups give."""

from nexti_api.identity import providers


def test_the_alias_is_the_slug_and_the_name() -> None:
    assert providers.alias_for("andes-bank", "Microsoft Entra ID (OIDC)") == "andes-bank-microsoft-entra-id-oidc"
    assert providers.alias_for("t", "¡!") == "t-sso"
    assert len(providers.alias_for("a" * 40, "b" * 40)) == 63


def test_only_known_non_secret_settings_are_kept() -> None:
    settings = {"issuer": " https://login.microsoftonline.com/x/v2.0 ", "client_id": "app", "client_secret": "nope",
                "evil": "x", "scopes": ""}  # fmt: skip
    assert providers.clean_settings("oidc", settings) == {"issuer": "https://login.microsoftonline.com/x/v2.0",
                                                          "client_id": "app"}  # fmt: skip
    assert providers.clean_settings("saml", {"metadata_url": "https://idp/metadata", "issuer": "x"}) == {
        "metadata_url": "https://idp/metadata"}  # fmt: skip


def test_an_oidc_provider_is_linked_by_domain_and_keeps_its_secret_when_unchanged() -> None:
    settings = {"issuer": "https://idp.example", "authorization_url": "https://idp.example/auth",
                "token_url": "https://idp.example/token", "jwks_url": "https://idp.example/jwks",
                "client_id": "app"}  # fmt: skip
    first = providers.representation("acme-sso", "Acme SSO", "oidc", settings, "s3cr3t-value", "corp.example")
    assert first["providerId"] == "oidc"
    assert first["hideOnLogin"] is True
    assert first["config"]["clientSecret"] == "s3cr3t-value"
    assert first["config"]["kc.org.domain"] == "corp.example"
    assert first["config"]["pkceEnabled"] == "true"
    assert first["config"]["validateSignature"] == "true"
    unchanged = providers.representation("acme-sso", "Acme SSO", "oidc", settings, None, None)
    assert unchanged["config"]["clientSecret"] == providers.KEEP_SECRET
    assert "kc.org.domain" not in unchanged["config"]


def test_a_saml_provider_takes_the_imported_metadata_and_signed_assertions() -> None:
    imported = {"singleSignOnServiceUrl": "https://okta/sso", "signingCertificate": "MIIC"}
    saml = providers.representation("okta", "Okta", "saml", {"entity_id": "urn:okta"}, None, "pacificcu.example",
                                    imported)  # fmt: skip
    assert saml["providerId"] == "saml"
    assert saml["config"]["singleSignOnServiceUrl"] == "https://okta/sso"
    assert saml["config"]["idpEntityId"] == "urn:okta"
    assert saml["config"]["wantAssertionsSigned"] == "true"
    assert "clientSecret" not in saml["config"]


def test_the_groups_go_to_idp_groups() -> None:
    (oidc,) = providers.mappers("oidc", {"groups_claim": "roles"})
    assert oidc["config"] == {"claim": "roles", "user.attribute": "idp_groups", "syncMode": "FORCE"}
    (saml,) = providers.mappers("saml", {})
    assert saml["config"]["attribute.name"] == "groups"
    assert saml["identityProviderMapper"] == "saml-user-attribute-idp-mapper"


def test_the_groups_give_roles_and_the_default_role_covers_the_rest() -> None:
    mapping = {"finance": "projectViewer", "it-admins": "tenantAdmin"}
    assert providers.roles_for(["it-admins", "auditors"], mapping, "projectViewer") == {"tenantAdmin"}
    assert providers.roles_for(["auditors"], mapping, "projectViewer") == {"projectViewer"}
    assert providers.roles_for([], mapping, None) == set()
