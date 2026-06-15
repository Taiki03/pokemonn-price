"""
メルカリ スクレイパー（mercapi ライブラリ版）

フィルタ条件:
  - status = ITEM_STATUS_ON_SALE（販売中のみ）
  - created >= 今日 - 30日（1ヶ月以内の出品のみ）
"""
import asyncio
import datetime
import logging
from typing import Optional

try:
    import mercapi as mercapi_lib
    MERCAPI_AVAILABLE = True
except ImportError:
    MERCAPI_AVAILABLE = False

from models import MercariListing
from config import MERCARI_MAX_ITEMS

logger = logging.getLogger(__name__)

ON_SALE_STATUS = "ITEM_STATUS_ON_SALE"
MAX_AGE_DAYS   = 30  # 出品から何日以内を対象にするか

# HOT候補の説明文チェック用キャッシュ（item_id → mercapi_item）
_ITEM_CACHE: dict = {}


def fetch_mercari_listings(card_name: str, keyword: str) -> list:
    """
    メルカリで keyword を検索し、以下の条件を満たす出品リストを返す：
    - 販売中（ITEM_STATUS_ON_SALE）
    - 1ヶ月以内に出品された商品

    Args:
        card_name: ログ用カード名
        keyword:   メルカリ検索キーワード

    Returns:
        MercariListing のリスト（取得失敗時は空リスト）
    """
    if not MERCAPI_AVAILABLE:
        logger.error("mercapi がインストールされていません: pip install mercapi")
        return []

    try:
        return asyncio.run(_fetch_async(card_name, keyword))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_fetch_async(card_name, keyword))
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"[Mercari][{card_name}] 予期しないエラー: {e}")
        return []


async def _fetch_async(card_name: str, keyword: str) -> list:
    """非同期でメルカリを検索・フィルタする。"""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=MAX_AGE_DAYS)

    try:
        m = mercapi_lib.Mercapi()
        results = await m.search(keyword)
        items = results.items or []

        listings = []
        skipped_status = 0
        skipped_old    = 0

        for item in items:
            try:
                # ── フィルタ①: 販売中のみ ────────────────────
                if item.status != ON_SALE_STATUS:
                    skipped_status += 1
                    continue

                # ── フィルタ②: 1ヶ月以内の出品のみ ──────────
                created = item.created  # datetime or None
                if created and created < cutoff:
                    skipped_old += 1
                    continue

                price   = int(item.price)
                name    = str(item.name or "不明")
                item_id = str(item.id_ or "")
                url     = f"https://jp.mercari.com/item/{item_id}" if item_id else ""
                thumb   = str(item.thumbnails[0]) if item.thumbnails else ""

                if price > 0 and url:
                    listings.append(MercariListing(
                        title     = name,
                        price     = price,
                        url       = url,
                        thumbnail = thumb,
                        created   = created,
                    ))
                    # 説明文チェック用にキャッシュ
                    _ITEM_CACHE[item_id] = item

            except (AttributeError, ValueError, TypeError):
                continue

        logger.info(
            f"[Mercari][{card_name}] {len(listings)} 件取得 "
            f"(販売終了除外:{skipped_status}件 / 1ヶ月超除外:{skipped_old}件)"
        )
        return listings[:MERCARI_MAX_ITEMS]

    except Exception as e:
        logger.error(f"[Mercari][{card_name}] 取得エラー: {e}")
        return []


def fetch_item_description(item_id: str) -> str:
    """
    item_id に対応する商品説明文を取得する。
    （_ITEM_CACHE に存在する場合のみ。事前に fetch_mercari_listings を呼ぶこと）

    Returns:
        説明文テキスト。取得できない場合は空文字列。
    """
    item = _ITEM_CACHE.get(item_id)
    if not item:
        return ""

    try:
        async def _get_desc():
            full = await item.full_item()
            return str(full.description or "")

        try:
            return asyncio.run(_get_desc())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_get_desc())
            finally:
                loop.close()
    except Exception:
        return ""
