/**
 * Runtime-fetched push configuration for the PWA.
 *
 * The push public key is never baked into build-time env vars; it is
 * fetched from the backend at runtime so the deployment can rotate keys
 * without a frontend rebuild. When push is disabled, the returned config
 * has ``enabled: false`` and no subscribers are registered.
 */

export interface PushConfig {
  enabled: boolean;
  public_key: string | null;
  fcm_project_id: string | null;
}

let _cachedConfig: PushConfig | null = null;

export async function fetchPushConfig(): Promise<PushConfig> {
  if (_cachedConfig !== null) {
    return _cachedConfig;
  }
  const res = await fetch("/api/push/config");
  if (!res.ok) {
    const fallback: PushConfig = { enabled: false, public_key: null, fcm_project_id: null };
    _cachedConfig = fallback;
    return fallback;
  }
  const config = (await res.json()) as PushConfig;
  _cachedConfig = config;
  return config;
}

export async function registerSubscription(
  subscription: PushSubscriptionJSON
): Promise<{ subscription_id: string; status: string }> {
  const res = await fetch("/api/push/subscriptions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      endpoint: subscription.endpoint,
      keys_p256dh: subscription.keys?.p256dh ?? "",
      keys_auth: subscription.keys?.auth ?? "",
      user_agent: navigator.userAgent,
    }),
  });
  if (!res.ok) {
    throw new Error("Failed to register push subscription");
  }
  return res.json();
}

export async function disableSubscription(
  subscriptionId: string
): Promise<{ subscription_id: string; status: string }> {
  const res = await fetch(`/api/push/subscriptions/${subscriptionId}/disable`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error("Failed to disable push subscription");
  }
  return res.json();
}

function urlBase64ToArrayBuffer(base64String: string): ArrayBuffer {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const buffer = new ArrayBuffer(rawData.length);
  const outputArray = new Uint8Array(buffer);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return buffer;
}

export async function subscribeToPush(
  config: PushConfig
): Promise<{ subscription_id: string; status: string } | null> {
  if (!config.enabled || !config.public_key) return null;

  const registration = await navigator.serviceWorker.ready;
  let subscription = await registration.pushManager.getSubscription();
  if (subscription) {
    await subscription.unsubscribe();
  }

  subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToArrayBuffer(config.public_key),
  });

  const subJSON = subscription.toJSON();
  return registerSubscription(subJSON);
}
