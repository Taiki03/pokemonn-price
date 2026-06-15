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
import time
import urllib.parse
from typing import Optional

import requests

from models import ReferencePrice
from config import REQUEST_TIMEOUT, TARGET_RARITIES, MIN_BUY_PRICE

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


# ──────────────────────────────────────────────────────────
# ダイナミックスキャン用：全カード一括取得
# ──────────────────────────────────────────────────────────

def fetch_all_cards_bulk(
    rarities: list = None,
    min_price: int = None,
) -> list:
    """
    カードラッシュから対象レアリティの全カードを一括取得する。

    同名・同レアリティが複数ある場合は最高買取価格のエントリを採用。

    Args:
        rarities:  対象レアリティリスト（デフォルト: config.TARGET_RARITIES）
        min_price: 最低買取価格（デフォルト: config.MIN_BUY_PRICE）

    Returns:
        [{'card_name', 'cardrush_name', 'cardrush_rarity',
          'model_number', 'buy_price', 'mercari_keyword'}, ...]
    """
    if rarities is None:
        rarities = TARGET_RARITIES
    if min_price is None:
        min_price = MIN_BUY_PRICE

    rarities_set = {r.upper() for r in rarities}

    # (name, rarity) → 最高買取価格エントリ
    seen: dict = {}
    page = 1
    consecutive_failures = 0
    MAX_FAILURES = 3

    while consecutive_failures < MAX_FAILURES:
        items = _fetch_cardrush_page(page)

        if items is None:
            # タイムアウト等のエラー → リトライカウント
            consecutive_failures += 1
            logger.warning(f"[CardRush] ページ{page} 取得失敗 ({consecutive_failures}/{MAX_FAILURES})")
            time.sleep(3)
            continue

        if not items:
            # 空ページ = データ終端
            break

        consecutive_failures = 0  # 成功したらリセット
        stop = False
        for item in items:
            amount = item.get("amount", 0)
            rarity = item.get("rarity", "").upper()
            name   = item.get("name", "")

            if amount < min_price:
                stop = True
                continue

            if rarity not in rarities_set:
                continue

            key = (name, rarity)
            if key not in seen or seen[key]["amount"] < amount:
                seen[key] = item

        if stop:
            break

        page += 1
        time.sleep(0.5)


    # カードリストを構築
    cards = []
    for (name, rarity), item in seen.items():
        model_number = item.get("model_number", "")
        cards.append({
            "card_name":       f"{name} {rarity}",
            "cardrush_name":   name,
            "cardrush_rarity": rarity,
            "model_number":    model_number,
            "buy_price":       item["amount"],
            "mercari_keyword": f"{name} {rarity}",
        })

    # 買取価格の高い順にソート
    cards.sort(key=lambda x: -x["buy_price"])

    logger.info(
        f"[CardRush] バルク取得完了: {len(cards)} 件 "
        f"(レアリティ:{rarities}, 最低¥{min_price:,})"
    )
    return cards


def _fetch_cardrush_page(page: int) -> Optional[list]:
    """
    カードラッシュの指定ページの買取価格リストを返す。

    Returns:
        list: 取得成功時
        []: 空ページ（データ終端）
        None: タイムアウト・エラー時
    """
    parts = [
        ("limit",              "100"),
        ("page",               str(page)),
        ("sort[key]",          "amount"),
        ("sort[order]",        "desc"),
        ("display_category[]", "最新弾"),
        ("display_category[]", "スタンダード"),
        ("display_category[]", "エクストラ"),
        ("display_category[]", "旧裏"),
        ("is_hot[]",           "true"),
        ("is_hot[]",           "false"),
    ]
    url = BASE_URL + "?" + urllib.parse.urlencode(parts)

    for attempt in range(1, 4):  # 最大3回リトライ
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            next_data = _extract_next_data(resp.text)
            if not next_data:
                return []
            return (
                next_data
                .get("props", {})
                .get("pageProps", {})
                .get("buyingPrices", [])
            )
        except requests.RequestException as e:
            logger.warning(f"[CardRush] ページ{page} 試行{attempt}/3: {e}")
            if attempt < 3:
                time.sleep(attempt * 2)

    return None  # 3回失敗
