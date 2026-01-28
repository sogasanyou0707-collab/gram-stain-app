import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
import os
from PIL import Image, ImageFilter
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア (ワイドモード) ===
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

st.title("🔬 グラム染色 AI (Self-Learning Ver)")

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
    
    st.info("Logic: ユーザーフィードバック学習型")

    # --- 学習機能エリア ---
    st.markdown("---")
    st.markdown("### 🧠 AIへの教育")
    st.caption("AIが間違えた時、ここに教訓を書き込んで「学習させる」を押すと、次回からそのルールを守るようになります。")
    
    current_rules = load_rules()
    with st.expander("現在の学習済みルールを見る"):
        if current_rules:
            st.text(current_rules)
        else:
            st.write("まだ学習データはありません。")

    new_feedback = st.text_area("新しいルールを追加", placeholder="例: ピンク色でもアスペクト比2.0以上ならグラム陰性桿菌と判定せよ")
    
    if st.button("学習させる (ルール保存)"):
        if new_feedback:
            save_rule(new_feedback)
            st.success("AIに学習させました！次回の解析から反映されます。")
            st.rerun() # 画面更新

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
                "表示サイズ調整", 
                min_value=600, 
                max_value=2500, 
                value=1000, 
                step=100
            )
            
            processed_image = process_image(raw_image, img_display_width)
            st.image(processed_image, caption="解析対象画像", use_container_width=True)

            st.markdown("---")
            
            if st.button("AI解析開始 (学習データ適用)", use_container_width=True):
                categories_str = ", ".join(valid_categories) if valid_categories else "登録なし"
                
                # 学習ルールを読み込む
                learned_rules = load_rules()
                
                with st.spinner(f'過去の教訓を参照しつつ解析中...'):
                    try:
                        prompt = f"""
                        あなたは臨床微生物検査技師です。光学顕微鏡の1000倍視野画像を解析します。

                        【重要：ユーザーからの学習/修正指示】
                        過去にユーザーから以下の指摘を受けています。このルールを**最優先**で守ってください。
                        {learned_rules}
                        --------------------------------------------------

                        【観察手順: 自動選別】
                        画像全体をスキャンし、**菌体が密集・凝集している場所は無視**してください。
                        背景に**「孤立散在（ばらけている）」している菌**を探し、その部分を重点的に観察してください。

                        【診断ロジック】
                        以下の手順①〜④に従って厳密に判定すること。

                        ① **グラム染色性**:
                           * **グラム陽性 (G+)**: 青紫、紺色、濃い紫。
                           * **グラム陰性 (G-)**: ピンク、赤、赤紫。

                        ② **形状判定 (アスペクト比とくびれ)**:
                           * **1.0 〜 1.5**: 球菌 (Cocci)
                           * **1.5 以上 (重要)**: 
                             **★必ず『くびれ』を確認してください★**
                             * **くびれ有り**: 連結部が凹んでいる → **球菌の連鎖**と判定。
                             * **くびれ無し**: 側面が平坦で直線的 → **桿菌 (Bacilli)** と判定。

                        ③ **配列・集落パターン**:
                           * **ブドウ球菌 (Staph)**: 立体的な「ブドウ房状」クラスター。
                           * **連鎖球菌 (Strep)**: 2連(双球菌)または数珠状の連鎖が80％以上。
                           * **その他**: 集落が不規則（いびつ）である場合は、球菌以外（コリネ等）を疑う。

                        ④ **サイズ感 (1000倍視野)**:
                           * **大型**: 赤血球(約7µm)の半径ほどある(3-5µm) → Bacillus/Clostridium等。
                           * **小型**: 赤血球より遥かに小さい(約1µm) → 肺炎球菌、ブドウ球菌、コリネ等。

                        【出力フォーマット】
                        1. **観察所見**:
                           * 染色性: [G+ / G-]
                           * アスペクト比: [1.0-1.5 / 1.5以上]
                           * くびれ: [有り / 無し / 対象外]
                           * 配列: [ブドウ房 / 連鎖 / 不規則]
                           * サイズ: [大型 / 小型]
                        
                        2. **推論**:
                           * 「アスペクト比は1.5以上ですが、くびれがあり、また過去の学習ルール『(該当すれば引用)』に基づき、[菌種]と判断します。」

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
                # 正解データの保存機能（学習の第一歩）
                st.markdown("### 💾 正解データの蓄積")
                st.caption("もしAIが間違えていたら、正しい菌名を選んで保存してください。将来的な精度向上に使われます。")
                
                # ユーザーが正しい答えを選べるようにする
                correct_label = st.selectbox("正しい菌種を選択", ["選択してください"] + valid_categories)
                
                if st.button("正解として保存する", use_container_width=True):
                    if correct_label != "選択してください" and GAS_APP_URL and DRIVE_FOLDER_ID:
                        with st.spinner("学習データとして保存中..."):
                            try:
                                img_byte_arr = io.BytesIO()
                                st.session_state['last_image'].save(img_byte_arr, format='PNG')
                                img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                # ファイル名に正解ラベルを含める
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
                    else:
                        st.warning("正しい菌種を選択するか、保存設定を確認してください。")

        except Exception as e:
            st.error(f"画像エラー: {e}")
