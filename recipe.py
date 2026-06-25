from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from googletrans import Translator
import re
import time
import mysql.connector
import requests
import os
from bs4 import BeautifulSoup

translator = Translator()

# ✅ 建立資料庫連線
conn = mysql.connector.connect(
    host="recipes-db.crkieu4eg5xp.ap-southeast-2.rds.amazonaws.com",
        user="admin",
        password="Lisa951024!",
        database="recipes",   
        charset="utf8mb4"
)
cursor = conn.cursor()

# ✅ 設定 headers（讓所有地方可用）
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36"
}

# ✅ 啟動 WebDriver（無頭模式）
options = Options()
options.add_argument('--headless')
options.add_argument('--disable-gpu')
options.add_argument('--no-sandbox')
 
# 啟動 WebDriver
driver = webdriver.Chrome(options=options)
 
# 開啟 iCook 熱門食譜頁
url = 'https://icook.tw/recipes/popular'
driver.get(url)
time.sleep(5)  # 等待網頁載入
 
recipes = driver.find_elements(By.CSS_SELECTOR, '.browse-recipe-item')
 
for idx, recipe in enumerate(recipes):
    try:
        title = recipe.find_element(By.CSS_SELECTOR, '.browse-recipe-name').text        
        link = recipe.find_element(By.CSS_SELECTOR, 'a').get_attribute('href')
        image_url = recipe.find_element(By.CSS_SELECTOR, 'img').get_attribute('src')

        recipe_response = requests.get(link, headers=headers, timeout=10)
        soup = BeautifulSoup(recipe_response.text, 'html.parser')

        serving_tag = soup.select_one('.servings') or soup.select_one('.recipe-portions')
        raw = serving_tag.text if serving_tag else ""
        match = re.search(r'(\d+)\s*人', raw)
        serving_text = f"{match.group(1)}人份" if match else "未標示"

        # ✅ 食材擷取
        ingredient_list = []
        zh_names = []
        ingredient_en = ""

        # ✅ 擷取食材（中文）+ 翻譯英文
        try:
            ingredient_items = soup.select('.ingredients li')

            for item in ingredient_items:
                name_tag = item.select_one('.ingredient-name')
                unit_tag = item.select_one('.ingredient-unit')
                if name_tag:
                    name = name_tag.text.strip()
                    unit = unit_tag.text.strip() if unit_tag else ""
                    zh = f"{name}：{unit}" if unit else name
                    ingredient_list.append(zh)
                    zh_names.append(name)
        except Exception as e:
            print("❌ 食材擷取失敗：", e)
            ingredient_list = []
            zh_names = []

        ingredient = ', '.join(ingredient_list) if ingredient_list else "食材擷取失敗"

        # ✅ 翻譯成英文
        en_list = []
        for zh in zh_names:
            try:
                en = translator.translate(zh, src='zh-tw', dest='en').text.lower()
                en_list.append(en)
                time.sleep(0.5)  # 防止被鎖
            except Exception as e:
                print(f"❌ 翻譯失敗：{zh} → {e}")
                en_list.append("unknown")
        ingredient_en = ', '.join(en_list) if en_list else "translation failed"

        # ✅ 步驟擷取（獨立於食材 try 區塊）
        try:
            steps = soup.select('.recipe-step-description')
            instructions = '\n'.join([step.text.strip() for step in steps])
        except Exception as e:
            print(f"步驟擷取失敗：{e}")
            instructions = "步驟擷取失敗"

        # ✅ 資料寫入 MySQL
        sql = "INSERT IGNORE INTO recipes (title, ingredients, ingredients_en, instructions, servings, category) VALUES (%s, %s, %s, %s, %s, %s)"
        val = (title, ingredient, ingredient_en, instructions, serving_text, "熱門")
        cursor.execute(sql, val)

        print(f"料理：{title}")
        print(f"份量：{serving_text}")
        print(f"食材：{ingredient}")
        print(f"步驟：{instructions}")
        print("-" * 40)
 
    except Exception as e:
        print("資料擷取失敗：", e)
 
conn.commit()
 
# 關閉瀏覽器和資料庫連線
cursor.close()
conn.close()
driver.quit()