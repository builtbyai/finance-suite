"""Merch Service — provider-agnostic fulfillment routing."""
from typing import Protocol, Optional
from dataclasses import dataclass
import requests
from sqlalchemy.orm import Session
from sqlalchemy import select

import config
from db import new_uuid, utcnow
from models import MerchProduct, MerchOrder
from services import ledger


@dataclass
class Quote:
    base_cost_cents: int
    ship_cents: int
    eta_days: int


class FulfillmentProvider(Protocol):
    name: str

    def quote(self, sku: str, qty: int, ship_to: dict) -> Quote: ...
    def submit_order(self, order: MerchOrder, product: MerchProduct, ship_to: dict) -> str: ...
    def order_status(self, provider_order_id: str) -> str: ...


class PrintifyProvider:
    name = "pod_printify"

    def __init__(self):
        self.key = config.PRINTIFY_KEY
        self.dry_run = not self.key

    def quote(self, sku, qty, ship_to):
        return Quote(base_cost_cents=1200 * qty, ship_cents=499, eta_days=5)

    def submit_order(self, order, product, ship_to):
        if self.dry_run:
            return f"printify-DRY-{new_uuid()[:10]}"
        r = requests.post(
            "https://api.printify.com/v1/shops/orders.json",
            headers={"Authorization": f"Bearer {self.key}"},
            json={"line_items": [{"product_id": product.provider_product_id,
                                  "quantity": order.qty}],
                  "address_to": ship_to},
            timeout=20,
        )
        r.raise_for_status()
        return str(r.json().get("id", new_uuid()))

    def order_status(self, provider_order_id):
        if self.dry_run:
            return "in_production"
        r = requests.get(f"https://api.printify.com/v1/shops/orders/{provider_order_id}.json",
                         headers={"Authorization": f"Bearer {self.key}"}, timeout=15)
        r.raise_for_status()
        return r.json().get("status", "unknown")


class PrintfulProvider:
    name = "pod_printful"

    def __init__(self):
        self.key = config.PRINTFUL_KEY
        self.dry_run = not self.key

    def quote(self, sku, qty, ship_to):
        return Quote(base_cost_cents=1450 * qty, ship_cents=599, eta_days=6)

    def submit_order(self, order, product, ship_to):
        if self.dry_run:
            return f"printful-DRY-{new_uuid()[:10]}"
        r = requests.post("https://api.printful.com/orders",
                          headers={"Authorization": f"Bearer {self.key}"},
                          json={"recipient": ship_to,
                                "items": [{"sync_variant_id": product.provider_product_id,
                                           "quantity": order.qty}]},
                          timeout=20)
        r.raise_for_status()
        return str(r.json().get("result", {}).get("id", new_uuid()))

    def order_status(self, provider_order_id):
        if self.dry_run:
            return "in_production"
        r = requests.get(f"https://api.printful.com/orders/{provider_order_id}",
                         headers={"Authorization": f"Bearer {self.key}"}, timeout=15)
        r.raise_for_status()
        return r.json().get("result", {}).get("status", "unknown")


class LocalProvider:
    name = "local"

    def quote(self, sku, qty, ship_to):
        return Quote(base_cost_cents=900 * qty, ship_cents=0, eta_days=1)

    def submit_order(self, order, product, ship_to):
        return f"local-queue-{new_uuid()[:10]}"

    def order_status(self, provider_order_id):
        return "queued"


class ChinaProvider:
    name = "china"

    def quote(self, sku, qty, ship_to):
        return Quote(base_cost_cents=400 * qty, ship_cents=799, eta_days=21)

    def submit_order(self, order, product, ship_to):
        return f"china-{new_uuid()[:10]}"

    def order_status(self, provider_order_id):
        return "shipped"


_PROVIDERS: dict[str, FulfillmentProvider] = {
    "pod_printify": PrintifyProvider(),
    "pod_printful": PrintfulProvider(),
    "local": LocalProvider(),
    "china": ChinaProvider(),
}


def route(product: MerchProduct) -> FulfillmentProvider:
    return _PROVIDERS[product.fulfillment]


def create_product(session: Session, *, sku: str, title: str, fulfillment: str,
                   base_cost_cents: int, retail_cents: int,
                   provider_product_id: Optional[str] = None) -> MerchProduct:
    if fulfillment not in _PROVIDERS:
        raise ValueError(f"unknown fulfillment: {fulfillment}")
    p = MerchProduct(
        id=new_uuid(), sku=sku, title=title, fulfillment=fulfillment,
        provider_product_id=provider_product_id,
        base_cost_cents=base_cost_cents,
        retail_cents=retail_cents,
        active=True,
    )
    session.add(p)
    session.flush()
    return p


def create_order(session: Session, *, product_id: str, qty: int,
                 ship_to: dict, customer_id: Optional[str] = None,
                 processor_fee_cents: int = 0) -> MerchOrder:
    product = session.get(MerchProduct, product_id)
    if product is None:
        raise ValueError("product not found")
    provider = route(product)
    quote = provider.quote(product.sku, qty, ship_to)

    o = MerchOrder(
        id=new_uuid(),
        customer_id=customer_id,
        product_id=product.id,
        qty=qty,
        provider=provider.name,
        total_cents=(product.retail_cents or 0) * qty,
        cogs_cents=quote.base_cost_cents + quote.ship_cents,
        status="created",
        created_at=utcnow().isoformat(),
    )
    session.add(o)
    session.flush()

    provider_order_id = provider.submit_order(o, product, ship_to)
    o.provider_order_id = provider_order_id
    o.status = "submitted"
    session.flush()

    ledger.post_merch_sale(
        session,
        order_id=o.id,
        retail_cents=o.total_cents,
        cogs_cents=o.cogs_cents,
        processor_fee_cents=processor_fee_cents,
        customer_id=customer_id,
    )
    return o
