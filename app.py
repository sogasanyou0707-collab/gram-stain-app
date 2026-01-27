
import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
from PIL import Image
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア（アプリっぽくする設定） ===
# page_title: ホーム画面に追加する時の名前になります（短めがおすすめ）
# page_icon: ブラウザタブのアイコンになります
st.set_page_config(
    page_title="GramAI", 
    page_icon="🦠", 
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- CSSで見た目をアプリ風にする（余計な表示を消す） ---
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

# --- モデル設定 ---
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

# サイドバー（隠しておく設定にしましたが、左上の矢印で出せます）
st.sidebar.header("🤖 設定")
if model_options:
    selected_model_name = st.sidebar.selectbox("モデル", model_options, index=0)
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

# フォルダ確認（サイドバーへ移動）
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

        if st.button("AIで解析する", use_container_width=True): # ボタンを大きく
            if len(valid_categories) == 0:
                st.error("比較用の菌フォルダがGoogleドライブにありません。")
            else:
                categories_str = ", ".join(valid_categories)
                with st.spinner(f'AI ({selected_model_name}) が解析中...'):
                    try:
                        # ★プロンプト（指定されたバージョン）
                        prompt = f"""
                        あなたは臨床微生物学の専門家です。以下の精密な基準で診断してください。

                        【STEP 1: 色の判定 (修正版)】
                        
                        * **A. グラム陽性 (G+)**:
                          * **色**: 紫色、濃青色、黒色。
                          * **特例**: 菌体が非常に濃い黒紫色であれば、背景がピンクでも、あるいは菌の一部が脱色して赤っぽくなっていても、**基本は「陽性」**と判定してください。(Gram-variable Bacillusの考慮)
                        
                        * **B. グラム陰性 (G-)**:
                          * **色**: 明るい赤色、ピンク色。
                          * **条件**: 菌全体が均一に赤く染まっていること。

                        【STEP 2: 形態鑑別 (大型桿菌ルール)】
                        
                        1. **Bacillus / Clostridium (Large GPR)**:
                           * **特徴**: 非常に太く、大きい桿菌 (Box-car shape)。
                           * **判定**: この形状が見えたら、多少色が赤っぽくても **GPR** と診断してください。(古い培養菌は陰性に見えることがあるため)

                        2. **Staphylococcus (GPC)**:
                           * **特徴**: 正円形、クラスター。

                        3. **Streptococcus (GPC)**:
                           * **特徴**: 楕円・ランセット状、連鎖、双球菌。

                        4. **GNR (Gram-Negative Rods)**:
                           * **特徴**: 陽性桿菌に比べて細い、小さい。全体がピンク色。
                           * **注意**: 赤紫色で短い球桿菌はGNR。

                        【STEP 3: 最終診断】
                        * 「黒紫色」で「太い棒状」 → **GPR (Bacillus/Clostridium)**
                        * 「ピンク色」で「細い棒状」 → **GNR**
                        * 「紫色」で「正円クラスター」 → **Staphylococcus**
                        * 「紫色」で「ランセット状双球菌」 → **Streptococcus**

                        【出力フォーマット】
                        1. **所見**:
                           （色、サイズ[太い/細い]、形状）
                        
                        2. **鑑別診断**:
                           * **検出菌**: [菌種名]
                             理由: [色とサイズに基づき論理的に]

                        3. **最も近いカテゴリ**:
                           リスト: [{categories_str}]
                           ※複数ある場合はカンマ区切り。
                        
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
