import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
from PIL import Image
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア ===
st.set_page_config(page_title="グラム染色AI ver10.3 (Diff)", page_icon="🔬")
st.title("🔬 グラム染色 AI (鑑別診断モード)")

# --- Secrets ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

GAS_APP_URL = st.secrets["GAS_APP_URL"] if "GAS_APP_URL" in st.secrets else None
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

# --- ライブラリ取得 ---
@st.cache_data(ttl=60)
def fetch_categories_from_drive():
    if not GAS_APP_URL:
        return []
    try:
        res = requests.get(GAS_APP_URL, params={"action": "list_categories"}, timeout=10)
        if res.status_code == 200:
            return res.json().get("categories", [])
    except:
        pass
    return []

# サイドバー確認用
st.sidebar.markdown("---")
st.sidebar.markdown("### 📂 認識中のフォルダ")
with st.spinner('Loading...'):
    raw_list = fetch_categories_from_drive()
    valid_categories = [
        c for c in raw_list 
        if c not in ["Inbox", "my_gram_app", "pycache", "__pycache__"] 
        and not c.startswith(".")
    ]
    if len(valid_categories) == 0:
        st.sidebar.warning("菌フォルダが見つかりません")
    else:
        st.sidebar.write(valid_categories)

# --- メイン処理 ---
if api_key:
    model = genai.GenerativeModel(selected_model_name)
    uploaded_file = st.file_uploader("写真を撮影 または 選択", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption='解析対象', use_container_width=True)

        if st.button("AIで解析する"):
            if len(valid_categories) == 0:
                st.error("比較用の菌フォルダ(GNR, GPCなど)がGoogleドライブにありません。")
            else:
                categories_str = ", ".join(valid_categories)
                with st.spinner('AIが思考中...'):
                    try:
                        # ★ここが改良版プロンプト！
                        prompt = f"""
                        あなたは臨床微生物学の専門家です。このグラム染色画像を詳細に分析してください。
                        
                        【思考プロセス】
                        まず画像を観察し、染色性（陽性/陰性）、形態（球菌/桿菌）、配列（連鎖/塊状/柵状など）、サイズなどを分析してください。
                        典型的なパターンだけでなく、「紛らわしい類似菌」の可能性も検討してください。

                        【出力フォーマット】
                        1. **所見**:
                           （染色性、形態、配列、サイズ感、背景など）
                        
                        2. **鑑別診断（可能性のある菌種）**:
                           * **第1候補**: [菌種名]
                             理由: ...
                           * **第2候補（鑑別）**: [菌種名]
                             理由: ...（例: 「球菌に見えるが、短桿菌（コリネバクテリウムなど）の可能性も否定できない」など）

                        3. **最も近いカテゴリ**:
                           以下のリストから、第1候補に最も近いものを1つ選んでください。
                           リスト: [{categories_str}]
                        
                        【重要】
                        最後に必ず「CATEGORY:カテゴリ名」という形式で1行だけ出力してください。
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

        # --- 結果表示 ---
        if 'last_result' in st.session_state:
            text = st.session_state['last_result']
            st.markdown("### 🤖 解析結果")
            
            # CATEGORY行だけ隠して表示
            display_text = text.replace("CATEGORY:", "") 
            st.write(display_text)
            
            match_category = None
            for line in text.split('\n'):
                if "CATEGORY:" in line:
                    match_category = line.split("CATEGORY:")[1].strip()
            
            # 参照画像
            if match_category and match_category != "None" and match_category in valid_categories:
                if GAS_APP_URL:
                    with st.spinner(f"☁️ 参照画像を取得: {match_category}"):
                        try:
                            res = requests.get(GAS_APP_URL, params={"action": "get_image", "category": match_category}, timeout=15)
                            data = res.json()
                            if data.get("found"):
                                img_data = base64.b64decode(data["image"])
                                ref_image = Image.open(io.BytesIO(img_data))
                                st.image(ref_image, caption=f'ライブラリー参照: {match_category}', use_container_width=True)
                            else:
                                st.caption("※フォルダ内に画像がありません")
                        except Exception as e:
                            st.caption(f"エラー: {e}")

            st
