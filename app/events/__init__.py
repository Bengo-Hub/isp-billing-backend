"""NATS / JetStream event integration (Phase 5, ADDITIVE).

This package adds inter-service eventing on top of the existing isp-billing
flows WITHOUT changing any of them:

- ``app.events.outbox``   — transactional-outbox write + publish helpers.
- ``app.events.nats``     — lazy NATS/JetStream connection helpers (nats-py).
- ``app.events.consumer`` — standalone durable consumer (``python -m
  app.events.consumer``) that subscribes to treasury.payment.succeeded,
  auth.user.* and subscription.*.

IMPORTANT (import safety): nothing here imports ``nats`` at module import time.
``nats-py`` may not be installed in every image (e.g. the API web pod), so the
NATS connection is imported lazily inside functions. This keeps ``app.main`` and
the Celery worker importable even when ``nats-py`` is absent — the event
subsystem just stays inert (see ``settings.nats_url``).

Subject convention (matches shared-events / shared-docs/event-architecture.md):
    subject = "{aggregate_type}.{event_type}"
isp-billing publishes under aggregate_type "isp":
    isp.payment.received     — successful customer payment provisioned
    isp.subscriber.created   — hotspot user provisioned on a router
    isp.invoice.created      — (optional) an ISP invoice was created
"""

# Aggregate type for everything isp-billing publishes.
AGGREGATE_TYPE = "isp"

# Published event types (the part after the aggregate in the subject).
EVT_PAYMENT_RECEIVED = "payment.received"
EVT_SUBSCRIBER_CREATED = "subscriber.created"
EVT_INVOICE_CREATED = "invoice.created"
# Lifecycle events consumed by notifications-api (ispbilling/* templates).
EVT_SUBSCRIPTION_RENEWED = "subscription.renewed"
EVT_SUBSCRIPTION_EXPIRING = "subscription.expiring"

# Consumed subjects (durable consumer interest).
SUB_TREASURY_PAYMENT_SUCCEEDED = "treasury.payment.succeeded"
# auth-api is the SoT for ISP-provider tenants + users (they sign up via SSO).
# It publishes auth.tenant.created and auth.user.created/updated (subject =
# {aggregate_type}.{event_type}); isp-billing mirrors them locally.
SUB_AUTH_TENANT = "auth.tenant.*"
SUB_AUTH_USER = "auth.user.*"
SUB_SUBSCRIPTION = "subscription.*"

__all__ = [
    "AGGREGATE_TYPE",
    "EVT_PAYMENT_RECEIVED",
    "EVT_SUBSCRIBER_CREATED",
    "EVT_INVOICE_CREATED",
    "EVT_SUBSCRIPTION_RENEWED",
    "EVT_SUBSCRIPTION_EXPIRING",
    "SUB_TREASURY_PAYMENT_SUCCEEDED",
    "SUB_AUTH_TENANT",
    "SUB_AUTH_USER",
    "SUB_SUBSCRIPTION",
]
