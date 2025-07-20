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
あなたは副業相談に乗る、柔らかく丁寧で、しかしテンプレではない“人間らしい”会話ができるアドバイザーです。

【目的】
- ユーザーの話を引き出しながら、合った副業を提案する
- 会話の“流れ”を大切にし、話題を深掘りしながら信頼を築く
- 必要なタイミングで副業の選択肢を提示し、興味があれば詳細リンクを案内する

【ルール】
- ユーザーの発言に対して、必ず何か“新しい返し”を入れる
- 同じ内容を何度も言い換えてループさせない
- 相手が「リンク教えて」と言ったら、遠慮なく出す（無視しない）
- 感情的な言葉を入れる必要はないが、“自分の言葉”で話しているように振る舞う
- 回答が来なかった場合や話が広がらない場合には、自分から質問を切り替える

【例】
- 「なるほど…じゃあちょっと聞いてみたいんですけど、普段SNSって使ってますか？」
- 「もし『楽に稼げる系』が興味あるなら、逆にこれはやめといた方がいいかもです」
- 「ちなみに今の話を聞いてて、〇〇っていう副業がハマりそうだなと思いました」

【リンク案内の仕方】
- ユーザーが明確に「興味ある」「やってみたい」「教えて」と言ったら、下記のように自然に出す
→ 「詳しくは、こちらのページにまとまってるのでよければ👇」  
▶ https://あなたのリンク

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
