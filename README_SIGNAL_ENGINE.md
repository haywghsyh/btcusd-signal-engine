# XAUUSD Signal Engine

XAUUSD専用の完全自動シグナルエンジン。TradingViewからWebhookでデータを受信し、AI（Claude）が最終判断を行い、Telegramにシグナルを通知します。

## アーキテクチャ

```
TradingView Alert (Webhook)
        ↓
  Webhook Server (Flask)
        ↓
  Market Data Receiver (バッファ保存)
        ↓
  Feature Engine (EMA, ATR, RSI等)
        ↓
  Market State Classifier (H4/H1/M15/M5)
        ↓
  Signal Candidate Generator
        ↓
  AI Judge (Claude API)
        ↓
  Risk Filter (SL/TP/RR検証)
        ↓
  Telegram Notifier
        ↓
  Signal Logger (SQLite)
```

## プロジェクト構成

```
src/
├── config/settings.py      # 設定管理
├── data/receiver.py         # TradingView Webhook受信・データ保存
├── features/engine.py       # 特徴量計算 (EMA, ATR, RSI等)
├── classifier/market_state.py # 市場状態分類
├── signals/generator.py     # シグナル候補生成
├── ai/judge.py              # AI評価 (Claude API)
├── risk/filter.py           # リスクフィルター
├── notifier/telegram.py     # Telegram通知
├── storage/database.py      # SQLiteログ保存
└── utils/                   # ユーティリティ
main.py                      # Webhookサーバー (Flask)
tests/                       # テストコード
```

## セットアップ

### 1. 依存関係インストール

```bash
pip install -r requirements-signal.txt
```

### 2. 環境変数設定

```bash
cp .env.example .env
# .env を編集して以下を設定:
# - TELEGRAM_TOKEN: Telegram Botトークン
# - TELEGRAM_CHAT_ID: 通知先チャットID
# - ANTHROPIC_API_KEY: Anthropic APIキー
```

### 3. サーバー起動

```bash
python main.py
```

デフォルトで `http://0.0.0.0:8080` で起動します。

## TradingView設定

### Alert Webhook URL

```
http://your-server:8080/webhook/tradingview
```

### Alert Message (JSON)

TradingViewのAlert設定で、以下のJSON形式でWebhookメッセージを設定してください。
各時間足（H4, H1, M15, M5）それぞれにAlertを設定します。

```json
{
    "symbol": "XAUUSD",
    "timestamp": "{{time}}",
    "open": {{open}},
    "high": {{high}},
    "low": {{low}},
    "close": {{close}},
    "volume": {{volume}},
    "timeframe": "M5"
}
```

> `timeframe` は各Alertで `H4`, `H1`, `M15`, `M5` に変更してください。

### 初期データロード

分析に必要な最低ローソク数を満たすため、初回は過去データのバッチロードが必要です。

```bash
curl -X POST http://localhost:8080/webhook/batch \
  -H "Content-Type: application/json" \
  -d '{
    "timeframe": "H4",
    "candles": [
      {"timestamp": "2025-01-01T00:00:00Z", "open": 3030, "high": 3035, "low": 3028, "close": 3033, "volume": 100},
      ...
    ]
  }'
```

## APIエンドポイント

| Endpoint | Method | 説明 |
|---|---|---|
| `/webhook/tradingview` | POST | TradingView Webhook受信 |
| `/webhook/batch` | POST | 過去データバッチロード |
| `/status` | GET | エンジン状態確認 |
| `/signals/recent` | GET | 直近シグナル取得 |
| `/analyze` | POST | 手動分析トリガー |

## 市場状態分類

### H4 (大局トレンド)
- `bullish_trend` / `bearish_trend` / `range` / `breakout_phase` / `choppy`

### H1 (押し目/戻り目)
- `bullish_pullback` / `bearish_pullback` / `continuation` / `range_middle` / `range_edge` / `reversal_candidate`

### M15 (構造確認)
- `reversal_confirmed` / `continuation_ready` / `compression` / `expansion` / `noisy`

### M5 (エントリータイミング)
- `execute_buy_ready` / `execute_sell_ready` / `waiting` / `invalid`

## リスクルール

- SL最大: 100 pips (設定変更可)
- 最低RR (TP3): 1.0以上
- BUY: SL < Entry < TP1 < TP2 < TP3
- SELL: TP3 < TP2 < TP1 < Entry < SL
- スプレッド閾値超過で棄却
- 重複シグナルのクールダウン（デフォルト15分）

## Telegram通知フォーマット

```
🔔 【XAUUSD SIGNAL】

📊 Decision: BUY
💰 Entry: MARKET
💲 Current Price: 3028.5

🛑 SL: 3021.8
🎯 TP1: 3033.2
🎯 TP2: 3038.7
🎯 TP3: 3045.4

📈 RR(TP3): 1.24
🔒 Confidence: 81%

⚠️ Invalidate: M15 closes below 3021.5

📝 Reason: H4 bullish trend, H1 pullback context, M15 reversal confirmed
```

## テスト実行

```bash
pytest tests/ -v
```

## 設定変更可能項目

環境変数または `Settings` クラスで変更可能:

| 設定 | 環境変数 | デフォルト |
|---|---|---|
| AIモデル | `AI_MODEL` | `claude-sonnet-4-6` |
| SL最大pips | `MAX_SL_PIPS` | `100` |
| 最低RR | `MIN_RR` | `1.0` |
| スプレッド閾値 | `SPREAD_THRESHOLD_PIPS` | `5.0` |
| クールダウン | `SIGNAL_COOLDOWN` | `900` (秒) |
| Webhookポート | `WEBHOOK_PORT` | `8080` |
| ログレベル | `LOG_LEVEL` | `INFO` |

## トレーディングセッション

デフォルト (JST):
- 東京: 09:00 - 15:00
- ロンドン: 16:00 - 21:00
- ニューヨーク: 21:00 - 02:00

セッション外は自動的に `NO_TRADE` となります。
