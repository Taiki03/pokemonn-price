"""
カードラッシュ スクレイパー（cardrush.media 版）

cardrush.media の買取表ページに埋め込まれた __NEXT_DATA__ JSON から
買取価格を取得する。

取得URL: https://cardrush.media/pokemon/buying_prices
データ場所: <script id="__NEXT_DATA__"> → props.pageProps.buyingPrices
"""
import json
import logging
import re
import urllib.parse
from typing import Optional

import requests

from models import ReferencePrice
from config import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

BASE_URL = "https://cardrush.media/pokemon/buying_prices"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
}

# 検索時に使うカテゴリ（全カテゴリ対象）
SEARCH_PARAMS = {
    "limit": "100",
    "page": "1",
    "sort[key]": "amount",
    "sort[order]": "desc",
    "display_category[]": ["最新弾", "スタンダード", "エクストラ", "旧裏"],
    "is_hot[]": ["true", "false"],
}


def _build_url(keyword: str) -> str:
    """検索URL を組み立てる。"""
    parts = [
        ("limit", "100"),
        ("page", "1"),
        ("name", keyword),
        ("sort[key]", "amount"),
        ("sort[order]", "desc"),
        ("display_category[]", "最新弾"),
        ("display_category[]", "スタンダード"),
        ("display_category[]", "エクストラ"),
        ("display_category[]", "旧裏"),
        ("is_hot[]", "true"),
        ("is_hot[]", "false"),
    ]
    return BASE_URL + "?" + urllib.parse.urlencode(parts)


def _extract_next_data(html: str) -> Optional[dict]:
    """HTMLから __NEXT_DATA__ JSONを抽出する。"""
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _find_best_match(buying_prices: list, name: str, rarity: str = "") -> Optional[dict]:
    """
    買取価格リストから name/rarity に最も一致するカードを探す。

    Args:
        buying_prices: Card Rush から取得した買取価格リスト
        name:    カード名（例: 'リザードンex'）
        rarity:  レアリティ（例: 'SAR', 'AR', 'SR' など。空文字列なら無視）
    """
    name_lower = name.lower().replace(" ", "").replace("　", "")

    # ── Step1: name でフィルタ ──────────────────────────
    name_matches = []
    for item in buying_prices:
        item_name = item.get("name", "").lower().replace(" ", "")
        if item_name == name_lower or name_lower in item_name:
            name_matches.append(item)

    if not name_matches:
        # ひらがな変換して再試行
        kw_hira = _kata_to_hira(name_lower)
        for item in buying_prices:
            if kw_hira in item.get("searchable_name", ""):
                name_matches.append(item)

    if not name_matches:
        return None

    # ── Step2: rarity でフィルタ ──────────────────────────
    if rarity:
        rarity_matches = [
            item for item in name_matches
            if item.get("rarity", "").upper() == rarity.upper()
        ]
        if rarity_matches:
            # extra_difference が空（特殊条件なし）を優先し、価格の高い順
            rarity_matches.sort(key=lambda x: (
                0 if not x.get("extra_difference") else 1,
                -x.get("amount", 0)
            ))
            return rarity_matches[0]

    # rarity フィルタ後も見つからない場合は name のみマッチで最高価格を返す
    name_matches.sort(key=lambda x: (
        0 if not x.get("extra_difference") else 1,
        -x.get("amount", 0)
    ))
    return name_matches[0]


def _kata_to_hira(text: str) -> str:
    """カタカナをひらがなに変換する。"""
    return "".join(
        chr(ord(c) - 0x60) if "ァ" <= c <= "ン" else c
        for c in text
    )


def fetch_reference_price(card_name: str, name: str, rarity: str = "") -> Optional[ReferencePrice]:
    """
    カードラッシュから買取価格を取得する。

    Args:
        card_name: 表示用カード名（ログ用）
        name:      Card Rush 上のカード名（例: 'リザードンex'）
        rarity:    レアリティフィルタ（例: 'SAR', 'AR', '' = フィルタなし）

    Returns:
        ReferencePrice or None（取得失敗時）
    """
    url = _build_url(name)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"[CardRush][{card_name}] HTTPエラー: {e}")
        return None

    # __NEXT_DATA__ を抽出
    next_data = _extract_next_data(resp.text)
    if not next_data:
        logger.error(f"[CardRush][{card_name}] __NEXT_DATA__ が見つかりません")
        return None

    # buyingPrices を取得
    buying_prices = (
        next_data
        .get("props", {})
        .get("pageProps", {})
        .get("buyingPrices", [])
    )

    if not buying_prices:
        logger.warning(f"[CardRush][{card_name}] 検索結果が0件 (name='{name}')")
        return None

    # 最適マッチを探す（rarity でフィルタあり）
    match = _find_best_match(buying_prices, name, rarity)
    if not match:
        logger.warning(f"[CardRush][{card_name}] 該当カードが見つかりません (name='{name}', rarity='{rarity}')")
        return None

    buy_price    = match.get("amount")
    matched_name = match.get("name", "")
    matched_rar  = match.get("rarity", "")
    model_number = match.get("model_number", "")

    logger.info(
        f"[CardRush][{card_name}] "
        f"マッチ: '{matched_name}' ({matched_rar}) "
        f"型番: {model_number} "
        f"買取: ¥{buy_price:,}"
    )

    return ReferencePrice(
        card_name    = card_name,
        buy_price    = buy_price,
        sell_price   = None,
        model_number = model_number,
        source_url   = (
            f"https://cardrush.media/pokemon/buying_prices"
            f"?name={urllib.parse.quote(name)}"
        ),
    )

