"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import { crmApi, type FeedbackView, type LeadStatus, type LeadView } from "@/lib/crm";

const STATUSES: LeadStatus[] = ["NEW", "CONTACTED", "QUALIFIED", "WON", "LOST"];

function LeadNotesAndTags({
  lead,
  botId,
  onChanged,
}: {
  lead: LeadView;
  botId: string;
  onChanged: () => void;
}) {
  const t = useTranslations();
  const { locale } = useIntl();
  const [noteText, setNoteText] = useState("");
  const [tagText, setTagText] = useState("");
  const [busy, setBusy] = useState(false);

  async function addNote(event: React.FormEvent) {
    event.preventDefault();
    if (!noteText.trim()) return;
    setBusy(true);
    try {
      await crmApi.addNote(botId, lead.id, noteText.trim(), locale);
      setNoteText("");
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function addTag(event: React.FormEvent) {
    event.preventDefault();
    if (!tagText.trim()) return;
    setBusy(true);
    try {
      await crmApi.tagLead(botId, lead.id, tagText.trim(), locale);
      setTagText("");
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-2 space-y-2 border-t border-line pt-2 text-xs">
      <div className="flex flex-wrap gap-1">
        {lead.tags.map((tag) => (
          <span key={tag} className="rounded-full border border-line px-2 py-0.5">
            {tag}
          </span>
        ))}
      </div>
      <form onSubmit={addTag} className="flex gap-1">
        <input
          className="field flex-1 py-1 text-xs"
          placeholder={t("bot.crm.addTagPlaceholder")}
          value={tagText}
          onChange={(e) => setTagText(e.target.value)}
        />
        <button type="submit" disabled={busy} className="btn-ghost px-2 py-1 text-xs shrink-0">
          {t("bot.crm.addTag")}
        </button>
      </form>

      {lead.notes.length > 0 ? (
        <ul className="space-y-1">
          {lead.notes.map((note) => (
            <li key={note.id} className="text-muted">
              {note.body}
            </li>
          ))}
        </ul>
      ) : null}
      <form onSubmit={addNote} className="flex gap-1">
        <input
          className="field flex-1 py-1 text-xs"
          placeholder={t("bot.crm.addNotePlaceholder")}
          value={noteText}
          onChange={(e) => setNoteText(e.target.value)}
        />
        <button type="submit" disabled={busy} className="btn-ghost px-2 py-1 text-xs shrink-0">
          {t("bot.crm.addNote")}
        </button>
      </form>
    </div>
  );
}

export function CrmPanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [leads, setLeads] = useState<LeadView[]>([]);
  const [feedback, setFeedback] = useState<FeedbackView[]>([]);
  const [error, setError] = useState<string | null>(null);

  function load() {
    crmApi.leads(botId, locale).then(setLeads).catch(() => setError(t("error.network")));
    crmApi.feedback(botId, locale).then(setFeedback).catch(() => {});
  }

  useEffect(load, [botId, locale, t]);

  async function changeStatus(leadId: string, status: LeadStatus) {
    try {
      await crmApi.updateLead(botId, leadId, { status }, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  if (leads.length === 0 && feedback.length === 0 && !error) return null;

  const averageRating = feedback.length
    ? (feedback.reduce((sum, f) => sum + f.rating, 0) / feedback.length).toFixed(1)
    : null;

  return (
    <section className="card space-y-5">
      <h2 className="font-medium">{t("bot.crm.title")}</h2>
      {error ? <p className="text-sm text-red-500">{error}</p> : null}

      <div className="space-y-2">
        <h3 className="text-sm font-medium text-muted">{t("bot.crm.leads")}</h3>
        {leads.length === 0 ? (
          <p className="text-sm text-muted">{t("bot.crm.noLeads")}</p>
        ) : (
          <ul className="space-y-2">
            {leads.map((lead) => (
              <li key={lead.id} className="rounded-lg border border-line p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{lead.contact_name || t("bot.crm.anonymous")}</span>
                  <select
                    className="field w-auto text-xs"
                    value={lead.status}
                    onChange={(e) => changeStatus(lead.id, e.target.value as LeadStatus)}
                  >
                    {STATUSES.map((status) => (
                      <option key={status} value={status}>
                        {t(`bot.crm.status.${status}`)}
                      </option>
                    ))}
                  </select>
                </div>
                {lead.message ? <p className="mt-1 text-muted">{lead.message}</p> : null}
                {lead.phone ? (
                  <p className="mt-1 text-muted" dir="ltr">
                    {lead.phone}
                  </p>
                ) : null}
                <LeadNotesAndTags lead={lead} botId={botId} onChanged={load} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {feedback.length > 0 ? (
        <div className="space-y-2 border-t border-line pt-4">
          <h3 className="text-sm font-medium text-muted">
            {t("bot.crm.feedback")} {averageRating ? `· ${"⭐"} ${averageRating}` : ""}
          </h3>
          <ul className="space-y-1">
            {feedback.slice(0, 10).map((entry) => (
              <li key={entry.id} className="text-sm">
                {"⭐".repeat(entry.rating)}
                {entry.comment ? ` — ${entry.comment}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
