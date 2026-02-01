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
st.set_page_config(page_title="GramAI", page_icon="🩸", layout="wide")
st.markdown("""<style>.stApp {margin-top: -20px;} iframe {border: 1px solid #ddd;}</style>""", unsafe_allow_html=True)
st.title("🔬 グラム染色 AI (v10.70: Final Stable)")

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
    
    # 描画ツールの選択
    drawing_mode = st.selectbox("マーカー:", ("rect", "circle", "transform"), 
        format_func=lambda x: {"rect":"四角 (□)", "circle":"円 (○)", "transform":"移動"}[x])
    
    camera_mag = st.number_input("カメラ倍率 (x)", 1.0, 10.0, 1.0, 0.1)

    # カテゴリ取得
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
    # ★ Gemini 2.5 Flash に固定
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    uploaded_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        try:
            raw_image = Image.open(uploaded_file)
            
            # 【重要】まず画像が正しく読み込めているかここで表示（確認用）
            st.markdown("### 1. アップロード画像の確認")
            st.image(raw_image, caption="元画像", use_column_width=True)

            st.markdown("---")
            st.markdown("### 2. 解析エリアの指定")
            st.info(f"現在のモード: {drawing_mode} で菌を囲んでください。")
            
            # 画像処理
            canvas_width = 800
            processed_image = process_image(raw_image, canvas_width)
            
            # キャンバス表示
            # ★重要修正: keyにファイル名を含めることで、画像が変わるたびにツールを強制リセットします
            canvas_key = f"canvas_{uploaded_file.name}_{drawing_mode}"
            
            canvas_result = st_canvas(
                fill_color="rgba(255, 0, 0, 0.1)",  # 薄い赤色
                stroke_width=3,
                stroke_color="#FF0000",
                background_image=processed_image,
                update_streamlit=True,
                height=processed_image.size[1],
                width=canvas_width,
                drawing_mode=drawing_mode,
                key=canvas_key,
            )
            
            # 解析ボタン
            if st.button("マーキング内を解析する"):
                final_image = processed_image.copy()
                draw = ImageDraw.Draw(final_image)
                
                has_mark = False
                # 描画データがあるか確認
                if canvas_result.json_data and "objects" in canvas_result.json_data:
                    objects = canvas_result.json_data["objects"]
                    if len(objects) > 0:
                        has_mark = True
                        for obj in objects:
                            # 座標の取得と補正
                            l = obj["left"]
                            t = obj["top"]
                            w = obj["width"]
                            h = obj["height"]
                            
                            # 赤枠・赤丸の焼き付け（線を太くする）
                            if obj["type"] == "rect":
                                for i in range(5):
                                    draw.rectangle([(l-i, t-i), (l+w+i, t+h+i)], outline="red")
                            elif obj["type"] in ["circle", "oval"]:
                                for i in range(5):
                                    draw.ellipse([(l-i, t-i), (l+w+i, t+h+i)], outline="red")
                
                # 結果画像の表示
                st.markdown("### 3. 解析対象イメージ")
                st.image(final_image, caption="AIが見ている画像（赤枠付き）", use_column_width=True)
                
                with st.spinner("Gemini 2.5 Flash で解析中..."):
                    try:
                        instruction = "画像上の【赤枠または赤丸の内側】を重点的に見てください" if has_mark else "画像全体から最も鮮明な菌体を探してください"
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
                            st.session_state['last_image'] = final_image
                    except Exception as e:
                        st.error(f"AI解析エラー: {e}")

            # 結果の表示
            if 'last_result' in st.session_state:
                st.markdown("---")
                st.markdown("### 4. 解析結果")
                st.write(st.session_state['last_result'].replace("CATEGORY:", ""))
                
                # 参照画像の表示
                match_cats = []
                for line in st.session_state['last_result'].split('\
