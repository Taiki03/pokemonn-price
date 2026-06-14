"""
Discord Webhook 通知モジュール

アービトラージアラートをDiscordのEmbedで送信する。
"""
import logging

import requests

from models import ArbitrageAlert, AlertLevel
from config import DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)

# Embedカラー
COLOR_HOT  = 0xFF4444  # 赤
COLOR_WARM = 0xFFAA00  # オレンジ


def send_alert(alert: ArbitrageAlert) -> bool:
    """
    Discord Webhook にアラートを送信する。

    Returns:
        True: 送信成功 / False: 失敗
    """
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL が未設定。通知をスキップします。")
        return False

    ref  = alert.reference
    lst  = alert.listing
    is_hot = alert.alert_level == AlertLevel.HOT

    # 参照価格の表示（型番・買取・販売）
    ref_price_lines = []
    if ref.model_number:
        ref_price_lines.append(f"型番: **{ref.model_number}**")
    if ref.buy_price:
        ref_price_lines.append(f"買取価格: **¥{ref.buy_price:,}**")
    if ref.sell_price:
        ref_price_lines.append(f"販売価格: ¥{ref.sell_price:,}")
    ref_price_text = "\n".join(ref_price_lines) if ref_price_lines else "不明"

    embed = {
        "title": (
            f"{alert.alert_level.value}  {alert.card_name}"
            + (f"【{ref.model_number}】" if ref.model_number else "")
        ),
        "color":       COLOR_HOT if is_hot else COLOR_WARM,
        "description": (
            f"推定利益 **¥{alert.profit_estimate:,}**（買取価格の "
            f"**{alert.discount_rate:.0%}** 安）"
        ),
        "fields": [
            {
                "name":   "📦 出品情報",
                "value":  f"[{lst.title[:60]}]({lst.url})\n出品価格: **¥{lst.price:,}**",
                "inline": False,
            },
            {
                "name":   "📊 カードラッシュ基準価格",
                "value":  ref_price_text,
                "inline": True,
            },
            {
                "name":   "🔗 カードラッシュ",
                "value":  f"[価格を確認]({ref.source_url})",
                "inline": True,
            },
        ],
        "footer": {"text": "ポケカ アービトラージスキャナー"},
        "thumbnail": {"url": lst.thumbnail} if lst.thumbnail else {},
    }

    # 空のthumbnailを除去
    if not embed["thumbnail"]:
        del embed["thumbnail"]

    payload = {
        "content": "@here" if is_hot else "",
        "embeds":  [embed],
    }

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            logger.info(f"[Discord] 通知送信: {alert.card_name} ¥{lst.price:,}")
            return True
        else:
            logger.error(f"[Discord] 送信失敗 status={resp.status_code}: {resp.text[:200]}")
            return False
    except requests.RequestException as e:
        logger.error(f"[Discord] 通信エラー: {e}")
        return False
