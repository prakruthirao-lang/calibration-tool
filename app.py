import streamlit as st
import pandas as pd
import io
import re

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from PIL import Image
    import pytesseract
    from pdf2image import convert_from_bytes
except ImportError:
    pytesseract = None

st.set_page_config(page_title="Calibration Chart Converter", layout="wide")
st.title("📊 Tank Calibration Chart Converter & OCR Tool")

uploaded_file = st.file_uploader("Upload Calibration File", type=["xlsx", "xls", "csv", "pdf", "png", "jpg", "jpeg"])

def parse_ocr_text_to_df(text):
    lines = text.split('\n')
    rows = []
    for line in lines:
        nums = re.findall(r'\b\d+(?:[.,]\d+)?\b', line)
        if len(nums) >= 2:
            rows.append(nums)
    if rows:
        max_cols = max(len(r) for r in rows)
        padded_rows = [r + [None]*(max_cols - len(r)) for r in rows]
        cols = ['H (mm)'] + [str(i) for i in range(max_cols - 1)]
        return pd.DataFrame(padded_rows, columns=cols[:max_cols])
    return pd.DataFrame()

def process_calibration_data(df):
    records = []
    h_col = df.columns[0]
    for _, row in df.iterrows():
        try:
            base_mm = float(str(row[h_col]).replace(',', '').strip())
            for offset in range(10):
                col_str = str(offset)
                if col_str in df.columns and pd.notnull(row[col_str]):
                    val = float(str(row[col_str]).replace(',', '').strip())
                    records.append({'MM': int(base_mm + offset), 'LTRS': val})
        except (ValueError, TypeError):
            continue
    flattened_df = pd.DataFrame(records)
    if not flattened_df.empty:
        flattened_df = flattened_df.sort_values('MM').drop_duplicates('MM').reset_index(drop=True)
        max_mm = int(flattened_df['MM'].max())
        full_mm_df = pd.DataFrame({'MM': range(0, max(1750, max_mm + 1))})
        merged = pd.merge(full_mm_df, flattened_df, on='MM', how='left')
        merged['LTRS'] = merged['LTRS'].interpolate(method='linear').bfill()
        return merged
    return df

if uploaded_file:
    file_type = uploaded_file.name.split('.')[-1].lower()
    df_extracted = None

    if file_type in ['xlsx', 'xls', 'csv']:
        df_extracted = pd.read_csv(uploaded_file) if file_type == 'csv' else pd.read_excel(uploaded_file)

    elif file_type == 'pdf':
        if pdfplumber:
            all_tables = []
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for t in tables:
                        if t:
                            all_tables.extend(t)
            if all_tables and len(all_tables) > 1:
                df_extracted = pd.DataFrame(all_tables[1:], columns=all_tables[0])

        # OCR fallback for DocScan scanned images
        if df_extracted is None or df_extracted.empty:
            st.info("⚡ Scanned image PDF detected. Running OCR processing...")
            if pytesseract:
                images = convert_from_bytes(uploaded_file.read())
                ocr_text = ""
                for img in images:
                    ocr_text += pytesseract.image_to_string(img) + "\n"
                df_extracted = parse_ocr_text_to_df(ocr_text)

    if df_extracted is not None and not df_extracted.empty:
        flattened_df = process_calibration_data(df_extracted)
        st.subheader("✅ Extracted Data Preview")
        st.dataframe(flattened_df.head(20), use_container_width=True)
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            flattened_df.to_excel(writer, sheet_name='Flattened_Calibration', index=False)
        buffer.seek(0)
        
        st.download_button(
            label="📥 Download Flattened Excel File",
            data=buffer,
            file_name="Flattened_Calibration_Data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
