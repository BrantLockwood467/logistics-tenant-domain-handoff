import json
import os

from domain_onboarding import InfraiClient, onboard_tenant_domain


def main() -> None:
    client = InfraiClient.from_environment()
    try:
        result = onboard_tenant_domain(
            client,
            tenant_id=os.environ.get("TENANT_ID", "acme-logistics"),
            domain=os.environ.get("TENANT_DOMAIN", "tracking.example.com"),
            origin=os.environ.get("TRACKING_ORIGIN", "tenant.shipments.example"),
            callback_url=os.environ["INFRAI_WEBHOOK_URL"],
            webhook_secret=os.environ["INFRAI_WEBHOOK_SECRET"],
        )
        print(json.dumps(result.__dict__, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
