from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, ImageMessage, TextSendMessage,
    FlexSendMessage, QuickReply, QuickReplyButton, MessageAction, PostbackEvent
)

import re, tempfile
import mysql.connector
from ultralytics import YOLO
from sep.recommend import get_random_recipe

# ====== Flask App ======
app = Flask(__name__)

# ====== LINE Bot 設定 ======
channel_access_token = 'bU54KhRXTsIdL62vsw+pK4P57ioelBvYKBvY5HOpU2tiRQsLmaziUBYFScF35u28SU9jBioaOYgfbLrPAUwItLUWYhSegwXYEWThzytFS6Hg0CZw1kw2ArpfiUKVYp6ROnXaybiMGJikO3f2y7f+9AdB04t89/1O/w1cDnyilFU='
channel_secret = 'adbd0ef6979c9025caecaefa77574753'
line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

# ====== 載入 YOLO 模型 ======
MODEL_PATH = r"C:\Users\user\Downloads\best.pt"
model = YOLO(MODEL_PATH)

# ====== 英文 → 中文 同義詞 ======
EN2ZH_SYNONYM = {
    "apple": ["蘋果"], "avocado": ["酪梨"], "banana": ["香蕉"],
    "bell pepper": ["甜椒"], "bitter gourd": ["苦瓜"], "broccoli": ["花椰菜"],
    "cabbage": ["高麗菜", "包心菜"], "carrot": ["紅蘿蔔", "胡蘿蔔"],
    "cauliflower": ["白花椰菜", "菜花"], "chili": ["辣椒"], "corn": ["玉米"],
    "cucumber": ["小黃瓜", "胡瓜"], "eggplant": ["茄子"], "garlic": ["大蒜", "蒜頭"],
    "grape": ["葡萄"], "hot pepper": ["辣椒", "朝天椒"], "kiwi": ["奇異果", "獼猴桃"],
    "lemon": ["檸檬"], "mango": ["芒果"], "melon": ["香瓜", "哈密瓜"],
    "onion": ["洋蔥"], "orange": ["柳橙", "橙子"], "papaya": ["木瓜"],
    "peach": ["桃子"], "pear": ["梨子"], "persimmon": ["柿子"],
    "pineapple": ["鳳梨", "菠蘿"], "plum": ["李子"], "potato": ["馬鈴薯"],
    "pumpkin": ["南瓜"], "radish": ["白蘿蔔", "蘿蔔"], "strawberry": ["草莓"],
    "tomato": ["蕃茄", "番茄"], "watermelon": ["西瓜"], "zucchini": ["櫛瓜", "西葫蘆"]
}

def detected_items_to_keywords(items, min_conf=0.25):
    """YOLO 偵測結果 → 中文關鍵字"""
    keywords, seen = [], set()
    for it in items:
        name = (it.get("name") or "").lower()
        conf = float(it.get("confidence", 0))
        if conf < min_conf or not name:
            continue
        zh_list = EN2ZH_SYNONYM.get(name, [name])
        main_kw = zh_list[0]
        if main_kw not in seen:
            seen.add(main_kw)
            keywords.append(main_kw)
    return " ".join(keywords)


# ====== MySQL 工具 ======
def get_conn_cursor(): 
    conn = mysql.connector.connect(
        host="recipes-db.crkieu4eg5xp.ap-southeast-2.rds.amazonaws.com",
        user="admin",
        password="Lisa951024!",
        database="recipes",   # ⚠️ 這是你 RDS 的資料庫名稱
        charset="utf8mb4"
    )
    return conn, conn.cursor(buffered=True)

def get_member_conn_cursor():
    conn = mysql.connector.connect(
        host="recipes-db.crkieu4eg5xp.ap-southeast-2.rds.amazonaws.com",
        user="admin",
        password="Lisa951024!",
        database="members",
        charset="utf8mb4"
    )
    return conn, conn.cursor(buffered=True)

    
# ====== 使用者設定 ======
def ensure_user_exists(user_id):
    conn, cur = get_conn_cursor()
    cur.execute("SELECT id FROM members WHERE user_id=%s", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO members (user_id) VALUES (%s)", (user_id,))
        conn.commit()
    cur.close(); conn.close()


def update_user_settings(user_id, preference=None, allergens=None):
    conn, cur = get_conn_cursor()
    if preference:
        cur.execute("UPDATE members SET preference=%s WHERE user_id=%s", (preference, user_id))
    if allergens:
        cur.execute("UPDATE members SET allergens=%s WHERE user_id=%s", (allergens, user_id))
    conn.commit()
    cur.close(); conn.close()


# ====== 查詢食譜 ======
def query_recipes(keyword, servings, preference=None, allergens=None):
    keywords = keyword.split()
    clauses, params = [], []

    # ---- 1. 食材關鍵字匹配 ----
    for kw in keywords:
        synonyms = [kw]
        for group in EN2ZH_SYNONYM.values():
            if kw in group:
                synonyms = group
                break
        or_clause = " OR ".join(["ingredients LIKE %s"] * len(synonyms))
        clauses.append(f"({or_clause})")
        params.extend([f"%{syn}%" for syn in synonyms])

    where_clause = " AND ".join(clauses)

    # ---- 2. 加上偏好分類條件 ----
    if preference:
        where_clause += " AND category LIKE %s"
        params.append(f"%{preference}%")

    # ---- 3. 避開過敏食材 ----
    if allergens:
        for a in allergens.split(","):
            where_clause += " AND ingredients NOT LIKE %s"
            params.append(f"%{a.strip()}%")

    # ---- 4. SQL 組合 ----
    sql = f"""
    SELECT id, title, ingredients, servings
    FROM recipes
    WHERE {where_clause}
      AND (servings LIKE %s OR servings = '未標示')
    ORDER BY 
      CASE WHEN servings LIKE %s THEN 1 ELSE 2 END,  -- 符合份數的排前面
      RAND()
    LIMIT 5
    """
    params.append(f"%{servings}%")
    params.append(f"%{servings}%")

    # ---- 5. 執行查詢 ----
    conn, cur = get_conn_cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close(); conn.close()

    # ---- 6. 回傳結果 ----
    return [
        {"id": r[0], "title": r[1], "ingredients": r[2], "servings": r[3]}
        for r in rows
    ]


def get_recipe_detail(recipe_id):
    conn, cur = get_conn_cursor()
    cur.execute("SELECT title, ingredients, instructions, servings, calories, protein, fat, carbs FROM recipes WHERE id=%s", (recipe_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if row:
        return dict(
            title=row[0], 
            ingredients=row[1], 
            instructions=row[2], 
            servings=row[3],
            calories=row[4],
            protein=row[5],
            fat=row[6],
            carbs=row[7]
        )
    return None


# ====== Flex bubble ======
def build_recipe_bubbles(recipes):
    bubbles = []
    for r in recipes:
        snippet = r["ingredients"][:30] + ("…" if len(r["ingredients"]) > 30 else "")
        servings_display = r["servings"] if r["servings"] else "未標示"
        bubbles.append({
            "type": "bubble", "size": "micro",
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "13px",
                "contents": [
                    {"type": "text", "text": r["title"], "weight": "bold", "size": "sm", "wrap": True},
                    {"type": "text", "text": f"份量：{servings_display}", "size": "xs", "color": "#555555", "wrap": True},
                    {"type": "text", "text": snippet, "size": "xs", "color": "#888888", "wrap": True}
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical", "contents": [
                    {"type": "button",
                     "action": {"type": "postback", "label": "查看食譜",
                                "data": f"action=view_recipe&id={r['id']}"},
                     "style": "link", "height": "sm"}
                ]
            }
        })
    return bubbles


# ====== 暫存使用者輸入 ======
user_pending_keyword = {}
user_setting_allergy = set()


# ====== LINE webhook ======
@app.route("/callback", methods=['POST'])
def callback():
    body = request.get_data(as_text=True)
    signature = request.headers.get('X-Line-Signature')
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ InvalidSignatureError: 檢查 Channel Secret 或 Webhook URL")
        return 'OK'
    except Exception as e:
        print("❌ handler error:", e)
        return 'OK'
    return 'OK'


# ====== 文字訊息 ======
@handler.add(MessageEvent, message=TextMessage)
def on_text(event):
    print("🔹 使用者 ID:", event.source.user_id)
    user_id = event.source.user_id
    user_input = event.message.text.strip()

    if re.fullmatch(r"(\d+)(?:\s*人)?$", user_input):
        if user_id not in user_pending_keyword:
            return line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請先輸入食材名稱或上傳圖片，我才能幫你找食譜喔 🍳")
            )
        
    # ✅ 會員專區（一定要放最前面，避免被後面誤判）
    if "會員專區" in user_input:
        print("✅ 進入會員專區區塊")

        bubble = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "會員專區",
                        "weight": "bold",
                        "size": "xl",
                        "align": "center",
                        "color": "#000000"
                    }
                ],
                "backgroundColor": "#F6C2B9",
                "paddingAll": "10px"            
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "link",
                        "height": "sm",
                        "color": "#000000",
                        "action": {
                            "type": "message",
                            "label": "設定飲食偏好",
                            "text": "設定偏好"
                        }
                    },
                    {
                        "type": "button",
                        "style": "link",
                        "height": "sm",
                        "color": "#000000",
                        "action": {
                            "type": "message",
                            "label": "設定過敏項目",
                            "text": "設定過敏"
                        }
                    }
                ]
            },
            "styles": {
                "body": {"backgroundColor": "#FFEBEB"},
                "footer": {"backgroundColor": "#FFEBEB"}
            }
        }

        return line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="會員專區", contents=bubble)
        )
        # ⚙️ 會員偏好設定
    ensure_user_exists(user_id)

    # 使用者選「設定偏好」
    if user_input == "設定偏好":
        quick_reply = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="素食", text="偏好:素食")),
            QuickReplyButton(action=MessageAction(label="減脂", text="偏好:減脂")),
            QuickReplyButton(action=MessageAction(label="增肌", text="偏好:增肌")),
            QuickReplyButton(action=MessageAction(label="低卡", text="偏好:低卡"))
        ])
        return line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請選擇你的飲食偏好：", quick_reply=quick_reply)
        )

    # 儲存偏好結果
    elif user_input.startswith("偏好:"):
        pref = user_input.split(":", 1)[1].strip()
        update_user_settings(user_id, preference=pref)
        return line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"已設定飲食偏好：{pref}")
        )

   # ✅ 過敏設定（新版：獨立狀態管理）
    if user_input == "設定過敏":
        user_setting_allergy.add(user_id)
        # 🔹 同時清掉食材查詢暫存，避免干擾
        user_pending_keyword.pop(user_id, None)
        return line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入你的過敏食材（例如：花生、蝦、牛奶）")
        )

    # ✅ 使用者正在輸入過敏食材
    if user_id in user_setting_allergy:
        allergens = user_input.strip()
        update_user_settings(user_id, allergens=allergens)
        user_setting_allergy.remove(user_id)
        # 🔹 清除所有暫存關鍵字
        user_pending_keyword.pop(user_id, None)
        return line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text=f"🚫 已更新過敏項目：{allergens}\n✅ 過敏設定完成，可以繼續查詢食譜囉！"
        )
    )

    # 🎲 Rich Menu「餐點推薦」 → 一次推薦三個 bubble
    if user_input == "餐點推薦":
        conn, cur = get_conn_cursor()
        cur.execute("""
            SELECT id, title, ingredients, servings
            FROM recipes
            ORDER BY RAND()
            LIMIT 3
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()

        if not rows:
            return line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="目前沒有可推薦的食譜 😢")
            )

        recipes = [
            {"id": r[0], "title": r[1], "ingredients": r[2], "servings": r[3]}
            for r in rows
        ]
        bubbles = build_recipe_bubbles(recipes)
        carousel = {"type": "carousel", "contents": bubbles}

        flex_msg = FlexSendMessage(alt_text="今日隨機推薦", contents=carousel)
        return line_bot_api.reply_message(event.reply_token, flex_msg)
    
    # 📌 若使用者正在輸入人數
    if user_id in user_pending_keyword:
        m = re.fullmatch(r"(\d+)(?:\s*人)?$", user_input)
        if not m:
            return line_bot_api.reply_message(
                event.reply_token, 
                TextSendMessage(text="請輸入幾人份，例如：2人、3人")
            )

        servings = m.group(1)
        keyword = user_pending_keyword.pop(user_id)
        # 取得使用者的偏好與過敏
        conn, cur = get_conn_cursor()
        cur.execute("SELECT preference, allergens FROM members WHERE user_id=%s", (user_id,))
        user = cur.fetchone()
        cur.close(); conn.close()

        preference = user[0] if user and user[0] else None
        allergens = user[1] if user and user[1] else None

        # 查詢時加入偏好與過敏
        recipes = query_recipes(keyword, servings, preference, allergens)

        if not recipes:
            return line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"找不到包含「{keyword}」的食譜 😢")
            )

        bubbles = build_recipe_bubbles(recipes)
        carousel = {"type": "carousel", "contents": bubbles}
        flex_msg = FlexSendMessage(alt_text="推薦食譜", contents=carousel)
        return line_bot_api.reply_message(event.reply_token, flex_msg)
        

    # 📌 第一次輸入：食材名稱
    keyword = user_input
    user_pending_keyword[user_id] = keyword
    quick = QuickReply(items=[QuickReplyButton(action=MessageAction(label=f"{n}人", text=f"{n}人")) for n in range(1, 7)])
    return line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text=f"「{keyword}」要做幾人份呢？", quick_reply=quick)
        )

# ====== 圖片訊息 (YOLO 辨識) ======
@handler.add(MessageEvent, message=ImageMessage)
def on_image(event):
    user_id = event.source.user_id

    # 下載圖片到暫存檔
    content = line_bot_api.get_message_content(event.message.id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        for chunk in content.iter_content():
            tmp.write(chunk)
        image_path = tmp.name

    # YOLO 推論
    res = model.predict(image_path, conf=0.25, imgsz=640, verbose=False)[0]
    items = [{"name": res.names[int(b.cls[0])], "confidence": float(b.conf[0])} for b in res.boxes]

    # 轉換成中文關鍵字
    keyword_str = detected_items_to_keywords(items, min_conf=0.25)
    if not keyword_str:
        return line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="我沒有在圖裡找到可用的食材😅\n可以再拍清楚一點或換角度試試。")
        )

    user_pending_keyword[user_id] = keyword_str
    quick = QuickReply(items=[QuickReplyButton(action=MessageAction(label=f"{n}人", text=f"{n}人")) for n in range(1, 7)])
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"辨識到：{keyword_str}\n要做幾人份呢？", quick_reply=quick)
    )


# ====== Postback 處理 ======
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    print("📩 收到 postback data:", data)   

    if data.startswith("action=view_recipe&id="):
        recipe_id = int(data.split("=")[-1])
        recipe = get_recipe_detail(recipe_id)
        if not recipe:
            return line_bot_api.reply_message(event.reply_token, TextSendMessage(text="找不到這道食譜了 😢"))

        msg1 = TextSendMessage(
            text=(
                f"{recipe['title']}（{recipe['servings']}）\n\n"
                f"食材：\n{recipe['ingredients']}\n\n"
                f"👨‍🍳 步驟：\n{recipe['instructions']}"
            )
        )

        # ✅ 第二則：營養分析
        msg2 = TextSendMessage(
            text=(
                f"📊 營養分析：\n"
                f"熱量：{recipe['calories']:.0f} kcal\n"
                f"蛋白質：{recipe['protein']:.1f} g\n"
                f"脂肪：{recipe['fat']:.1f} g\n"
                f"碳水化合物：{recipe['carbs']:.1f} g"
            )
        )

        # ✅ 分兩則訊息一起回覆
        return line_bot_api.reply_message(event.reply_token, [msg1, msg2])


# ====== 啟動伺服器 ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)