"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import {
  checkoutApi,
  submitProof,
  type OrderView,
  type PaymentMethodView,
  type PaymentView,
} from "@/lib/checkout";

function CopyField({ label, value }: { label: string; value: string }) {
  const t = useTranslations();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be denied; the value is visible either way.
    }
  }

  return (
    <div className="flex items-center justify-between gap-2 border-b border-line py-2 last:border-0">
      <span className="text-xs text-muted">{label}</span>
      <span className="flex items-center gap-2">
        <code className="text-sm" dir="ltr">
          {value || "—"}
        </code>
        {value ? (
          <button type="button" onClick={copy} className="text-xs text-accent">
            {copied ? t("payment.copied") : t("payment.copy")}
          </button>
        ) : null}
      </span>
    </div>
  );
}

export function PaymentPanel({
  order,
  onChanged,
}: {
  order: OrderView;
  onChanged: () => void;
}) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [methods, setMethods] = useState<PaymentMethodView[]>([]);
  const [payment, setPayment] = useState<PaymentView | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [txHash, setTxHash] = useState("");
  const [senderWallet, setSenderWallet] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const payable = order.status === "PENDING_PAYMENT" || order.status === "PAYMENT_REJECTED";

  useEffect(() => {
    if (!payable) return;
    checkoutApi
      .paymentMethods(order.id, locale)
      .then(setMethods)
      .catch(() => setError(t("error.network")));
  }, [order.id, locale, payable, t]);

  async function choose(method: PaymentMethodView) {
    setBusy(true);
    setError(null);
    try {
      setPayment(await checkoutApi.startPayment(order.id, method.id, locale));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!payment) return;

    setBusy(true);
    setError(null);
    try {
      await submitProof(
        payment.id,
        { file, tx_hash: txHash, sender_wallet: senderWallet },
        locale,
      );
      setPayment(null);
      setFile(null);
      setTxHash("");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  if (order.status === "RECEIPT_SUBMITTED" || order.status === "PAYMENT_REVIEW") {
    return (
      <section className="card space-y-2">
        <h2 className="font-medium">{t("payment.review.title")}</h2>
        <p className="text-sm text-muted">{t("payment.review.body")}</p>
      </section>
    );
  }

  if (!payable) return null;

  return (
    <section className="card space-y-4">
      <h2 className="font-medium">{t("payment.title")}</h2>

      {order.payment?.rejection_reason ? (
        <p className="rounded-lg border border-red-500/40 p-3 text-sm text-red-500">
          {t("payment.rejected", { reason: order.payment.rejection_reason })}
        </p>
      ) : null}

      {!payment ? (
        <>
          <p className="text-sm text-muted">{t("payment.choose")}</p>
          <div className="grid gap-2">
            {methods.map((method) => (
              <button
                key={method.id}
                type="button"
                disabled={busy}
                onClick={() => choose(method)}
                className="card text-start transition hover:border-accent"
              >
                <span className="block text-sm font-medium">{method.name}</span>
                <span className="block text-xs text-muted">
                  {method.currency}
                  {method.network ? ` · ${method.network}` : ""}
                </span>
              </button>
            ))}
            {methods.length === 0 ? (
              <p className="text-sm text-muted">{t("payment.noMethods")}</p>
            ) : null}
          </div>
        </>
      ) : (
        <div className="space-y-4">
          <p className="text-sm">{payment.instructions.headline}</p>

          <div className="rounded-lg border border-line px-3">
            {payment.instructions.fields.map((field) => (
              <CopyField key={field.label} label={field.label} value={field.value} />
            ))}
            <CopyField label={t("payment.amount")} value={payment.amount.formatted} />
          </div>

          {payment.instructions.notes.map((note) => (
            <p key={note} className="text-xs text-muted">
              {note}
            </p>
          ))}

          <form onSubmit={send} className="space-y-3">
            {payment.proof.requires_tx_hash ? (
              <>
                <label className="block space-y-1">
                  <span className="text-sm text-muted">{t("payment.txHash")}</span>
                  <input
                    className="field"
                    dir="ltr"
                    required
                    value={txHash}
                    onChange={(event) => setTxHash(event.target.value)}
                  />
                </label>
                <label className="block space-y-1">
                  <span className="text-sm text-muted">{t("payment.senderWallet")}</span>
                  <input
                    className="field"
                    dir="ltr"
                    value={senderWallet}
                    onChange={(event) => setSenderWallet(event.target.value)}
                  />
                </label>
              </>
            ) : null}

            <label className="block space-y-1">
              <span className="text-sm text-muted">
                {payment.proof.requires_file ? t("payment.receipt") : t("payment.receiptOptional")}
              </span>
              <input
                type="file"
                className="field"
                accept=".jpg,.jpeg,.png,.webp,.pdf"
                required={payment.proof.requires_file}
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <span className="block text-xs text-muted">{t("payment.receiptHint")}</span>
            </label>

            {error ? (
              <p role="alert" className="text-sm text-red-500">
                {error}
              </p>
            ) : null}

            <div className="flex gap-2">
              <button type="submit" disabled={busy} className="btn-primary">
                {busy ? t("common.loading") : t("payment.submit")}
              </button>
              <button type="button" className="btn-ghost" onClick={() => setPayment(null)}>
                {t("common.cancel")}
              </button>
            </div>
          </form>
        </div>
      )}

      {error && !payment ? (
        <p role="alert" className="text-sm text-red-500">
          {error}
        </p>
      ) : null}
    </section>
  );
}
