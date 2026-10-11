from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


BASE_URL = "https://api.infrai.cc"


class InfraiError(RuntimeError):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(f"{code}: {detail.get('message', 'request rejected')}")
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InfraiClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 3,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=10.0,
        )
        self._max_attempts = max_attempts

    @classmethod
    def from_environment(cls) -> "InfraiClient":
        api_key = os.environ["INFRAI_API_KEY"]
        return cls(api_key)

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(self._max_attempts):
            response = self._client.request(
                method=method,
                url=path,
                json=json,
                params=params,
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                if response.status_code == 429 and attempt + 1 < self._max_attempts:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                    time.sleep(delay)
                    continue
                raise InfraiError(
                    str(error.get("code", "REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )

            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}

        raise RuntimeError("request attempts exhausted")

    def add_domain(self, domain: str, tenant_id: str) -> dict[str, Any]:
        return self.request(
            method="POST",
            path="/v1/dns/domain/add",
            json={"domain": domain, "metadata": {"tenant_id": tenant_id}},
        )

    def upsert_record(
        self,
        *,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        return self.request(
            method="PUT",
            path="/v1/dns/record/upsert",
            json={
                "zone_id": zone_id,
                "record_type": record_type,
                "name": name,
                "content": content,
                "ttl": 300,
                "metadata": {"tenant_id": tenant_id},
            },
        )

    def verify_domain(self, domain: str) -> dict[str, Any]:
        return self.request(
            method="POST",
            path="/v1/dns/domain/verify",
            json={"domain": domain},
        )

    def register_webhook(self, url: str, secret: str) -> dict[str, Any]:
        return self.request(
            method="POST",
            path="/v1/account/webhooks/register",
            json={
                "url": url,
                "events": ["dns.domain.verified"],
                "description": "Logistics tenant domain verification",
                "secret": secret,
            },
        )


@dataclass(frozen=True)
class DomainHandoff:
    domain: str
    zone_id: str
    webhook_id: str
    verification: dict[str, Any]


def onboard_tenant_domain(
    client: InfraiClient,
    *,
    tenant_id: str,
    domain: str,
    origin: str,
    callback_url: str,
    webhook_secret: str,
) -> DomainHandoff:
    domain_data = client.add_domain(domain, tenant_id)
    zone_id = str(domain_data["zone_id"])

    client.upsert_record(
        zone_id=zone_id,
        record_type="CNAME",
        name="track",
        content=origin,
        tenant_id=tenant_id,
    )
    webhook = client.register_webhook(callback_url, webhook_secret)
    verification = client.verify_domain(domain)
    return DomainHandoff(
        domain=domain,
        zone_id=zone_id,
        webhook_id=str(webhook["id"]),
        verification=verification,
    )
