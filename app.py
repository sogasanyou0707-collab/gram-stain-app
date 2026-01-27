import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
from PIL import Image
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア ===
st.set_page_config(
    page_title="GramAI", 
    page_icon="🦠", 
    layout="centered",
    initial_sidebar_state="collapsed"
)

# スタイル調整
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .stApp {margin-top: -80px;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

st.title("🔬 グラム染色 AI")

# --- Secrets ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

GAS_APP_URL = st.secrets["GAS_APP_URL"] if "GAS_APP_URL" in st.secrets else None
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"] if "DRIVE_FOLDER_ID" in st.secrets else None

# --- モデル設定 (Flash優先) ---
model_options = []
if api_key:
    try:
        genai.configure(api_key=api_key)
        all_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                name = m.name.replace("models/", "")
                all_models.append(name)
        flash_models = sorted([m for m in all_models if "flash" in m.lower()], reverse=True)
        other_models = sorted([m for m in all_models if "flash" not in m.lower()], reverse=True)
        model_options = flash_models + other_models
    except:
        model_options = ["gemini-1.5-flash", "gemini-1.5-pro"]

st.sidebar.header("🤖 使用モデル")
if model_options:
    selected_model_name = st.sidebar.selectbox("モデルを選択", model_options, index=0)
else:
    selected_model_name = "gemini-1.5-flash"

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

# サイドバー
with st.sidebar:
    st.markdown("---")
    st.markdown("### 📂 認識中のフォルダ")
    with st.spinner('Loading...'):
        raw_list = fetch_categories_from_drive()
        valid_categories = [
            c for c in raw_list 
            if c not in ["Inbox", "my_gram_app", "pycache", "__pycache__"] 
            and not c.startswith(".")
        ]
        if len(valid_categories) == 0:
            st.warning("フォルダなし")
        else:
            st.write(valid_categories)

# --- メイン処理 ---
if api_key:
    try:
        model = genai.GenerativeModel(selected_model_name)
    except:
        model = genai.GenerativeModel("gemini-1.5-flash")

    uploaded_file = st.file_uploader("写真を撮影 または 選択", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption='解析対象', use_container_width=True)

        if st.button("AIで解析する", use_container_width=True):
            if len(valid_categories) == 0:
                st.error("比較用の菌フォルダがGoogleドライブにありません。")
            else:
                categories_str = ", ".join(valid_categories)
                with st.spinner(f'AI ({selected_model_name}) が解析中...'):
                    try:
                        # ★プロンプト（ver10.17の論理的思考プロセス版を維持）
                        prompt = f"""
                        あなたは臨床微生物学の専門家です。
                        画像を見て、以下の【思考プロセス】の手順通りに観察を行い、論理的に診断してください。
                        いきなり結論を出さず、必ずステップごとに確認してください。

                        【思考プロセス】

                        1. **色の確認（絶対基準）**:
                           * 菌体の色は **赤/ピンク** ですか？ それとも **紫/青** ですか？
                           * 赤/ピンクなら → 絶対に **グラム陰性 (Gram-Negative)** です。
                             * 注意: 赤い Corynebacterium や 赤い Staphylococcus は存在しません。
                           * 紫/青なら → **グラム陽性 (Gram-Positive)** です。

                        2. **個々の形の確認**:
                           * **球菌 (Cocci)**: 完全な丸、または少し尖った丸。
                           * **桿菌 (Rods)**: 細長い棒状。短くても側面が平行なら桿菌です。
                             * 重要: Corynebacterium は「不規則な棒状（こん棒状）」であり、丸（Cocci）ではありません。

                        3. **矛盾チェック（自己添削）**:
                           * 「GNR（赤色）なのに Corynebacterium（陽性菌）と判断していないか？」→ 赤ならGNRです。
                           * 「棒状（Rod）なのに GPC（球菌）と判断していないか？」→ 棒状ならGPRかGNRです。

                        4. **最終診断**:
                           * 赤色 + 桿菌 → **GNR**
                           * 紫色 + 丸い + クラスター → **Staphylococcus**
                           * 紫色 + 少し尖った丸 + 双球菌 → **Streptococcus**
                           * 紫色 + 不規則な棒状 + V字/柵状 → **Corynebacterium**
                           * 紫色 + 太い棒状 → **Bacillus / Clostridium**

                        【出力フォーマット】
                        1. **観察所見**:
                           * 色: [赤/ピンク または 紫/青]
                           * 形: [球菌 または 桿菌]
                           * 配列: [クラスター/連鎖/散在/V字など]
                        
                        2. **論理的推論**:
                           * 「色が〇〇であり、形が〇〇であるため、[菌種グループ]と考えられます。」
                           * 否定根拠: 「色は似ているが、形が〇〇ではないため、xxではありません。」

                        3. **最も近いカテゴリ**:
                           リスト: [{categories_str}]
                           ※確信度が高い順に。
                        
                        最後に必ず「CATEGORY:カテゴリ名」の形式で出力してください。
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
            display_text = text.replace("CATEGORY:", "") 
            st.write(display_text)
            
            match_categories = []
            for line in text.split('\n'):
                if "CATEGORY:" in line:
                    cats_str = line.split("CATEGORY:")[1].strip()
                    cats_str = cats_str.replace("、", ",")
                    match_categories = [c.strip() for c in cats_str.split(',')]
            
            if match_categories:
                st.markdown("---")
                st.markdown("#### 📚 参考画像ライブラリー")
                cols = st.columns(len(match_categories))
                
                for i, category in enumerate(match_categories):
                    if category in valid_categories and category != "None":
                        if GAS_APP_URL:
                            with cols[i]:
                                with st.spinner(f"取得中: {category}..."):
                                    try:
                                        res = requests.get(GAS_APP_URL, params={"action": "get_image", "category": category}, timeout=15)
                                        data = res.json()
                                        if data.get("found"):
                                            img_data = base64.b64decode(data["image"])
                                            ref_image = Image.open(io.BytesIO(img_data))
                                            st.image(ref_image, caption=f'{category}', use_container_width=True)
                                        else:
                                            st.caption(f"※{category}: 画像なし")
                                    except:
                                        st.caption(f"※{category}: エラー")

            st.write("---")
            if st.button("☁️ Googleドライブに保存", use_container_width=True):
                if GAS_APP_URL and DRIVE_FOLDER_ID:
                    with st.spinner("保存中..."):
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
                            res = requests.post(GAS_APP_URL, json=payload)
                            if res.status_code == 200 and res.json().get('status') == 'success':
                                st.success(f"✅ 保存成功")
                            else:
                                st.error("保存失敗")
                        except Exception as e:
                            st.error(f"エラー: {e}")
