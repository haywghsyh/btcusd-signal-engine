import os
import openai
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境変数から各キーを取得
openai.api_key = os.getenv("OPENAI_API_KEY")
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# ChatGPTへの指示（副業診断用プロンプト）
system_prompt = """あなたは副業診断AIです。ユーザーの性格・価値観・スキル・働き方に関する質問を通じて最適な副業を1つ提案します。
診断結果のあとに「詳細はこちら」として副業に関する外部リンクを紹介してください。
"""

# LINEからのWebhook受信エンドポイント
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# LINEメッセージイベントに応答
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text

    # ChatGPTに渡す会話履歴
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
    # ユーザーにはエラーメッセージを返信
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="診断に失敗しました。もう一度お試しください。")
    )
    # Renderログにエラー内容を表示（ここが重要）
    print("OpenAIエラー内容:", str(e))


# ローカル開発用
if __name__ == "__main__":
    app.run()
