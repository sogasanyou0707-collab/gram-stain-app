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

# === 設定エリア (Latest Version) ===
st.set_page_config(page_title="GramAI", page_icon="🩸", layout="wide")
st.markdown("""<style>.stApp {margin-top: -20px;} iframe {border: 1px solid #ddd;}</style>""", unsafe_allow_html=True)
st.title("🔬 グラム染色 AI (v12.1: Canvas Fixed)")

# --- キャンバスライブラリ ---
try:
    from streamlit_drawable_canvas import st_canvas
except ImportError:
    st.error("エラー: アプリを再起動(Reboot)してください。")
    st.stop()

# --- APIキー等の取得 ---
api_key = None
GAS_APP_URL = None
DRIVE_FOLDER_ID = None
try:
    if dict(st.secrets):
        api_key = st.secrets.get("GEMINI_API_KEY")
        GAS_APP_URL = st.secrets.get("GAS_APP_URL")
        DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID")
except: pass

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 設定")
    if not api_key: api_key = st.text_input("Gemini APIキー", type="password")
    
    st.info("Mode: 自由描画マーキング")
    
    drawing_mode = st.selectbox("マーカー:", ("rect", "circle", "transform"), 
        format_func=lambda x: {"rect":"四角 (□)", "circle":"円 (○)", "transform":"移動"}[x])
    
    camera_mag = st.number_input("カメラ倍率 (x)", 1.0, 10.0, 1.0, 0.1)

    @st.cache_data(ttl=60)
    def fetch_categories():
        if not GAS_APP_URL: return []
        try:
            r = requests.get(GAS_APP_URL, params={"action":"list_categories"}, timeout=5)
            return r.json().get("categories", [])
        except: return []
    
    valid_categories = [c for c in fetch_categories() if c not in ["Inbox", "my_gram_app", "pycache"] and not c.startswith(".")]
    if valid_categories: st.write("📂 カテゴリ:", valid_categories)

# --- 画像処理関数 ---
def process_image(img, target_width):
    img = img.convert("RGB")
    w, h = img.size
    ratio = target_width / w
    new_h = int(h * ratio)
    return img.resize((target_width, new_h), Image.LANCZOS).filter(ImageFilter.SHARPEN)

# --- メイン処理 ---
if api_key:
    genai.configure(api_key=api_key)
    # ★ Gemini 2.5 Flash
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    uploaded_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        try:
            uploaded_file.seek(0)
            raw_image = Image.open(uploaded_file)
            
            st.info(f"👇 下の画像にマウスで【{drawing_mode}】を描いてください。")
            
            canvas_width = 800
            processed_image = process_image(raw_image, canvas_width)
            
            # キャッシュ詰まり防止キー
            canvas_key = f"canvas_{uploaded_file.name}_{drawing_mode}"
            
            # キャンバス表示
            canvas_result = st_canvas(
                fill_color="rgba(255, 0, 0, 0.1)",
                stroke_width=3,
                stroke_color="#FF0000",
                background_image=processed_image,
                update_streamlit=True,
                height=processed_image.size[1],
                width=canvas_width,
                drawing_mode=drawing_mode,
                key=canvas_key,
            )
            
            # 解析ボタン (最新版対応)
            if st.button("マーキング内を解析する", use_container_width=True):
                final_image = processed_image.copy()
                draw = ImageDraw.Draw(final_image)
                
                has_mark = False
                if canvas_result.json_data and "objects" in canvas_result.json_data:
                    objects = canvas_result.json_data["objects"]
                    if len(objects) > 0:
                        has_mark = True
                        for obj in objects:
                            l = int(obj["left"])
                            t = int(obj["top"])
                            w = int(obj["width"])
                            h = int(obj["height"])
                            
                            if obj["type"] == "rect":
                                for i in range(5):
                                    draw.rectangle([(l-i, t-i), (l+w+i, t+h+i)], outline="red")
                            elif obj["type"] in ["circle", "oval"]:
                                for i in range(5):
                                    draw.ellipse([(l-i, t-i), (l+w+i, t+h+i)], outline="red")
                
                st.session_state['display_image'] = final_image
                st.session_state['has_mark'] = has_mark
                
                with st.spinner("Gemini 2.5 Flash で解析中..."):
                    try:
                        if has_mark:
                            instruction = "赤枠または赤丸の内側を重点的に見てください"
                        else:
                            instruction = "画像全体を見てください"

                        prompt = f"""
                        あなたは臨床微生物検査技師です。血液培養グラム染色(1000倍, カメラ{camera_mag}倍)を解析。
                        指示: {instruction}
                        条件: 溶血ボトル(RBCなし, 背景無視)。
                        判定困難時は「ACTION: REQUEST_SECOND_SLIDE」と理由を出力。
                        最後は「CATEGORY:カテゴリ名」。
                        """
                        res = model.generate_content([prompt, final_image])
                        
                        if "REQUEST_SECOND_SLIDE" in res.text:
                            reason = res.text.split("理由:")[-1] if "理由:" in res.text else "判定困難"
                            st.warning(f"再撮影推奨: {reason}")
                        else:
                            st.session_state['last_result'] = res.text
                    except Exception as e:
                        st.error(f"AI解析エラー: {e}")

            # === 結果表示エリア ===
            if 'display_image' in st.session_state:
                st.markdown("### 解析対象イメージ")
                st.image(st.session_state['display_image'], caption="AIが見ている画像", use_container_width=True)

            if 'last_result' in st.session_state:
                st.markdown("---")
                st.markdown("### 解析結果")
                st.write(st.session_state['last_result'].replace("CATEGORY:", ""))
                
                match_cats = []
                for line in st.session_state['last_result'].splitlines():
                    if "CATEGORY:" in line:
                        match_cats = [c.strip() for c in line.split("CATEGORY:")[1].split(',')]
                
                if match_cats and GAS_APP_URL:
                    cols = st.columns(len(match_cats))
                    for i, c in enumerate(match_cats):
                        if c in valid_categories:
                            with cols[i]:
                                try:
                                    r = requests.get(GAS_APP_URL, params={"action":"get_image","category":c}, timeout=5)
                                    d = r.json()
                                    if d.get("found"):
                                        img = Image.open(io.BytesIO(base64.b64decode(d["image"])))
                                        st.image(img, caption=c, use_container_width=True)
                                except: pass
                
                st.markdown("---")
                correct = st.selectbox("正解ラベル", ["選択してください"] + valid_categories)
                if st.button("保存", use_container_width=True):
                    if correct != "選択してください" and GAS_APP_URL and 'display_image' in st.session_state:
                        buf = io.BytesIO()
                        st.session_state['display_image'].save(buf, format='PNG')
                        try:
                            requests.post(GAS_APP_URL, json={
                                'image': base64.b64encode(buf.getvalue()).decode(),
                                'filename': f"CORRECT_{correct}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                                'folderId': DRIVE_FOLDER_ID,
                                'mimeType': 'image/png'
                            })
                            st.success("保存しました")
                        except: st.error("保存失敗")

        except Exception as e:
            st.error(f"画像エラー: {e}")
