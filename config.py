"""
設定ファイル
- アラート閾値
- 監視カードリストの読み込み（cards.csv）
"""
import csv
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ─── Discord ──────────────────────────────────────
DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")

# ─── アラート閾値（買取価格に対する割合）──────────────
# 例: 買取価格5,000円のカードが2,400円以下 → HOT
HOT_THRESHOLD:  float = float(os.getenv("HOT_THRESHOLD",  "0.50"))
WARM_THRESHOLD: float = float(os.getenv("WARM_THRESHOLD", "0.70"))

# ─── スクレイピング設定 ─────────────────────────────
REQUEST_TIMEOUT:    int = 15   # 秒
SLEEP_BETWEEN_CARDS: int = 3   # カード間のウェイト（秒）
MERCARI_MAX_ITEMS:  int = 30   # メルカリから取得する最大件数

# ─── カードリスト ──────────────────────────────────
CARDS_CSV = Path(__file__).parent / "cards.csv"


def load_cards() -> list:
    """
    cards.csv を読み込んでカードリストを返す。

    CSVフォーマット:
        card_name,cardrush_name,cardrush_rarity,mercari_keyword
        リザードン ex SAR,リザードンex,SAR,リザードンex SAR

    cardrush_rarity: Card Rush の rarity フィールドと照合する値（SAR/AR/SR など）
    mercari_keyword: メルカリ検索キーワード
    """
    if not CARDS_CSV.exists():
        raise FileNotFoundError(f"cards.csv が見つかりません: {CARDS_CSV}")

    cards = []
    with open(CARDS_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["card_name"].startswith("#"):
                continue
            cards.append({
                "card_name":        row["card_name"].strip(),
                "cardrush_name":    row["cardrush_name"].strip(),
                "cardrush_rarity":  row.get("cardrush_rarity", "").strip(),
                "mercari_keyword":  row.get("mercari_keyword", "").strip()
                                    or row["cardrush_name"].strip(),
            })
    return cards
