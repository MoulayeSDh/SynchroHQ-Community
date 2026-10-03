"use client";
import { useUI } from "../ui/session";
import { useState } from "react";
import { canEdit, type Draft, type Profile } from "./store";
import { confirmReport, finalizeReport, reopenReport, type LocalReport } from "./reports";
export function ReportActions({ draft, profile, report, disabled, revision, run, sync }: {
    draft: Draft;
    profile: Profile;
    report?: LocalReport;
    disabled: boolean;
    revision: number;
    run: (action: () => Promise<void>) => Promise<void>;
    sync: () => Promise<void>;
}) {
    const { t } = useUI();
    const [accepted, setAccepted] = useState(false);
    const business = draft.business_state ?? "DRAFT";
    return <section aria-label={t("Confirmation du rapport")}>
    <p>{t("État métier")} : <strong data-testid="report-business-state">{business === "DRAFT" ? t("Brouillon") : business === "FINALIZED" ? t("Finalisé") : t("Confirmé")}</strong></p>
    {business === "DRAFT" && <button disabled={disabled || !canEdit(profile)} onClick={() => void run(() => finalizeReport(draft.id, revision, profile))}>{t("Finaliser le rapport")}</button>}
    {business === "FINALIZED" && <>
      <p>{t("La confirmation fige les réponses, les fichiers et votre affectation. Relisez le rapport avant de confirmer.")}</p>
      {draft.report_context && <p>{t("Auteur")} : {draft.report_context.snapshot.author.display_name} ·
        {draft.report_context.snapshot.organization.name}</p>}
      <label><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)}/>{t("J’ai relu ce rapport et je confirme son contenu.")}</label>
      <button disabled={disabled || !canEdit(profile) || !accepted} onClick={() => void run(async () => { await confirmReport(draft.id, profile); await sync(); })}>{t("Confirmer définitivement")}</button>
      <button disabled={disabled || !canEdit(profile)} onClick={() => void run(async () => {
                await reopenReport(draft.id, profile);
                setAccepted(false);
            })}>{t("Revenir au brouillon")}</button>
    </>}
    {report && <>
      <p data-testid="report-sync-state">{report.state === "RECEIVED" ? t("Rapport reçu par le serveur") : report.state === "BLOCKED" ? t("Rapport bloqué — copie conservée") : report.state === "ERROR" ? t("Rapport à réessayer") : t("Rapport confirmé — en attente de réception")}</p>
      <p>{t("Empreinte SHA‑256")} : <code data-testid="report-hash" style={{ overflowWrap: "anywhere" }}>{report.payload_hash}</code></p>
      {report.error && <p role="alert">{t(report.error)}</p>}
      {report.receipt && <p>{t("Accusé serveur")} : {report.receipt.server_received_at}</p>}
      <p>{t("La confirmation conserve une preuve technique d’intégrité et d’attribution.")}</p>
    </>}
  </section>;
}
