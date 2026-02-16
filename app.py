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

st.set_page_config(page_title="GramAI", page_icon="🔬", layout="wide")
st.title("🔬 グラム染色 AI (v24.0: Pro/Flash Selector)")

# --- API & Secrets ---
api_key = None
GAS_APP_URL = None
DRIVE_FOLDER_ID = None
try:
    if dict(st.secrets):
        api_key = st.secrets.get("GEMINI_API_KEY")
        GAS_APP_URL = st.secrets.get("GAS_APP_URL")
        DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID")
except: pass

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ 設定")
    if not api_key: api_key = st.text_input("Gemini APIキー", type="password")
    
    # ★ モデル選択スイッチ (2.5 Flash vs 2.5 Pro)
    st.markdown("### 🤖 モデル選択")
    model_type = st.radio(
        "精度と速度のバランス",
        ["Gemini 2.5 Flash (高速)", "Gemini 2.5 Pro (高知能)"],
        index=0,
        help="Proは菌の形状をより深く分析しますが、処理に少し時間がかかります。"
    )

    st.info("【操作】画面の「青いフチ」を長押しでスクロール")
    camera_mag = st.number_input("カメラ倍率 (x)", 1.0, 10.0, 1.0, 0.1)
    
    st.markdown("---")
    scroll_speed = st.slider("スクロール速度", 5, 100, 20, 5)
    img_quality = st.select_slider("画質 (幅px)", options=[700, 1000, 1400, 2000], value=1400)
    sharpness = st.checkbox("シャープ化", value=True)

    @st.cache_data(ttl=60)
    def fetch_categories():
        if not GAS_APP_URL: return []
        try:
            r = requests.get(GAS_APP_URL, params={"action":"list_categories"}, timeout=5)
            return r.json().get("categories", [])
        except: return []
    valid_categories = [c for c in fetch_categories() if c not in ["Inbox", "my_gram_app", "pycache"] and not c.startswith(".")]
    if valid_categories: st.write("📂 カテゴリ:", valid_categories)

# --- CSS ---
st.markdown(f"""
<style>
    html, body, [data-testid="stAppViewContainer"] {{
        overflow: auto !important;
        -webkit-overflow-scrolling: touch;
    }}
    [data-testid="stAppViewContainer"] {{ padding: 20px !important; }}
    iframe {{
        min-width: {img_quality}px !important;
        width: {img_quality}px !important;
    }}
</style>
""", unsafe_allow_html=True)

# --- JavaScript (Scroll Logic) ---
js_code = """
<script>
    const existing = window.parent.document.getElementById('scroll-frame');
    if (existing) existing.remove();

    const frame = window.parent.document.createElement('div');
    frame.id = 'scroll-frame';
    frame.style.cssText = 'position:fixed; top:0; left:0; width:100vw; height:100vh; pointer-events:none; z-index:999999;';

    const edgeSize = '15px';
    const edgeColor = 'rgba(0, 150, 255, 0.3)';
    const activeColor = 'rgba(0, 150, 255, 0.9)';
    const speed = __SPEED__;

    const edgeStyle = `position:fixed; background:${edgeColor}; pointer-events:auto; touch-action:none;`;
    const edges = [
        { s: `top:0; left:0; width:100%; height:${edgeSize};`, dx:0, dy:-speed },
        { s: `bottom:0; left:0; width:100%; height:${edgeSize};`, dx:0, dy:speed },
        { s: `top:0; left:0; width:${edgeSize}; height:100%;`, dx:-speed, dy:0 },
        { s: `top:0; right:0; width:${edgeSize}; height:100%;`, dx:speed, dy:0 }
    ];

    let scrollInterval = null;

    function performScroll(dx, dy) {
        window.parent.scrollBy(dx, dy);
        const els = window.parent.document.querySelectorAll('div, section, main, [data-testid="stAppViewContainer"]');
        els.forEach(el => {
            if (el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight) {
                el.scrollBy({ left: dx, top: dy, behavior: 'auto' });
            }
        });
    }

    function start(dx, dy, el) {
        if (scrollInterval) return;
        el.style.backgroundColor = activeColor;
        performScroll(dx, dy);
        scrollInterval = setInterval(() => performScroll(dx, dy), 30);
    }

    function stop(el) {
        clearInterval(scrollInterval);
        scrollInterval = null;
        if(el) el.style.backgroundColor = edgeColor;
    }

    edges.forEach(e => {
        const div = window.parent.document.createElement('div');
        div.style.cssText = edgeStyle + e.s;
        
        const startFn = (ev) => { ev.preventDefault(); start(e.dx, e.dy, div); };
        const stopFn = () => stop(div);

        div.addEventListener('touchstart', startFn, {passive: false});
        div.addEventListener('touchend', stopFn);
        div.addEventListener('mousedown', startFn);
        div.addEventListener('mouseup', stopFn);
        div.addEventListener('mouseleave', stopFn);
        
        frame.appendChild(div);
    });

    window.parent.document.body.appendChild(frame);
</script>
"""
components.html(js_code.replace("__SPEED__", str(scroll_speed)), height=0)

# --- Main Logic ---
if api_key:
    genai.configure(api_key=api_key)
    
    # ★ モデル切り替えロジック
    if "Pro" in model_type:
        model_name = "gemini-2.5-pro"
        btn_label = "解析開始 (Gemini 2.5 Pro)"
    else:
        model_name = "gemini-2.5-flash"
        btn_label = "解析開始 (Gemini 2.5 Flash)"
        
    model = genai.GenerativeModel(model_name)
    
    uploaded_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        try:
            uploaded_file.seek(0)
            raw_image = Image.open(uploaded_file)
            target_width = img_quality
            if raw_image.width != target_width:
                ratio = target_width / raw_image.width
                new_height = int(raw_image.height * ratio)
                raw_image = raw_image.resize((target_width, new_height), Image.LANCZOS)
            
            if sharpness:
                raw_image = raw_image.filter(ImageFilter.UnsharpMask(radius=2, percent=150))

            st.markdown(f"### 1. エリア選択 (幅: {target_width}px)")
            st.info("青いフチを長押しでスクロール")
            cropped_img = st_cropper(raw_image, realtime_update=True, box_color='#FF0000', aspect_ratio=None, should_resize_image=False)
            
            st.markdown("---")
            col1, col2 = st.columns([1, 2])
            with col1: st.image(cropped_img, caption="送信画像", use_container_width=True)
            with col2:
                # ボタンのラベルも連動して変化
                if st.button(btn_label, type="primary", use_container_width=True):
                    st.session_state['display_image'] = cropped_img
                    with st.spinner(f"{model_name} で解析中..."):
                        try:
                            prompt = f"臨床微生物検査技師として血液培養グラム染色(1000倍, カメラ{camera_mag}倍)を解析。菌体特徴を詳述。条件:溶血ボトル(RBCなし)。判定困難時は再撮影依頼。最後は「CATEGORY:カテゴリ名」。"
                            res = model.generate_content([prompt, cropped_img])
                            st.session_state['last_result'] = res.text
                        except Exception as e: st.error(f"Error: {e}")

            if 'last_result' in st.session_state:
                st.markdown("### 3. 解析結果")
                st.write(st.session_state['last_result'].replace("CATEGORY:", ""))
                match_cats = []
                for line in st.session_state['last_result'].splitlines():
                    if "CATEGORY:" in line: match_cats = [c.strip() for c in line.split("CATEGORY:")[1].split(',')]
                
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
                correct = st.selectbox("正解ラベル", ["選択"] + valid_categories)
                if st.button("保存", use_container_width=True):
                    if correct != "選択" and GAS_APP_URL and 'display_image' in st.session_state:
                        buf = io.BytesIO()
                        st.session_state['display_image'].save(buf, format='PNG')
                        try:
                            requests.post(GAS_APP_URL, json={
                                'image': base64.b64encode(buf.getvalue()).decode(),
                                'filename': f"CORRECT_{correct}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                                'folderId': DRIVE_FOLDER_ID,
                                'mimeType': 'image/png'
                            })
                            st.success("保存完了")
                        except: st.error("保存失敗")
        except Exception as e: st.error(f"画像エラー: {e}")

