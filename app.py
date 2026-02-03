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
st.title("🔬 グラム染色 AI (v18.0: Auto-Target Scroll)")

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
    
    st.info("【操作方法】\n左下のコントローラーで画像をスクロールできます。")
    
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
    /* 全体のスクロール設定を微調整 */
    .stApp {{ overflow: hidden !important; }} /* 外枠のスクロールは禁止 */
    
    /* コンテンツエリアだけスクロール許可 */
    [data-testid="stAppViewContainer"] {{
        overflow: auto !important;
        -webkit-overflow-scrolling: touch;
    }}
    
    iframe {{
        min-width: {img_quality}px !important;
        width: {img_quality}px !important;
    }}
</style>
""", unsafe_allow_html=True)

# --- JavaScript: 自動検出スクロールコントローラー ---
components.html("""
<script>
    const existing = window.parent.document.getElementById('gram-dpad');
    if (existing) existing.remove();

    const dpad = window.parent.document.createElement('div');
    dpad.id = 'gram-dpad';
    dpad.style.position = 'fixed';
    dpad.style.bottom = '20px';
    dpad.style.left = '20px';
    dpad.style.width = '140px';
    dpad.style.height = '140px';
    dpad.style.zIndex = '999999';
    dpad.style.backgroundColor = 'rgba(0,0,0,0.1)';
    dpad.style.borderRadius = '50%';
    dpad.style.touchAction = 'none';

    const btnStyle = `
        position: absolute;
        width: 45px;
        height: 45px;
        background: rgba(255, 75, 75, 0.95);
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

    // ★スクロール可能な要素を探し出す関数
    function findScrollableElement() {
        const doc = window.parent.document;
        // 優先度1: Streamlitのビューコンテナ
        let el = doc.querySelector('[data-testid="stAppViewContainer"]');
        if (el && el.scrollWidth > el.clientWidth) return el;

        // 優先度2: メインセクション
        el = doc.querySelector('section.main');
        if (el && el.scrollWidth > el.clientWidth) return el;
        
        // 優先度3: スクロール可能なdivを全検索
        const divs = doc.querySelectorAll('div');
        for (let d of divs) {
            const style = window.getComputedStyle(d);
            if ((style.overflowX === 'auto' || style.overflowX === 'scroll') && d.scrollWidth > d.clientWidth) {
                return d;
            }
        }
        return null;
    }

    function scrollTarget(x, y) {
        const target = findScrollableElement();
        if (target) {
            target.scrollBy({ left: x, top: y, behavior: 'smooth' });
        } else {
            // 見つからない場合はwindow自体を試す（最後の手段）
            window.parent.scrollBy({ left: x, top: y, behavior: 'smooth' });
        }
    }

    function createBtn(text, top, left, scrollX, scrollY) {
        const b = window.parent.document.createElement('div');
        b.innerHTML = text;
        b.style.cssText = btnStyle;
        b.style.top = top;
        b.style.left = left;
        
        const action = (e) => {
            e.preventDefault();
            e.stopPropagation();
            scrollTarget(scrollX, scrollY);
        };

        b.addEventListener('touchstart', action, {passive: false});
        b.addEventListener('click', action);
        
        return b;
    }

    // 上下左右ボタン
    dpad.appendChild(createBtn('▲', '0px', '47.5px', 0, -200));
    dpad.appendChild(createBtn('▼', '95px', '47.5px', 0, 200));
    dpad.appendChild(createBtn('◀', '47.5px', '0px', -200, 0));
    dpad.appendChild(createBtn('▶', '47.5px', '95px', 200, 0));

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
                st.write("")
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
