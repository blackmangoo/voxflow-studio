import os
import requests
from typing import Any, Dict, Optional


def send_whatsapp_verification_ping(
    wa_token: str,
    wa_user_id: str,
    user_email: str = "",
) -> Dict[str, Any]:
    """
    Sends a live verification test message to the user's own WhatsApp number/ID
    when they paste their key in the Studio Workspace, before asking them to confirm receipt.
    """
    clean_token = (wa_token or "").strip()
    clean_uid = (wa_user_id or "").strip()
    if not clean_token or not clean_uid:
        return {"ok": False, "status_code": 400, "detail": "Both WhatsApp Agent Token and User ID are required."}

    url = "https://api.whatsapp.com/agent/v1/messages"
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json",
    }
    account_line = f" for *{user_email}*" if user_email else ""
    body_text = (
        f"✅ *VoxFlow Studio — WhatsApp Verification*\n\n"
        f"This is a live test message{account_line}.\n"
        f"If you received this on your WhatsApp, click *'Yes, I received it'* in your Studio Workspace to activate automatic video completion alerts on this number."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_uid,
        "type": "text",
        "text": {"body": body_text},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code in (200, 201):
            return {"ok": True, "status_code": resp.status_code, "detail": "Verification message dispatched to WhatsApp."}
        return {
            "ok": False,
            "status_code": resp.status_code,
            "detail": f"WhatsApp API returned {resp.status_code}: {resp.text[:180]}",
        }
    except Exception as e:
        return {"ok": False, "status_code": 502, "detail": f"Connection error: {str(e)[:160]}"}


def send_whatsapp_agent_notification(
    title: str,
    concept: str,
    channel: str,
    video_path: str,
    hashtags: list = None,
    drive_folder_url: str = "",
    wa_token: Optional[str] = None,
    wa_user_id: Optional[str] = None,
    allow_env_fallback: bool = True,
):
    """
    Sends a WhatsApp notification using the Native WhatsApp Agent API.
    CRITICAL MULTI-TENANT RULE:
      - When `allow_env_fallback=False` (client account render), it NEVER uses
        os.environ['WA_AGENT_TOKEN'] or os.environ['WA_USER_ID'] (the Founder's phone).
      - It only dispatches if the client has verified their own `wa_token` and `wa_user_id`.
    """
    if allow_env_fallback:
        token = (wa_token or os.environ.get("WA_AGENT_TOKEN", "")).strip()
        recipient_id = (wa_user_id or os.environ.get("WA_USER_ID", "")).strip()
    else:
        token = (wa_token or "").strip()
        recipient_id = (wa_user_id or "").strip()

    if not token or not recipient_id or recipient_id == "YOUR_USER_ID_HERE":
        print("    [WhatsApp Agent] Skipped: No verified WhatsApp credentials configured for this user.")
        return

    url = "https://api.whatsapp.com/agent/v1/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    hashtag_block = " ".join(hashtags) if hashtags else ""
    drive_line = f"\n\n📂 *Drive / Video Link:* {drive_folder_url}" if drive_folder_url else ""

    message_text = (
        f"✅ *New AI Video Ready!*\n\n"
        f"📺 *Channel:* {channel.replace('_', ' ').title()}\n"
        f"🎬 *Title:* {title}\n"
        f"💡 *Concept:* {concept}"
        f"{drive_line}\n\n"
        f"📋 *Copy-paste hashtags:*\n{hashtag_block}"
    )

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_id,
        "type": "text",
        "text": {"body": message_text},
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=12)
        if response.status_code in [200, 201]:
            print(f"    [WhatsApp] Notification sent to {recipient_id}!")
        else:
            print(f"    [WhatsApp] Failed to send: {response.text[:180]}")
    except Exception as e:
        print(f"    [WhatsApp] Error sending notification: {e}")


def send_discord_webhook(
    title: str,
    concept: str,
    channel: str,
    video_path: str,
    hashtags: list = None,
    drive_folder_url: str = "",
):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        return
    drive_field = [{"name": "📂 Drive", "value": drive_folder_url, "inline": False}] if drive_folder_url else []
    embed = {
        "title": "🎉 New AI Video Rendered",
        "color": 5814783,
        "fields": [
            {"name": "📺 Channel", "value": channel.replace("_", " ").title(), "inline": True},
            {"name": "🎬 Title", "value": title, "inline": False},
            {"name": "💡 Concept", "value": concept, "inline": False},
        ]
        + drive_field,
    }
    try:
        requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        print("    [Discord] Log embedded successfully!")
    except Exception as e:
        print(f"    [Discord] Error sending webhook: {e}")


def send_telegram_notification(
    title: str,
    concept: str,
    channel: str,
    video_path: str,
    hashtags: list = None,
    drive_folder_url: str = "",
):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return

    drive_line = f"\n📂 [Open in Drive]({drive_folder_url})" if drive_folder_url else ""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": (
            f"✅ *New AI Video Ready!*\n\n"
            f"📺 *Channel:* {channel.replace('_', ' ').title()}\n"
            f"🎬 *Title:* {title}\n"
            f"💡 *Concept:* {concept}"
            f"{drive_line}"
        ),
        "parse_mode": "Markdown",
    }
    try:
        requests.post(url, json=payload, timeout=10)
        print("    [Telegram] Notification sent successfully!")
    except Exception as e:
        print(f"    [Telegram] Error sending notification: {e}")


def notify_all(
    title: str,
    concept: str,
    channel: str,
    video_path: str,
    hashtags: list = None,
    drive_folder_url: str = "",
    wa_token: Optional[str] = None,
    wa_user_id: Optional[str] = None,
    allow_env_fallback: bool = True,
):
    """Fires configured notifications, isolating WhatsApp per user when allow_env_fallback=False."""
    send_whatsapp_agent_notification(
        title,
        concept,
        channel,
        video_path,
        hashtags,
        drive_folder_url,
        wa_token=wa_token,
        wa_user_id=wa_user_id,
        allow_env_fallback=allow_env_fallback,
    )
    if allow_env_fallback:
        send_discord_webhook(title, concept, channel, video_path, hashtags, drive_folder_url)
        send_telegram_notification(title, concept, channel, video_path, hashtags, drive_folder_url)


if __name__ == "__main__":
    notify_all("Test Video", "This is a test notification", "body_simulator", "C:/test/video.mp4")
