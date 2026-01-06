import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

# --- CẤU HÌNH TRANG ---
st.set_page_config(page_title="PVM Test Result Tool", layout="wide")

# --- HÀM CHUẨN HÓA CÂU HỎI ---
def chuan_hoa_cau_hoi(text):
    if pd.isna(text): return ""
    text = text.lower().replace("\r", "").replace("\n", " ")
    text = re.sub(r'[?:.,]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# --- HÀM LOGIN ---
def login_user():
    login_url = 'https://perfettivanmelle.acabiz.vn/login'
    session = requests.Session()
    try:
        r = session.get(login_url)
        soup = BeautifulSoup(r.text, 'html.parser')
        token_input = soup.find('input', {'name': '_token'})
        csrf_token = token_input['value'] if token_input else ''
        xsrf_token = session.cookies.get("XSRF-TOKEN")

        user = st.secrets["web_credentials"]["username"]
        pw = st.secrets["web_credentials"]["password"]

        payload = {'email': user, 'password': pw, '_token': csrf_token, "remember":'on'}
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0",
            "Referer": login_url,
            "X-XSRF-TOKEN": xsrf_token or ""
        }
        response = session.post(login_url, data=payload, headers=headers)
        if response.status_code in [200, 302]:
            return session, True
        return None, False
    except:
        return None, False

# --- HÀM LẤY DANH SÁCH BÀI TEST (DICTIONARY) ---

def get_h4_text(url):
    r = session.get(url, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")
    h4 = soup.find('h4', class_='fs-20px').get_text(strip=True)
    return h4 if h4 else None, url

def get_test_options(session):
  # Take link to access test results
    report_url = 'https://perfettivanmelle.acabiz.vn/company/quizscore/report/type=assign'
    response = session.get(report_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    tbody = soup.find('tbody')
    rows = tbody.find_all('tr')
    test_link = []
    for tr in rows:
        a_tag = tr.find('a')
        if a_tag and a_tag.has_attr('href'):
            link = a_tag['href']
            test_link.append(link)

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = dict(executor.map(get_h4_text, test_link))
        return results

# --- HÀM LẤY LINK CHI TIẾT TỪNG NGƯỜI ---
def get_candidate_links(session, report_url):
    response = session.get(report_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    def extract(s):
        return [a["href"] for a in s.find_all("a", string=lambda x: x and "Chi tiết" in x)]
    
    links = extract(soup)
    pagination = soup.find('ul', class_='pagination')
    if pagination:
        page_urls = list(set([a['href'] for a in pagination.find_all('a', href=True) if '?page=' in a['href']]))
        for url in page_urls:
            links.extend(extract(BeautifulSoup(session.get(url).text, 'html.parser')))
    return list(set(links))

# --- HÀM XỬ LÝ KẾT QUẢ CHI TIẾT (LOGIC CỦA BẠN) ---
def take_result(session, link, df_cau_hoi):
    response = session.get(link)
    soup = BeautifulSoup(response.text, 'html.parser')
    ho_ten_tag = soup.find("span", class_="span_lable", string="Họ và tên:")
    ho_ten = ho_ten_tag.find_next("span", class_="span_content").text.strip() if ho_ten_tag else "Không rõ"
    
    tables = soup.find_all("table", class_="table_point")
    data = []
    for table in tables:
        header = table.find("th", colspan="2")
        raw_q = header.get_text(strip=True) if header else ""
        raw_q = re.sub(r"Đạt\s*\d+/\d+\s*điểm", "", raw_q).strip()
        cau_hoi = re.sub(r"^Câu hỏi\s*\d+\s*:?", "", raw_q).strip()
        
        is_sai = table.find("span", class_="badge badge-danger")
        is_boqua = table.find("span", class_="badge badge-dark")
        
        dap_an_dung_da_chon, dap_an_sai_da_chon, dap_an_dung_bo_sot = [], [], []
        dap_an_dung, dap_an_sai = None, None
        
        rows = table.find_all("tr")
        all_options = []
        for row in rows:
            div = row.find("div")
            if not div: continue
            input_tag = div.find("input")
            span = div.find("span")
            style = div.get("style", "").lower()
            all_options.append((span.text.strip() if span else "", input_tag and input_tag.has_attr("checked"), style))

        num_checked = sum(1 for _, c, _ in all_options if c)
        num_blue = sum(1 for _, _, s in all_options if "#0871d0" in s)

        if num_blue == 1 and num_checked <= 1:
            for text, checked, style in all_options:
                if "#0871d0" in style: dap_an_dung = text
                if checked and "#28a745" not in style: dap_an_sai = text
            data.append({"Câu hỏi": cau_hoi, "Trạng thái": "Bỏ qua" if is_boqua else ("Sai" if is_sai else "Đúng"), 
                         "Kiểu": "1_lua_chon", "Đáp án đúng": dap_an_dung, "Đáp án sai đã chọn": dap_an_sai or ""})
        else:
            for text, checked, style in all_options:
                if checked:
                    if "#28a745" in style: dap_an_dung_da_chon.append(text)
                    else: dap_an_sai_da_chon.append(text)
                elif "#0871d0" in style: dap_an_dung_bo_sot.append(text)
            data.append({"Câu hỏi": cau_hoi, "Trạng thái": "Bỏ qua" if is_boqua else ("Sai" if is_sai else "Đúng"),
                         "Kiểu": "nhieu_lua_chon", "Đáp án đúng": "\n".join(dap_an_dung_da_chon), "Đáp án sai đã chọn": "\n".join(dap_an_sai_da_chon)})

    df = pd.DataFrame(data)
    df["Câu hỏi chuẩn hóa"] = df["Câu hỏi"].apply(chuan_hoa_cau_hoi)
    df_merged = df.merge(df_cau_hoi, on="Câu hỏi chuẩn hóa", how="left").drop(columns=["Câu hỏi chuẩn hóa"])
    df_merged["Họ và tên"] = ho_ten
    return df_merged

# --- GIAO DIỆN STREAMLIT ---
st.title("🛠 PVM Automatic Scraper")
st.sidebar.header("📁 Bước 1: Tải Question Bank")
file_qb = st.sidebar.file_uploader("Chọn file Excel ngân hàng câu hỏi", type=["xlsx"])

if file_qb:
    df_qb = pd.read_excel(file_qb, header=8).iloc[:, 2:]
    df_qb["Câu hỏi chuẩn hóa"] = df_qb["NỘI DUNG CÂU HỎI*"].apply(chuan_hoa_cau_hoi)
    df_qb_clean = df_qb[["Câu hỏi chuẩn hóa", "GROUP SKILL", "SKILL"]].drop_duplicates()
    
    if st.sidebar.button("🔐 Đăng nhập & Lấy danh sách bài test"):
        with st.spinner("Đang kết nối..."):
            session, success = login_user()
            if success:
                st.success("Đăng nhập thành công!")
                st.session_state.session = session
                st.session_state.tests = get_test_options(session)
            else:
                st.error("Thất bại. Kiểm tra st.secrets!")

if "tests" in st.session_state:
    st.header("📋 Bước 2: Chọn bài kiểm tra")
    selected_test = st.selectbox("Danh sách bài test trên hệ thống:", list(st.session_state.tests.keys()))
    
    if st.button("🔍 Quét danh sách ứng viên"):
        with st.spinner("Đang tìm bài làm..."):
            links = get_candidate_links(st.session_state.session, st.session_state.tests[selected_test])
            st.session_state.candidate_links = links
            st.write(f"Tìm thấy **{len(links)}** bài làm chi tiết.")

if "candidate_links" in st.session_state:
    st.header("📊 Bước 3: Xuất dữ liệu")
    if st.button("🚀 Bắt đầu xử lý (Có thể mất vài phút)"):
        all_dfs = []
        progress_bar = st.progress(0)
        for i, link in enumerate(st.session_state.candidate_links):
            df_item = take_result(st.session_state.session, link, df_qb_clean)
            all_dfs.append(df_item)
            progress_bar.progress((i + 1) / len(st.session_state.candidate_links))
        
        final_df = pd.concat(all_dfs, ignore_index=True)
        st.dataframe(final_df)
        
        # Tạo nút tải file
        output = BytesIO()
        final_df.to_excel(output, index=False)
        st.download_button(label="📥 Tải file kết quả (Excel)", data=output.getvalue(), 
                           file_name=f"Result_{int(time.time())}.xlsx", 
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

      