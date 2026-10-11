import hashlib
import hmac

import httpx

from domain_onboarding import InfraiClient, onboard_tenant_domain
from logistics_service import (
    EventKind,
    ExceptionAction,
    ShipmentEvent,
    decide_exception,
    verify_webhook_signature,
)


def test_delayed_shipment_is_escalated_but_transit_is_tracked() -> None:
    delayed = ShipmentEvent(
        shipment_id="SHP-2048",
        kind=EventKind.DELAYED,
        occurred_at="2026-09-17T09:30:00Z",
        location="Shanghai hub",
    )
    transit = delayed.model_copy(update={"kind": EventKind.IN_TRANSIT})

    assert decide_exception(delayed).action is ExceptionAction.ESCALATE
    assert decide_exception(transit).action is ExceptionAction.TRACK


def test_onboarding_hands_zone_id_to_dns_record_and_registers_webhook() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/dns/domain/add":
            data = {"zone_id": "zone-logistics-7"}
        elif request.url.path == "/v1/dns/record/upsert":
            data = {"record_id": "record-3"}
        elif request.url.path == "/v1/account/webhooks/register":
            data = {"id": "webhook-9"}
        else:
            data = {"status": "pending"}
        return httpx.Response(200, json={"ok": True, "data": data, "error": None, "metadata": {}})

    client = InfraiClient("test-key", transport=httpx.MockTransport(handler))
    result = onboard_tenant_domain(
        client,
        tenant_id="tenant-42",
        domain="tracking.customer.test",
        origin="tenant.shipments.example",
        callback_url="https://logistics.example/webhooks/infrai",
        webhook_secret="unit-test-secret",
    )
    client.close()

    record_body = requests[1].read().decode()
    assert result.zone_id == "zone-logistics-7"
    assert '"zone_id":"zone-logistics-7"' in record_body
    assert [request.headers["authorization"] for request in requests] == [
        "Bearer test-key",
        "Bearer test-key",
        "Bearer test-key",
        "Bearer test-key",
    ]


def test_webhook_signature_is_real_hmac() -> None:
    body = b'{"event":"dns.domain.verified","domain":"tracking.customer.test","zone_id":"zone-7"}'
    signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, signature, "secret")
