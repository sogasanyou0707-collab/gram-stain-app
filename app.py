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
st.title("🔬 グラム染色 AI (v19.4: Safe Syntax Fix)")

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
    
    st.info("【操作方法】\n画面の「上下左右のフチ」を長押しするとスクロールします。")
    
    camera_mag = st.number_input("カメラ倍率 (x)", 1.0, 10.0, 1.0, 0.1)
    
    st.markdown("---")
    
    # スクロール感度（速度）
    scroll_speed = st.slider(
        "スクロール感度 (速度)",
        min_value=5,
        max_value=100,
        value=20,
        step=5,
        help="数値が小さいほどゆっくり細かく動きます。"
    )

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
    /* 可能な限りスクロールを許可する設定 */
    html, body, [data-testid="stAppViewContainer"] {{
        overflow: auto !important;
        -webkit-overflow-scrolling: touch;
    }}
    
    /* 操作エリアと重ならないよう余白設定 */
    [data-testid="stAppViewContainer"] {{
        padding: 20px !important;
    }}
    
    iframe {{
        min-width: {img_quality}px !important;
        width: {img_quality}px !important;
    }}
</style>
""", unsafe_allow_html=True)

# --- JavaScript: 安全な記述方式に変更 ---
# JSコードを普通の文字列として定義し、後から __SPEED__ を置換します
js_code = """
<script>
    const existing = window.parent.document.getElementById('scroll-frame');
    if (existing) existing.remove();

    const frame = window.parent.document.createElement('div');
    frame.id = 'scroll-frame';
    frame.style.cssText = 'position:fixed; top:0; left:0; width:100vw; height:100vh; pointer-events:none; z-index:999999;';

    // 帯の太さ (15px)
    const edgeSize = '15px';
    const edgeColor = 'rgba(0, 150, 255, 0.3)';
    const activeColor = 'rgba(0, 150, 255, 0.9)';
    
    // Pythonから渡された速度
    const speed = __SPEED__;

    const edgeStyle = `position:fixed; background:${edgeColor}; pointer-events:auto; touch-action:none;`;
    
    const edges = [
        { style: `${edgeStyle} top:0; left:0; width:100%; height:${edgeSize};`, dx:0, dy:-speed },
        { style: `${edgeStyle} bottom:0; left:0; width:100%; height:${edgeSize};`, dx:0, dy:speed },
        { style: `${edgeStyle} top:0; left:0; width:${edgeSize}; height:100%;`, dx:-speed, dy:0 },
        { style: `${edgeStyle} top:0; right:0; width:${edgeSize}; height:100%;`, dx:speed, dy:0 }
    ];

    let scrollInterval = null;

    function performScroll(dx, dy) {
        window.parent.scrollBy(dx, dy);
        const elements = window.parent.document.querySelectorAll('div, section, main, [data-testid="stAppViewContainer"]');
        elements.forEach(el => {
            if (el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight) {
                el.scrollBy({ left: dx, top: dy, behavior: 'auto' });
            }
        });
    }

    function startScroll(dx, dy, element) {
        if (scrollInterval) return;
        
        element.style.backgroundColor = activeColor;
        performScroll(dx, dy);

        scrollInterval = setInterval(() => {
            performScroll(dx, dy);
        }, 30);
    }

    function stopScroll(element) {
        clearInterval(scrollInterval);
        scrollInterval = null;
        if(element) element.style.backgroundColor = edgeColor;
    }

    edges.forEach(e => {
        const div = window.parent.document.createElement('div');
        div.style.cssText = e.style;
        
        div.addEventListener('touchstart', (ev) => { 
            ev.preventDefault(); 
            startScroll(e.dx, e.dy, div); 
        }, {passive: false});
        
        div.addEventListener('touchend', () => stopScroll(div));
        div.addEventListener('mousedown', () => startScroll(e.dx, e.dy, div));
        div.addEventListener('mouseup', () => stopScroll(div));
        div.addEventListener('mouseleave', () => stopScroll(div));
        
        frame.appendChild(div);
    });

    window.parent.document.body.appendChild(frame);
</script>
"""

# ここで速度数値を埋め込みます
components.html(js_code.replace("__SPEED__", str(scroll_speed)), height=0)

# --- メイン処理 ---
if api_key:
    genai.configure(api_key=api_key
