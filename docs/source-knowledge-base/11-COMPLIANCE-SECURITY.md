# 11 — Compliance & Security

The boundaries that keep Acme Finance out of money-transmitter and data-liability territory. These are not optional polish — they're the difference between a buildable feature and a regulated one.

## Consent: two distinct authorization types

Authorization language differs by **direction of money flow**. Do not reuse one for the other.

### PM payout consent (pushing money TO the PM — simpler)
You are sending approved payouts to an account the PM chose. Store the signed record (`payout_authorizations`): version, text hash, timestamp, IP, user agent.

> *"I authorize Acme Finance and its payment processor to send approved payouts to the payout method I have provided. This authorization remains in effect until I remove or replace my payout method."*

### Customer ACH debit consent (pulling money FROM a customer — stricter, later feature)
Pulling from a customer's account triggers stronger rules. **NACHA's WEB Debit Account Validation Rule requires validation of first-use consumer account information for online ACH debits.** This needs NACHA-compliant authorization language, account validation (Plaid Auth/Signal satisfies this), and clear revocation terms.

> At launch, customers pay via PayPal only. ACH debit is a gated, later feature — do not enable it without the stronger consent flow and account validation in place.

## Tokenization & data minimization

| Always store | Never store in app DB |
|---|---|
| Dwolla `funding_source_id`, `customer_id` | Full bank account number |
| Plaid `item_id` | Full routing number |
| `bank_last4`, `bank_name`, `account_type` | Full SSN/EIN (TIN) |
| `tin_last4`, `tin_match_status` | Raw card numbers (PayPal handles cards) |
| Encrypted Plaid `access_token` | Plaintext access tokens |

Rationale: the Plaid→Dwolla **processor-token** path means raw account/routing numbers never reach Acme Finance. Storing raw numbers would impose a far higher PCI/banking-data security burden — explicitly out of scope.

## Secrets & access

- All provider secrets server-side (Railway env / secret store); never in frontend bundles or git.
- Plaid `link_token` and any client tokens minted server-side, short-lived, scoped per user.
- Encrypt Plaid `access_token` at rest; restrict DB access to the Bank Link Service role.
- Rotate webhook signing secrets; store separately from API keys.

## Webhook security (all providers)

1. **Verify** signature/cert (PayPal verify-webhook-signature; Dwolla HMAC; Plaid; Tax1099).
2. **Dedupe** on `webhook_events (provider, event_id)`.
3. **Idempotent processing** — reprocessing an event yields one effect.
4. **Persist raw payload** + `signature_ok` for audit.

## Audit & retention

- Append-only ledger (`06-LEDGER-SERVICE.md`) is the financial audit trail.
- `payout_authorizations` retained as legal consent proof (ts/IP/UA/text hash).
- Receipts, W-9 PDFs, raw `.eml`: retain ≥ 4 years in R2.
- Log every payout approval with `approved_by`.

## KYC / KYB

- Acme Finance completes Dwolla KYB for its master account.
- PMs onboarded as Dwolla customers (`receive-only` default) — provider runs required checks.
- Cross-check Plaid Identity name against W-9 legal name before a profile goes `active`.

## The hard lines (restated)

1. **Not a money transmitter** — all movement on PayPal/Dwolla rails.
2. **No raw bank numbers** in the app DB — processor tokens only.
3. **No auto-filed income tax returns** — packets only; a CPA/licensed e-filer files.
4. **No customer ACH debit** without NACHA-compliant consent + account validation.

## Acceptance Criteria

- [ ] Static scan confirms no provider secret in any frontend bundle or commit.
- [ ] DB audit confirms zero columns hold full account/routing/TIN/card numbers.
- [ ] Every webhook handler verifies signature, dedupes, and is idempotent.
- [ ] PM payout consent and customer ACH-debit consent are separate, versioned texts.
- [ ] Customer ACH debit is disabled until the stronger consent flow ships.

Read next: [`12-BUILD-ORDER.md`](./12-BUILD-ORDER.md)
