"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError } from "@/lib/api";
import {
  botsApi,
  type AppointmentServiceView,
  type AppointmentView,
  type StaffMemberView,
} from "@/lib/bots";

export function AppointmentsPanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [services, setServices] = useState<AppointmentServiceView[]>([]);
  const [staff, setStaff] = useState<StaffMemberView[]>([]);
  const [appointments, setAppointments] = useState<AppointmentView[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [serviceName, setServiceName] = useState("");
  const [duration, setDuration] = useState(30);
  const [staffName, setStaffName] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    botsApi.appointmentServices(botId, locale).then(setServices).catch(() => setError(t("error.network")));
    botsApi.staffMembers(botId, locale).then(setStaff).catch(() => {});
    botsApi.appointments(botId, locale).then(setAppointments).catch(() => {});
  }

  useEffect(load, [botId, locale, t]);

  async function addService(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await botsApi.createAppointmentService(botId, { name: serviceName, duration_minutes: duration }, locale);
      setServiceName("");
      setDuration(30);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function removeService(serviceId: number) {
    try {
      await botsApi.deleteAppointmentService(botId, serviceId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function addStaff(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await botsApi.createStaffMember(botId, { name: staffName }, locale);
      setStaffName("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function removeStaff(staffId: number) {
    try {
      await botsApi.deleteStaffMember(botId, staffId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function cancel(appointmentId: string) {
    try {
      await botsApi.cancelAppointment(botId, appointmentId, "", locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  const upcoming = appointments.filter((a) => a.status === "CONFIRMED");

  return (
    <section className="card space-y-5">
      <h2 className="font-medium">{t("bot.appointments.title")}</h2>

      {error ? <p className="text-sm text-red-500">{error}</p> : null}

      <div className="space-y-2">
        <h3 className="text-sm font-medium text-muted">{t("bot.appointments.services")}</h3>
        <ul className="space-y-1">
          {services.map((service) => (
            <li key={service.id} className="flex items-center justify-between gap-3 text-sm">
              <span>
                {service.name} · {service.duration_minutes} {t("bot.appointments.minutes")}
              </span>
              <button type="button" onClick={() => removeService(service.id)} className="text-xs text-red-500">
                {t("common.remove")}
              </button>
            </li>
          ))}
          {services.length === 0 ? <p className="text-sm text-muted">{t("bot.appointments.noServices")}</p> : null}
        </ul>
        <form onSubmit={addService} className="flex flex-wrap gap-2">
          <input
            className="field flex-1"
            placeholder={t("bot.appointments.serviceNamePlaceholder")}
            value={serviceName}
            onChange={(e) => setServiceName(e.target.value)}
            required
          />
          <input
            type="number"
            min={1}
            className="field w-28"
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
          />
          <button type="submit" disabled={busy} className="btn-primary shrink-0">
            {t("common.add")}
          </button>
        </form>
      </div>

      <div className="space-y-2 border-t border-line pt-4">
        <h3 className="text-sm font-medium text-muted">{t("bot.appointments.staff")}</h3>
        <ul className="space-y-1">
          {staff.map((member) => (
            <li key={member.id} className="flex items-center justify-between gap-3 text-sm">
              <span>{member.name}</span>
              <button type="button" onClick={() => removeStaff(member.id)} className="text-xs text-red-500">
                {t("common.remove")}
              </button>
            </li>
          ))}
          {staff.length === 0 ? <p className="text-sm text-muted">{t("bot.appointments.noStaff")}</p> : null}
        </ul>
        <form onSubmit={addStaff} className="flex gap-2">
          <input
            className="field flex-1"
            placeholder={t("bot.appointments.staffNamePlaceholder")}
            value={staffName}
            onChange={(e) => setStaffName(e.target.value)}
            required
          />
          <button type="submit" disabled={busy} className="btn-primary shrink-0">
            {t("common.add")}
          </button>
        </form>
      </div>

      <div className="space-y-2 border-t border-line pt-4">
        <h3 className="text-sm font-medium text-muted">{t("bot.appointments.upcoming")}</h3>
        {upcoming.length === 0 ? (
          <p className="text-sm text-muted">{t("bot.appointments.noUpcoming")}</p>
        ) : (
          <ul className="space-y-1">
            {upcoming.map((appointment) => (
              <li key={appointment.id} className="flex items-center justify-between gap-3 text-sm">
                <span>
                  {new Date(appointment.starts_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")} ·{" "}
                  {appointment.service} · {appointment.staff}
                  {appointment.contact_name ? ` · ${appointment.contact_name}` : ""}
                </span>
                <button type="button" onClick={() => cancel(appointment.id)} className="text-xs text-red-500">
                  {t("bot.appointments.cancel")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
