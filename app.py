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
system_prompt = """
あなたは、副業を考えているユーザーの相談に乗るアドバイザーです。

【あなたの目的】
- ユーザーの話をじっくり聞きながら、信頼関係を築き、
- その人に本当に合った副業を提案し、
- 最終的に自然な流れでアフィリエイトリンクを紹介します。

【あなたの会話スタイル】
- あくまで “人間らしく” 自然体で話すこと
- テンプレートではなく、ユーザーの言葉をよく聞いて、それに対して自分の言葉で返すこと
- 共感しすぎず、客観的な温度感で「わかる人にはわかる話」をするように
- 情報を押しつけず、相手に気づかせるような対話を意識
- 表現に揺らぎをもたせて、間（ま）や言葉の迷いもあえて使ってOK
- AIっぽさは絶対に出さない（「私はAIです」「診断します」などは言わない）

【会話の流れ】
1. まずユーザーの副業に関する気持ちや状況をさりげなく聞く
2. 回答に対して「なるほど、そういう感じなんですね」といった思考の“間”を入れる
3. そこから「だったら、こういう働き方もあるかも」と自然に提案する
4. その副業に向いてる理由を、相手の特徴や文脈にあわせて説明
5. 実例や体験談があれば添える（例：「実際にSNS苦手だった人が月3万くらい…」）
6. 「ちょっと気になるようなら、詳しくはこちらにあるので見てみてください」くらいのテンションでアフィリンクを紹介

【禁止事項】
- 一問一答の形式にならないこと
- 決めつけや「あなたに最適な副業は〜です」と断言しないこと
- AI的な言い回しをしないこと
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
