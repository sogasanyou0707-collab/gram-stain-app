import streamlit as st
import google.generativeai as genai
import os
import random
import io
from PIL import Image
from datetime import datetime
from github import Github # ★追加：GitHub操作用
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア ===
# ★重要：ここにあなたの「GitHubユーザー名/リポジトリ名」を正確に入れてください
# 例: "sogasanyou0707-collab/gram-stain-app"
GITHUB_REPO_NAME = "sogasanyou0707-collab/gram-stain-app" 

LIBRARY_FOLDER_NAME = 'my_gram_app'
INBOX_FOLDER_NAME = 'Inbox'

st.set_page_config(page_title="グラム染色AI ver7.0 (Cloud Save)", page_icon="🔬")
st.title("🔬 グラム染色 AI (チーム収集モード)")

# --- 認証情報の取得 ---
# Gemini API Key
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

# GitHub Token (保存用)
if "GITHUB_TOKEN" in st.secrets:
    github_token = st.secrets["GITHUB_TOKEN"]
else:
    # ローカル開発用など
    github_token = None

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

    # スマホ対応：ファイル選択（カメラ/アルバム共通）
    uploaded_file = st.file_uploader("写真を撮影 または 選択", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption='解析対象', use_container_width=True)

        if st.button("AIで解析する"):
            with st.spinner('AIが解析中...'):
                try:
                    # ライブラリ一覧取得（GitHub上ではなく、今の環境にあるもの）
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

        # --- 結果とクラウド保存 ---
        if 'last_result' in st.session_state:
            text = st.session_state['last_result']
            st.markdown("### 🤖 解析結果")
            st.write(text.replace("CATEGORY:", ""))
            
            # (参考画像表示ロジックは省略せず維持)
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
            
            # ★★★ GitHubへのクラウド保存ボタン ★★★
            if st.button("☁️ クラウド(Inbox)に保存"):
                if github_token:
                    with st.spinner("GitHubに転送中..."):
                        try:
                            # 1. 画像をデータ化
                            img_byte_arr = io.BytesIO()
                            st.session_state['last_image'].save(img_byte_arr, format='PNG')
                            img_data = img_byte_arr.getvalue()

                            # 2. ファイル名生成
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            file_name = f"{INBOX_FOLDER_NAME}/{timestamp}.png"

                            # 3. GitHubへプッシュ
                            g = Github(github_token)
                            repo = g.get_repo(GITHUB_REPO_NAME)
                            repo.create_file(file_name, f"Add image {timestamp}", img_data, branch="main")
                            
                            st.success(f"✅ 保存成功！\nGitHubのInboxに追加されました。\n管理者は 'git pull' で取得できます。")
                        except Exception as e:
                            st.error(f"保存失敗: {e}")
                else:
                    st.error("⚠️ GitHubトークンが設定されていません。管理者に連絡してください。")

else:
    st.info("👈 APIキー設定が必要です。")
