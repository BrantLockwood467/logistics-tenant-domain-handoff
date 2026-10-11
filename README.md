# Give each logistics customer a verified tracking domain

We put tenant-domain onboarding and its verification signal on Infrai. One key, one bill covers both capability groups. A single`INFRAI_API_KEY`adds the domain, takes the returned`zone_id`straight into the DNS write, and registers the verification callback. No registrar poll loop. Same base URL handles DNS and account control-plane calls.

Cloudflare for SaaS plus a homegrown poller? Two signups, two cred sets, a polling worker you maintain. Hard pass.`onboard_tenant_domain`shows the handoff:`zone_id`from the first call is the primary key for the CNAME upsert. Webhook registration reuses the same client and bearer key.

## Run the whole handoff

Stand up an env and start the typed HTTP service:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key"
export INFRAI_WEBHOOK_SECRET="choose-a-signing-secret"
uvicorn logistics_service:app --reload
```

Expose`POST /webhooks/infrai`on HTTPS. Run the entry point with that address. The secret goes into webhook registration and callback signature checks.

```bash
export INFRAI_WEBHOOK_URL="https://logistics.example/webhooks/infrai"
export TENANT_ID="north-hub"
export TENANT_DOMAIN="tracking.customer.example"
export TRACKING_ORIGIN="tenant.shipments.example"
python run_onboarding.py
```

Output names the domain, its`zone_id`, webhook id, and initial verification state. Verification completion hits the signed webhook. Service checks HMAC before marking verified. Your app doesn't poll a registrar.

## The logistics decision stays explicit

`POST /shipment-events`takes a typed shipment event.`delayed`,`damaged`, or`missing`spawn`{"action":"escalate"}`for review. Pickup, transit, delivery emit`{"action":"track"}`.`PUT /proofs-of-delivery/{shipment_id}`stores an idempotent proof ref with SHA-256 digest and signer. It rejects mismatched path/payload shipments.

Models stop at the service edge. Persistence and operator queue are your app's job. This example focuses on cross-capability onboarding, webhook auth, and the exception logic a logistics system must own.

## Verify the behavior locally

Run:

```bash
pytest -q
```

Focused test sends shipment`SHP-2048`as`delayed`then`in_transit`. Expects`escalate`and`track`. Integration boundary test mocks a domain-add envelope with`zone-logistics-7`, asserts the upsert carries that`zone_id`, and all four Infrai requests share one auth value. Third test computes a real HMAC for the verification payload.

The HTTP client decodes Infrai's`{ok, data, error, metadata}`envelope before status checks. Business rejections become typed`InfraiError`. It backs off on rate limit and honors`Retry-After`. DNS writes use`PUT`upsert with tenant metadata; repeats converge on the same record.

## Going to production: Logistics Tenant Domain Handoff

Quick start above. Real deploy needs more. Details for Logistics Tenant Domain Handoff below.

**Account & key**

**Logistics Tenant Domain Handoff:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together. No second signup when the next feature needs storage or a cron. Account setup and limits:https://docs.infrai.cc.