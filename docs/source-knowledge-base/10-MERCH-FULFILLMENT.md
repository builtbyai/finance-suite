# 10 — Merch Service (Fulfillment)

Three fulfillment modes behind one **provider-agnostic routing layer**, so swapping a fulfiller never touches the storefront. Build the routing abstraction first; plug providers in behind it.

## The three modes

### Mode 1 — Print-on-demand API (start here)
No inventory, no upfront risk; products print on order. Both major providers expose REST APIs.

| Provider | Model | Pick when |
|---|---|---|
| **Printful** | Vertically integrated, consistent quality, branding depth | Your branded storefront (rep merch, premium) |
| **Printify** | Network of 80+ providers; base cost on the same SKU varies ~10–20%; larger catalog; lets you choose supplier | Margin-sensitive runs, broad catalog |

Common split: Printful for the branded Acme store, Printify for margin-sensitive SKUs. Build platform-agnostic, vector-ready design files so a provider swap doesn't force re-artwork.

### Mode 2 — Local DFW print partner
Same-day shirts, **rep cards**, truck/yard decals, hats, event material. This is an **operational vendor relationship**, not primarily an API play. Carries MOQ + inventory. Best for physical, fast-turn, and in-house brand / field needs.

### Mode 3 — China manufacturer (later)
Bulk hats, embroidered jackets, bags, roofing storm kits, higher-margin physical inventory. Use **only after a SKU proves demand** — you pre-buy inventory and absorb lead time + customs. Source via Alibaba/1688 + a sourcing agent.

## Routing abstraction

```python
class FulfillmentProvider(Protocol):
    def create_product(self, design, blank_sku) -> provider_product_id: ...
    def quote(self, sku, qty, ship_to) -> {base_cost_cents, ship_cents, eta}: ...
    def submit_order(self, order) -> provider_order_id: ...
    def order_status(self, provider_order_id) -> status: ...

def route(product) -> FulfillmentProvider:
    return {
      'pod_printful': PrintfulProvider(),
      'pod_printify': PrintifyProvider(),
      'local':        LocalVendorProvider(),   # manual / email queue
      'china':        InventoryProvider(),      # ships from owned stock
    }[product.fulfillment]
```

Store `fulfillment` + `provider_product_id` on `merch_products` (see `02-DATA-MODEL.md`).

## Order → ledger

On a merch sale:
```
Dr cash           retail            (less processor fee line)
Cr merch_revenue  retail
Dr cogs           base_cost+ship    (attribute merch_orders.id)
Cr cash           base_cost+ship    (paid to fulfiller)
```
Margin = `retail - cogs - fees`, surfaced per product and per order.

## Storefront integration

- Products published to the Acme Finance store (dark `#0f0f0f`, gold `#C9A84C`/`#E8D5A3`, Fraunces/Inter).
- Customer checkout uses the same PayPal rail as invoices (`03-BILLING-PAYPAL.md`) — one inbound money path.
- POD order auto-submitted to the routed provider on payment confirmation; status synced via provider polling/webhooks.

## Acceptance Criteria

- [ ] Storefront/checkout code calls only the routing abstraction, never a provider SDK directly.
- [ ] Switching a product's `fulfillment` mode requires no storefront code change.
- [ ] Every merch sale posts revenue **and** COGS ledger lines with margin computed.
- [ ] Local-vendor orders enter a manual fulfillment queue with the same status surface as POD.

Read next: [`11-COMPLIANCE-SECURITY.md`](./11-COMPLIANCE-SECURITY.md)
