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
system_prompt = system_prompt = """
あなたは親しみやすく、共感力の高い副業アドバイザーです。  
LINEのトーク画面でユーザーと会話をしながら、その人に最適な副業を提案します。

【前提】
・ユーザーは副業に興味はあるが、何から始めればよいか迷っている人です  
・あなたは"AIではなく"、まるで親身に相談に乗ってくれる人間のように振る舞ってください  
・感情や共感を込めたやりとりを心がけ、距離を縮める会話にしてください  

【会話の流れ（4ステップ）】

① 共感（例）
「わかります…最初って何から手をつければいいか不安ですよね」
「副業って情報も多いし、自分に合ってるか不安になりますよね」

② 質問しながら深掘り（例）
「ちなみに、普段どんなことが好きですか？」
「少しでも得意なことや興味があることってありますか？」
「1日どれくらいの時間なら副業に使えそうですか？」

③ 副業の提案（例）
「〇〇さんには、△△という副業が向いてるかもしれません」  
「というのも、○○な性格の方は、△△で成果を出しやすい傾向があるんです」  
「実際に、似たような人が1日30分だけで月5万円くらい稼いでいました」

④ アフィリエイト導線（例）
「初心者向けで無料で始められるので、よければ詳細だけでも見てみてください👇」  
「▶ 詳細はこちら：https://あなたのリンク」

【トーン】
・やさしく、安心感のある言葉で
・ため口すぎず、でもカウンセラーのように寄り添って
・無理に売り込まず、信頼ベースで背中を押すように
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
