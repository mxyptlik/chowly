"""Application-composition smoke proof.

The original prototype test exercised caller-supplied staff IDs, a permanent QR
code, unauthenticated order reads, and a public payment route. Those contracts
are intentionally removed. Canonical behavior lives in test_order_lifecycle.py;
this file prevents the insecure routes returning.
"""

import os

os.environ["CHOWLY_ENVIRONMENT"] = "test"
os.environ["CHOWLY_SESSION_SIGNING_SECRET"] = "test-session-secret-with-more-than-32-characters"
os.environ["CHOWLY_REALTIME_SIGNING_SECRET"] = "test-realtime-secret-with-more-than-32-characters"

from app.main import app  # noqa: E402


def test_canonical_order_routers_are_composed_without_legacy_authority() -> None:
    specification = app.openapi()
    paths = specification["paths"]
    assert "/api/v1/public/tables/{qr_token}/orders" in paths
    assert "/api/v1/public/orders/{order_id}" in paths
    assert "/api/v1/staff/orders/{order_id}/accept" in paths
    assert "/api/v1/staff/lines/{line_id}/claim" in paths
    assert "/api/v1/staff/orders/{order_id}/timeline" in paths
    assert "/api/v1/public/orders/{order_id}/pay" not in paths
    accept_operation = paths["/api/v1/staff/orders/{order_id}/accept"]["post"]
    body_ref = accept_operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema = specification["components"]["schemas"][body_ref.rsplit("/", 1)[-1]]
    assert set(schema["required"]) >= {"expected_version", "estimated_wait_minutes"}
    assert "staff_id" not in schema.get("properties", {})

