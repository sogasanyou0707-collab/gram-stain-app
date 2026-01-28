import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
from PIL import Image
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ★追加: 切り抜き用ライブラリ
try:
    from streamlit_cropper import st_cropper
except ImportError:
    # 万が一入っていない場合のフォールバック（エラーではなくメッセージを出す）
    st.error("⚠️ ライブラリ 'streamlit-cropper' が見つかりません。requirements.txtを確認してください。")
    st.stop()

# === 設定エリア ===
st.set_page_config(
    page_title="GramAI", 
    page_icon="🦠", 
    layout="centered",
    initial_sidebar_state="expanded" 
)

st.markdown("""
    <style>
    .stApp {margin-top: -20px;}
    </style>
    """, unsafe_allow_html=True)

st.title("🔬 グラム染色 AI")

# --- Secrets ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

GAS_APP_URL = st.secrets["GAS_APP_URL"] if "GAS_APP_URL" in st.secrets else None
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"] if "DRIVE_FOLDER_ID" in st.secrets else None

# --- モデル設定 ---
priority_models = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.5-pro-latest"]
model_options = ["gemini-1.5-flash"]

if api_key:
    try:
        genai.configure(api_key=api_key)
        all_models = [m.name.replace("models/", "") for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        sorted_models = []
        for p in priority_models:
            if p in all_models: sorted_models.append(p)
        for m in all_models:
            if m not in sorted_models: sorted_models.append(m)
        if sorted_models: model_options = sorted_models
    except:
        pass

with st.expander("🤖 モデル選択・設定", expanded=False):
    selected_model_name = st.selectbox("使用モデル", model_options, index=0)

# --- ライブラリ取得 ---
@st.cache_data(ttl=60)
def fetch_categories_from_drive():
    if not GAS_APP_URL: return []
    try:
        res = requests.get(GAS_APP_URL, params={"action": "list_categories"}, timeout=10)
        return res.json().get("categories", []) if res.status_code == 200 else []
    except:
        return []

valid_categories = [c for c in fetch_categories_from_drive() if c not in ["Inbox", "my_gram_app", "pycache", "__pycache__"] and not c.startswith(".")]

with st.sidebar:
    st.header("設定")
    st.write(f"選択中: {selected_model_name}")
    st.markdown("---")
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
        original_image = Image.open(uploaded_file)
        
        # ★新機能: 画像切り抜きツール
        st.markdown("### ✂️ 解析エリアの指定")
        st.info("画像の四隅をドラッグして、**「菌が綺麗に見えている場所」**だけを囲ってください。")
        
        # 切り抜き実行
        cropped_image = st_cropper(
            original_image,
            realtime_update=True,
            box_color='#FF0000', # 赤い枠
            aspect_ratio=None    # 自由な形
        )

        st.markdown("---")
        st.markdown("### 🔍 解析プレビュー")
        st.image(cropped_image, caption="AIはこの画像だけを見て診断します", use_container_width=True)

        if st.button("このエリアを解析する", use_container_width=True):
            if len(valid_categories) == 0:
                st.error("比較用の菌フォルダがGoogleドライブにありません。")
            else:
                categories_str = ", ".join(valid_categories)
                with st.spinner(f'AI ({selected_model_name}) が指定エリアを集中解析中...'):
                    try:
                        # プロンプト (切り抜き画像用)
                        prompt = f"""
                        あなたは臨床微生物検査技師です。
                        提供された画像は、顕微鏡視野の中から**「最も観察に適した部分」を選んで切り抜いたもの**です。
                        画像内の細菌の特徴を詳細に分析し、菌種を推定してください。

                        【観察手順】
                        1. **菌の形状**:
                           * 完全な「球（真円）」か？
                           * 少し伸びた「卵型/ランセット状」か？
                           * 明らかな「棒状（桿菌）」か？
                        
                        2. **菌の配列**:
                           * 双球菌（ペア）か？
                           * 連鎖か？
                           * クラスター（塊）か？
                           * 柵状・V字か？

                        3. **診断ロジック**:
                           * **肺炎球菌 (Strep. pneumoniae)**: 
                             * 特徴: ランセット状（涙型）の双球菌。
                             * 鑑別点: 桿菌と間違えやすいが、よく見ると「2つの尖った球」のセットである。
                           * **コリネバクテリウム (Corynebacterium)**:
                             * 特徴: 不規則な多形性を持つ桿菌。V字や柵状配列。
                           * **ブドウ球菌 (Staphylococcus)**:
                             * 特徴: 均一なサイズの真円。クラスター形成。

                        【出力フォーマット】
                        1. **所見**:
                           * 色: [GPC / GNR]
                           * 形: [真円 / 卵型 / 桿菌]
                           * 配列: [双球菌 / 連鎖 / クラスター / V字]
                        
                        2. **推論**:
                           * 「形状が〇〇で、配列が〇〇であるため、[菌種]が強く疑われます。」
                           * ※肺炎球菌の場合は「桿菌のように見えるが、ランセット状双球菌の特徴がある」等と記述。

                        3. **最も近いカテゴリ**:
                           リスト: [{categories_str}]

                        最後に必ず「CATEGORY:カテゴリ名」を出力。
                        """
                        
                        safety_settings = {
                            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                        }
                        
                        response = model.generate_content([prompt, cropped_image], safety_settings=safety_settings)
                        if response.text:
                            st.session_state['last_result'] = response.text
                            st.session_state['last_image'] = cropped_image # 保存用も切り抜き画像にする
                    except Exception as e:
                        if "429" in str(e):
                            st.error("⚠️ AIの利用制限にかかりました。")
                        else:
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
            if st.button("☁️ Googleドライブに保存 (切り抜き画像を保存)", use_container_width=True):
                if GAS_APP_URL and DRIVE_FOLDER_ID:
                    with st.spinner("保存中..."):
                        try:
                            img_byte_arr = io.BytesIO()
                            st.session_state['last_image'].save(img_byte_arr, format='PNG')
                            img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            payload = {
                                'image': img_base64,
                                'filename': f"{timestamp}_crop.png",
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

