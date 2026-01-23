import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
from PIL import Image
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア ===
st.set_page_config(page_title="グラム染色AI ver10.11 (Angle)", page_icon="🔬")
st.title("🔬 グラム染色AI (角度判定ロジック)")

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
    try:
        model = genai.GenerativeModel(selected_model_name)
    except:
        model = genai.GenerativeModel("gemini-1.5-flash")

    uploaded_file = st.file_uploader("写真を撮影 または 選択", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption='解析対象', use_container_width=True)

        if st.button("AIで解析する"):
            if len(valid_categories) == 0:
                st.error("比較用の菌フォルダがGoogleドライブにありません。")
            else:
                categories_str = ", ".join(valid_categories)
                with st.spinner(f'AI ({selected_model_name}) が解析中...'):
                    try:
                        # ★ここを修正：角度（Angle）による鑑別を追加
                        prompt = f"""
                        あなたは臨床微生物学の専門家です。以下の決定木に従って厳密に診断を行ってください。

                        【STEP 1: 色の判定（最優先・絶対ルール）】
                        * **A. 赤色・ピンク色** (Gram-Negative):
                          * 判定: **GNR** または **GNC**。
                          * 禁止: GPR, GPC, Yeast と診断してはいけません。

                        * **B. 紫色・濃青色** (Gram-Positive):
                          * 判定: GPC, GPR, Yeast のいずれかです。

                        【STEP 2: 紫色(G+菌)の形態鑑別ルール】
                        
                        1. **Staphylococcus (ブドウ球菌)**:
                           * 個々の菌体が「正円形」である。
                           * 配列が「立体的」で「ブドウの房状」のクラスターを作る。
                           
                        2. **Streptococcus (連鎖球菌・双球菌)** vs **GPR** の「2連(Pair)」鑑別:
                           ★ここが最重要ポイントです。2つの菌がつながっている場合、その「角度」を見てください。
                           
                           * **Streptococcus (GPC)**:
                             * 配列の軸が **「直線的 (Straight)」** である。(角度 180度)
                             * 4連以上の鎖がある場合は、問答無用で Streptococcus。
                             
                           * **Corynebacterium (GPR)**:
                             * 配列の軸が **「折れ曲がっている (Angled / V-shape)」**。(スナッピング分裂による角度)
                             * 「V字」「L字」「漢字の『八』の字」のような並びであれば GPR を選択。
                             * 個々の菌体が正円ではなく、やや不整形。

                        3. **Yeast (真菌)**:
                           * サイズが明らかに大きい、または卵円形。

                        【STEP 3: 混合感染の確認】
                        明らかに色の異なる2種類がいる場合は併記してください。

                        【出力フォーマット】
                        1. **所見**:
                           （色、形態、配列[直線性かV字か]）
                        
                        2. **鑑別診断**:
                           * **検出菌**: [菌種名]
                             理由: [角度や形状について言及すること]

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
            if st.button("☁️ Googleドライブに保存"):
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
