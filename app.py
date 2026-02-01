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

st.title("🔬 グラム染色 AI (v10.50: Drawing Mode)")

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

# --- 学習ルール ---
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
    if not api_key: api_key = st.text_input("Gemini APIキー", type="password")
    
    st.info("Mode: 自由描画マーキング")
    
    # ★追加機能: 描画ツールの選択
    st.markdown("### 🖍️ ツール選択")
    drawing_mode = st.selectbox(
        "マーカーの形を選んでください:",
        ("rect", "circle", "transform"),
        format_func=lambda x: {"rect": "四角形 (□)", "circle": "円 (○)", "transform": "移動・変形"}[x]
    )
    st.caption("※「移動・変形」を選ぶと、描いた図形を動かせます。")

    st.markdown("---")
    st.markdown("### 📷 倍率設定")
    camera_mag = st.number_input("カメラ倍率 (x)", value=1.0, step=0.1, min_value=0.1, max_value=10.0)

    st.markdown("---")
    st.markdown("### 🧠 AIへの教育")
    current_rules = load_rules()
    with st.expander("現在の学習済みルール"):
        st.text(current_rules if current_rules else "データなし")
    new_feedback = st.text_area("新しいルールを追加")
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
    st.error("ライブラリ不足: pip install streamlit-drawable-canvas")
    st.stop()

# --- 画像処理関数 ---
def process_image(img, target_width):
    img = img.convert("RGB")
    w, h = img.size
    ratio = target_width / w
    new_h = int(h * ratio)
    img = img.resize((target_width, new_h), Image.LANCZOS)
    return img.filter(ImageFilter.SHARPEN)

# --- メイン処理 ---
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
    except:
        model = genai.GenerativeModel("gemini-1.5-flash")

    uploaded_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        try:
            raw_image = Image.open(uploaded_file)
            
            st.markdown("### 🖍️ 観察位置の指定")
            st.info("サイドバーで「四角」か「円」を選び、**菌がいる場所を囲んで**ください。")
            
            canvas_width = 800
            processed_image = process_image(raw_image, canvas_width)
            
            # キャンバスの描画
            canvas_result = st_canvas(
                fill_color="rgba(255, 0, 0, 0.1)",  # 塗りつぶし色
                stroke_width=3,
                stroke_color="#FF0000",             # 赤線
                background_image=processed_image,
                update_streamlit=True,
                height=processed_image.size[1],
                width=canvas_width,
                drawing_mode=drawing_mode,          # ★選択したツールを使用
                key="canvas",
            )

            st.markdown("---")
            
            # 最新Streamlitなので use_container_width=True が正しく動作します
            if st.button("マーキング内を解析する", use_container_width=True):
                categories_str = ", ".join(valid_categories) if valid_categories else "登録なし"
                learned_rules = load_rules()
                
                # 画像に描画内容を焼き付ける
                final_image = processed_image.copy()
                draw = ImageDraw.Draw(final_image)
                
                has_mark = False
                if canvas_result.json_data is not None:
                    objects = canvas_result.json_data["objects"]
                    if len(objects) > 0:
                        has_mark = True
                        for obj in objects:
                            # 座標の取得
                            left = obj["left"]
                            top = obj["top"]
                            w = obj["width"]
                            h = obj["height"]
                            
                            # 図形タイプに応じて描画
                            if obj["type"] == "rect":
                                for i in range(5):
                                    draw.rectangle([(left-i, top-i), (left+w+i, top+h+i)], outline="red")
                            elif obj["type"] == "circle" or obj["type"] == "oval":
                                for i in range(5):
                                    draw.ellipse([(left-i, top-i), (left+w+i, top+h+i)], outline="red")
                
                st.image(final_image, caption=f"解析対象 (倍率補正: {camera_mag}x)", use_container_width=True)
                
                with st.spinner(f'倍率{camera_mag}xで解析中...'):
                    try:
                        box_instruction = "画像上の**「赤枠または赤丸の内側」**のみを診断対象としてください。" if has_mark else "画像全体から、最も鮮明な菌体を探してください。"

                        prompt = f"""
                        あなたは臨床微生物検査技師です。血液培養ボトルのグラム染色像（1000倍視野）を解析します。

                        {box_instruction}

                        【重要条件: 溶血ボトル】
                        * **RBC不在**: 溶血のため赤血球サイズ比較は不可。
                        * **背景無視**: 「輪郭が不明瞭なピンク色」は全て背景ノイズとして無視。菌体は「明確なエッジ」があるものだけ。

                        【倍率設定】
                        * カメラアダプタ倍率: **{camera_mag}倍**
                        (※この倍率を考慮して、標準的な菌体サイズと比較してください)

                        【診断ロジック】
                        ① **グラム染色性**: G+(青紫) / G-(濃い赤/ピンクかつ明瞭な輪郭)
                        ② **形状**: アスペクト比や配列パターンを確認。
                        
                        【判断保留ルール】
                        判定困難な場合(菌が少ない、デブリ過多、区別不能)は、
                        「ACTION: REQUEST_SECOND_SLIDE」と「理由」のみを出力せよ。

                        【出力フォーマット】
                        判断可能な場合:
                        1. **観察所見**:
                           * 染色性: [G+ / G-]
                           * 形状: [球菌 / 桿菌]
                           * サイズ感: [大型 / 小型 / 標準]
                        
                        2. **推論**: ...

                        3. **最も近いカテゴリ**: [{categories_str}]

                        最後に「CATEGORY:カテゴリ名」。
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
                
                # 正解データ保存機能など (省略なしで動作します)
                match_categories = []
                for line in text.split('\n'):
                    if "CATEGORY:" in line:
                        cats_str = line.split("CATEGORY:")[1].strip().replace("、", ",")
                        match_categories = [c.strip() for c in cats_str.split(',')]
                
                if match_categories and GAS_APP_URL:
                     st.markdown("#### 📚 参考画像")
                     cols = st.columns(len(match_categories))
                     for i, cat in enumerate(match_categories):
                         if cat in valid_categories:
                             with cols[i]:
                                 try:
                                     res = requests.get(GAS_APP_URL, params={"action":"get_image","category":cat}, timeout=5)
                                     d = res.json()
                                     if d.get("found"):
                                         st.image(Image.open(io.BytesIO(base64.b64decode(d["image"]))), caption=cat, use_container_width=True)
                                 except: pass
                
                st.markdown("---")
                correct = st.selectbox("正しい菌種", ["選択してください"] + valid_categories)
                if st.button("正解として保存", use_container_width=True):
                    if correct != "選択してください" and GAS_APP_URL:
                        with st.spinner("保存中..."):
                            try:
                                buf = io.BytesIO()
                                st.session_state['last_image'].save(buf, format='PNG')
                                requests.post(GAS_APP_URL, json={
                                    'image': base64.b64encode(buf.getvalue()).decode('utf-8'),
                                    'filename': f"CORRECT_{correct}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                                    'folderId': DRIVE_FOLDER_ID,
                                    'mimeType': 'image/png'
                                })
                                st.success("保存成功")
                            except: st.error("保存失敗")

        except Exception as e:
            st.error(f"画像読み込みエラー: {e}")
