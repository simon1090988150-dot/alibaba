import streamlit as st
import pandas as pd
import re
import math
import datetime
import requests

# ==========================================
# 1. 配置与样式
# ==========================================
st.set_page_config(page_title="Smart Quote Pro", page_icon="⚡", layout="wide")

# 自定义 CSS 让界面更像 APP
st.markdown("""
<style>
    .main {background-color: #f8f9fa;}
    .stButton>button {width: 100%; border-radius: 8px; height: 3em; font-weight: bold;}
    .stSelectbox, .stTextInput {margin-bottom: 10px;}
    .price-card {
        background-color: white; padding: 20px; border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-left: 5px solid #0078d4;
    }
    .highlight {color: #0078d4; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 核心逻辑 (复用之前的引擎)
# ==========================================
class PricingEngine:
    @staticmethod
    def calculate(desc, options, stroke_req):
        logs = []; total_cny = 0
        if not isinstance(desc, str): return 0, ["Error: No description"]
        
        # 基础价格
        base_match = re.search(r'单价[:：]?\s*(\d+)', desc)
        if base_match:
            base_price = float(base_match.group(1))
            total_cny += base_price
            logs.append(f"基础价格 (Base): {base_price} CNY")
        
        # 行程加价
        stroke_match = re.search(r'行程(\d+)-(\d+).*?每加行程(\d+)毫米加(\d+)元', desc)
        if stroke_match:
            base_end = int(stroke_match.group(2))
            inc_len = int(stroke_match.group(3))
            inc_cost = int(stroke_match.group(4))
            if stroke_req > base_end:
                steps = math.ceil((stroke_req - base_end) / inc_len)
                cost = steps * inc_cost
                total_cny += cost
                logs.append(f"行程加价 ({stroke_req}mm): +{cost} CNY")

        # 选配项逻辑
        addon_map = {
            'ball_screw': (r'滚珠丝杆.*?加(\d+)元', '滚珠丝杆 (Ball Screw)'),
            'fisheye': (r'鱼眼.*?加(\d+)元', '鱼眼接头 (Fisheye)'),
            'rear_plate': (r'后接头加底板.*?加(\d+)元', '后底板 (Rear Plate)'),
            'front_plate': (r'前接头.*?加顶板.*?加(\d+)元', '前顶板 (Front Plate)'),
            'machining': (r'开槽和孔径.*?(\d+)元', '开槽加工 (Machining)'),
            'hall': (r'加霍尔.*?加(\d+)元', '霍尔感应 (Hall Sensor)'),
            'comm': (r'通讯.*?加(\d+)元', 'RS485/CAN'),
            'pot': (r'电位器.*?加(\d+)元', '电位器 (Potentiometer)'),
            'ctrl_1': (r'单控.*?(\d+)元', '单控 (Single Ctrl)'),
            'ctrl_2': (r'二同步.*?(\d+)元', '二同步 (Dual Ctrl)'),
            'ctrl_3': (r'三同步.*?(\d+)元', '三同步 (Triple Ctrl)'),
            'ctrl_4': (r'四同步.*?(\d+)元', '四同步 (Quad Ctrl)')
        }
        
        for key, (pat, name) in addon_map.items():
            if options.get(key):
                m = re.search(pat, desc)
                if m: 
                    cost = int(m.group(1))
                    total_cny += cost
                    logs.append(f"{name}: +{cost} CNY")
                elif key == 'ball_screw': # 滚珠丝杆特殊兜底
                    total_cny += 280
                    logs.append(f"{name}: +280 CNY (Default)")
        
        return total_cny, logs

class WeightEngine:
    MODEL_PARAMS = {
        "520": {"base": 4.40, "factor": 0.0050}, "521": {"base": 3.90, "factor": 0.0060}, 
        "524": {"base": 3.40, "factor": 0.0050}, "523": {"base": 2.40, "factor": 0.0040}, 
        "525": {"base": 2.10, "factor": 0.0040}, "522": {"base": 1.10, "factor": 0.0025}, 
        "526": {"base": 1.50, "factor": 0.0030}, "528": {"base": 3.50, "factor": 0.0055}, 
        "Default": {"base": 4.00, "factor": 0.0050}
    }
    @staticmethod
    def calculate(model_str, stroke_mm, qty):
        key = "Default"
        for k in WeightEngine.MODEL_PARAMS.keys():
            if k in str(model_str): key = k; break
        params = WeightEngine.MODEL_PARAMS[key]
        single_nw = params["base"] + (stroke_mm * params["factor"])
        total_nw = single_nw * qty
        return single_nw, total_nw

@st.cache_data(ttl=3600) # 缓存汇率1小时
def get_exchange_rate(to_curr):
    if to_curr == "CNY": return 1.0
    try:
        url = f"https://api.frankfurter.app/latest?from=CNY&to={to_curr}"
        data = requests.get(url, timeout=2).json()
        return data['rates'][to_curr]
    except:
        # 离线兜底
        rates = {"USD": 0.138, "EUR": 0.127, "GBP": 0.109}
        return rates.get(to_curr, 0.14)

# ==========================================
# 3. 界面布局 (UI)
# ==========================================
# 侧边栏：设置区
with st.sidebar:
    st.title("⚙️ 参数设置 (Settings)")
    
    # 读取 CSV
    try:
        df = pd.read_csv("product_data.csv")
        models = df['model_number'].tolist()
    except:
        st.error("找不到 product_data.csv")
        models = ["No Data"]
        df = pd.DataFrame()

    # 核心参数
    sel_model = st.selectbox("选择型号 (Model)", models)
    sel_curr = st.selectbox("目标货币 (Currency)", ["USD", "EUR", "CNY", "GBP", "AUD"])
    val_stroke = st.number_input("行程 (Stroke mm)", value=100, step=50)
    val_qty = st.number_input("数量 (Qty)", value=1, min_value=1)

    st.markdown("---")
    st.subheader("🔧 选配组件 (Options)")
    
    # 选配项 (双列布局)
    col1, col2 = st.columns(2)
    opts = {}
    with col1:
        opts['ball_screw'] = st.checkbox("滚珠丝杆")
        opts['fisheye'] = st.checkbox("鱼眼接头")
        opts['rear_plate'] = st.checkbox("后底板")
        opts['front_plate'] = st.checkbox("前顶板")
        opts['machining'] = st.checkbox("开槽加工")
        opts['hall'] = st.checkbox("霍尔感应")
    with col2:
        opts['comm'] = st.checkbox("RS485/CAN")
        opts['pot'] = st.checkbox("电位器")
        opts['ctrl_1'] = st.checkbox("单控")
        opts['ctrl_2'] = st.checkbox("二同步")
        opts['ctrl_3'] = st.checkbox("三同步")
        opts['ctrl_4'] = st.checkbox("四同步")

# 主界面
st.title("🚀 Smart Quote Pro (智能报价)")

# 获取当前型号数据
if not df.empty and sel_model != "No Data":
    row = df[df['model_number'] == sel_model].iloc[0]
    desc = str(row['description'])
    
    # 1. 产品描述卡片
    with st.expander("📄 产品描述 (Product Description)", expanded=True):
        # 简单的格式化，把序号换行
        fmt_desc = re.sub(r'(\d+[:：])', r'\n\n**\1**', desc)
        st.markdown(fmt_desc)

    # 2. 计算逻辑
    cny_price, logs = PricingEngine.calculate(desc, opts, val_stroke)
    rate = get_exchange_rate(sel_curr)
    final_price = cny_price * rate
    total_price = final_price * val_qty
    
    # 重量计算
    s_nw, t_nw = WeightEngine.calculate(sel_model, val_stroke, val_qty)

    # 3. 结果展示区 (两列)
    st.markdown("### 💰 报价详情 (Quotation)")
    
    c1, c2 = st.columns([3, 2])
    
    with c1:
        st.markdown(f"""
        <div class="price-card">
            <h4>单价 (Unit Price)</h4>
            <h2 class="highlight">{final_price:,.2f} {sel_curr}</h2>
            <p style="color:gray">≈ {cny_price:,.2f} CNY (汇率: {rate:.4f})</p>
            <hr>
            <h4>总价 (Total Price) - {val_qty} Pcs</h4>
            <h2 style="color:#d13438">{total_price:,.2f} {sel_curr}</h2>
        </div>
        """, unsafe_allow_html=True)
        
        st.info(f"📦 **重量预估**: 单个净重 **{s_nw:.2f} kg** | 总净重 **{t_nw:.2f} kg**")

    with c2:
        st.markdown("**费用明细 (Cost Breakdown):**")
        for log in logs:
            st.text(f"• {log}")
            
    # 4. 底部工具栏
    st.markdown("---")
    st.caption(f"Generated by Smart Quote Pro | Date: {datetime.date.today()}")

else:
    st.warning("请先上传或检查 product_data.csv 文件")
