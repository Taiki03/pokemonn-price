"""
共通データモデル
"""
import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AlertLevel(Enum):
    HOT  = "🔴 超お得"   # 参照価格の50%以下
    WARM = "🟡 お得候補"  # 参照価格の70%以下


@dataclass
class ReferencePrice:
    """カードラッシュから取得した基準価格"""
    card_name:    str
    buy_price:    Optional[int]   # 買取価格
    sell_price:   Optional[int]   # 販売価格
    model_number: str             # 型番（例: 201/165）
    source_url:   str


@dataclass
class MercariListing:
    """メルカリの出品1件"""
    title:     str
    price:     int
    url:       str
    thumbnail: str = ""
    created:   Optional[datetime.datetime] = None  # 出品日時


@dataclass
class ArbitrageAlert:
    """アービトラージチャンス"""
    card_name:       str
    listing:         MercariListing
    reference:       ReferencePrice
    alert_level:     AlertLevel
    profit_estimate: int    # 推定利益（円）
    discount_rate:   float  # 買取価格比の割引率（例: 0.40 = 60%安）
