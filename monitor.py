"""
ポケモンカード相場監視ツール (MVP)

監視対象のURLから価格を取得し、平均価格より一定以上安い商品を
Discordに通知する。
"""

import os
import re
import time
import logging
import statistics
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
load_dotenv()

DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
ALERT_THRESHOLD: float = float(os.getenv("ALERT_THRESHOLD", "0.20"))  # 20% 安い

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
}

# ─────────────────────────────────────────────
# 監視対象カードリスト
# card_name : 表示名
# search_url : メルカリ検索URL（キーワード検索）
# ─────────────────────────────────────────────
WATCH_LIST = [
    {
        "card_name": "リザードン ex SAR",
        "search_url": (
            "https://mercari.com/jp/search/"
            "?keyword=%E3%83%AA%E3%82%B6%E3%83%BC%E3%83%89%E3%83%B3+ex+SAR"
            "&status=on_sale&order=created_time&sort=created_time"
        ),
    },
    {
        "card_name": "ピカチュウ ex SAR",
        "search_url": (
            "https://mercari.com/jp/search/"
            "?keyword=%E3%83%94%E3%82%AB%E3%83%81%E3%83%A5%E3%82%A6+ex+SAR"
            "&status=on_sale&order=created_time&sort=created_time"
        ),
    },
    {
        "card_name": "イーブイヒーローズ イーブイ AR",
        "search_url": (
            "https://mercari.com/jp/search/"
            "?keyword=%E3%82%A4%E3%83%BC%E3%83%96%E3%82%A4+AR+%E3%82%A4%E3%83%BC%E3%83%96%E3%82%A4%E3%83%92%E3%83%BC%E3%83%AD%E3%83%BC%E3%82%BA"
            "&status=on_sale&order=created_time&sort=created_time"
        ),
    },
]


# ─────────────────────────────────────────────
# データクラス
# ─────────────────────────────────────────────
@dataclass
class Listing:
    """商品1件分の情報"""
    card_name: str
    price: int
    url: str
    title: str


# ─────────────────────────────────────────────
# スクレイピング
# ─────────────────────────────────────────────
def fetch_mercari_listings(card_name: str, search_url: str) -> list[Listing]:
    """
    メルカリ検索結果ページから商品リストを取得する。

    Notes:
        メルカリはSPA（React）のため、静的HTMLには価格が含まれない場合がある。
        ここでは公開APIエンドポイント（search API）を利用する代替手段を採用。
        ※ API仕様は変更される可能性があるため、失敗した場合はHTMLフォールバック。
    """
    listings: list[Listing] = []

    # メルカリ内部API経由で取得を試みる
    try:
        keyword = re.search(r"keyword=([^&]+)", search_url)
        if not keyword:
            logger.warning(f"[{card_name}] URLからキーワードを抽出できませんでした。")
            return listings

        keyword_decoded = requests.utils.unquote(keyword.group(1))
        api_url = "https://api.mercari.jp/v2/entities:search"
        payload = {
            "pageSize": 30,
            "pageToken": "",
            "searchSessionId": "dummy",
            "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
            "thumbnailTypes": [],
            "searchCondition": {
                "keyword": keyword_decoded,
                "excludeKeyword": "",
                "sort": "SORT_CREATED_TIME",
                "order": "ORDER_DESC",
                "status": ["STATUS_ON_SALE"],
                "categoryId": [],
                "brandId": [],
                "sellerId": [],
                "priceMin": 0,
                "priceMax": 0,
                "itemConditionId": [],
                "shippingPayerId": [],
                "shippingFromArea": [],
                "shippingMethod": [],
                "hasCoupon": False,
                "attributes": [],
                "itemTypes": [],
                "skuIds": [],
            },
            "userId": "",
            "withItemBrand": True,
            "withItemSize": False,
            "withItemPromotions": True,
            "withItemSizes": False,
            "withShops": False,
            "withOfferOptions": False,
        }
        api_headers = {
            **HEADERS,
            "X-Platform": "web",
            "Content-Type": "application/json; charset=utf8",
            "DPoP": "dummy",  # 実際には正しいトークンが必要
        }
        resp = requests.post(api_url, json=payload, headers=api_headers, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            for item in items:
                price = item.get("price", 0)
                item_id = item.get("id", "")
                title = item.get("name", "")
                item_url = f"https://jp.mercari.com/item/{item_id}"
                if price > 0:
                    listings.append(
                        Listing(
                            card_name=card_name,
                            price=int(price),
                            url=item_url,
                            title=title,
                        )
                    )
            logger.info(f"[{card_name}] API経由で {len(listings)} 件取得")
            return listings
        else:
            logger.warning(
                f"[{card_name}] API失敗 (status={resp.status_code})。HTMLフォールバックへ。"
            )

    except Exception as e:
        logger.warning(f"[{card_name}] API取得エラー: {e}。HTMLフォールバックへ。")

    # ── HTMLフォールバック ──
    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # メルカリHTMLの価格要素を探す（セレクターは変更される可能性あり）
        price_elements = soup.select("span[class*='price']")
        item_links = soup.select("a[data-testid='item-cell']")

        for link, price_el in zip(item_links, price_elements):
            price_text = price_el.get_text(strip=True).replace(",", "").replace("¥", "")
            try:
                price = int(re.sub(r"[^\d]", "", price_text))
                item_url = "https://jp.mercari.com" + link.get("href", "")
                title = link.get("aria-label", "不明")
                if price > 0:
                    listings.append(
                        Listing(
                            card_name=card_name,
                            price=price,
                            url=item_url,
                            title=title,
                        )
                    )
            except ValueError:
                continue

        logger.info(f"[{card_name}] HTML経由で {len(listings)} 件取得")

    except requests.RequestException as e:
        logger.error(f"[{card_name}] HTTPエラー: {e}")
    except Exception as e:
        logger.error(f"[{card_name}] スクレイピングエラー: {e}")

    return listings


# ─────────────────────────────────────────────
# 価格判定
# ─────────────────────────────────────────────
def find_bargains(listings: list[Listing], threshold: float = ALERT_THRESHOLD) -> list[tuple[Listing, float, float]]:
    """
    平均価格より threshold 以上安い商品を抽出する。

    Returns:
        List of (listing, avg_price, discount_rate)
    """
    if len(listings) < 3:
        logger.warning(f"サンプル数が少なすぎます ({len(listings)} 件)。スキップ。")
        return []

    prices = [l.price for l in listings]
    avg_price = statistics.mean(prices)
    logger.info(f"平均価格: ¥{avg_price:,.0f} (サンプル数: {len(prices)} 件)")

    bargains = []
    for listing in listings:
        discount = (avg_price - listing.price) / avg_price
        if discount >= threshold:
            bargains.append((listing, avg_price, discount))
            logger.info(
                f"  🎯 お買い得検出: {listing.title[:30]} "
                f"¥{listing.price:,} ({discount:.1%} 安)"
            )

    return bargains


# ─────────────────────────────────────────────
# Discord 通知
# ─────────────────────────────────────────────
def send_discord_alert(listing: Listing, avg_price: float, discount: float) -> bool:
    """Discord Webhook にアラートを送信する。"""
    if not DISCORD_WEBHOOK_URL:
        logger.error("DISCORD_WEBHOOK_URL が未設定です。")
        return False

    embed = {
        "title": "🚨 ポケカ お買い得アラート！",
        "color": 0xFF6347,  # トマト色
        "fields": [
            {"name": "カード名", "value": listing.card_name, "inline": False},
            {"name": "商品タイトル", "value": listing.title[:100], "inline": False},
            {"name": "出品価格", "value": f"¥{listing.price:,}", "inline": True},
            {"name": "平均価格", "value": f"¥{avg_price:,.0f}", "inline": True},
            {"name": "割引率", "value": f"{discount:.1%} 安", "inline": True},
            {"name": "URL", "value": listing.url, "inline": False},
        ],
        "footer": {"text": "ポケカ相場監視ツール"},
    }

    payload = {"embeds": [embed]}

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            logger.info(f"Discord通知送信成功: {listing.title[:30]}")
            return True
        else:
            logger.error(f"Discord通知失敗 (status={resp.status_code}): {resp.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"Discord通知エラー: {e}")
        return False


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────
def main() -> None:
    logger.info("=== ポケカ相場監視ツール 起動 ===")

    if not DISCORD_WEBHOOK_URL:
        logger.warning("⚠️  DISCORD_WEBHOOK_URL が未設定のため、通知はスキップされます。")

    total_alerts = 0

    for card in WATCH_LIST:
        card_name = card["card_name"]
        search_url = card["search_url"]

        logger.info(f"--- [{card_name}] 監視開始 ---")

        # 価格取得
        listings = fetch_mercari_listings(card_name, search_url)

        if not listings:
            logger.warning(f"[{card_name}] 商品が取得できませんでした。スキップ。")
            time.sleep(2)
            continue

        # お買い得判定
        bargains = find_bargains(listings)

        # Discord通知
        for listing, avg_price, discount in bargains:
            send_discord_alert(listing, avg_price, discount)
            total_alerts += 1
            time.sleep(1)  # レート制限対策

        # 過負荷防止のため次のカードまで少し待つ
        time.sleep(3)

    logger.info(f"=== 監視完了 (アラート送信数: {total_alerts}) ===")


if __name__ == "__main__":
    main()
