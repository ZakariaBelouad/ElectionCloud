"""Keyless AWS-to-Google authentication for the private fallback endpoint."""
import os

CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def google_token_provider(fallback_url, audience, service_account):
    if not audience or not service_account:
        raise ValueError("Fallback requires a Google workload identity provider and invoker account.")

    from google.auth import aws, impersonated_credentials
    from google.auth.transport.requests import Request

    source = aws.Credentials(
        audience=audience,
        subject_token_type="urn:ietf:params:aws:token-type:aws4_request",
        token_url="https://sts.googleapis.com/v1/token",
        credential_source={
            "environment_id": "aws1",
            "regional_cred_verification_url":
                "https://sts.{region}.amazonaws.com?Action=GetCallerIdentity&Version=2011-06-15",
        },
        scopes=[CLOUD_SCOPE],
    )
    target = impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=service_account,
        target_scopes=[CLOUD_SCOPE],
    )
    identity = impersonated_credentials.IDTokenCredentials(
        target_credentials=target, target_audience=fallback_url, include_email=True,
    )
    request = Request()

    def token():
        if not all(os.environ.get(name) for name in (
            "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        )):
            raise RuntimeError("AWS Lambda execution role credentials are unavailable.")
        if not identity.valid:
            identity.refresh(request)
        return identity.token

    return token
