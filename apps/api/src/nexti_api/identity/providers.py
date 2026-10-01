"""The Keycloak identity provider of a tenant's provider (ADR-0022), built by code from what the platform stores.

OIDC providers (Entra ID, Okta, Google, any OpenID Provider) and SAML 2.0 ones. Every provider imports the groups of
the user into the attribute `idp_groups`, which the client `nexti-bff` puts in the ID token; the platform turns them
into tenant roles at sign-in. The client secret is sent to Keycloak and never stored by the platform: when an update
does not change it, Keycloak keeps the one it has (its masked value means "unchanged").
"""

import re
from typing import Any

KEEP_SECRET = "**********"  # noqa: S105 - a mask, not a secret: what Keycloak returns for a secret, and accepts as "keep the current one"
OIDC_SETTINGS = ("issuer", "authorization_url", "token_url", "jwks_url", "userinfo_url", "logout_url", "client_id",
                 "scopes", "groups_claim")  # fmt: skip
SAML_SETTINGS = ("metadata_url", "entity_id", "sso_url", "signing_certificate", "groups_attribute")
PRESETS = {
    # Microsoft Entra ID: the issuer of the customer's directory, e.g. https://login.microsoftonline.com/<tid>/v2.0.
    "entra": {"scopes": "openid email profile", "groups_claim": "groups"},
    "okta": {"scopes": "openid email profile groups", "groups_claim": "groups"},
    "google": {"issuer": "https://accounts.google.com", "scopes": "openid email profile"},
}


def alias_for(tenant_slug: str, display_name: str) -> str:
    """The Keycloak alias: the tenant's slug and the provider's name, lowercase with hyphens, at most 63 chars."""
    name = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-") or "sso"
    return f"{tenant_slug}-{name}"[:63].rstrip("-")


def clean_settings(protocol: str, settings: dict[str, Any]) -> dict[str, str]:
    """Only the known, non-secret settings of the protocol, as strings."""
    keys = OIDC_SETTINGS if protocol == "oidc" else SAML_SETTINGS
    return {k: str(settings[k]).strip() for k in keys if settings.get(k) not in (None, "")}


def representation(alias: str, display_name: str, protocol: str, settings: dict[str, str], client_secret: str | None,
                   domain: str | None, imported: dict[str, str] | None = None) -> dict[str, Any]:  # fmt: skip
    """The Keycloak IdP of the provider. `domain` links it to the Organization (redirect when the e-mail matches)."""
    config: dict[str, str] = {"syncMode": "FORCE", "guiOrder": "0"}
    if protocol == "oidc":
        config.update({
            "clientId": settings.get("client_id", ""),
            "clientSecret": client_secret or KEEP_SECRET,
            "clientAuthMethod": "client_secret_post",
            "issuer": settings.get("issuer", ""),
            "authorizationUrl": settings.get("authorization_url", ""),
            "tokenUrl": settings.get("token_url", ""),
            "jwksUrl": settings.get("jwks_url", ""),
            "useJwksUrl": "true",
            "validateSignature": "true",
            "pkceEnabled": "true",
            "pkceMethod": "S256",
            "defaultScope": settings.get("scopes", "openid email profile"),
        })  # fmt: skip
        if settings.get("userinfo_url"):
            config["userInfoUrl"] = settings["userinfo_url"]
        if settings.get("logout_url"):
            config["logoutUrl"] = settings["logout_url"]
    else:
        config.update(imported or {})
        if settings.get("sso_url"):
            config["singleSignOnServiceUrl"] = settings["sso_url"]
        if settings.get("entity_id"):
            config["idpEntityId"] = settings["entity_id"]
        if settings.get("signing_certificate"):
            config.update({"signingCertificate": settings["signing_certificate"], "validateSignature": "true"})
        config.update({"nameIDPolicyFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
                       "principalType": "SUBJECT", "postBindingResponse": "true", "postBindingAuthnRequest": "true",
                       "wantAssertionsSigned": "true"})  # fmt: skip
    if domain:
        config.update({"kc.org.domain": domain, "kc.org.broker.redirect.mode.email-matches": "true"})
    return {
        "alias": alias,
        "displayName": display_name,
        "providerId": protocol,
        "enabled": True,
        "trustEmail": True,
        "hideOnLogin": True,
        "firstBrokerLoginFlowAlias": "first broker login",
        "config": config,
    }


def mappers(protocol: str, settings: dict[str, str]) -> list[dict[str, Any]]:
    """The groups of the user into `idp_groups`, refreshed at every sign-in."""
    if protocol == "oidc":
        return [{"name": "groups", "identityProviderMapper": "oidc-user-attribute-idp-mapper",
                 "config": {"claim": settings.get("groups_claim", "groups"), "user.attribute": "idp_groups",
                            "syncMode": "FORCE"}}]  # fmt: skip
    return [{"name": "groups", "identityProviderMapper": "saml-user-attribute-idp-mapper",
             "config": {"attribute.name": settings.get("groups_attribute", "groups"), "user.attribute": "idp_groups",
                        "syncMode": "FORCE"}}]  # fmt: skip


def roles_for(groups: list[str], group_roles: dict[str, str], default_role: str | None) -> set[str]:
    """The tenant roles the groups of the user give; the default role when no group is mapped."""
    found = {group_roles[g] for g in groups if g in group_roles}
    if not found and default_role:
        found.add(default_role)
    return found
