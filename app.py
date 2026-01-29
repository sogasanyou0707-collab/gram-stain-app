import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
import os
import numpy as np
from PIL import Image, ImageFilter, ImageDraw
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア ===
st.set_page_config(
    page_title="GramAI", 
    page_icon="🩸", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stApp {margin-top: -20px;}
    .stImage {overflow-x: auto;}
    iframe {border: 1px solid #ddd;}
    .warning-box {
        padding: 15px;
        background-color: #fff3cd;
        border: 2px solid #ffc107;
        border-radius: 5px;
        color: #856404;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("🔬 グラム染色 AI (v10.44: Fix Error)")

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

# --- 学習ルールの読み書き ---
RULE_FILE = "learning_rules.txt"
def load_rules():
    if os.path.exists(RULE_FILE):
        with open(RULE_FILE, "r", encoding="utf-8") as f: return f.read()
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
    
    st.info("Mode: 血液培養 (エラー修正版)")
    
    st.markdown("---")
    st.markdown("### 📷 倍率設定")
    camera_mag = st.number_input("カメラ倍率 (x)", value=1.0, step=0.1, min_value=0.1, max_value=10.0)

    st.markdown("---")
    st.markdown("### 🧠 AIへの教育")
    current_rules = load_rules()
    with st.expander("現在の学習済みルール"):
        st.text(current_rules if current_rules else "データなし")
    new_feedback = st.text_area("新しいルールを追加", placeholder="例: 背景のデブリは無視せよ")
    if st.button("学習させる"):
        if new_feedback:
            save_rule(new_feedback)
            st.success("保存しました！")
            st.rerun()

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
        st.write("📂 カテゴリ:", valid_categories)

# --- キャンバスライブラリ ---
try:
    from streamlit_drawable_canvas import st_canvas
except ImportError:
    st.error("ライブラリ不足: pip install streamlit-drawable-canvas を実行してください")
    st.stop()

# --- 画像処理関数 (エラー対策版) ---
def process_image(img, target_width):
    img = img.convert("RGB")
    # width/height属性を使わず、sizeタプルを使う（古いPillow対策）
    current_w, current_h = img.size 
    ratio = target_width / current_w
    new_height = int(current_h * ratio)
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
            
            st.markdown("### 🖍️ 観察位置の指定")
            st.info("マウスで**菌がいる場所を四角く囲んで**ください。")
            
            canvas_width = 800
            processed_image = process_image(raw_image, canvas_width)
            
            # キャンバス表示
            canvas_result = st_canvas(
                fill_color="rgba(255, 0, 0, 0.1)",
                stroke_width=3,
                stroke_color="#FF0000",
                background_image=processed_image,
                update_streamlit=True,
                height=processed_image.size[1], # .heightではなく.size[1]を使用
                width=canvas_width,
                drawing_mode="rect",
                key="canvas",
            )

            st.markdown("---")
            
            if st.button("この赤枠内を解析する", use_container_width=True):
                categories_str = ", ".join(valid_categories) if valid_categories else "登録なし"
                learned_rules = load_rules()
                
                final_image = processed_image.copy()
                draw = ImageDraw.Draw(final_image)
                
                has_box = False
                if canvas_result.json_data is not None:
                    objects = canvas_result.json_data["objects"]
                    if len(objects) > 0:
                        has_box = True
                        for obj in objects:
                            # 枠を描画（widthパラメータのエラー回避のため、太さはループで描画）
                            rect_coords = [(obj["left"], obj["top"]), (obj["left"] + obj["width"], obj["top"] + obj["height"])]
                            for i in range(5): # 太さ5px
                                draw.rectangle(
                                    [(rect_coords[0][0]-i, rect_coords[0][1]-i), (rect_coords[1][0]+i, rect_coords[1][1]+i)],
                                    outline="red"
                                )

                st.image(final_image, caption=f"解析対象 (倍率補正: {camera_mag}x)", use_container_width=True)
                
                with st.spinner(f'溶血背景を除去し、倍率{camera_mag}xで解析中...'):
                    try:
                        box_instruction = "画像上の**「赤枠の内側」**のみを診断対象としてください。" if has_box else "画像全体から、最も鮮明な菌体を探してください。"

                        prompt = f"""
                        あなたは臨床微生物検査技師です。血液培養ボトルのグラム染色像（光学顕微鏡 1000倍視野）を解析します。

                        {box_instruction}

                        【重要条件: 溶血ボトル】
                        1. **赤血球(RBC)は溶血して存在しません**。
                        2. **背景**: 溶血によるピンク色のデブリ（残渣）が大量にあります。
                           * **ルール**: 「輪郭が不明瞭なピンク色」は全て背景ノイズとして**徹底的に無視**してください。
                           * 菌体とみなすのは「明確なエッジ（境界線）」があるものだけです。

                        【倍率設定】
                        * 顕微鏡: 1000倍
                        * カメラアダプタ倍率: **{camera_mag}倍**

                        【診断ロジック】
                        ① **グラム染色性**:
                           * 背景のピンクは無視。
                           * G+: 青紫/紺色。
                           * G-: 濃い赤/ピンク（輪郭がくっきりとあるもの限定）。

                        ② **形状とサイズ**:
                           * アスペクト比 1.0-1.5: 球菌。
                           * アスペクト比 1.5以上: くびれがあれば連鎖球菌、なければ桿菌。
                           * サイズ: 倍率補正{camera_mag}x を考慮して判断。

                        【最重要: 判断保留】
                        もし以下の理由で判定できない場合は、**「ACTION: REQUEST_SECOND_SLIDE」** とその「理由」のみを出力してください。
                        * 菌体が少なすぎる / デブリと区別がつかない / 形や色がどっちつかず

                        【出力フォーマット】
                        判断可能な場合:
                        1. **観察所見**:
                           * 染色性: [G+ / G-]
                           * 形状: [球菌 / 桿菌]
                           * サイズ感: [大型 / 小型 / 標準]
                        
                        2. **推論**:
                           * 「倍率{camera_mag}倍を考慮すると...」

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
                        
                        response = model.generate_content([prompt, final_image], safety_settings=safety_settings)
                        
                        if response.text:
                            if "REQUEST_SECOND_SLIDE" in response.text:
                                reason = response.text.split("理由:")[-1].strip() if "理由:" in response.text else "判定困難"
                                st.markdown(f"""<div class="warning-box">⚠️ AI判定不能: 再撮影が必要です<br>理由: {reason}</div>""", unsafe_allow_html=True)
                            else:
                                st.session_state['last_result'] = response.text
                                st.session_state['last_image'] = final_image
                    except Exception as e:
                        st.error(f"解析エラー: {e}")

            if 'last_result' in st.session_state:
                st.markdown("---")
                text = st.session_state['last_result']
                st.markdown("### 🤖 解析結果")
                display_text = text.replace("CATEGORY:", "") 
                st.write(display_text)
                
                # ... (以下、画像表示と保存機能は共通のため省略せずそのまま使用可能ですが、文字数制限のため主要部分のみ提示しました。元のコードの後半部分はそのまま機能します) ...
                # ※ 完全な動作のためには、先ほどのコードの後半（match_categories以降）も含めてください。
                
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
                correct_label = st.selectbox("正しい菌種を選択", ["選択してください"] + valid_categories)
                if st.button("正解として保存する", use_container_width=True):
                    if correct_label != "選択してください" and GAS_APP_URL and DRIVE_FOLDER_ID:
                        with st.spinner("保存中..."):
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
                                st.success("✅ 保存成功")
                            except:
                                st.error("保存失敗")

        except Exception as e:
            st.error(f"画像エラー: {e}")
