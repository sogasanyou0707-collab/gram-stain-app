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
    initial_sidebar_state="expanded" # サイドバーを開いた状態で開始
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

# --- モデル設定 (バージョン番号順にソート) ---
model_options = []
if api_key:
    try:
        genai.configure(api_key=api_key)
        all_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                name = m.name.replace("models/", "")
                all_models.append(name)
        
        # 名前で降順ソート（例: gemini-3.0 -> gemini-2.0 -> gemini-1.5）
        # これにより、数字が大きい最新モデルが先頭に来ます
        model_options = sorted(all_models, reverse=True)
    except:
        # エラー時のフォールバック
        model_options = ["gemini-1.5-pro-latest", "gemini-1.5-flash"]

# サイドバー（復活）
st.sidebar.header("🤖 モデル選択")
if model_options:
    # リストの先頭（最新モデル）をデフォルトにする
    selected_model_name = st.sidebar.selectbox("使用するAIモデル", model_options, index=0)
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

# サイドバー: フォルダ情報
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
                        # プロンプト (物理的特徴解析版)
                        prompt = f"""
                        あなたは画像解析アルゴリズムです。医学的な推測をする前に、画像の物理的な特徴を厳密に解析してください。
                        背景色（ピンクや赤のモヤ）は「ノイズ」として完全に無視し、**「輪郭のはっきりした濃い物体」**だけを見てください。

                        【Step 1: 色彩強度解析】
                        画像の中で最も「色が濃く、輪郭がはっきりしている粒子」を探してください。
                        * その粒子は **黒・濃い紫・濃紺** ですか？ → はいの場合: **Gram Positive (陽性)** で確定。
                          (※背景がどれだけ赤くても、主役の粒子が黒ければ陽性です)
                        * その粒子は **赤・ピンク・薄い赤** だけですか？ → はいの場合: **Gram Negative (陰性)** です。

                        【Step 2: 幾何学形状解析】
                        検出した粒子を1つ拡大して見てください。
                        * **アスペクト比（縦横比）の測定**:
                          * 縦と横の長さがほぼ同じ（1:1〜1:1.2）の「真円」ですか？ → **Cocci (球菌)**
                          * 少しでも縦に長い（1:1.5以上）、または楕円、こん棒状、長方形ですか？ → **Rods (桿菌)**
                        
                        【Step 3: コリネバクテリウム判定の特別ルール】
                        * 多くの細菌が「V字」や「文字のような並び」を形成していますか？
                        * 粒子の一つ一つを見ると、片方が太く、片方が細い（涙型・こん棒状）ですか？
                        * **重要**: もし「球菌か桿菌か迷う（少し長い気がする）」場合は、**必ず「桿菌 (Corynebacterium疑い)」**と判定してください。球菌は「完全な円」だけです。

                        【Step 4: 最終出力】
                        上記解析に基づき、以下の最も近いカテゴリを1つ選んでください。
                        候補リスト: [{categories_str}]

                        出力形式:
                        1. **画像解析**:
                           * ターゲット色: [黒紫 / 赤] (背景は無視)
                           * 粒子形状: [真円 / 楕円・棒状]
                           * 特徴: [V字配列 / クラスター / 連鎖 / 散在]
                        
                        2. **判定**:
                           * 色判定: [GPC / GNR / GPR]
                           * 理由: [形状と色の物理的特徴]

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
            display_text = text.replace("CATEGORY:", "") 
            st.write(display_text)
            
            match_categories = []
            for line in text.split('\n'):
                if "CATEGORY:" in line:
                    cats_str = line.split("CATEGORY:")[1].strip()
                    cats_str = cats_str.replace("、", ",")
