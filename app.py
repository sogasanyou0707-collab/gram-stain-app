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
try:
    from streamlit_drawable_canvas import st_canvas
except ImportError:
    st.error("Restarting app environment...")
    st.stop()

# === 設定エリア ===
st.set_page_config(page_title="GramAI", page_icon="🩸", layout="wide")
st.markdown("""<style>.stApp {margin-top: -20px;} iframe {border: 1px solid #ddd;}</style>""", unsafe_allow_html=True)
st.title("🔬 グラム染色 AI (v10.52: Reborn)")

# --- APIキー等 ---
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
    cats = fetch_categories()
    valid_cats = [c for c in cats if c not in ["Inbox", "my_gram_app", "pycache", "__pycache__"] and not c.startswith(".")]
    if valid_cats: st.write("📂 カテゴリ:", valid_cats)

# --- メイン処理 ---
def process_image(img, w_target):
    img = img.convert("RGB")
    w, h = img.size
    new_h = int(h * (w_target / w))
    return img.resize((w_target, new_h), Image.LANCZOS).filter(ImageFilter.SHARPEN)

if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash") # 安定版モデル指定
    
    uploaded_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])
    if uploaded_file:
        raw_img = Image.open(uploaded_file)
        st.info(f"モード: {drawing_mode} で菌を囲んでください。")
        
        proc_img = process_image(raw_img, 800)
        
        canvas = st_canvas(
            fill_color="rgba(255, 0, 0, 0.1)", stroke_width=3, stroke_color="#FF0000",
            background_image=proc_img, update_streamlit=True,
            height=proc_img.size[1], width=800, drawing_mode=drawing_mode, key="canvas"
        )
        
        if st.button("解析する", use_container_width=True):
            final_img = proc_img.copy()
            draw = ImageDraw.Draw(final_img)
            has_mark = False
            if canvas.json_data and canvas.json_data["objects"]:
                has_mark = True
                for o in canvas.json_data["objects"]:
                    l, t, w, h = o["left"], o["top"], o["width"], o["height"]
                    if o["type"] == "rect": draw.rectangle([(l,t), (l+w,t+h)], outline="red", width=5)
                    elif o["type"] in ["circle","oval"]: draw.ellipse([(l,t), (l+w,t+h)], outline="red", width=5)
            
            st.image(final_img, caption="解析対象", use_container_width=True)
            
            with st.spinner("AI解析中..."):
                prompt = f"""
                あなたは臨床微生物検査技師です。血液培養グラム染色(1000倍, カメラ{camera_mag}倍)を解析します。
                {'赤枠/赤丸の中を見てください。' if has_mark else '全体を見てください。'}
                溶血によりRBCなし。背景のピンクは無視。
                判定困難時は「ACTION: REQUEST_SECOND_SLIDE」と理由を出力。
                最後は「CATEGORY:カテゴリ名」。
                """
                try:
                    res = model.generate_content([prompt, final_img])
                    st.write(res.text)
                except Exception as e: st.error(f"Error: {e}")
