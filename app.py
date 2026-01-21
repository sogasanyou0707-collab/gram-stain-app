import streamlit as st
import google.generativeai as genai
import os
import random
import io
import requests # ★追加：HTTP通信用
import base64   # ★追加：画像を文字データに変換用
from PIL import Image
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア ===
LIBRARY_FOLDER_NAME = 'my_gram_app'
INBOX_FOLDER_NAME = 'Inbox'

st.set_page_config(page_title="グラム染色AI ver9.0 (GAS)", page_icon="🔬")
st.title("🔬 グラム染色 AI (チーム共有)")

# --- 設定値の取得 ---
# 1. Gemini API Key
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

# 2. GASのURL (さっきコピーしたやつ)
GAS_APP_URL = st.secrets["GAS_APP_URL"] if "GAS_APP_URL" in st.secrets else None

# 3. GoogleドライブのフォルダID
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"] if "DRIVE_FOLDER_ID" in st.secrets else None


# --- モデル設定 ---
model_options = ["gemini-1.5-pro"]
if api_key:
    try:
        genai.configure(api_key=api_key)
        for m in genai.list_models():
             if 'generateContent' in m.supported_generation_methods:
                name = m.name.replace("models/", "")
                if name not in model_options:
                    model_options.append(name)
    except:
        pass
default_backups = ["gemini-1.5-flash", "gemini-3-flash-preview"]
for m in default_backups:
    if m not in model_options:
        model_options.append(m)

selected_model_name = st.sidebar.selectbox("モデル", model_options)

# --- メイン処理 ---
if api_key:
    model = genai.GenerativeModel(selected_model_name)

    uploaded_file = st.file_uploader("写真を撮影 または 選択", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption='解析対象', use_container_width=True)

        if st.button("AIで解析する"):
            with st.spinner('AIが解析中...'):
                try:
                    if os.path.exists(LIBRARY_FOLDER_NAME):
                        categories = [f for f in os.listdir(LIBRARY_FOLDER_NAME) if not f.startswith('.') and f != INBOX_FOLDER_NAME]
                        categories_str = ", ".join(categories)
                    else:
                        categories_str = "なし"

                    prompt = f"""
                    あなたは臨床微生物学の専門家です。このグラム染色画像を解説してください。
                    【出力フォーマット】
                    1. 所見
                    2. 推定菌種
                    3. 最も近いカテゴリ: [{categories_str}]
                    最後に必ず「CATEGORY:カテゴリ名」を出力。
                    """
                    
                    safety_settings = {
                        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }

                    response = model.generate_content([prompt, image], safety_settings=safety_settings)
                    
                    if response.text:
                        st.session_state['last_result'] = response.text
                        st.session_state['last_image'] = image
                except Exception as e:
                    st.error(f"エラー: {e}")

        # --- 結果とGAS経由保存 ---
        if 'last_result' in st.session_state:
            text = st.session_state['last_result']
            st.markdown("### 🤖 解析結果")
            st.write(text.replace("CATEGORY:", ""))
            
            # (参考画像ロジック維持)
            match_category = None
            for line in text.split('\n'):
                if "CATEGORY:" in line:
                    match_category = line.split("CATEGORY:")[1].strip()
            if match_category and match_category != "None" and os.path.exists(os.path.join(LIBRARY_FOLDER_NAME, match_category)):
                 path = os.path.join(LIBRARY_FOLDER_NAME, match_category)
                 files = [f for f in os.listdir(path) if f.lower().endswith(('png', 'jpg'))]
                 if files:
                     st.image(os.path.join(path, random.choice(files)), caption=f'参考: {match_category}', use_container_width=True)

            st.write("---")
            
            # ★★★ GAS経由 Drive保存ボタン ★★★
            if st.button("☁️ Googleドライブに保存"):
                if GAS_APP_URL and DRIVE_FOLDER_ID:
                    with st.spinner("クラウドに転送中..."):
                        try:
                            # 1. 画像をBase64文字列に変換
                            img_byte_arr = io.BytesIO()
                            st.session_state['last_image'].save(img_byte_arr, format='PNG')
                            img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')

                            # 2. 送信データ作成
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"{timestamp}.png"
                            
                            payload = {
                                'image': img_base64,
                                'filename': filename,
                                'folderId': DRIVE_FOLDER_ID,
                                'mimeType': 'image/png'
                            }

                            # 3. GASへ送信
                            response = requests.post(GAS_APP_URL, json=payload)
                            
                            if response.status_code == 200:
                                res_json = response.json()
                                if res_json.get('status') == 'success':
                                    st.success(f"✅ 保存成功！\nGoogleドライブに保存されました。")
                                else:
                                    st.error(f"保存失敗(GAS): {res_json.get('message')}")
                            else:
                                st.error(f"通信エラー: {response.status_code}")

                        except Exception as e:
                            st.error(f"システムエラー: {e}")
                else:
                    st.error("⚠️ 保存先設定(Secrets)が不足しています。")

else:
    st.info("👈 APIキー設定が必要です。")
