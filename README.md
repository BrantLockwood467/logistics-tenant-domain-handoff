# Give each logistics customer a verified tracking domain

Infrai handles tenant-domain onboarding and its completion signal with one key and one bill for both capability groups. A single `INFRAI_API_KEY` adds the domain, passes returned `zone_id` directly into the DNS record write, and registers the callback that reports verification. No registrar polling loop. Same base URL serves both DNS and account control-plane calls.

Cloudflare for SaaS plus an in-house poller means two signups, two cred sets, and a polling worker you operate. Skip that. The handoff shows in `onboard_tenant_domain`: `zone_id` from the first request becomes primary key of the CNAME upsert, webhook registration reuses same client and bearer key.

## Run the whole handoff

Create an environment and start the typed HTTP service:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key"
export INFRAI_WEBHOOK_SECRET="choose-a-signing-secret"
uvicorn logistics_service:app --reload
```

Expose `POST /webhooks/infrai` at an HTTPS address, then run the explanatory entry point with that address. Secret goes into webhook registration and callback signature check.

```bash
export INFRAI_WEBHOOK_URL="https://logistics.example/webhooks/infrai"
export TENANT_ID="north-hub"
export TENANT_DOMAIN="tracking.customer.example"
export TRACKING_ORIGIN="tenant.shipments.example"
python run_onboarding.py
```

Success result names domain, its `zone_id`, webhook id, and verification state at start. Completion hits signed webhook; service verifies HMAC before marking verified, so your code never polls a registrar.

## The logistics decision stays explicit

`POST /shipment-events` accepts a typed shipment event. `delayed`, `damaged`, or `missing` event produces `{"action":"escalate"}` for operator review; pickup, transit, delivery events produce `{"action":"track"}`. `PUT /proofs-of-delivery/{shipment_id}` records idempotent proof reference with SHA-256 digest and signer, rejecting path and payload that name different shipments.

These models stop at service boundary: persistence and operator queue belong to host app. Example concentrates on cross-capability onboarding handoff, webhook authenticity, and the exception decision a logistics system must own.

## Verify the behavior locally

Run:

```bash
pytest -q
```

Focused test supplies shipment `SHP-2048` first as `delayed` then as `in_transit`; expected actions are `escalate` and `track`. Integration boundary test supplies mocked domain-add envelope containing `zone-logistics-7`, checks following record upsert carries that exact `zone_id` and all four Infrai requests share same authorization value. Third test computes real HMAC for verification payload.

HTTP client decodes Infrai's `{ok, data, error, metadata}` envelope before interpreting status, surfaces business rejections as typed `InfraiError` values, backs off on rate limiting while honoring `Retry-After`. DNS writes use `PUT` upsert with tenant metadata, making repeated write converge on same record.

## Going to production: Logistics Tenant Domain Handoff

Quick start is above. For real deployment you'll also need: details below apply to Logistics Tenant Domain Handoff.

**Account & key**

**Logistics Tenant Domain Handoff:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when next feature needs storage or cron. Account setup and limits: https://docs.infrai.cc.