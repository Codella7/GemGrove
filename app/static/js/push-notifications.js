const pushButton = document.getElementById("push-toggle");
const pushStatus = document.getElementById("push-status");

function setPushStatus(message) {
  if (pushStatus) pushStatus.textContent = message;
}

function decodeVapidKey(encodedKey) {
  const padding = "=".repeat((4 - encodedKey.length % 4) % 4);
  const base64 = (encodedKey + padding).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(base64), (character) => character.charCodeAt(0));
}

async function syncButtonLabel(registration) {
  const subscription = await registration.pushManager.getSubscription();
  pushButton.textContent = subscription ? "Turn off notifications" : "Enable notifications";
}

async function togglePushNotifications() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    setPushStatus("Push notifications are not supported by this browser.");
    return;
  }

  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  if (existing) {
    const response = await fetch("/push/subscriptions", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: existing.endpoint })
    });
    if (!response.ok) throw new Error("Could not update this device's notification settings.");
    await existing.unsubscribe();
    setPushStatus("Notifications are off for this device.");
    await syncButtonLabel(registration);
    return;
  }

  const keyResponse = await fetch("/push/vapid-public-key");
  const keyData = await keyResponse.json();
  if (!keyResponse.ok) throw new Error(keyData.error || "Push notifications are not configured.");

  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    setPushStatus(permission === "denied"
      ? "Notifications are blocked in your browser settings."
      : "Notification permission was not granted.");
    return;
  }

  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: decodeVapidKey(keyData.publicKey)
  });
  const saveResponse = await fetch("/push/subscriptions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription)
  });
  if (!saveResponse.ok) {
    await subscription.unsubscribe();
    const errorData = await saveResponse.json();
    throw new Error(errorData.error || "Could not save this device.");
  }
  setPushStatus("This device will alert you when a payment is due today.");
  await syncButtonLabel(registration);
}

if (pushButton) {
  pushButton.addEventListener("click", () => {
    pushButton.disabled = true;
    togglePushNotifications()
      .catch((error) => setPushStatus(error.message || "Could not update notification settings."))
      .finally(() => { pushButton.disabled = false; });
  });
  navigator.serviceWorker?.ready
    .then(syncButtonLabel)
    .catch(() => setPushStatus("Open GemGrove online to set up notifications."));
}