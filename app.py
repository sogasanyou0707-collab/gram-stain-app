import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
import os
from PIL import Image
from datetime import datetime
from streamlit_cropper import st_cropper

# === 設定エリア ===
st.set_page_config(page_title="GramAI", page_icon="🩸", layout="wide")
st.title("🔬 グラム染色 AI (v13.1: Mobile Fix)")

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
    
    st.info("【使い方】\n画像の「解析したい部分」を枠で囲んでください。")
    
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

# --- メイン処理 ---
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    uploaded_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        try:
            uploaded_file.seek(0)
            raw_image = Image.open(uploaded_file)
            
            # ★スマホ対策: 画像が大きすぎるとはみ出るため、幅を調整する
            # (iPhone等の写真は4000px以上あるため、画面に収まるサイズに縮小)
            max_width = 700
            if raw_image.width > max_width:
                ratio = max_width / raw_image.width
                new_height = int(raw_image.height * ratio)
                raw_image = raw_image.resize((max_width, new_height))
            
            # --- 切り抜きエリア (スマホで見やすいよう縦並びに変更) ---
            
            st.markdown("### 1. 解析エリアの選択")
            st.caption("枠を動かして、菌がいる場所を囲んでください")
            
            # 切り抜きツール
            cropped_img = st_cropper(
                raw_image,
                realtime_update=True,
                box_color='#FF0000',
                aspect_ratio=None,
                should_resize_image=True
            )
            
            st.markdown("---")
            st.markdown("### 2. 選択された画像")
            
            # プレビューとボタンを横並びにする
            col1, col2 = st.columns([1, 2])
            with col1:
                 st.image(cropped_img, caption="送信画像", use_container_width=True)
            
            with col2:
                st.write("") # 余白
                if st.button("この範囲を解析する", type="primary", use_container_width=True):
                    st.session_state['display_image'] = cropped_img
                    
                    with st.spinner("Gemini 2.5 Flash で解析中..."):
                        try:
                            prompt = f"""
                            あなたは臨床微生物検査技師です。血液培養グラム染色(1000倍, カメラ{camera_mag}倍)の「切り抜き画像」を解析してください。
                            
                            指示: 画像内の菌体の特徴を詳細に分析してください。
                            条件: 溶血ボトル(RBCなし, 背景無視)。
                            判定困難時は「ACTION: REQUEST_SECOND_SLIDE」と理由を出力。
                            最後は「CATEGORY:カテゴリ名」。
                            """
                            res = model.generate_content([prompt, cropped_img])
                            st.session_state['last_result'] = res.text
                        except Exception as e:
                            st.error(f"AI解析エラー: {e}")

            # === 結果表示エリア ===
            if 'last_result' in st.session_state:
                st.markdown("---")
                st.subheader("3. 解析結果")
                st.write(st.session_state['last_result'].replace("CATEGORY:", ""))
                
                # 参照画像の表示
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
