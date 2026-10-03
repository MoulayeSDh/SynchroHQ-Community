const CACHE = "synchrohq-shell-v4";
const ROUTES = ["/", "/collect", "/inbox", "/reports", "/forms", "/profile", "/administration"];
let preparation: Promise<void> | null = null;
let prepared = false;

async function warmShell(): Promise<void> {
  if (!("serviceWorker" in navigator)) throw new Error("Ce navigateur ne permet pas le démarrage hors ligne.");
  const registered = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  const worker = registered.installing ?? registered.waiting;
  if (worker && worker.state !== "activated") await new Promise<void>((resolve,reject) => {
    const timer = setTimeout(() => { worker.removeEventListener("statechange", changed); reject(new Error("Préparation hors ligne incomplète. Réessayez en ligne.")); },20000);
    function changed() {
      if (worker!.state === "activated" || worker!.state === "redundant") {
        clearTimeout(timer); worker!.removeEventListener("statechange",changed);
        if (worker!.state === "activated") resolve(); else reject(new Error("Préparation hors ligne incomplète. Réessayez en ligne."));
      }
    }
    worker.addEventListener("statechange",changed); changed();
  });
  const registration = await navigator.serviceWorker.ready;
  const cache = await caches.open(CACHE);
  if (!navigator.onLine) {
    if ((await Promise.all(ROUTES.map(route => cache.match(route)))).every(Boolean)) return;
    throw new Error("Préparation hors ligne incomplète. Réessayez en ligne.");
  }
  // Every page is a public static shell. Identity and business data are fetched separately and never cached here.
  const pages = await Promise.all(ROUTES.map(async route => {
    const response = await fetch(route,{cache:"no-store"});
    if (!response.ok) throw new Error("Préparation hors ligne incomplète. Réessayez en ligne.");
    await cache.put(route,response.clone());
    const html = new DOMParser().parseFromString(await response.text(),"text/html");
    return [...html.querySelectorAll("script[src],link[href]")].map(node => new URL(node.getAttribute("src") ?? node.getAttribute("href")!,location.origin).href)
      .filter(value => new URL(value).pathname.startsWith("/_next/static/"));
  }));
  const assets = performance.getEntriesByType("resource").map(entry => entry.name).filter(value => new URL(value).pathname.startsWith("/_next/static/"));
  await new Promise<void>((resolve,reject) => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => { channel.port1.close(); reject(new Error("Préparation hors ligne incomplète. Réessayez en ligne.")); },20000);
    channel.port1.onmessage = event => { clearTimeout(timer); channel.port1.close(); if (event.data.ready) resolve(); else reject(new Error("Préparation hors ligne incomplète. Réessayez en ligne.")); };
    registration.active?.postMessage({type:"CACHE_ASSETS",urls:[...new Set([...assets,...pages.flat()])]},[channel.port2]);
  });
  prepared = true;
}
export async function prepareOfflineShell(): Promise<void> {
  if (prepared) return;
  if (!preparation) preparation = warmShell().finally(() => { preparation = null; });
  return preparation;
}
