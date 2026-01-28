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

# --- モデル設定 (安定版優先) ---
priority_models = [
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-1.5-pro-latest",
]

model_options = []
if api_key:
    try:
        genai.configure(api_key=api_key)
        all_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                name = m.name.replace("models/", "")
                all_models.append(name)
        
        sorted_models = []
        for p in priority_models:
            if p in all_models:
                sorted_models.append(p)
        for m in all_models:
            if m not in sorted_models:
                sorted_models.append(m)
        model_options = sorted_models
    except:
        model_options = ["gemini-1.5-flash", "gemini-1.5-pro"]
else:
    model_options = ["gemini-1.5-flash"]

with st.expander("🤖 モデル選択・設定", expanded=True):
    selected_model_name = st.selectbox("使用モデル", model_options, index=0)

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

valid_categories = []
raw_list = fetch_categories_from_drive()
valid_categories = [
    c for c in raw_list 
    if c not in ["Inbox", "my_gram_app", "pycache", "__pycache__"] 
    and not c.startswith(".")
]

with st.sidebar:
    st.header("設定")
    st.write(f"選択中: {selected_model_name}")
    st.markdown("---")
    st.markdown("### 📂 認識中のフォルダ")
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
                        # ★プロンプト (密集除外・単離菌フォーカス版)
                        prompt = f"""
                        あなたは臨床微生物検査技師です。以下の手順を厳守し、慎重に鏡検を行ってください。

                        【Step 0: 観察エリアの選定 (最重要)】
                        画像全体を見て、菌が密集して重なり合っている「塊（クラスター）」部分は **全て無視** してください。
                        それらの重なりは「V字」や「桿菌」に見える偽像（アーチファクト）の原因になります。
                        
                        * **指示**: 画像の端や、菌がまばらに散らばっている部分にある **「孤立した菌（単離菌）」だけ** を探してください。
                        * **条件**: 他の菌と接触していない、あるいはせいぜい2個（ペア）で存在している菌だけを評価対象とします。

                        【Step 1: 単離菌の形態評価】
                        選定した「孤立した菌」について、以下の特徴を確認してください。
                        
                        * **形状**: 
                          * 完全な「球（真ん丸）」ですか？
                          * 少し尖った「卵型 / ランセット状」ですか？（→ 肺炎球菌の疑い）
                          * 明らかな「棒状（側面が平行）」ですか？
                        * **サイズ**: 
                          * 周囲の白血球や他のゴミと比較して、極端に小さいですか？
                          * 陽性桿菌としては小さすぎませんか？

                        【Step 2: 菌種推定のロジック】
                        
                        1. **Streptococcus pneumoniae (肺炎球菌) パターン**:
                           * 色: GPC (紫)
                           * 形: ランセット状（双球菌）。少し伸びているため、密集部では桿菌に見えやすいが、単離部では「2個ペアの卵型」に見える。
                           * **重要**: コリネバクテリウムとの違いは、「V字ではなく、縦に2つ並んでいること」です。

                        2. **Corynebacterium (コリネバクテリウム) パターン**:
                           * 色: GPR (紫)
                           * 形: 不規則な棒状。
                           * 条件: 単離部でも明らかに「棒」に見える場合のみ判定する。密集部のV字は信用しないこと。

                        3. **Staphylococcus (ブドウ球菌) パターン**:
                           * 色: GPC (紫)
                           * 形: どの菌を見ても、サイズが均一な「完全な球形」であること。

                        【Step 3: 最終出力】
                        観察した「単離菌」の特徴に基づき、以下のフォーマットで出力してください。

                        1. **観察所見 (密集部は除外)**:
                           * 観察対象: [密集部を避け、単離した菌を観察]
                           * 色調: [GPC / GNR 等]
                           * 個々の形態: [真円 / 卵型・ランセット状 / 棒状]
                           * 配列（単離部）: [双球菌 / 短連鎖 / 散在]
                        
                        2. **推論**:
                           * 「密集部では〇〇のように見えるが、単離した菌を見ると〇〇であるため、[菌種]と考えられます。」

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
                        response = model.generate_content([prompt, image], safety_settings=safety_settings)
                        if response.text:
                            st.session_state['last_result'] = response.text
                            st.session_state['last_image'] = image
                    except Exception as e:
                        if "429" in str(e):
                            st.error("⚠️ AIの利用制限にかかりました。少し待つか、モデルをFlashに変更してください。")
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
