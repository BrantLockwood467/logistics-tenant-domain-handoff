from __future__ import annotations

import hashlib
import hmac
import json
import os
from enum import Enum
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from domain_onboarding import InfraiClient, InfraiError, onboard_tenant_domain


class EventKind(str, Enum):
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    DELAYED = "delayed"
    DAMAGED = "damaged"
    MISSING = "missing"


class ShipmentEvent(BaseModel):
    shipment_id: str = Field(min_length=1)
    kind: EventKind
    occurred_at: str
    location: str | None = None
    note: str | None = None


class ProofOfDelivery(BaseModel):
    shipment_id: str = Field(min_length=1)
    object_key: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    signed_by: str = Field(min_length=1)


class ExceptionAction(str, Enum):
    TRACK = "track"
    ESCALATE = "escalate"


class EventDecision(BaseModel):
    shipment_id: str
    action: ExceptionAction
    reason: str


class TenantDomainRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    domain: str = Field(min_length=3)
    origin: str = Field(min_length=3)
    callback_url: str = Field(min_length=8)


class TenantDomainResult(BaseModel):
    domain: str
    zone_id: str
    webhook_id: str
    verification: dict[str, object]


class VerificationEvent(BaseModel):
    event: Literal["dns.domain.verified"]
    domain: str
    zone_id: str


def decide_exception(event: ShipmentEvent) -> EventDecision:
    exceptions = {EventKind.DELAYED, EventKind.DAMAGED, EventKind.MISSING}
    if event.kind in exceptions:
        return EventDecision(
            shipment_id=event.shipment_id,
            action=ExceptionAction.ESCALATE,
            reason=f"{event.kind.value} requires an operator review",
        )
    return EventDecision(
        shipment_id=event.shipment_id,
        action=ExceptionAction.TRACK,
        reason=f"{event.kind.value} remains in the normal shipment timeline",
    )


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


app = FastAPI(title="Tenant shipment domain service")
shipment_events: list[ShipmentEvent] = []
proofs_of_delivery: dict[str, ProofOfDelivery] = {}
verified_domains: set[str] = set()


@app.post("/tenant-domains", response_model=TenantDomainResult)
def create_tenant_domain(payload: TenantDomainRequest) -> TenantDomainResult:
    secret = os.environ["INFRAI_WEBHOOK_SECRET"]
    client = InfraiClient.from_environment()
    try:
        result = onboard_tenant_domain(
            client,
            tenant_id=payload.tenant_id,
            domain=payload.domain,
            origin=payload.origin,
            callback_url=payload.callback_url,
            webhook_secret=secret,
        )
    except InfraiError as exc:
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(status_code=status, detail=exc.detail) from exc
    finally:
        client.close()
    return TenantDomainResult(
        domain=result.domain,
        zone_id=result.zone_id,
        webhook_id=result.webhook_id,
        verification=result.verification,
    )


@app.post("/shipment-events", response_model=EventDecision)
def record_shipment_event(event: ShipmentEvent) -> EventDecision:
    shipment_events.append(event)
    return decide_exception(event)


@app.put("/proofs-of-delivery/{shipment_id}", response_model=ProofOfDelivery)
def put_proof_of_delivery(shipment_id: str, proof: ProofOfDelivery) -> ProofOfDelivery:
    if shipment_id != proof.shipment_id:
        raise HTTPException(status_code=400, detail="shipment id does not match payload")
    proofs_of_delivery[shipment_id] = proof
    return proof


@app.post("/webhooks/infrai", status_code=204, response_model=None)
async def receive_verification(
    request: Request,
    x_infrai_signature: Annotated[str, Header()],
) -> None:
    body = await request.body()
    secret = os.environ["INFRAI_WEBHOOK_SECRET"]
    if not verify_webhook_signature(body, x_infrai_signature, secret):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    event = VerificationEvent.model_validate(json.loads(body))
    verified_domains.add(event.domain)
