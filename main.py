"""
ポケカ アービトラージスキャナー - メインスクリプト

処理フロー（ダイナミックモード）:
  1. カードラッシュから SAR/AR 全カードを一括取得
  2. cards.csv の手動追加カードもマージ
  3. カードごとに:
     - メルカリで出品リストを取得
     - 買取価格の50%以下のものを検出
     - タイトル・説明文に傷あり等のキーワードがないか確認
     - Discordに通知
"""
import logging
import re
import sys
import time
from typing import Optional

from config import (
    HOT_THRESHOLD,
    SLEEP_BETWEEN_CARDS,
    EXCLUSION_KEYWORDS,
    load_cards,
)
from models import ArbitrageAlert, AlertLevel, MercariListing, ReferencePrice
from scrapers.cardrush import fetch_all_cards_bulk
from scrapers.mercari import fetch_mercari_listings, fetch_item_description
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
    1件の出品が HOT 閾値（買取価格の50%以下）に当てはまるか判定する。
    """
    base_price = ref.buy_price or ref.sell_price
    if not base_price:
        return None

    discount = 1.0 - (listing.price / base_price)

    if discount >= (1.0 - HOT_THRESHOLD):
        level = AlertLevel.HOT
    else:
        return None

    profit = base_price - listing.price

    return ArbitrageAlert(
        card_name       = ref.card_name,
        listing         = listing,
        reference       = ref,
        alert_level     = level,
        profit_estimate = profit,
        discount_rate   = discount,
    )


def build_reference(card: dict) -> ReferencePrice:
    """
    カード情報（バルク取得 or CSV）から ReferencePrice を生成する。
    バルク取得済みの場合は追加API不要。
    """
    return ReferencePrice(
        card_name    = card["card_name"],
        buy_price    = card.get("buy_price"),
        sell_price   = None,
        model_number = card.get("model_number", ""),
        source_url   = (
            f"https://cardrush.media/pokemon/buying_prices"
            f"?name={card['cardrush_name']}"
        ),
    )


def process_card(card: dict) -> int:
    """
    1枚のカードを処理し、送信したアラート数を返す。
    """
    card_name       = card["card_name"]
    mercari_keyword = card["mercari_keyword"]
    cardrush_name   = card["cardrush_name"]
    target_rarity   = card.get("cardrush_rarity", "").upper()
    model_number    = card.get("model_number", "")

    logger.info(f"━━ [{card_name}] ¥{card.get('buy_price', '?'):,} ━━")

    # ① 基準価格（バルク取得済みのデータを使用、追加API不要）
    ref = build_reference(card)
    if not ref.buy_price:
        logger.warning(f"  [{card_name}] 買取価格不明 → スキップ")
        return 0

    # ② メルカリ出品取得
    listings = fetch_mercari_listings(card_name, mercari_keyword)
    if not listings:
        return 0

    # ③ アラート判定 → ④ 厳密なカード判定 → ⑤ 通知
    alert_count = 0
    for listing in listings:
        alert = evaluate_listing(listing, ref)
        if not alert:
            continue

        title_lower = listing.title.lower()

        # ── 1. タイトルの除外キーワードチェック（傷あり、折れなど） ──
        if any(kw in listing.title for kw in EXCLUSION_KEYWORDS):
            logger.info(f"  除外(タイトル傷): {listing.title[:40]}")
            continue

        # ── 2. カード名チェック ──
        # メルカリの曖昧検索対策。カード名（exを除く主要部分）が含まれているか
        name_clean = cardrush_name.lower().replace("ex", "").strip()
        if name_clean not in title_lower:
            logger.info(f"  除外(カード名不一致): {listing.title[:40]} (検索: {cardrush_name})")
            continue

        # ── 3. レアリティ不一致チェック ──
        # 対象が SAR で、タイトルに RR, SR, UR, HR, R, U, C など別のレアリティのみが書かれており、
        # かつ SAR という文字が一切ない場合は除外
        all_rarities = ["SAR", "AR", "SR", "UR", "HR", "RR", "TR", "CHR", "CSR"]
        other_rarities = [r for r in all_rarities if r != target_rarity]
        has_target_rarity = target_rarity.lower() in title_lower
        has_other_rarity = any(f" {r.lower()} " in f" {title_lower} " or r.lower() in title_lower for r in other_rarities)
        if target_rarity and not has_target_rarity and has_other_rarity:
            logger.info(f"  除外(レアリティ不一致): {listing.title[:40]} (Target: {target_rarity})")
            continue

        # ── 4. 型番チェック ──
        if model_number:
            nums = re.findall(r"\d+", model_number)
            if nums:
                # nums=['201', '165'] -> r"201[\s\-/]*165"
                pattern = r"[\s\-/]*".join(nums)
                
                # ① まずタイトルでチェック
                if re.search(pattern, title_lower):
                    # タイトルに含まれていれば型番チェック通過
                    pass
                else:
                    # ② タイトルになければ説明文を取得してチェック
                    item_id = listing.url.split("/")[-1]
                    description = fetch_item_description(item_id).lower()
                    
                    # 説明文に傷ありキーワードがあれば除外
                    if description and any(kw in description for kw in EXCLUSION_KEYWORDS):
                        logger.info(f"  除外(説明文傷): {listing.title[:40]}")
                        continue
                        
                    # 型番チェック
                    if not description or not re.search(pattern, description):
                        logger.info(f"  除外(型番不一致): {listing.title[:40]} (型番: {model_number})")
                        continue
            else:
                # 型番がない場合は、説明文の傷キーワードチェックだけ行う
                item_id = listing.url.split("/")[-1]
                description = fetch_item_description(item_id).lower()
                if description and any(kw in description for kw in EXCLUSION_KEYWORDS):
                    logger.info(f"  除外(説明文傷): {listing.title[:40]}")
                    continue
        else:
            # 型番がない場合は、説明文の傷キーワードチェックだけ行う
            item_id = listing.url.split("/")[-1]
            description = fetch_item_description(item_id).lower()
            if description and any(kw in description for kw in EXCLUSION_KEYWORDS):
                logger.info(f"  除外(説明文傷): {listing.title[:40]}")
                continue

        logger.info(
            f"  🔴 ¥{listing.price:,} → 推定利益 ¥{alert.profit_estimate:,}"
        )
        send_alert(alert)
        alert_count += 1
        time.sleep(1)

    return alert_count


def main() -> None:
    logger.info("=" * 55)
    logger.info("  ポケカ アービトラージスキャナー 起動")
    logger.info("=" * 55)

    # ① カードラッシュから SAR/AR 全カードを一括取得
    logger.info("📥 カードラッシュからカードリストを取得中...")
    bulk_cards = fetch_all_cards_bulk()

    # ② cards.csv の手動追加カードをマージ（重複は除外）
    try:
        csv_cards = load_cards()
        # バルク取得済みのカード名と被らないものだけ追加
        bulk_names = {c["card_name"] for c in bulk_cards}
        extra_cards = []
        for c in csv_cards:
            if c["card_name"] not in bulk_names:
                # CSV形式のカードも buy_price を取得する必要あり
                from scrapers.cardrush import fetch_reference_price
                ref = fetch_reference_price(
                    c["card_name"], c["cardrush_name"], c.get("cardrush_rarity", "")
                )
                if ref and ref.buy_price:
                    c["buy_price"]    = ref.buy_price
                    c["model_number"] = ref.model_number
                    extra_cards.append(c)
        if extra_cards:
            logger.info(f"📋 cards.csv から {len(extra_cards)} 件追加")
    except FileNotFoundError:
        extra_cards = []

    all_cards = bulk_cards + extra_cards
    logger.info(f"📊 スキャン対象: 合計 {len(all_cards)} 件")
    logger.info("=" * 55)

    # ③ 各カードをスキャン
    total_alerts = 0
    for i, card in enumerate(all_cards, 1):
        logger.info(f"[{i}/{len(all_cards)}]")
        alerts = process_card(card)
        total_alerts += alerts
        time.sleep(SLEEP_BETWEEN_CARDS)

    logger.info("=" * 55)
    logger.info(f"  完了: アラート送信数 = {total_alerts}")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
