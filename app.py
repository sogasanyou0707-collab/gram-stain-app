import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
from PIL import Image
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア ===
st.set_page_config(page_title="グラム染色AI ver10.0 (Cloud Lib)", page_icon="🔬")
st.title("🔬 グラム染色 AI (完全クラウド版)")

# --- Secrets取得 ---
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

# --- ライブラリ情報の取得 (Googleドライブから) ---
@st.cache_data(ttl=300) # 5分間は結果を覚えておく（高速化）
def fetch_categories_from_drive():
    if not GAS_APP_URL:
        return []
    try:
        # GASに「フォルダ一覧ちょーだい」と聞く
        res = requests.get(GAS_APP_URL, params={"action": "list_categories"}, timeout=10)
        if res.status_code == 200:
            return res.json().get("categories", [])
    except:
        pass
    return []

# アプリ起動時にドライブからカテゴリ一覧を取得
with st.spinner('Googleドライブから最新のライブラリを読み込み中...'):
    categories = fetch_categories_from_drive()
    if categories:
        categories_str = ", ".join(categories)
        st.success(f"📚 クラウド・ライブラリー連携中: {len(categories)} 種の菌データを認識")
    else:
        categories_str = "なし"
        st.warning("⚠️ ライブラリーを読み込めませんでした（GAS設定を確認してください）")

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

        # --- 結果表示 ---
        if 'last_result' in st.session_state:
            text = st.session_state['last_result']
            st.markdown("### 🤖 解析結果")
            st.write(text.replace("CATEGORY:", ""))
            
            # カテゴリ抽出
            match_category = None
            for line in text.split('\n'):
                if "CATEGORY:" in line:
                    match_category = line.split("CATEGORY:")[1].strip()
            
            # ★ドライブから参照画像を取得して表示
            if match_category and match_category != "None" and match_category in categories:
                if GAS_APP_URL:
                    with st.spinner(f"☁️ Googleドライブから {match_category} の画像を取得中..."):
                        try:
                            # GASに「このカテゴリの画像を1枚ちょーだい」と聞く
                            res = requests.get(GAS_APP_URL, params={"action": "get_image", "category": match_category}, timeout=15)
                            data = res.json()
                            if data.get("found"):
                                # Base64を画像に戻す
                                img_data = base64.b64decode(data["image"])
                                ref_image = Image.open(io.BytesIO(img_data))
                                st.image(ref_image, caption=f'Googleドライブ参照画像: {match_category}', use_container_width=True)
                            else:
                                st.caption("※ドライブ内のフォルダに画像が見つかりませんでした")
                        except Exception as e:
                            st.caption(f"画像取得エラー: {e}")

            st.write("---")
            
            # 保存ボタン
            if st.button("☁️ Googleドライブに保存"):
                if GAS_APP_URL and DRIVE_FOLDER_ID:
                    with st.spinner("転送中..."):
                        try:
                            img_byte_arr = io.BytesIO()
                            st.session_state['last_image'].save(img_byte_arr, format='PNG')
                            img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            
                            payload = {
                                'image': img_base64,
                                'filename': f"{timestamp}.png",
                                'folderId': DRIVE_FOLDER_ID,
                                'mimeType': 'image/png'
                            }
                            response = requests.post(GAS_APP_URL, json=payload)
                            if response.status_code == 200 and response.json().get('status') == 'success':
                                st.success(f"✅ 保存成功！")
                            else:
                                st.error("保存失敗")
                        except Exception as e:
                            st.error(f"エラー: {e}")
                else:
                    st.error("⚠️ 設定不足")
