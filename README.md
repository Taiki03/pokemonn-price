# ポケカ相場監視ツール MVP

特定のポケモンカードの市場価格を定期監視し、**平均より20%以上安い商品**をDiscordに自動通知するツールです。

---

## 📁 ファイル構成

```
purchase/
├── monitor.py                  # メインスクリプト
├── requirements.txt            # Pythonライブラリ一覧
├── .env.example                # 環境変数のサンプル
├── .env                        # ← 自分で作成（Gitに含めないこと！）
├── .gitignore
└── .github/
    └── workflows/
        └── monitor.yml         # GitHub Actions設定
```

---

## 🚀 セットアップ手順

### 1. 依存ライブラリのインストール

```bash
cd /Users/taikitezuka/purchase
pip install -r requirements.txt
```

### 2. `.env` ファイルを作成

```bash
cp .env.example .env
```

`.env` を開き、Discord Webhook URLを設定：

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxxxxxx/xxxxxxxxxx
ALERT_THRESHOLD=0.20
```

### 3. ローカルでテスト実行

```bash
python monitor.py
```

---

## 🔔 Discord Webhook の発行手順

1. Discordを開き、通知を送りたい**サーバー**を開く
2. 通知先チャンネル（例: `#ポケカアラート`）を右クリック → **「チャンネルの編集」**
3. 左メニューの **「連携サービス」** → **「ウェブフック」** → **「新しいウェブフック」**
4. 名前を設定（例: `ポケカ監視Bot`）して **「ウェブフックのURLをコピー」**
5. コピーしたURLを `.env` の `DISCORD_WEBHOOK_URL=` に貼り付ける

---

## ⚙️ GitHub Actions での自動化

### 1. リポジトリをGitHubにプッシュ

```bash
cd /Users/taikitezuka/purchase
git init
git add .
git commit -m "feat: ポケカ相場監視ツール MVP"
git remote add origin https://github.com/<あなたのユーザー名>/<リポジトリ名>.git
git push -u origin main
```

### 2. GitHub Secrets に Webhook URL を登録

1. GitHubリポジトリ → **Settings** → **Secrets and variables** → **Actions**
2. **「New repository secret」** をクリック
3. 以下を入力して保存：
   - **Name**: `DISCORD_WEBHOOK_URL`
   - **Secret**: Discordからコピーした Webhook URL

### 3. 動作確認

- `Actions` タブ → `ポケカ相場監視` → **「Run workflow」** で手動実行できます
- 以降、毎時0分に自動実行されます（GitHub Actionsの無料枠: 月2,000分）

---

## 📋 監視対象カードの追加方法

`monitor.py` の `WATCH_LIST` に追記するだけです：

```python
WATCH_LIST = [
    {
        "card_name": "任意のカード名",
        "search_url": "https://mercari.com/jp/search/?keyword=検索キーワード&status=on_sale",
    },
    # ... 追加
]
```

---

## ⚠️ 注意事項

- メルカリはスクレイピングを規約で制限しています。本ツールはあくまで学習・個人利用目的です。
- メルカリのHTML構造やAPI仕様は変更される可能性があります。動作しなくなった場合はセレクターを更新してください。
- `.env` ファイルは **絶対にGitにコミットしないでください**（`.gitignore` に含めること）。
