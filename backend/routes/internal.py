"""HMAC-gated internal routes — called by the CRM Worker
(api.example.com) when it acts as the gateway.

Every request here must pass `@require_worker_hmac`. The Worker holds the
matching FINANCE_RELAY_SECRET. Replay window: ±60s on the timestamp header.

Routes:
    GET  /api/internal/health
    POST /api/internal/customers/upsert
    POST /api/internal/invoices/create
    GET  /api/internal/invoices/<invoice_id>
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, g
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import session_scope, new_uuid, utcnow
from models import Customer, Invoice
from services.billing import PayPalClient
from services import ledger
from middleware.hmac_auth import require_worker_hmac
from middleware.jwt_validator import require_user_jwt


internal = Blueprint("internal", __name__, url_prefix="/api/internal")


# ---------- Health ----------

@internal.get("/health")
@require_worker_hmac
def health():
    return jsonify({"ok": True, "service": "acme-finance-suite", "time": utcnow().isoformat()})


# ---------- Customers (upsert by external_id) ----------

def _user_id() -> str | None:
    user = getattr(g, "user", None) or {}
    return user.get("sub") or user.get("user_id") or user.get("id")


@internal.post("/customers/upsert")
@require_worker_hmac
@require_user_jwt
def upsert_customer():
    data = request.get_json(force=True, silent=True) or {}
    external_id = data.get("external_id")
    name = data.get("name")
    if not external_id:
        return jsonify({"error": "external_id required"}), 400
    if not name:
        return jsonify({"error": "name required"}), 400

    user_id = _user_id()
    with session_scope() as s:
        existing = s.execute(
            select(Customer).where(Customer.external_id == external_id)
        ).scalar_one_or_none()

        if existing:
            existing.name = name
            existing.email = data.get("email") or existing.email
            existing.phone = data.get("phone") or existing.phone
            existing.address = data.get("address") or existing.address
            if user_id and hasattr(existing, "updated_by"):
                existing.updated_by = user_id
            s.flush()
            return jsonify({
                "id": existing.id,
                "external_id": existing.external_id,
                "created": False,
            })

        c = Customer(
            id=new_uuid(),
            external_id=external_id,
            name=name,
            email=data.get("email"),
            phone=data.get("phone"),
            address=data.get("address"),
            project_id=data.get("project_id"),
            created_at=utcnow().isoformat(),
        )
        if user_id and hasattr(c, "created_by"):
            c.created_by = user_id
        s.add(c)
        try:
            s.flush()
        except IntegrityError:
            # Race: another upsert won the slot between our SELECT and INSERT.
            # Re-resolve and return the winner.
            s.rollback()
            with session_scope() as s2:
                winner = s2.execute(
                    select(Customer).where(Customer.external_id == external_id)
                ).scalar_one()
                return jsonify({"id": winner.id, "external_id": winner.external_id, "created": False})

        return jsonify({"id": c.id, "external_id": c.external_id, "created": True})


# ---------- Invoices ----------

@internal.post("/invoices/create")
@require_worker_hmac
@require_user_jwt
def create_invoice():
    data = request.get_json(force=True, silent=True) or {}
    customer_id = data.get("customer_id")
    amount_cents = data.get("amount_cents")
    if not customer_id:
        return jsonify({"error": "customer_id required"}), 400
    try:
        amount_cents = int(amount_cents)
    except (TypeError, ValueError):
        return jsonify({"error": "amount_cents must be an integer"}), 400
    if amount_cents <= 0:
        return jsonify({"error": "amount_cents must be positive"}), 400

    currency = (data.get("currency") or "USD").upper()
    number = data.get("number") or f"INV-{int(utcnow().timestamp())}"
    description = data.get("description") or "Services"
    external_ref = data.get("external_ref") or ""
    user_id = _user_id()

    with session_scope() as s:
        customer = s.get(Customer, customer_id)
        if not customer:
            return jsonify({"error": "customer not found"}), 404

        if not customer.email:
            return jsonify({"error": "customer email missing — cannot create PayPal invoice"}), 422

        pp = PayPalClient()
        pp_inv = pp.create_invoice(
            customer_email=customer.email,
            number=number,
            amount_cents=amount_cents,
            memo=description,
            reference=external_ref,
        )

        inv = Invoice(
            id=new_uuid(),
            customer_id=customer.id,
            project_id=customer.project_id,
            provider="paypal",
            provider_invoice_id=pp_inv.get("id"),
            number=number,
            amount_cents=amount_cents,
            currency=currency,
            status="draft",
            created_at=utcnow().isoformat(),
        )
        if user_id and hasattr(inv, "created_by"):
            inv.created_by = user_id
        s.add(inv)
        s.flush()

        return jsonify({
            "id": inv.id,
            "provider_invoice_id": inv.provider_invoice_id,
            "status": inv.status,
            "number": inv.number,
            "amount_cents": inv.amount_cents,
            "currency": inv.currency,
            "external_ref": external_ref,
            "dry_run": pp.dry_run,
        })


@internal.get("/invoices/<invoice_id>")
@require_worker_hmac
def get_invoice(invoice_id):
    with session_scope() as s:
        inv = s.get(Invoice, invoice_id)
        if not inv:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "id": inv.id,
            "customer_id": inv.customer_id,
            "provider_invoice_id": inv.provider_invoice_id,
            "number": inv.number,
            "amount_cents": inv.amount_cents,
            "currency": inv.currency,
            "status": inv.status,
            "payable_url": inv.payable_url,
            "issued_at": inv.issued_at,
            "paid_at": inv.paid_at,
            "created_at": inv.created_at,
        })
