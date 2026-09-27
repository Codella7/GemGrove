# WhatsApp purchase-payment reminders

GemGrove sends each unpaid `Purchase` reminder to the buyer's registered WhatsApp number one day before the payment due date. If the scheduled run was missed, it retries on the due date or later. A sent reminder is recorded on the ledger entry so it is not sent twice.

## 1. Create a permanent Meta token

Do not use the temporary token from the WhatsApp API Setup page for automation.

In Meta Business Settings:

1. Open **Users** > **System users**, add a system user with admin access, and assign it to the WhatsApp Business Account that owns the sending phone number.
2. Generate a token for the Meta app used by GemGrove.
3. Select the `whatsapp_business_messaging` and `whatsapp_business_management` permissions.
4. Copy the token once and store it in a password manager. Never put it in this repository or a source file.

The Meta app and WhatsApp Business Account must be in Live mode before sending to real users. Obtain each recipient's clear WhatsApp opt-in before sending a reminder.

## 2. Save settings for this Windows user

Run the following in PowerShell, replacing only the token. `setx` makes the values available to future PowerShell windows and scheduled tasks; it does not change the current window.

```powershell
setx WHATSAPP_ACCESS_TOKEN "PASTE_PERMANENT_TOKEN_HERE"
setx WHATSAPP_PHONE_NUMBER_ID "1355945257595042"
setx WHATSAPP_TEMPLATE_NAME "purchase_payment_due"
setx WHATSAPP_TEMPLATE_LANGUAGE "en"
```

Open a **new** PowerShell window after running those commands. Confirm the configured values without revealing the token:

```powershell
$env:WHATSAPP_ACCESS_TOKEN.Length
$env:WHATSAPP_PHONE_NUMBER_ID
$env:WHATSAPP_TEMPLATE_NAME
$env:WHATSAPP_TEMPLATE_LANGUAGE
```

## 3. Test

```powershell
Set-Location D:\GemGrove\GemGrove
.\run-reminders.ps1
```

Read the outcome in `logs\whatsapp-reminders.log`. Remove the explicitly labelled test entries after successful testing.

## 4. Schedule the daily run

Create a Windows Task Scheduler task that runs as the same Windows user that owns the environment variables.

- Trigger: Daily, at the desired reminder time (for example, 09:00).
- Program: `powershell.exe`
- Arguments: `-NoProfile -ExecutionPolicy Bypass -File "D:\GemGrove\GemGrove\run-reminders.ps1"`
- Start in: `D:\GemGrove\GemGrove`

Run the task manually once from Task Scheduler and check `logs\whatsapp-reminders.log` before relying on it.

## Push notifications for the app

GemGrove can also be installed on a phone's home screen and send a private push alert to each subscribed device when that account has unpaid payments due today. Push runs separately from WhatsApp. The website must use HTTPS (or localhost during development), and the browser must support Web Push. On iPhone/iPad, add the site to the Home Screen and open that installed app before enabling notifications (iOS/iPadOS 16.4 or newer).

### Configure push delivery

Install dependencies in the same Python environment used to run GemGrove:
Install dependencies in GemGrove's virtual environment (the scheduler uses it automatically when it exists):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Generate a VAPID key pair using the `web-push` command-line tool (`npm install -g web-push`, then `web-push generate-vapid-keys`). Keep the private key secret. Save the values for the Windows user that runs the app and its scheduled task:

```powershell
setx VAPID_PUBLIC_KEY "PASTE_PUBLIC_KEY_HERE"
setx VAPID_PRIVATE_KEY "PASTE_PRIVATE_KEY_HERE"
setx VAPID_SUBJECT "mailto:you@example.com"
```

Restart the app after setting these values. Each user enables notifications on each phone/browser from **Reminders**. Schedule `run-push-reminders.ps1` daily at the desired local time in Windows Task Scheduler, using the same Windows account as the app's VAPID environment variables. Set **Start in** to the GemGrove project directory. The script records results in `logs\push-reminders.log`; successful devices are not sent a second alert that day.
Open a new PowerShell window after setting the values, then restart GemGrove so it reads the new environment. Each user enables notifications on each phone/browser from **Reminders**. For an immediate test, create an unpaid entry due today, enable notifications in the browser, and run:

```powershell
.\run-push-reminders.ps1
```

Schedule that same script daily at the desired local time in Windows Task Scheduler, using the same Windows account. Program: `powershell.exe`. Arguments: `-NoProfile -ExecutionPolicy Bypass -File "D:\GemGrove - Copy\GemGrove\run-push-reminders.ps1"`. Set **Start in** to `D:\GemGrove - Copy\GemGrove`. Keep the computer awake and GemGrove's environment configured; the script records results in `logs\push-reminders.log`. Successful devices are not sent a second alert that day.

### Install on a phone

Open GemGrove in the phone's browser over HTTPS. Use the browser's **Install app** prompt where available. On iPhone/iPad, use **Share** > **Add to Home Screen**, launch GemGrove from its new icon, then enable notifications on the Reminders page.
