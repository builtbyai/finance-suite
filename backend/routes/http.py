"""All HTTP routes. Single file for the local-MVP; split into blueprints later if it grows."""
import json
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import session_scope, new_uuid, utcnow
from models import (
    Customer, Invoice, User, Project,
    PmPayoutProfile, Payout, PayoutAuthorization,
    Receipt, MileageLog, MileageRate, TaxThreshold,
    MerchProduct, MerchOrder, LedgerAccount, LedgerEntry, LedgerLine,
)
from services import billing, ledger, bank_link, payout as payout_svc, tax, receipt as receipt_svc, mileage, merch


api = Blueprint("api", __name__, url_prefix="/api")


# ---------- Health ----------

@api.get("/health")
def health():
    with session_scope() as s:
        accts = s.execute(select(LedgerAccount)).scalars().all()
    return jsonify({
        "ok": True,
        "time": utcnow().isoformat(),
        "chart_of_accounts": len(accts),
    })


# ---------- Dashboard ----------

@api.get("/dashboard")
def dashboard():
    # Materialize every aggregate INSIDE the session_scope. The previous
    # version computed `payouts` status counts inside the jsonify() call,
    # which ran AFTER the with-block had already closed the session — every
    # ORM attribute access on the detached instances raised
    # DetachedInstanceError and the route 500'd.
    with session_scope() as s:
        now = utcnow()
        ytd_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        pnl_ytd = ledger.pnl(s, ytd_start, now)
        invoices = s.execute(select(Invoice)).scalars().all()
        inv_total = len(invoices)
        inv_paid = sum(1 for i in invoices if i.status == "paid")
        inv_sent = sum(1 for i in invoices if i.status == "sent")
        pms = s.execute(select(PmPayoutProfile)).scalars().all()
        pm_total = len(pms)
        pm_active = sum(1 for p in pms if p.status == "active")
        pm_verified = sum(1 for p in pms if p.status == "verified")
        pm_pending = sum(1 for p in pms if p.status == "pending")
        payouts = s.execute(select(Payout)).scalars().all()
        payout_total = len(payouts)
        payout_completed = sum(1 for p in payouts if p.status == "completed")
        payout_processing = sum(1 for p in payouts if p.status == "processing")
        payout_failed = sum(1 for p in payouts if p.status == "failed")
    return jsonify({
        "pnl_ytd": pnl_ytd,
        "invoices": {"total": inv_total, "paid": inv_paid, "sent": inv_sent},
        "pms": {"total": pm_total, "active": pm_active,
                "verified": pm_verified, "pending": pm_pending},
        "payouts": {"total": payout_total, "completed": payout_completed,
                    "processing": payout_processing, "failed": payout_failed},
    })


# ---------- Acme Finance bridge status ----------

@api.get("/bridge/status")
def bridge_status():
    """Surfaces how connected Flask is to the CRM Worker (CRM).

    Reports:
      - configured: both CRM_API_BASE_URL and FINANCE_RELAY_SECRET set
      - reachable:  /api/finance/health pings Flask's /api/internal/health
                    through the Worker; if the round-trip succeeds we report
                    reachable=true. This requires the Worker to be deployed
                    AND FINANCE_RELAY_URL on the Worker to point back at us
                    (the Worker also needs to be reachable from here).
      - linked_customers: how many customers carry external_id starting with
                          "lead:" — the count that originated from a CRM
                          lead via /api/internal/customers/upsert.
      - last_paid_at:     latest invoice.paid_at across this Flask DB so the
                          frontend can show "last paid: 3 min ago".
    """
    import config
    from sqlalchemy import func
    from models import Customer

    configured = bool(config.CRM_API_BASE_URL and config.FINANCE_RELAY_SECRET)

    reachable = None
    reach_error = None
    if configured:
        # Ping the Worker's public /api/health (no auth needed) to confirm
        # the URL resolves + the Worker is responding. This does NOT prove
        # the HMAC secret matches; the only round-trip auth proof would be
        # to hit a bridge-only endpoint, which doesn't exist yet (planned
        # follow-up: add /api/finance/webhook/bridge-ping HMAC-gated for a
        # real handshake).
        try:
            import requests
            url = config.CRM_API_BASE_URL.rstrip("/") + "/api/health"
            r = requests.get(url, timeout=4.0)
            reachable = r.status_code == 200
            if not reachable:
                reach_error = f"worker {r.status_code}"
        except Exception as e:  # noqa: BLE001
            reachable = False
            reach_error = str(e)[:200]

    # Defensive: the dev SQLite DB may pre-date migration 0002 which adds
    # customers.external_id. SQLAlchemy's create_all() doesn't ALTER, so
    # legacy dev DBs raise OperationalError. Treat that as "no linked
    # customers yet" rather than 500'ing the whole status endpoint.
    schema_warning = None
    linked = 0
    last_paid = None
    try:
        with session_scope() as s:
            linked = s.execute(
                select(func.count(Customer.id)).where(Customer.external_id.like("lead:%"))
            ).scalar_one()
    except Exception as e:  # noqa: BLE001
        schema_warning = f"customers.external_id missing — run migration 0002 or delete data/finance.db ({type(e).__name__})"
    try:
        with session_scope() as s:
            last_paid = s.execute(
                select(func.max(Invoice.paid_at)).where(Invoice.status == "paid")
            ).scalar_one()
    except Exception:  # noqa: BLE001
        last_paid = None

    return jsonify({
        "configured": configured,
        "reachable": reachable,
        "reach_error": reach_error,
        "linked_customers": int(linked or 0),
        "last_paid_at": last_paid,
        "worker_base_url": config.CRM_API_BASE_URL or None,
        "schema_warning": schema_warning,
    })


# ---------- Customers ----------

@api.get("/customers")
def list_customers():
    with session_scope() as s:
        rows = s.execute(select(Customer)).scalars().all()
        return jsonify([{"id": c.id, "name": c.name, "email": c.email,
                         "phone": c.phone, "project_id": c.project_id} for c in rows])


@api.post("/customers")
def create_customer():
    data = request.get_json(force=True) or {}
    if not data.get("name"):
        return jsonify({"error": "name required"}), 400
    with session_scope() as s:
        c = Customer(id=new_uuid(), name=data["name"],
                     email=data.get("email"), phone=data.get("phone"),
                     project_id=data.get("project_id"),
                     created_at=utcnow().isoformat())
        s.add(c)
        s.flush()
        return jsonify({"id": c.id, "name": c.name, "email": c.email}), 201


# ---------- Invoices ----------

@api.get("/invoices")
def list_invoices():
    with session_scope() as s:
        rows = s.execute(select(Invoice).order_by(Invoice.created_at.desc())).scalars().all()
        return jsonify([{
            "id": i.id,
            "number": i.number,
            "customer_id": i.customer_id,
            "amount_cents": i.amount_cents,
            "status": i.status,
            "issued_at": i.issued_at,
            "paid_at": i.paid_at,
            "payable_url": i.payable_url,
            "provider_invoice_id": i.provider_invoice_id,
        } for i in rows])


@api.post("/invoices")
def create_invoice():
    data = request.get_json(force=True) or {}
    try:
        with session_scope() as s:
            inv = billing.create_invoice(
                s,
                customer_id=data["customer_id"],
                amount_cents=int(data["amount_cents"]),
                memo=data.get("memo"),
                project_id=data.get("project_id"),
            )
            return jsonify({"id": inv.id, "number": inv.number,
                            "provider_invoice_id": inv.provider_invoice_id,
                            "status": inv.status}), 201
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400


@api.post("/invoices/<inv_id>/send")
def send_invoice(inv_id: str):
    try:
        with session_scope() as s:
            inv = billing.send_invoice(s, inv_id)
            return jsonify({"id": inv.id, "status": inv.status,
                            "payable_url": inv.payable_url})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@api.post("/invoices/<inv_id>/cancel")
def cancel_invoice(inv_id: str):
    try:
        with session_scope() as s:
            inv = billing.cancel_invoice(s, inv_id)
            return jsonify({"id": inv.id, "status": inv.status})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@api.post("/invoices/<inv_id>/refund")
def refund_invoice(inv_id: str):
    data = request.get_json(force=True) or {}
    try:
        with session_scope() as s:
            inv = billing.refund_invoice(s, inv_id, int(data.get("amount_cents", 0)))
            return jsonify({"id": inv.id, "status": inv.status})
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


# ---------- PM payout profiles ----------

@api.post("/users")
def create_user():
    data = request.get_json(force=True) or {}
    with session_scope() as s:
        u = User(id=new_uuid(), email=data.get("email"), name=data.get("name"),
                 role=data.get("role", "pm"), created_at=utcnow().isoformat())
        s.add(u)
        s.flush()
        return jsonify({"id": u.id, "name": u.name, "email": u.email, "role": u.role}), 201


@api.get("/users")
def list_users():
    with session_scope() as s:
        rows = s.execute(select(User)).scalars().all()
        return jsonify([{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in rows])


@api.get("/payouts/profiles")
def list_profiles():
    with session_scope() as s:
        rows = s.execute(select(PmPayoutProfile)).scalars().all()
        return jsonify([_profile_dict(p) for p in rows])


@api.post("/payouts/profiles")
def create_profile():
    data = request.get_json(force=True) or {}
    with session_scope() as s:
        p = PmPayoutProfile(
            id=new_uuid(),
            pm_user_id=data["pm_user_id"],
            legal_name=data["legal_name"],
            entity_type=data.get("entity_type", "individual"),
            tax_classification=data.get("tax_classification"),
            payout_method=data.get("payout_method", "ach_bank"),
            status="pending",
            w9_status="not_collected",
            created_at=utcnow().isoformat(),
            updated_at=utcnow().isoformat(),
        )
        s.add(p)
        s.flush()
        return jsonify(_profile_dict(p)), 201


@api.post("/payouts/profiles/<pid>/w9")
def submit_w9(pid: str):
    data = request.get_json(force=True) or {}
    with session_scope() as s:
        try:
            rec = tax.collect_w9(
                s, pid,
                tin_last4=data.get("tin_last4", data.get("tin", "")[-4:]),
                provider=data.get("provider"),
                provider_ref=data.get("provider_ref"),
                document_r2_key=data.get("document_r2_key"),
            )
            return jsonify({"w9_id": rec.id, "tin_last4": rec.tin_last4,
                            "tin_match_status": rec.tin_match_status}), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400


@api.post("/payouts/profiles/<pid>/authorize")
def authorize_profile(pid: str):
    import hashlib
    data = request.get_json(force=True) or {}
    text = data.get("consent_text", "")
    if not text:
        return jsonify({"error": "consent_text required"}), 400
    with session_scope() as s:
        prof = s.get(PmPayoutProfile, pid)
        if prof is None:
            return jsonify({"error": "profile not found"}), 404
        auth = PayoutAuthorization(
            id=new_uuid(),
            profile_id=pid,
            consent_version=data.get("consent_version", "pm-payout-v1"),
            consent_text_hash=hashlib.sha256(text.encode()).hexdigest(),
            authorized_at=utcnow().isoformat(),
            ip_address=request.remote_addr or "0.0.0.0",
            user_agent=request.user_agent.string if request.user_agent else "unknown",
        )
        s.add(auth)
        # advance state if W-9 collected and bank linked
        if prof.w9_status in ("collected", "tin_verified") and prof.provider_funding_id:
            prof.status = "active"
        s.flush()
        return jsonify({"authorization_id": auth.id, "profile_status": prof.status}), 201


# ---------- Plaid + Dwolla bank link ----------

@api.post("/bank-link/token")
def plaid_link_token():
    data = request.get_json(force=True) or {}
    if not data.get("pm_user_id"):
        return jsonify({"error": "pm_user_id required"}), 400
    return jsonify({"link_token": bank_link.create_link_token(data["pm_user_id"])})


@api.post("/bank-link/exchange")
def plaid_exchange():
    """Server step after Plaid Link onSuccess. Creates Dwolla customer + funding source."""
    data = request.get_json(force=True) or {}
    required = ("profile_id", "public_token", "account_id", "bank_name",
                "bank_last4", "account_type")
    for k in required:
        if k not in data:
            return jsonify({"error": f"{k} required"}), 400
    with session_scope() as s:
        prof = s.get(PmPayoutProfile, data["profile_id"])
        if prof is None:
            return jsonify({"error": "profile not found"}), 404
        exch = bank_link.link_account(s, prof.id, data["public_token"],
                                      data["account_id"], data["bank_name"],
                                      data["bank_last4"], data["account_type"])
        # Hand off to Dwolla
        user = s.get(User, prof.pm_user_id)
        result = payout_svc.onboard_pm(
            s, prof.id, exch["processor_token"],
            first_name=(user.name or "PM").split(" ")[0] if user else "PM",
            last_name=(user.name or "User").split(" ")[-1] if user else "User",
            email=user.email if user else "pm@example.com",
            bank_last4=data["bank_last4"],
        )
        return jsonify({"profile_id": prof.id, "status": prof.status,
                        "dwolla": result})


# ---------- Payouts ----------

@api.get("/payouts")
def list_payouts():
    with session_scope() as s:
        rows = s.execute(select(Payout).order_by(Payout.created_at.desc())).scalars().all()
        return jsonify([_payout_dict(p) for p in rows])


@api.post("/payouts/initiate")
def initiate_payout_route():
    data = request.get_json(force=True) or {}
    try:
        with session_scope() as s:
            p = payout_svc.initiate_payout(
                s,
                profile_id=data["profile_id"],
                amount_cents=int(data["amount_cents"]),
                approved_by=data.get("approved_by"),
                same_day=bool(data.get("same_day", False)),
            )
            return jsonify(_payout_dict(p)), 201
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400


@api.post("/payouts/<pid>/simulate-complete")
def simulate_complete(pid: str):
    """Local-dev helper — settle a payout without a real Dwolla webhook."""
    with session_scope() as s:
        p = s.get(Payout, pid)
        if p is None:
            return jsonify({"error": "payout not found"}), 404
        if p.status not in ("processing", "pending"):
            return jsonify({"error": f"cannot complete payout in status={p.status}"}), 400
        p.status = "completed"
        p.completed_at = utcnow().isoformat()
        if p.reserved_entry_id:
            ledger.settle_reservation(s, p.reserved_entry_id)
        return jsonify(_payout_dict(p))


# ---------- Ledger ----------

@api.get("/ledger/accounts")
def list_accounts():
    with session_scope() as s:
        rows = s.execute(select(LedgerAccount)).scalars().all()
        return jsonify([{"code": a.code, "name": a.name, "type": a.type} for a in rows])


@api.get("/ledger/balance/<code>")
def ledger_balance(code: str):
    with session_scope() as s:
        try:
            return jsonify({"code": code, "balance_cents": ledger.balance(s, code)})
        except ledger.LedgerError as e:
            return jsonify({"error": str(e)}), 404


@api.get("/ledger/entries")
def list_entries():
    limit = int(request.args.get("limit", "50"))
    with session_scope() as s:
        rows = s.execute(
            select(LedgerEntry).order_by(LedgerEntry.occurred_at.desc()).limit(limit)
        ).scalars().all()
        out = []
        for e in rows:
            lines = s.execute(
                select(LedgerLine, LedgerAccount.code).join(
                    LedgerAccount, LedgerAccount.id == LedgerLine.account_id
                ).where(LedgerLine.entry_id == e.id)
            ).all()
            out.append({
                "id": e.id,
                "entry_type": e.entry_type,
                "occurred_at": e.occurred_at,
                "posted": e.posted,
                "memo": e.memo,
                "source_table": e.source_table,
                "source_id": e.source_id,
                "lines": [{"account": code, "direction": ln.direction,
                           "amount_cents": ln.amount_cents,
                           "tax_category": ln.tax_category}
                          for ln, code in lines],
            })
        return jsonify(out)


@api.get("/ledger/pnl")
def get_pnl():
    year = int(request.args.get("year", str(utcnow().year)))
    with session_scope() as s:
        return jsonify(ledger.pnl(
            s,
            datetime(year, 1, 1, tzinfo=timezone.utc),
            datetime(year + 1, 1, 1, tzinfo=timezone.utc),
        ))


# ---------- Receipts ----------

@api.get("/receipts")
def list_receipts():
    with session_scope() as s:
        rows = s.execute(select(Receipt).order_by(Receipt.created_at.desc())).scalars().all()
        return jsonify([{
            "id": r.id, "source": r.source, "merchant": r.merchant,
            "total_cents": r.total_cents, "tax_cents": r.tax_cents,
            "txn_date": r.txn_date, "category": r.category,
            "confidence": float(r.confidence) if r.confidence else None,
            "status": r.status, "ledger_entry_id": r.ledger_entry_id,
        } for r in rows])


@api.post("/receipts")
def create_receipt():
    data = request.get_json(force=True) or {}
    with session_scope() as s:
        r = receipt_svc.ingest_upload(
            s,
            merchant=data.get("merchant"),
            total_cents=int(data.get("total_cents", 0)),
            tax_cents=data.get("tax_cents"),
            txn_date=data.get("txn_date"),
            pm_user_id=data.get("pm_user_id"),
            project_id=data.get("project_id"),
            customer_id=data.get("customer_id"),
            r2_key=data.get("r2_key"),
        )
        return jsonify({"id": r.id, "status": r.status, "category": r.category,
                        "confidence": float(r.confidence)}), 201


@api.post("/receipts/<rid>/confirm")
def confirm_receipt(rid: str):
    data = request.get_json(silent=True) or {}
    try:
        with session_scope() as s:
            r = receipt_svc.confirm(s, rid, override_account_code=data.get("account_code"))
            return jsonify({"id": r.id, "status": r.status, "ledger_entry_id": r.ledger_entry_id})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ---------- Mileage ----------

@api.get("/mileage")
def list_mileage():
    with session_scope() as s:
        rows = s.execute(select(MileageLog).order_by(MileageLog.logged_at.desc())).scalars().all()
        return jsonify([{
            "id": m.id, "driver_user_id": m.driver_user_id,
            "miles": float(m.miles), "minutes": m.minutes,
            "tax_year": m.tax_year, "rate_cents": m.rate_cents,
            "deduction_cents": m.deduction_cents,
            "purpose": m.purpose, "customer_id": m.customer_id, "project_id": m.project_id,
            "logged_at": m.logged_at,
        } for m in rows])


@api.post("/mileage")
def create_mileage():
    data = request.get_json(force=True) or {}
    try:
        with session_scope() as s:
            log = mileage.log_trip(
                s,
                driver_user_id=data["driver_user_id"],
                miles=float(data["miles"]),
                tax_year=int(data.get("tax_year", utcnow().year)),
                vehicle=data.get("vehicle"),
                start_location=data.get("start_location"),
                end_location=data.get("end_location"),
                minutes=data.get("minutes"),
                purpose=data.get("purpose"),
                customer_id=data.get("customer_id"),
                project_id=data.get("project_id"),
                lead_id=data.get("lead_id"),
            )
            return jsonify({
                "id": log.id, "miles": float(log.miles),
                "deduction_cents": log.deduction_cents,
                "rate_cents": log.rate_cents,
            }), 201
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400


# ---------- Tax packet ----------

@api.get("/tax/thresholds")
def list_thresholds():
    with session_scope() as s:
        rows = s.execute(select(TaxThreshold)).scalars().all()
        return jsonify([{"tax_year": t.tax_year, "form_type": t.form_type,
                         "threshold_cents": t.threshold_cents,
                         "notes": t.notes} for t in rows])


@api.get("/tax/eligibility")
def tax_eligibility():
    pm = request.args.get("pm_user_id")
    year = int(request.args.get("year", str(utcnow().year)))
    if not pm:
        return jsonify({"error": "pm_user_id required"}), 400
    with session_scope() as s:
        return jsonify(tax.compute_1099_eligibility(s, pm, year))


@api.get("/tax/schedule-c")
def schedule_c_json():
    year = int(request.args.get("year", str(utcnow().year)))
    with session_scope() as s:
        return jsonify(tax.export_schedule_c(s, year))


@api.get("/tax/schedule-c.csv")
def schedule_c_csv():
    year = int(request.args.get("year", str(utcnow().year)))
    with session_scope() as s:
        csv_text = tax.export_schedule_c_csv(s, year)
    return Response(csv_text, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename=schedule-c-{year}.csv'})


# ---------- Merch ----------

@api.get("/merch/products")
def list_merch_products():
    with session_scope() as s:
        rows = s.execute(select(MerchProduct).where(MerchProduct.active.is_(True))).scalars().all()
        return jsonify([{"id": p.id, "sku": p.sku, "title": p.title,
                         "fulfillment": p.fulfillment,
                         "base_cost_cents": p.base_cost_cents,
                         "retail_cents": p.retail_cents} for p in rows])


@api.post("/merch/products")
def create_merch_product():
    data = request.get_json(force=True) or {}
    with session_scope() as s:
        try:
            p = merch.create_product(
                s, sku=data["sku"], title=data["title"],
                fulfillment=data["fulfillment"],
                base_cost_cents=int(data.get("base_cost_cents", 0)),
                retail_cents=int(data.get("retail_cents", 0)),
                provider_product_id=data.get("provider_product_id"),
            )
            return jsonify({"id": p.id, "sku": p.sku, "title": p.title}), 201
        except (KeyError, ValueError) as e:
            return jsonify({"error": str(e)}), 400


@api.get("/merch/orders")
def list_merch_orders():
    with session_scope() as s:
        rows = s.execute(select(MerchOrder).order_by(MerchOrder.created_at.desc())).scalars().all()
        return jsonify([{"id": o.id, "product_id": o.product_id, "qty": o.qty,
                         "provider": o.provider, "provider_order_id": o.provider_order_id,
                         "total_cents": o.total_cents, "cogs_cents": o.cogs_cents,
                         "status": o.status, "created_at": o.created_at} for o in rows])


@api.post("/merch/orders")
def create_merch_order():
    data = request.get_json(force=True) or {}
    try:
        with session_scope() as s:
            o = merch.create_order(
                s,
                product_id=data["product_id"],
                qty=int(data.get("qty", 1)),
                ship_to=data.get("ship_to", {}),
                customer_id=data.get("customer_id"),
                processor_fee_cents=int(data.get("processor_fee_cents", 0)),
            )
            return jsonify({"id": o.id, "status": o.status,
                            "provider_order_id": o.provider_order_id,
                            "total_cents": o.total_cents,
                            "cogs_cents": o.cogs_cents}), 201
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400


# ---------- Webhooks ----------

@api.post("/webhooks/paypal")
def webhook_paypal():
    raw = request.get_data()
    with session_scope() as s:
        result = billing.process_webhook(s, dict(request.headers), raw)

    # Best-effort relay to the CRM Worker so the CRM lead reflects the
    # paid state without a polling loop. Failures here do not roll back the
    # webhook — PayPal already considers the event delivered, and Flask's
    # local state is the source of truth.
    if result.get("ok"):
        try:
            body_json = json.loads(raw or b"{}")
        except (TypeError, ValueError):
            body_json = {}
        if body_json.get("event_type") == "INVOICING.INVOICE.PAID":
            try:
                from middleware.hmac_sign import post_to_worker
                resource = body_json.get("resource", {}) or {}
                pid = resource.get("id") or (resource.get("invoice", {}) or {}).get("id")
                amount_value = (resource.get("amount", {}) or {}).get("value")
                if amount_value is None:
                    amount_value = ((resource.get("invoice", {}) or {})
                                    .get("amount", {}) or {}).get("value")
                amount_cents = None
                if amount_value is not None:
                    try:
                        amount_cents = int(round(float(amount_value) * 100))
                    except (TypeError, ValueError):
                        amount_cents = None
                if pid:
                    post_to_worker(
                        "/api/finance/webhook/paypal-paid",
                        {"invoice_id": pid, "amount_cents": amount_cents},
                        timeout=10.0,
                    )
            except Exception as e:  # noqa: BLE001 — best-effort relay
                import logging
                logging.warning("worker relay failed for paid invoice: %s", e)

    return jsonify(result)


@api.post("/webhooks/dwolla")
def webhook_dwolla():
    with session_scope() as s:
        return jsonify(payout_svc.process_webhook(s, dict(request.headers), request.get_data()))


@api.post("/webhooks/plaid")
def webhook_plaid():
    with session_scope() as s:
        return jsonify(bank_link.process_webhook(s, dict(request.headers), request.get_data()))


# ---------- Helpers ----------

def _profile_dict(p: PmPayoutProfile) -> dict:
    return {
        "id": p.id,
        "pm_user_id": p.pm_user_id,
        "legal_name": p.legal_name,
        "entity_type": p.entity_type,
        "payout_method": p.payout_method,
        "provider_name": p.provider_name,
        "bank_name": p.bank_name,
        "bank_last4": p.bank_last4,
        "account_type": p.account_type,
        "status": p.status,
        "w9_status": p.w9_status,
        "is_1099_eligible": p.is_1099_eligible,
    }


def _payout_dict(p: Payout) -> dict:
    return {
        "id": p.id,
        "profile_id": p.profile_id,
        "pm_user_id": p.pm_user_id,
        "amount_cents": p.amount_cents,
        "status": p.status,
        "provider_transfer_id": p.provider_transfer_id,
        "failure_code": p.failure_code,
        "initiated_at": p.initiated_at,
        "completed_at": p.completed_at,
        "created_at": p.created_at,
    }
