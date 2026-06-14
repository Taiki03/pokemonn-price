"""
Discordへのテスト通知を送るスクリプト。
.env に DISCORD_WEBHOOK_URL を設定後、以下で実行:
    python3 test_discord.py
"""
import os
from dotenv import load_dotenv
from models import ArbitrageAlert, AlertLevel, MercariListing, ReferencePrice
from notifiers.discord import send_alert

load_dotenv()

if not os.getenv("DISCORD_WEBHOOK_URL"):
    print("❌ .env ファイルに DISCORD_WEBHOOK_URL が設定されていません。")
    print("   .env.example をコピーして .env を作成し、Webhook URLを設定してください。")
    exit(1)

# テスト用のダミーデータ
test_alert = ArbitrageAlert(
    card_name="リザードン ex SAR（テスト）",
    listing=MercariListing(
        title="【PSA不要美品】リザードン ex SAR 即購入OK",
        price=28000,
        url="https://jp.mercari.com/item/m00000000000",
        thumbnail="",
    ),
    reference=ReferencePrice(
        card_name="リザードン ex SAR",
        buy_price=70000,
        sell_price=None,
        model_number="201/165",
        source_url="https://cardrush.media/pokemon/buying_prices?name=リザードンex",
    ),
    alert_level=AlertLevel.HOT,
    profit_estimate=42000,
    discount_rate=0.60,
)

print("Discordにテスト通知を送信中...")
success = send_alert(test_alert)
if success:
    print("✅ 送信成功！Discordを確認してください。")
else:
    print("❌ 送信失敗。DISCORD_WEBHOOK_URL が正しいか確認してください。")
