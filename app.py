import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
import os
from PIL import Image, ImageFilter
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア ===
st.set_page_config(
    page_title="GramAI", 
    page_icon="🦠", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stApp {margin-top: -20px;}
    .stImage {overflow-x: auto;}
    </style>
    """, unsafe_allow_html=True)

st.title("🔬 グラム染色 AI (v10.41: 背景誤認対策)")

# --- 秘密情報の取得 ---
api_key = None
GAS_APP_URL = None
DRIVE_FOLDER_ID = None

try:
    if dict(st.secrets):
        if "GEMINI_API_KEY" in st.secrets: api_key = st.secrets["GEMINI_API_KEY"]
        if "GAS_APP_URL" in st.secrets: GAS_APP_URL = st.secrets["GAS_APP_URL"]
        if "DRIVE_FOLDER_ID" in st.secrets: DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
except Exception:
    pass

# --- 学習ルールの読み書き関数 ---
RULE_FILE = "learning_rules.txt"

def load_rules():
    if os.path.exists(RULE_FILE):
        with open(RULE_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def save_rule(new_rule):
    with open(RULE_FILE, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y/%m/%d")
        f.write(f"\n- [{timestamp}] {new_rule}")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 設定")
    if not api_key:
        api_key = st.text_input("Gemini APIキー", type="password")
    
    st.info("Logic: 背景ピンク除外 & 学習型")

    # --- 学習機能エリア ---
    st.markdown("---")
    st.markdown("### 🧠 AIへの教育")
    st.caption("「背景のピンクを菌と間違えるな」などのルールは、ここに書いて保存してください。")
    
    current_rules = load_rules()
    with st.expander("現在の学習済みルールを見る"):
        st.text(current_rules if current_rules else "まだ学習データはありません。")

    new_feedback = st.text_area("新しいルールを追加", placeholder="例: ピンク色でも輪郭がボヤけていたら背景のゴミとみなす")
    
    if st.button("学習させる (ルール保存)"):
        if new_feedback:
            save_rule(new_feedback)
            st.success("ルールを保存しました！次回から適用されます。")
            st.rerun()

    # --- フォルダ情報 ---
    @st.cache_data(ttl=60)
    def fetch_categories_from_drive():
        if not GAS_APP_URL: return []
        try:
            res = requests.get(GAS_APP_URL, params={"action": "list_categories"}, timeout=10)
            return res.json().get("categories", []) if res.status_code == 200 else []
        except:
            return []

    valid_categories = [c for c in fetch_categories_from_drive() if c not in ["Inbox", "my_gram_app", "pycache", "__pycache__"] and not c.startswith(".")]
    
    if valid_categories:
        st.markdown("---")
        st.write("📂 登録カテゴリ:", valid_categories)

# --- 画像処理関数 ---
def process_image(img, target_width):
    img = img.convert("RGB")
    ratio = target_width / img.width
    new_height = int(img.height * ratio)
    img = img.resize((target_width, new_height), Image.LANCZOS)
    sharpened_img = img.filter(ImageFilter.SHARPEN)
    return sharpened_img

# --- メイン処理 ---
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
    except:
        model = genai.GenerativeModel("gemini-1.5-flash")

    uploaded_file = st.file_uploader("画像をアップロード (1000倍視野)", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        try:
            raw_image = Image.open(uploaded_file)

            st.markdown("### 🔍 画像確認")
            img_display_width = st.slider(
                "表示サイズ調整", min_value=600, max_value=2500, value=1000, step=100
            )
            
            processed_image = process_image(raw_image, img_display_width)
            st.image(processed_image, caption="解析対象画像", use_container_width=True)

            st.markdown("---")
            
            if st.button("AI解析開始 (学習データ適用)", use_container_width=True):
                categories_str = ", ".join(valid_categories) if valid_categories else "登録なし"
                learned_rules = load_rules()
                
                with st.spinner(f'背景ノイズを除去し、学習ルールを適用中...'):
                    try:
                        # ★背景誤認を防ぐための強化プロンプト
                        prompt = f"""
                        あなたは臨床微生物検査技師です。光学顕微鏡の1000倍視野画像を解析します。

                        【最重要ルール: ユーザー学習データ】
                        以下の過去の指摘を絶対遵守してください:
                        {learned_rules}
                        --------------------------------------------------

                        【観察手順: 背景と菌の分離】
                        画像全体をスキャンしますが、**「ピンク色の背景」に騙されないでください。**
                        
                        * **菌体**: 明確な「輪郭（エッジ）」があり、コントラストがはっきりしている。
                        * **背景**: ピンク色だが、輪郭がボヤけている、雲のようなモヤ、不定形の粘液。
                        * → **輪郭が不明瞭なピンク色はすべて「背景（ゴミ）」として無視**し、診断対象に入れないでください。

                        【診断ロジック】
                        以下の手順①〜④に従って判定すること。

                        ① **グラム染色性 (背景除外後)**:
                           * **グラム陽性 (G+)**: 青紫、紺色。
                           * **グラム陰性 (G-)**: 
                             濃い赤〜ピンク。**ただし、明確な桿菌/球菌の形をしているものに限る。**
                             形が定まらないピンクはG-ではない。

                        ② **形状判定 (アスペクト比とくびれ)**:
                           * **1.0 〜 1.5**: 球菌 (Cocci)
                           * **1.5 以上**: 
                             **★くびれ確認★**: くびれ有=連鎖球菌、くびれ無=桿菌。

                        ③ **配列・集落パターン**:
                           * **ブドウ球菌**: 立体的なクラスター。
                           * **連鎖球菌**: 双球菌または連鎖が80％以上。

                        ④ **サイズ感 (1000倍視野)**:
                           * **大型**: 赤血球(約7µm)の半分〜同等(3-5µm) → Bacillus/Clostridium等。
                           * **小型**: 赤血球より遥かに小さい(約1µm) → 肺炎球菌、ブドウ球菌、コリネ等。

                        【出力フォーマット】
                        1. **観察所見**:
                           * 染色性: [G+ / G-] (※背景のピンクは無視済み)
                           * 形状: [球菌 / 桿菌]
                           * 配列: [ブドウ房 / 連鎖 / 不規則]
                           * サイズ: [大型 / 小型]
                        
                        2. **推論**:
                           * 「背景のピンク色は粘液成分として除外しました。明確な輪郭を持つ菌体は〇〇であるため...」

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
                        
                        response = model.generate_content([prompt, processed_image], safety_settings=safety_settings)
                        if response.text:
                            st.session_state['last_result'] = response.text
                            st.session_state['last_image'] = processed_image
                    except Exception as e:
                        st.error(f"解析エラー: {e}")

            # 結果表示
            if 'last_result' in st.session_state:
                st.markdown("---")
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
                    st.markdown("#### 📚 参考画像")
                    cols = st.columns(len(match_categories))
                    for i, category in enumerate(match_categories):
                        if category in valid_categories and category != "None":
                            if GAS_APP_URL:
                                with cols[i]:
                                    with st.spinner(f"取得中..."):
                                        try:
                                            res = requests.get(GAS_APP_URL, params={"action": "get_image", "category": category}, timeout=10)
                                            data = res.json()
                                            if data.get("found"):
                                                img_data = base64.b64decode(data["image"])
                                                st.image(Image.open(io.BytesIO(img_data)), caption=category, use_container_width=True)
                                        except:
                                            pass
                
                st.markdown("---")
                st.markdown("### 💾 正解データの蓄積")
                st.caption("AIの精度向上のため、正しい菌種を選んで保存してください。")
                correct_label = st.selectbox("正しい菌種を選択", ["選択してください"] + valid_categories)
                
                if st.button("正解として保存する", use_container_width=True):
                    if correct_label != "選択してください" and GAS_APP_URL and DRIVE_FOLDER_ID:
                        with st.spinner("学習データとして保存中..."):
                            try:
                                img_byte_arr = io.BytesIO()
                                st.session_state['last_image'].save(img_byte_arr, format='PNG')
                                img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                payload = {
                                    'image': img_base64,
                                    'filename': f"CORRECT_{correct_label}_{timestamp}.png",
                                    'folderId': DRIVE_FOLDER_ID,
                                    'mimeType': 'image/png'
                                }
                                requests.post(GAS_APP_URL, json=payload)
                                st.success(f"✅ 「{correct_label}」の正解データとして保存しました。")
                            except:
                                st.error("保存失敗")

        except Exception as e:
            st.error(f"画像エラー: {e}")
