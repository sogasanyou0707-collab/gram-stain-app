import streamlit as st
import google.generativeai as genai
import os
import random
from PIL import Image
from datetime import datetime
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# === 設定エリア ===
LIBRARY_FOLDER_NAME = 'my_gram_app'
INBOX_FOLDER_NAME = 'Inbox'

st.set_page_config(page_title="グラム染色AI ver4.2 (診断モード)", page_icon="🔬")
st.title("🔬 グラム染色 AI相談アプリ (ver4.2)")

# --- サイドバー ---
st.sidebar.header("⚙️ 設定")
api_key = st.sidebar.text_input("Gemini APIキー", type="password")

# モデル選択
model_options = ["gemini-3-flash-preview"] 
if api_key:
    try:
        genai.configure(api_key=api_key)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                name = m.name.replace("models/", "")
                if name not in model_options:
                    model_options.append(name)
    except Exception:
        pass 
default_backups = ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"]
for m in default_backups:
    if m not in model_options:
        model_options.append(m)
selected_model_name = st.sidebar.selectbox("使用するAIモデル", model_options, index=0)

# フォルダ準備
if not os.path.exists(INBOX_FOLDER_NAME):
    os.makedirs(INBOX_FOLDER_NAME)

# --- メイン処理 ---
if api_key:
    try:
        model = genai.GenerativeModel(selected_model_name)
    except Exception as e:
        st.error(f"モデル設定エラー: {e}")

    uploaded_file = st.file_uploader("顕微鏡写真を選択...", type=["jpg", "png", "jpeg"])

    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption='アップロード画像', use_container_width=True)

        if st.button("AIで解析する"):
            st.write("---")
            with st.spinner(f'AIモデル ({selected_model_name}) が思考中...'):
                try:
                    # ライブラリー確認
                    if os.path.exists(LIBRARY_FOLDER_NAME):
                        categories = [f for f in os.listdir(LIBRARY_FOLDER_NAME) if not f.startswith('.') and f != INBOX_FOLDER_NAME]
                        categories_str = ", ".join(categories)
                    else:
                        categories = []
                        categories_str = "なし"

                    # プロンプト
                    prompt = f"""
                    あなたは臨床微生物学の専門家です。このグラム染色画像を解説してください。
                    
                    【出力フォーマット】
                    1. 所見（染色性、形態、配列など）
                    2. 推定される菌種グループ
                    3. 以下のリストの中で、最も近いカテゴリがあれば1つ選んでください。
                       リスト: [{categories_str}]
                       
                    【重要】
                    最後に必ず「CATEGORY:選択したカテゴリ名」という形式で1行だけ出力してください。
                    該当なしの場合は「CATEGORY:None」としてください。
                    """

                    safety_settings = {
                        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }

                    response = model.generate_content([prompt, image], safety_settings=safety_settings)
                    
                    if response.text:
                        text = response.text
                        st.session_state['last_result'] = text
                        st.session_state['last_image'] = image
                    else:
                        st.error("AIからの応答が空でした。")

                except Exception as e:
                    st.error(f"エラー: {e}")

        # --- 結果表示 & 画像参照ロジック ---
        if 'last_result' in st.session_state:
            text = st.session_state['last_result']
            st.markdown("### 🤖 解析結果")
            st.write(text.replace("CATEGORY:", ""))

            # カテゴリ抽出
            match_category = None
            for line in text.split('\n'):
                if "CATEGORY:" in line:
                    # 空白を除去してクリーンにする
                    match_category = line.split("CATEGORY:")[1].strip()
            
            # === ★ここから診断モード ===
            st.write("---")
            st.caption("🔧 システム診断情報 (開発用)")
            
            if match_category:
                st.info(f"AIが指定したカテゴリ名: [{match_category}]")
                
                target_path = os.path.join(LIBRARY_FOLDER_NAME, match_category)
                st.text(f"探しに行ったフォルダ: {target_path}")

                if os.path.exists(target_path):
                    # フォルダはある。ファイルを探す
                    files = [f for f in os.listdir(target_path) if f.lower().endswith(('png', 'jpg', 'jpeg'))]
                    st.text(f"見つかった画像ファイル数: {len(files)} 枚")
                    
                    if files:
                        # 成功ルート
                        ref_image_path = os.path.join(target_path, random.choice(files))
                        st.success(f"📂 ライブラリー「{match_category}」の画像を表示します")
                        st.image(ref_image_path, caption=f'参照画像: {match_category}', use_container_width=True)
                    else:
                        # フォルダはあるが画像がない
                        st.warning("⚠️ フォルダは見つかりましたが、中に画像ファイル(png, jpg)が入っていません。")
                        st.text(f"フォルダの中身: {os.listdir(target_path)}")
                else:
                    # フォルダ自体がない
                    st.error(f"⚠️ フォルダ '{match_category}' が見つかりません。")
                    st.text(f"現在あるフォルダ一覧: {os.listdir(LIBRARY_FOLDER_NAME)}")
            else:
                st.warning("⚠️ AIの回答から 'CATEGORY:' の行が見つけられませんでした。")

            # 保存ボタン
            st.write("---")
            col1, col2 = st.columns([1, 2])
            with col1:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_filename = f"{timestamp}.png"
                if st.button("📥 画像をInboxに保存"):
                    save_path = os.path.join(INBOX_FOLDER_NAME, save_filename)
                    st.session_state['last_image'].save(save_path)
                    st.success(f"保存完了: {save_filename}")

else:
    st.info("👈 左側のサイドバーにAPIキーを入力してください。")
