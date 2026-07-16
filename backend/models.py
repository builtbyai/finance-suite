"""SQLAlchemy models matching docs/source-knowledge-base/02-DATA-MODEL.md.

Local dev runs SQLite — PG-specific types (TIMESTAMPTZ, JSONB, INET, UUID) become
SQLite-compatible (String/JSON) but column meaning is preserved. Production migrates
to Postgres via migrations/0001_init_postgres.sql.
"""
from sqlalchemy import (
    String, Integer, BigInteger, Boolean, ForeignKey, JSON, Text, Numeric,
    UniqueConstraint, CheckConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, date
from typing import Optional

from db import Base, new_uuid, utcnow


def _id():
    return mapped_column(String(36), primary_key=True, default=new_uuid)


def _ts(default=True, nullable=False):
    return mapped_column(String(40), default=lambda: utcnow().isoformat(), nullable=nullable) if default \
        else mapped_column(String(40), nullable=nullable)


# ---------- Users / Customers / Projects ----------

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = _id()
    email: Mapped[Optional[str]] = mapped_column(String(255))
    name: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), default="pm")  # pm | operator | admin
    created_at: Mapped[str] = _ts()


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[str] = _ts()


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    address: Mapped[Optional[str]] = mapped_column(Text)
    # External CRM identifier (e.g. "lead:<storm_leads.id>"). Unique so the
    # Worker's /api/internal/customers/upsert is idempotent on retry.
    external_id: Mapped[Optional[str]] = mapped_column(String(120), unique=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("projects.id"))
    created_at: Mapped[str] = _ts()


# ---------- PM payout ----------

class PmPayoutProfile(Base):
    __tablename__ = "pm_payout_profiles"
    id: Mapped[str] = _id()
    pm_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    legal_name: Mapped[str] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(40))  # individual|sole_prop|llc|s_corp|c_corp|partnership
    tax_classification: Mapped[Optional[str]] = mapped_column(String(40))
    payout_method: Mapped[str] = mapped_column(String(20), default="ach_bank")  # ach_bank|paypal|venmo
    provider_name: Mapped[Optional[str]] = mapped_column(String(20))            # 'dwolla'
    provider_customer_id: Mapped[Optional[str]] = mapped_column(String(255))
    provider_funding_id: Mapped[Optional[str]] = mapped_column(String(255))
    bank_name: Mapped[Optional[str]] = mapped_column(String(120))
    bank_last4: Mapped[Optional[str]] = mapped_column(String(4))
    account_type: Mapped[Optional[str]] = mapped_column(String(20))  # checking|savings
    plaid_item_id: Mapped[Optional[str]] = mapped_column(String(120))
    plaid_access_token_enc: Mapped[Optional[str]] = mapped_column(Text)  # encrypted at rest
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|verified|active|failed|disabled
    w9_status: Mapped[str] = mapped_column(String(20), default="not_collected")  # not_collected|collected|tin_verified|tin_mismatch
    is_1099_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = _ts()
    updated_at: Mapped[str] = _ts()


class PayoutAuthorization(Base):
    __tablename__ = "payout_authorizations"
    id: Mapped[str] = _id()
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("pm_payout_profiles.id"))
    consent_version: Mapped[str] = mapped_column(String(40))
    consent_text_hash: Mapped[str] = mapped_column(String(64))
    authorized_at: Mapped[str] = _ts()
    ip_address: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str] = mapped_column(String(512))
    revoked_at: Mapped[Optional[str]] = _ts(default=False, nullable=True)


# ---------- Invoices ----------

class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[str] = _id()
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"))
    project_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("projects.id"))
    provider: Mapped[str] = mapped_column(String(20), default="paypal")
    provider_invoice_id: Mapped[Optional[str]] = mapped_column(String(120), unique=True)
    number: Mapped[str] = mapped_column(String(40))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|sent|paid|partially_paid|cancelled|refunded
    payable_url: Mapped[Optional[str]] = mapped_column(String(512))
    issued_at: Mapped[Optional[str]] = _ts(default=False, nullable=True)
    paid_at: Mapped[Optional[str]] = _ts(default=False, nullable=True)
    created_at: Mapped[str] = _ts()


# ---------- Ledger ----------

class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"
    id: Mapped[str] = _id()
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(20))  # asset|liability|equity|revenue|expense


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[str] = _id()
    entry_type: Mapped[str] = mapped_column(String(40))
    source_table: Mapped[Optional[str]] = mapped_column(String(60))
    source_id: Mapped[Optional[str]] = mapped_column(String(36))
    memo: Mapped[Optional[str]] = mapped_column(Text)
    occurred_at: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = _ts()
    reverses_entry: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("ledger_entries.id"))
    posted: Mapped[bool] = mapped_column(Boolean, default=True)  # False == reservation


class LedgerLine(Base):
    __tablename__ = "ledger_lines"
    id: Mapped[str] = _id()
    entry_id: Mapped[str] = mapped_column(String(36), ForeignKey("ledger_entries.id"))
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("ledger_accounts.id"))
    direction: Mapped[str] = mapped_column(String(6))  # debit | credit
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    pm_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    customer_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("customers.id"))
    project_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("projects.id"))
    tax_category: Mapped[Optional[str]] = mapped_column(String(40))

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_line_amount_positive"),
        CheckConstraint("direction in ('debit','credit')", name="ck_line_direction"),
        Index("ix_ledger_lines_entry", "entry_id"),
    )


# ---------- Payouts ----------

class Payout(Base):
    __tablename__ = "payouts"
    id: Mapped[str] = _id()
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("pm_payout_profiles.id"))
    pm_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    provider: Mapped[str] = mapped_column(String(20), default="dwolla")
    provider_transfer_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    failure_code: Mapped[Optional[str]] = mapped_column(String(10))
    approved_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    approved_at: Mapped[Optional[str]] = _ts(default=False, nullable=True)
    initiated_at: Mapped[Optional[str]] = _ts(default=False, nullable=True)
    completed_at: Mapped[Optional[str]] = _ts(default=False, nullable=True)
    reserved_entry_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("ledger_entries.id"))
    created_at: Mapped[str] = _ts()


# ---------- W-9 ----------

class W9Record(Base):
    __tablename__ = "w9_records"
    id: Mapped[str] = _id()
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("pm_payout_profiles.id"))
    provider: Mapped[Optional[str]] = mapped_column(String(40))
    provider_ref: Mapped[Optional[str]] = mapped_column(String(255))
    tin_last4: Mapped[Optional[str]] = mapped_column(String(4))
    tin_match_status: Mapped[Optional[str]] = mapped_column(String(20))  # pending|match|mismatch|foreign
    collected_at: Mapped[Optional[str]] = _ts(default=False, nullable=True)
    document_r2_key: Mapped[Optional[str]] = mapped_column(String(255))


# ---------- Receipts ----------

class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[str] = _id()
    source: Mapped[str] = mapped_column(String(20))  # email|upload|bank_feed
    r2_key: Mapped[Optional[str]] = mapped_column(String(255))
    raw_email_key: Mapped[Optional[str]] = mapped_column(String(255))
    merchant: Mapped[Optional[str]] = mapped_column(String(255))
    total_cents: Mapped[Optional[int]] = mapped_column(BigInteger)
    tax_cents: Mapped[Optional[int]] = mapped_column(BigInteger)
    txn_date: Mapped[Optional[str]] = mapped_column(String(10))
    category: Mapped[Optional[str]] = mapped_column(String(40))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    pm_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    customer_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("customers.id"))
    project_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("projects.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|confirmed|rejected|reconciled
    ledger_entry_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("ledger_entries.id"))
    created_at: Mapped[str] = _ts()


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    id: Mapped[str] = _id()
    plaid_account_id: Mapped[str] = mapped_column(String(64))
    plaid_txn_id: Mapped[str] = mapped_column(String(64), unique=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    category: Mapped[Optional[str]] = mapped_column(String(80))
    posted_date: Mapped[Optional[str]] = mapped_column(String(10))
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    matched_receipt_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("receipts.id"))
    missing_receipt: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = _ts()


# ---------- Mileage ----------

class MileageRate(Base):
    __tablename__ = "mileage_rates"
    tax_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    rate_cents: Mapped[int] = mapped_column(Integer)  # cents per mile
    source: Mapped[Optional[str]] = mapped_column(String(255))
    set_at: Mapped[str] = _ts()


class MileageLog(Base):
    __tablename__ = "mileage_logs"
    id: Mapped[str] = _id()
    driver_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    vehicle: Mapped[Optional[str]] = mapped_column(String(120))
    start_location: Mapped[Optional[str]] = mapped_column(String(255))
    end_location: Mapped[Optional[str]] = mapped_column(String(255))
    miles: Mapped[float] = mapped_column(Numeric(8, 2))
    minutes: Mapped[Optional[int]] = mapped_column(Integer)
    purpose: Mapped[Optional[str]] = mapped_column(String(255))
    customer_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("customers.id"))
    project_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("projects.id"))
    lead_id: Mapped[Optional[str]] = mapped_column(String(36))
    reimbursement_status: Mapped[str] = mapped_column(String(20), default="unreimbursed")
    tax_year: Mapped[int] = mapped_column(Integer)
    rate_cents: Mapped[int] = mapped_column(Integer)
    deduction_cents: Mapped[int] = mapped_column(BigInteger)
    ledger_entry_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("ledger_entries.id"))
    logged_at: Mapped[str] = _ts()


# ---------- Tax thresholds ----------

class TaxThreshold(Base):
    __tablename__ = "tax_thresholds"
    tax_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    form_type: Mapped[str] = mapped_column(String(20), primary_key=True)  # 1099-NEC | 1099-MISC | 1099-K
    threshold_cents: Mapped[int] = mapped_column(BigInteger)
    txn_count_min: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(String(255))


# ---------- Merch ----------

class MerchProduct(Base):
    __tablename__ = "merch_products"
    id: Mapped[str] = _id()
    sku: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    fulfillment: Mapped[str] = mapped_column(String(20))  # pod_printify|pod_printful|local|china
    provider_product_id: Mapped[Optional[str]] = mapped_column(String(120))
    base_cost_cents: Mapped[Optional[int]] = mapped_column(BigInteger)
    retail_cents: Mapped[Optional[int]] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MerchOrder(Base):
    __tablename__ = "merch_orders"
    id: Mapped[str] = _id()
    customer_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("customers.id"))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("merch_products.id"))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[Optional[str]] = mapped_column(String(20))
    provider_order_id: Mapped[Optional[str]] = mapped_column(String(120))
    total_cents: Mapped[int] = mapped_column(BigInteger)
    cogs_cents: Mapped[Optional[int]] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="created")
    created_at: Mapped[str] = _ts()


# ---------- Webhook events ----------

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[str] = _id()
    provider: Mapped[str] = mapped_column(String(20))
    event_id: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    signature_ok: Mapped[bool] = mapped_column(Boolean)
    processed_at: Mapped[Optional[str]] = _ts(default=False, nullable=True)
    received_at: Mapped[str] = _ts()
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_event"),)
