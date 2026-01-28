import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
# ★追加: ImageFilterをインポート
from PIL import Image, ImageFilter
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# 切り抜き用ライブラリ確認
try:
    from streamlit_cropper import st_cropper
except ImportError:
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

st.title("🔬 グラム染色 AI (Sharp & Resize)")

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

# ★追加: 画像のリサイズとシャープ化を行う関数
def process_image(img, max_width=800):
    # 1. リサイズ（横幅がmax_widthを超えていたら縮小）
    if img.width > max_width:
        ratio = max_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height), Image.LANCZOS)
    
    # 2. シャープ化（輪郭強調）
    # SHARPENフィルタを適用して輪郭をくっきりさせる
    sharpened_img = img.filter(ImageFilter.SHARPEN)
    return sharpened_img

# --- メイン処理 ---
if api_key:
    try:
        model = genai.GenerativeModel(selected_model_name)
    except:
        model = genai.GenerativeModel("gemini-1.5-flash")

    uploaded_file = st.file_uploader("写真を撮影 または 選択", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        # 画像を開く
        raw_image = Image.open(uploaded_file)
        
        # ★ここでリサイズとシャープ化を適用
        processed_image = process_image(raw_image)

        st.markdown("### ✂️ 解析エリアの指定 (自動補正済み)")
        st.info("画像は操作しやすいサイズに縮小され、輪郭がシャープに強調されています。四隅をドラッグして解析エリアを囲ってください。")
        
        # 切り抜き実行（処理済みの画像を使用）
        cropped_image = st_cropper(
            processed_image,
            realtime_update=True,
            box_color='#FF0000',
            aspect_ratio=None
        )

        st.markdown("---")
        st.markdown("### 🔍 解析プレビュー (シャープ化済み)")
        st.image(cropped_image, caption="AIはこのくっきりした画像を見て診断します", use_container_width=True)

        if st.button("このエリアを解析する", use_container_width=True):
            if len(valid_categories) == 0:
                st.error("比較用の菌フォルダがGoogleドライブにありません。")
            else:
                categories_str = ", ".join(valid_categories)
                with st.spinner(f'AI ({selected_model_name}) が集中解析中...'):
                    try:
                        # ★プロンプト (シャープ化前提の微細構造解析)
                        prompt = f"""
                        あなたは臨床微生物検査技師です。
                        提供された画像は、**輪郭強調（シャープ化）処理済み**の顕微鏡写真から、最適な部分を切り抜いたものです。
                        輪郭が強調されていることを前提に、菌の微細な構造を厳密に分析してください。

                        【観察の重要ポイント】
                        シャープ化により、菌体の境界線が明確になっています。「つながっているように見える部分」の境界をよく見てください。

                        1. **連鎖球菌 (Streptococcus) vs コリネバクテリウム (Corynebacterium)**:
                           * **連鎖球菌**: 球菌がつながっているため、菌と菌の間に必ず**「くびれ（凹み）」**があります。シャープ化された画像では、このくびれが明確に見えるはずです。
                           * **コリネバクテリウム**: 1本の棒状であるため、側面のラインは**「直線的で滑らか」**であり、深いくびれはありません。多少曲がっていても、球の連なりとは異なります。

                        【診断ロジック】
                        * **GPC連鎖**:
                          * 色は紫。形は丸または卵型。「くびれ」のある連鎖が見える。
                          * ※密集していても、個々の菌の輪郭が丸ければ球菌です。
                        * **GPR (コリネ型)**:
                          * 色は紫。形は不規則な棒状。側面が直線的で、くびれがない。V字配列などがある。
                        * **肺炎球菌**:
                          * 色は紫。ランセット状（尖った卵型）のペア。くびれは明瞭。

                        【出力フォーマット】
                        1. **所見 (微細構造)**:
                           * 色: [GPC / GNR]
                           * 基本形状: [球菌 / 桿菌]
                           * 境界部の特徴: [明確なくびれ有り / 直線的で滑らか]
                           * 配列: [双球菌 / 連鎖 / クラスター / V字 / 柵状]
                        
                        2. **推論**:
                           * 「形状が〇〇で、菌の連結部に明確な〇〇（くびれ等）が確認できるため、[菌種]と判断します。」
                           * 否定根拠: 「一見〇〇に見えるが、〇〇という特徴がないため、それは否定されます。」

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
                            st.session_state['last_image'] = cropped_image
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
                                'filename': f"{timestamp}_crop_sharp.png", # ファイル名にsharpを追加
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
