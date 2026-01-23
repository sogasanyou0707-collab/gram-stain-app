import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
from PIL import Image
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア ===
st.set_page_config(page_title="グラム染色AI ver10.7 (Auto-Latest)", page_icon="🔬")
st.title("🔬 グラム染色AI (最新モデル対応版)")

# --- Secrets ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

GAS_APP_URL = st.secrets["GAS_APP_URL"] if "GAS_APP_URL" in st.secrets else None
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"] if "DRIVE_FOLDER_ID" in st.secrets else None

# --- モデル設定（★ここを完全自動化）---
model_options = []
default_index = 0

if api_key:
    try:
        genai.configure(api_key=api_key)
        # 1. APIから現在使える全モデルを取得
        all_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                name = m.name.replace("models/", "")
                all_models.append(name)
        
        # 2. 並び替えロジック
        # Flash系を優先的に先頭に集める（特にバージョン数字が大きい順）
        flash_models = sorted([m for m in all_models if "flash" in m.lower()], reverse=True)
        other_models = sorted([m for m in all_models if "flash" not in m.lower()], reverse=True)
        
        # Flashを先頭に、残りを後ろに結合
        model_options = flash_models + other_models
        
    except Exception as e:
        st.sidebar.error(f"モデル取得エラー: {e}")
        # 万が一取得できない場合の非常用フォールバック（ユーザー指定の新しいものを含む）
        model_options = ["gemini-2.0-flash-exp", "gemini-1.5-flash", "gemini-1.5-pro"]

# サイドバー表示
st.sidebar.header("🤖 使用モデル")
if model_options:
    selected_model_name = st.sidebar.selectbox("モデルを選択", model_options, index=0)
    st.sidebar.caption(f"※{selected_model_name} を使用中")
else:
    st.sidebar.warning("APIキーを入力してください")
    selected_model_name = "gemini-1.5-flash" # 仮


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

# サイドバー確認
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
                        # ★診断ロジック（連鎖球菌重視）
                        prompt = f"""
                        あなたは臨床微生物学の専門家です。画像を分析し、以下の厳格なルールに基づいて診断してください。

                        【診断の鉄則（優先順位）】
                        
                        1. **連鎖球菌（Streptococcus）の絶対ルール**:
                           * 画像内に**「明らかな連鎖（4連以上の数珠つなぎ）」**が見られる場合は、**問答無用で Streptococcus** と診断してください。
                           * この場合、GPR（コリネバクテリウム）の可能性は**完全に除外**してください。

                        2. **ブドウ球菌 vs GPR の鑑別**:
                           * 明らかな連鎖がなく、「クラスター（塊）」や「散在」している場合：
                             * 基本は **Staphylococcus** を疑う。
                             * ただし、個々の菌体が「楕円形・短桿菌様」であったり、「不規則な並び」がある場合のみ、**Corynebacterium (GPR)** を鑑別に挙げる。

                        3. **色のルール**:
                           * 赤色なら **GNR** (またはGNC)。GPRとは診断しないこと。

                        【出力フォーマット】
                        1. **所見**:
                           （染色性、形態、配列）
                        
                        2. **鑑別診断**:
                           * **第1候補**: [菌種名]
                             理由: [簡潔に]
                           * **第2候補**: [菌種名]（※必要な場合のみ）

                        3. **最も近いカテゴリ**:
                           リスト: [{categories_str}]
                        
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
            display_text = text.replace("CATEGORY:", "") 
            st.write(display_text)
            
            match_category = None
            for line in text.split('\n'):
                if "CATEGORY:" in line:
                    match_category = line.split("CATEGORY:")[1].strip()
            
            if match_category and match_category != "None" and match_category in valid_categories:
                if GAS_APP_URL:
                    with st.spinner(f"☁️ 参照画像: {match_category}"):
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
