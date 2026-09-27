"""Direct delivery through Meta's official WhatsApp Cloud API (no Twilio)."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def send_reminder(entry, whatsapp_number, overdue=False):
    """Send a due-purchase template to a registered WhatsApp number.

    The configured Meta template must define these body variables in order:
    {{1}} seller, {{2}} gemstone, {{3}} amount, {{4}} due date.
    """
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    template_name = os.getenv("WHATSAPP_TEMPLATE_NAME")
    api_version = os.getenv("WHATSAPP_GRAPH_API_VERSION", "v23.0")
    # The approved purchase_payment_due template is saved in WhatsApp Manager
    # under the generic English locale, whose Cloud API language code is `en`.
    language = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en")
    if not all((access_token, phone_number_id, template_name)):
        raise RuntimeError("WhatsApp is not configured. Set WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, and WHATSAPP_TEMPLATE_NAME.")

    payload = {
        "messaging_product": "whatsapp",
        "to": whatsapp_number.lstrip("+"),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": entry.customer_name},
                {"type": "text", "text": entry.product_name},
                {"type": "text", "text": f"{entry.currency or 'INR'} {entry.total_price:,.2f}"},
                {"type": "text", "text": f"OVERDUE - {entry.due_date.strftime('%d %b %Y')}" if overdue else entry.due_date.strftime("%d %b %Y")},
            ]}],
        },
    }
    request = Request(
        f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = ""
        try:
            response_body = json.loads(error.read().decode("utf-8"))
            detail = response_body.get("error", {}).get("message", "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Meta WhatsApp API rejected the reminder ({error.code}){suffix}") from error
    except URLError as error:
        raise RuntimeError("Could not reach Meta's WhatsApp API.") from error
    return result["messages"][0]["id"]
