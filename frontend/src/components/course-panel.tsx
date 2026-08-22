"use client";

import { useEffect, useState } from "react";
import { useIntl, useTranslations } from "@/i18n/provider";
import { ApiError, mediaUrl } from "@/lib/api";
import { commerceApi, type CourseOfferingView } from "@/lib/commerce";

function CourseEditForm({
  course,
  botId,
  onDone,
}: {
  course: CourseOfferingView;
  botId: string;
  onDone: () => void;
}) {
  const t = useTranslations();
  const { locale } = useIntl();
  const [title, setTitle] = useState(course.title);
  const [instructor, setInstructor] = useState(course.instructor_name);
  const [price, setPrice] = useState(String(course.price.amount_minor / 100));
  const [durationLabel, setDurationLabel] = useState(course.duration_label);
  const [description, setDescription] = useState(course.description);
  const [busy, setBusy] = useState(false);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const priceMinor = Math.round(Number(price) * 100);
    if (!title.trim() || !Number.isFinite(priceMinor) || priceMinor < 0) return;

    setBusy(true);
    try {
      await commerceApi.updateCourse(
        botId,
        course.id,
        { title, instructor_name: instructor, price_minor: priceMinor, duration_label: durationLabel, description },
        locale,
      );
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="grid gap-2 border-t border-line pt-2 sm:grid-cols-2">
      <input className="field sm:col-span-2" value={title} onChange={(e) => setTitle(e.target.value)} required />
      <input
        className="field"
        placeholder={t("bot.courses.instructorPlaceholder")}
        value={instructor}
        onChange={(e) => setInstructor(e.target.value)}
      />
      <input
        type="number"
        min={0}
        step="0.01"
        className="field"
        placeholder={t("bot.commerce.pricePlaceholder")}
        value={price}
        onChange={(e) => setPrice(e.target.value)}
        required
      />
      <input
        className="field sm:col-span-2"
        placeholder={t("bot.courses.durationPlaceholder")}
        value={durationLabel}
        onChange={(e) => setDurationLabel(e.target.value)}
      />
      <textarea
        className="field sm:col-span-2"
        rows={2}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <div className="flex gap-2 sm:col-span-2">
        <button type="submit" disabled={busy} className="btn-primary">
          {t("common.save")}
        </button>
        <button type="button" onClick={onDone} className="btn-ghost">
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}

export function CoursePanel({ botId }: { botId: string }) {
  const t = useTranslations();
  const { locale } = useIntl();

  const [courses, setCourses] = useState<CourseOfferingView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  const [title, setTitle] = useState("");
  const [instructor, setInstructor] = useState("");
  const [price, setPrice] = useState("");

  function load() {
    commerceApi.courses(botId, locale).then(setCourses).catch(() => setError(t("error.network")));
  }

  useEffect(load, [botId, locale, t]);

  async function addCourse(event: React.FormEvent) {
    event.preventDefault();
    const priceMinor = Math.round(Number(price) * 100);
    if (!title.trim() || !Number.isFinite(priceMinor) || priceMinor < 0) return;

    setBusy(true);
    setError(null);
    try {
      await commerceApi.createCourse(botId, { title, instructor_name: instructor, price_minor: priceMinor }, locale);
      setTitle("");
      setInstructor("");
      setPrice("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(courseId: number) {
    try {
      await commerceApi.deleteCourse(botId, courseId, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  async function setThumbnail(courseId: number, file: File | undefined) {
    if (!file) return;
    try {
      await commerceApi.setCourseThumbnail(botId, courseId, file, locale);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error.generic"));
    }
  }

  return (
    <section className="card space-y-5">
      <h2 className="font-medium">{t("bot.courses.title")}</h2>
      {error ? <p className="text-sm text-red-500">{error}</p> : null}

      <ul className="space-y-2">
        {courses.map((course) => (
          <li key={course.id} className="space-y-1.5 rounded-lg border border-line p-2 text-sm">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                {course.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaUrl(course.thumbnail_url)}
                    alt=""
                    className="h-10 w-10 rounded-md border border-line object-cover"
                  />
                ) : (
                  <label className="btn-ghost cursor-pointer px-2 py-1 text-xs">
                    {t("bot.commerce.addPhoto")}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      className="hidden"
                      onChange={(event) => {
                        void setThumbnail(course.id, event.target.files?.[0]);
                        event.target.value = "";
                      }}
                    />
                  </label>
                )}
                <span>
                  {course.title} · {course.price.formatted}
                  {course.instructor_name ? ` · ${course.instructor_name}` : ""}
                </span>
              </div>
              <span className="flex shrink-0 gap-2 text-xs">
                <button type="button" onClick={() => setEditingId(editingId === course.id ? null : course.id)}>
                  {t("common.edit")}
                </button>
                <button type="button" onClick={() => remove(course.id)} className="text-red-500">
                  {t("common.remove")}
                </button>
              </span>
            </div>
            {editingId === course.id ? (
              <CourseEditForm
                course={course}
                botId={botId}
                onDone={() => {
                  setEditingId(null);
                  load();
                }}
              />
            ) : null}
          </li>
        ))}
        {courses.length === 0 ? <p className="text-sm text-muted">{t("bot.courses.empty")}</p> : null}
      </ul>

      <form onSubmit={addCourse} className="grid gap-2 border-t border-line pt-4 sm:grid-cols-2">
        <input
          className="field sm:col-span-2"
          placeholder={t("bot.courses.titlePlaceholder")}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
        />
        <input
          className="field"
          placeholder={t("bot.courses.instructorPlaceholder")}
          value={instructor}
          onChange={(e) => setInstructor(e.target.value)}
        />
        <input
          type="number"
          min={0}
          step="0.01"
          className="field"
          placeholder={t("bot.commerce.pricePlaceholder")}
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          required
        />
        <button type="submit" disabled={busy} className="btn-primary sm:col-span-2">
          {t("bot.courses.add")}
        </button>
      </form>
    </section>
  );
}
