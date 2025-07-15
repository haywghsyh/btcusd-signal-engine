import os
import openai
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境変数からAPIキーを取得
openai.api_key = os.getenv("OPENAI_API_KEY")
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# ChatGPT用のプロンプト
system_prompt = """あなたは副業診断AIです。ユーザーの性格・価値観・スキル・働き方に関する質問を通じて最適な副業を1つ提案します。
提案のあとに「詳細はこちら」として外部リンク（アフィリンク）を紹介してください。
"""

# LINEからのWebhook受信エンドポイント
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# メッセージを受信してChatGPTに渡す
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text}
    ]

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=500
        )
        reply_text = response.choices[0].message["content"]

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )

    except Exception as e:
        print("OpenAIエラー内容:", str(e))  # ← これがログに出力されます
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="診断に失敗しました。もう一度お試しください。")
        )

# ローカル開発用
if __name__ == "__main__":
    app.run()
