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
st.set_page_config(page_title="GramAI", page_icon="🔬", layout="wide")
st.title("🔬 グラム染色 AI (v19.0: Frame Scroll)")

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
    st.info("【操作方法】\n画面の「上下左右の白いフチ」を長押しすると、その方向にスクロールします。")
    camera_mag = st.number_input("カメラ倍率 (x)", 1.0, 10.0, 1.0, 0.1)
    
    st.markdown("---")
    img_quality = st.select_slider("画質 (幅ピクセル)", options=[700, 1000, 1400, 2000], value=1400)
    sharpness = st.checkbox("画像をシャープにする", value=True)

# --- CSS: 画像幅の固定と余白の確保 ---
st.markdown(f"""
<style>
    [data-testid="stAppViewContainer"] {{
        overflow: auto !important;
        -webkit-overflow-scrolling: touch;
        padding: 40px !important; /* 四方のフチを空ける */
    }}
    iframe {{
        min-width: {img_quality}px !important;
        width: {img_quality}px !important;
    }}
</style>
""", unsafe_allow_html=True)

# --- JavaScript: 4辺スクロール「額縁」の実装 ---
components.html("""
<script>
    const existing = window.parent.document.getElementById('scroll-frame');
    if (existing) existing.remove();

    const frame = window.parent.document.createElement('div');
    frame.id = 'scroll-frame';
    frame.style.cssText = 'position:fixed; top:0; left:0; width:100vw; height:100vh; pointer-events:none; z-index:999999;';

    const edgeStyle = 'position:fixed; background:rgba(255,255,255,0.4); pointer-events:auto; display:flex; align-items:center; justify-content:center; font-size:20px; color:#666; font-weight:bold;';
    const edges = [
        { id:'top', style: edgeStyle + 'top:0; left:0; width:100%; height:40px; border-bottom:1px solid #ddd;', dx:0, dy:-30, label:'▲ SCROLL UP ▲' },
        { id:'bottom', style: edgeStyle + 'bottom:0; left:0; width:100%; height:40px; border-top:1px solid #ddd;', dx:0, dy:30, label:'▼ SCROLL DOWN ▼' },
        { id:'left', style: edgeStyle + 'top:0; left:0; width:40px; height:100%; border-right:1px solid #ddd; writing-mode:vertical-rl;', dx:-30, dy:0, label:'◀ SCROLL LEFT' },
        { id:'right', style: edgeStyle + 'top:0; right:0; width:40px; height:100%; border-left:1px solid #ddd; writing-mode:vertical-rl;', dx:30, dy:0, label:'SCROLL RIGHT ▶' }
    ];

    let scrollInterval = null;

    function startScroll(dx, dy) {
        if (scrollInterval) return;
        scrollInterval = setInterval(() => {
            const container = window.parent.document.querySelector('[data-testid="stAppViewContainer"]') || window.parent;
            container.scrollBy({ left: dx, top: dy, behavior: 'auto' });
        }, 50);
    }

    function stopScroll() {
        clearInterval(scrollInterval);
        scrollInterval = null;
    }

    edges.forEach(e => {
        const div = window.parent.document.createElement('div');
        div.style.cssText = e.style;
        div.innerText = e.label;
        div.addEventListener('touchstart', (ev) => { ev.preventDefault(); startScroll(e.dx, e.dy); });
        div.addEventListener('touchend', stopScroll);
        div.addEventListener('mousedown', () => startScroll(e.dx, e.dy));
        div.addEventListener('mouseup', stopScroll);
        div.addEventListener('mouseleave', stopScroll);
        frame.appendChild(div);
    });

    window.parent.document.body.appendChild(frame);
</script>
""", height=0)

# --- メイン処理 ---
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    uploaded_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        try:
            raw_image = Image.open(uploaded_file)
            target_width = img_quality
            if raw_image.width != target_width:
                ratio = target_width / raw_image.width
                new_height = int(raw_image.height * ratio)
                raw_image = raw_image.resize((target_width, new_height), Image.LANCZOS)
            if sharpness:
                raw_image = raw_image.filter(ImageFilter.UnsharpMask(radius=2, percent=150))

            st.markdown(f"### 1. 解析エリアの選択")
            cropped_img = st_cropper(raw_image, realtime_update=True, box_color='#FF0000', aspect_ratio=None, should_resize_image=False)
            
            st.markdown("---")
            col1, col2 = st.columns([1, 2])
            with col1:
                 st.image(cropped_img, caption="AI送信画像", use_container_width=True)
            with col2:
                if st.button("この範囲を解析する", type="primary", use_container_width=True):
                    st.session_state['display_image'] = cropped_img
                    with st.spinner("解析中..."):
                        prompt = f"臨床微生物検査技師として血液培養グラム染色(1000倍, カメラ{camera_mag}倍)の画像を解析し、菌体の特徴を詳細に分析してください。最後は「CATEGORY:カテゴリ名」で。判定困難時は再撮影依頼。背景無視。"
                        res = model.generate_content([prompt, cropped_img])
                        st.session_state['last_result'] = res.text

            if 'last_result' in st.session_state:
                st.markdown("### 2. 解析結果")
                st.write(st.session_state['last_result'].replace("CATEGORY:", ""))
                # 保存処理などは省略せず維持
        except Exception as e:
            st.error(f"エラー: {e}")
