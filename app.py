import streamlit as st
import google.generativeai as genai
import requests
import io
import base64
import os
import streamlit.components.v1 as components
from PIL import Image, ImageFilter
from datetime import datetime
from streamlit_cropper import st_cropper

# === 設定エリア ===
st.set_page_config(page_title="GramAI", page_icon="🩸", layout="wide")
st.title("🔬 グラム染色 AI (v17.1: Left D-Pad Fix)")

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
    
    st.info("【操作方法】\n画面左下の「十字キー」でスクロールできます。")
    
    camera_mag = st.number_input("カメラ倍率 (x)", 1.0, 10.0, 1.0, 0.1)
    
    st.markdown("---")
    img_quality = st.select_slider(
        "画質 (幅ピクセル)",
        options=[700, 1000, 1400, 2000],
        value=1400
    )
    
    sharpness = st.checkbox("画像をシャープにする", value=True)

    @st.cache_data(ttl=60)
    def fetch_categories():
        if not GAS_APP_URL: return []
        try:
            r = requests.get(GAS_APP_URL, params={"action":"list_categories"}, timeout=5)
            return r.json().get("categories", [])
        except: return []
    
    valid_categories = [c for c in fetch_categories() if c not in ["Inbox", "my_gram_app", "pycache"] and not c.startswith(".")]
    if valid_categories: st.write("📂 カテゴリ:", valid_categories)

# --- CSS: 画像幅の強制固定 ---
st.markdown(f"""
<style>
    .stApp {{ overflow: auto !important; }}
    iframe {{
        min-width: {img_quality}px !important;
        width: {img_quality}px !important;
    }}
</style>
""", unsafe_allow_html=True)

# --- JavaScript: 左下コントローラー (タッチ対応版) ---
components.html("""
<script>
    // 既存のボタンがあれば削除
    const existing = window.parent.document.getElementById('gram-dpad');
    if (existing) existing.remove();

    // コントローラーのコンテナ作成
    const dpad = window.parent.document.createElement('div');
    dpad.id = 'gram-dpad';
    dpad.style.position = 'fixed';
    dpad.style.bottom = '20px';
    dpad.style.left = '20px';  /* 左下に配置 */
    dpad.style.width = '140px';
    dpad.style.height = '140px';
    dpad.style.zIndex = '999999';
    dpad.style.backgroundColor = 'rgba(0, 0, 0, 0.1)'; /* 薄いグレー背景 */
    dpad.style.borderRadius = '50%';
    dpad.style.touchAction = 'none'; // ブラウザのデフォルト動作防止

    // 共通ボタンスタイル (指で押しやすいように少し大きく)
    const btnStyle = `
        position: absolute;
        width: 45px;
        height: 45px;
        background: rgba(255, 75, 75, 0.95); /* ストリームリット赤 */
        color: white;
        border: 2px solid white;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        font-weight: bold;
        cursor: pointer;
        box-shadow: 0 4px 8px rgba(0,0,0,0.4);
        user-select: none;
        -webkit-tap-highlight-color: transparent;
    `;

    // スクロール実行関数 (複数のターゲットを試す)
    function scrollTarget(x, y) {
        const doc = window.parent.document;
        // Streamlitのメインコンテナを探す
        const targets = [
            doc.querySelector('.stApp'),
            doc.querySelector('section.main'),
            doc.documentElement,
            doc.body
        ];

        for (let t of targets) {
            if (t) {
                t.scrollBy({ left: x, top: y, behavior: 'smooth' });
            }
        }
    }

    // ボタン生成関数 (タッチイベント対応)
    function createBtn(text, top, left, scrollX, scrollY) {
        const b = window.parent.document.createElement('div');
        b.innerHTML = text;
        b.style.cssText = btnStyle;
        b.style.top = top;
        b.style.left = left;
        
        // タッチとクリックの両方で反応させる
        const action = (e) => {
            e.preventDefault(); // デフォルト動作(選択など)を無効化
            e.stopPropagation();
            scrollTarget(scrollX, scrollY);
        };

        b.addEventListener('touchstart', action, {passive: false});
        b.addEventListener('click', action);
        
        return b;
    }

    // 上下左右ボタンの配置 (140pxエリア内の座標)
    // センター位置: 47.5px ( (140 - 45) / 2 )
    
    // 上
    dpad.appendChild(createBtn('▲', '0px', '47.5px', 0, -300));
    // 下
    dpad.appendChild(createBtn('▼', '95px', '47.5px', 0, 300));
    // 左
    dpad.appendChild(createBtn('◀', '47.5px', '0px', -300, 0));
    // 右
    dpad.appendChild(createBtn('▶', '47.5px', '95px', 300, 0));

    // 親ウィンドウに追加
    window.parent.document.body.appendChild(dpad);

</script>
""", height=0)

# --- メイン処理 ---
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    uploaded_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        try:
            uploaded_file.seek(0)
            raw_image = Image.open(uploaded_file)
            
            # --- 画像のリサイズ ---
            target_width = img_quality
            if raw_image.width != target_width:
                ratio = target_width / raw_image.width
                new_height = int(raw_image.height * ratio)
                raw_image = raw_image.resize((target_width, new_height), Image.LANCZOS)
            
            # --- シャープネス ---
            if sharpness:
                raw_image = raw_image.filter(ImageFilter.UnsharpMask(radius=2, percent=150))

            st.markdown(f"### 1. 解析エリアの選択 (幅: {target_width}px)")
            st.info("👇 **画面左下のコントローラー** でスクロールしてください")

            # 画像本体
            cropped_img = st_cropper(
                raw_image,
                realtime_update=True,
                box_color='#FF0000',
                aspect_ratio=None,
                should_resize_image=False
            )
            
            st.markdown("---")
            st.markdown("### 2. 選択された画像")
            
            col1, col2 = st.columns([1, 2])
            with col1:
                 st.image(cropped_img, caption="AI送信画像", use_container_width=True)
            
            with col2:	
