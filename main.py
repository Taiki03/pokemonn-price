"""
ポケカ アービトラージスキャナー - メインスクリプト

処理フロー:
  cards.csv を読み込む
    ↓
  カードごとに:
    1. カードラッシュから基準価格（買取・販売）を取得
    2. メルカリから出品リストを取得
    3. 閾値以下の価格の出品を検出
    4. Discordに通知
"""
import logging
import sys
import time
from typing import Optional, Tuple

from config import (
    HOT_THRESHOLD,
    WARM_THRESHOLD,
    SLEEP_BETWEEN_CARDS,
    load_cards,
)
from models import ArbitrageAlert, AlertLevel, MercariListing, ReferencePrice
from scrapers.cardrush import fetch_reference_price
from scrapers.mercari import fetch_mercari_listings
from notifiers.discord import send_alert

# ─── ログ設定 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def evaluate_listing(
    listing: MercariListing,
    ref: ReferencePrice,
) -> Optional[ArbitrageAlert]:
    """
    1件の出品が HOT/WARM 閾値に当てはまるか判定する。

    基準価格には買取価格を優先し、なければ販売価格を使用。
    """
    base_price = ref.buy_price or ref.sell_price
    if not base_price:
        return None

    # 割引率: 1.0 = 同額, 0.5 = 50%安
    discount = 1.0 - (listing.price / base_price)

    if discount >= (1.0 - HOT_THRESHOLD):    # 買取価格の50%以下
        level = AlertLevel.HOT
    elif discount >= (1.0 - WARM_THRESHOLD):  # 買取価格の70%以下
        level = AlertLevel.WARM
    else:
        return None

    profit = base_price - listing.price  # 粗利（送料等未考慮）

    return ArbitrageAlert(
        card_name       = ref.card_name,
        listing         = listing,
        reference       = ref,
        alert_level     = level,
        profit_estimate = profit,
        discount_rate   = discount,
    )


def process_card(card: dict) -> int:
    """
    1枚のカードを処理し、送信したアラート数を返す。
    """
    card_name       = card["card_name"]
    cardrush_name   = card["cardrush_name"]
    cardrush_rarity = card.get("cardrush_rarity", "")
    mercari_keyword = card["mercari_keyword"]

    logger.info(f"━━ [{card_name}] 処理開始 ━━")

    # ① 基準価格取得（カードラッシュ）
    ref = fetch_reference_price(card_name, cardrush_name, cardrush_rarity)
    if ref is None:
        logger.warning(f"  [{card_name}] カードラッシュ価格取得失敗 → スキップ")
        return 0

    logger.info(
        f"  基準価格: 買取=¥{ref.buy_price:,}" if ref.buy_price else "  基準価格: 買取=不明"
    )

    # ② メルカリ出品取得
    listings = fetch_mercari_listings(card_name, mercari_keyword)
    if not listings:
        logger.warning(f"  [{card_name}] メルカリ出品取得失敗 → スキップ")
        return 0

    logger.info(f"  メルカリ出品: {len(listings)} 件取得")

    # ③ アラート判定 & 通知
    alert_count = 0
    for listing in listings:
        alert = evaluate_listing(listing, ref)
        if alert:
            logger.info(
                f"  {alert.alert_level.value}: ¥{listing.price:,} "
                f"(推定利益 ¥{alert.profit_estimate:,})"
            )
            send_alert(alert)
            alert_count += 1
            time.sleep(1)  # Discord レート制限対策

    return alert_count



def main() -> None:
    logger.info("=" * 50)
    logger.info("  ポケカ アービトラージスキャナー 起動")
    logger.info("=" * 50)

    # カードリスト読み込み
    try:
        cards = load_cards()
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    logger.info(f"監視対象: {len(cards)} 枚")

    total_alerts = 0
    for i, card in enumerate(cards):
        alerts = process_card(card)
        total_alerts += alerts

        # 最後のカード以外はウェイト
        if i < len(cards) - 1:
            time.sleep(SLEEP_BETWEEN_CARDS)

    logger.info("=" * 50)
    logger.info(f"  完了: アラート送信数 = {total_alerts}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
