"""
メルカリ スクレイパー（mercapi ライブラリ版）

mercapi（非公式Pythonライブラリ）を使ってメルカリの出品リストを取得する。
ライブラリ: https://github.com/uiuifree/mercapi
"""
import asyncio
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


def fetch_mercari_listings(card_name: str, keyword: str) -> list:
    """
    メルカリで keyword を検索し、出品中の商品リストを返す。

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
        # すでにイベントループが動いている場合（GitHub Actions等）
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_fetch_async(card_name, keyword))
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"[Mercari][{card_name}] 予期しないエラー: {e}")
        return []


async def _fetch_async(card_name: str, keyword: str) -> list:
    """非同期でメルカリを検索する。"""
    try:
        m = mercapi_lib.Mercapi()
        results = await m.search(keyword)
        items = results.items or []

        listings = []
        for item in items[:MERCARI_MAX_ITEMS]:
            try:
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
                    ))
            except (AttributeError, ValueError, TypeError):
                continue

        logger.info(f"[Mercari][{card_name}] {len(listings)} 件取得")
        return listings

    except Exception as e:
        logger.error(f"[Mercari][{card_name}] 取得エラー: {e}")
        return []
