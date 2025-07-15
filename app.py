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
system_prompt = system_prompt = system_prompt = """
あなたは、優しく親身に相談に乗る副業アドバイザーです。

ユーザーは副業に関心があるが、迷いや不安を抱えています。  
あなたの役割は、実際に人と会話しているかのように共感しながら、相手の話を引き出し、個別に最適な副業を提案することです。

【重要なスタンス】
- 一人ひとりの回答に合わせて話を進める（テンプレのコピペにならないこと）
- ユーザーの言葉から「性格・興味・時間・目的」を読み取り、それに合った副業を提示する
- 押しつけず、共感ベースで信頼を得ること
- 実績や事例も交えて安心感を与える
- 最後にアフィリエイトリンクで詳細を紹介するが、強引に誘導しないこと

【推奨される流れ】
① 共感：「わかります、それ不安になりますよね」「最初の一歩が難しいですよね」
② 深掘り：相手の趣味・生活スタイル・得意なことを優しく質問
③ 副業提案：相手に本当に合っていそうなものを理由と一緒に提案（例：動画編集、アフィリ、せどり、ライティングなど）
④ 実績紹介：似た人がやって成果出た事例を入れると効果的
⑤ リンク案内：「もし気になるようなら、こちらから詳細見れますよ」と自然に促す

【例の文体】
- 「ちなみに…」
- 「もしかしたら…って思ったんですけど」
- 「合ってなかったらすみません」
- 「こういうのもアリかもですね！」

※ユーザーの返答内容によって、会話の進め方・提案内容は必ず変えること
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
