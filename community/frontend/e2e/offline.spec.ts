import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

test("offline reload retains draft and queue; reconnect acknowledges once", async ({ page, context }) => {
  const file = path.resolve("../../.local/forms-demo.json");
  test.skip(!fs.existsSync(file), "Run demo seed first");
  const credentials = JSON.parse(fs.readFileSync(file, "utf8"));
  await page.goto("http://localhost:3000/collect");
  await page.getByLabel("Jeton d’accès").fill(credentials.token);
  await page.getByRole("button", { name: "Préparer mes formulaires" }).click();
  await expect(page.getByRole("button", { name: /Rapport quotidien territorial · v/ }).last()).toBeVisible();
  await expect(page.getByText(/Application préparée pour le hors-ligne/)).toBeVisible();
  await page.getByRole("button", { name: /Rapport quotidien territorial · v/ }).last().click();
  await page.getByLabel(/Résumé de la journée/).fill("Brouillon saisi hors connexion et conservé après rechargement.");
  await expect(page.getByTestId("draft-state")).toHaveText("Enregistré sur cet appareil");
  await context.setOffline(true);
  await page.getByLabel("Ajouter une pièce jointe").setInputFiles({
    name: "preuve-offline.pdf", mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\nSynchroHQ offline evidence\n%%EOF"),
  });
  await expect(page.getByText(/preuve-offline.pdf.*LOCAL/)).toBeVisible();
  await page.getByRole("button", { name: "Mettre en attente d’envoi" }).click();
  await expect(page.getByTestId("draft-state")).toHaveText("En attente d’envoi");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Collecte hors ligne" })).toBeVisible();
  await page.getByRole("button", { name: /Rapport quotidien territorial.*En attente d’envoi/ }).click();
  await expect(page.getByLabel(/Résumé de la journée/)).toHaveValue("Brouillon saisi hors connexion et conservé après rechargement.");
  await expect(page.getByTestId("draft-state")).toHaveText("En attente d’envoi");
  await expect(page.getByText(/preuve-offline.pdf.*LOCAL/)).toBeVisible();
  await context.setOffline(false);
  await page.getByText("Session et formulaires disponibles", { exact: true }).click();
  await page.getByLabel("Jeton d’accès").fill(credentials.token);
  await page.getByRole("button", { name: "Préparer mes formulaires" }).click();
  await expect(page.getByTestId("draft-state")).toHaveText("Reçu par le serveur", { timeout: 20000 });
  await expect(page.getByText(/brouillon reçu, réponses à compléter/)).toBeVisible();
  await expect(page.getByText(/preuve-offline.pdf.*RECEIVED/)).toBeVisible({ timeout: 20000 });
  await page.screenshot({ path: "../../.local/offline-sync.png", fullPage: true });
});
