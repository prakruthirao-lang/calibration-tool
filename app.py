import streamlit as st
import pandas as pd
import io
import re
from PIL import Image

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from pdf2image import convert_from_bytes
except ImportError:
    convert_from_bytes = None

st.set_page_config(page_title="Calibration Chart Pipeline", layout="wide")

# Sidebar Navigation
mode = st.sidebar.radio("Select Pipeline Stage", ["Stage 1: Raw OCR Extractor", "Stage 2: Excel Normalizer & Flatten"])

# ---------------------------------------------------------
# STAGE 1: RAW OCR EXTRACTION
# ---------------------------------------------------------
if mode == "Stage 1: Raw OCR Extractor":
    st.title("📄 Stage 1: Raw OCR Extraction to Excel")
    st.write("Upload your PDF or Image chart to extract raw scanned text lines into a draft Excel file for manual review.")

    uploaded_file = st.file_uploader("Upload Chart (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])

    def extract_raw_rows(image):
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        word_boxes = []
        for i in range(len(data['text'])):
            text = data['text'][i].strip()
            if text:
                word_boxes.append({'top': data['top'][i], 'left': data['left'][i], 'text': text})
                
        word_boxes.sort(key=lambda item: item['top'])
        rows, current_row, last_y = [], [], None
        for box in word_boxes:
            if last_y is None or abs(box['top'] - last_y) < 12:
                current_row.append(box)
            else:
                current_row.sort(key=lambda item: item['left'])
                rows.append([b['text'] for b in current_row])
                current_row = [box]
            last_y = box['top']
            
        if current_row:
            current_row.sort(key=lambda item: item['left'])
            rows.append([b['text'] for b in current_row])
            
        return rows

    if uploaded_file:
        if pytesseract is None:
            st.error("PyTesseract module is not available.")
        else:
            images = []
            ext = uploaded_file.name.split('.')[-1].lower()
            if ext == 'pdf':
                images = convert_from_bytes(uploaded_file.read())
            else:
                images = [Image.open(uploaded_file)]
                
            raw_rows = []
            for idx, img in enumerate(images):
                st.info(f"Scanning page {idx + 1}...")
                raw_rows.extend(extract_raw_rows(img))
                
            max_cols = max([len(r) for r in raw_rows]) if raw_rows else 0
            df_raw = pd.DataFrame([r + [''] * (max_cols - len(r)) for r in raw_rows])
            
            if not df_raw.empty:
                st.subheader("📋 Raw OCR Matrix Preview")
                st.dataframe(df_raw, use_container_width=True)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_raw.to_excel(writer, index=False, header=[f"Col_{i+1}" for i in range(max_cols)])
                buffer.seek(0)
                st.download_button("📥 Download Raw Excel for Inspection", buffer, "raw_ocr_output.xlsx")

# ---------------------------------------------------------
# STAGE 2: EXCEL NORMALIZATION & FLATTENING
# ---------------------------------------------------------
else:
    st.title("⚙️ Stage 2: Cleaned Excel to Flattened Table")
    st.write("Upload your reviewed or edited Stage 1 Excel file (`raw_ocr_output.xlsx`) to generate the final calibration dataset.")

    uploaded_excel = st.file_uploader("Upload Intermediate Excel File", type=["xlsx", "xls"])

    def process_and_flatten_excel(df):
        records = []
        for _, row in df.iterrows():
            nums = []
            for cell in row.dropna():
                cleaned = re.sub(r'[^0-9.]', '', str(cell).replace(',', '.'))
                if cleaned:
                    try:
                        nums.append(float(cleaned))
                    except ValueError:
                        continue
            
            if len(nums) >= 11:
                base_mm = nums[0]
                if 0 <= base_mm <= 5000:
                    for offset in range(10):
                        records.append({'MM': int(base_mm + offset), 'LTRS': nums[offset + 1]})
            elif len(nums) == 2:
                mm_val, ltrs_val = nums[0], nums[1]
                if 0 <= mm_val <= 5000:
                    records.append({'MM': int(mm_val), 'LTRS': ltrs_val})
                    
        result_df = pd.DataFrame(records)
        if not result_df.empty:
            result_df = result_df.sort_values('MM').drop_duplicates('MM').reset_index(drop=True)
            min_mm, max_mm = int(result_df['MM'].min()), int(result_df['MM'].max())
            full_range = pd.DataFrame({'MM': range(min_mm, max_mm + 1)})
            result_df = pd.merge(full_range, result_df, on='MM', how='left')
            result_df['LTRS'] = result_df['LTRS'].interpolate(method='linear').bfill().ffill()
            
        return result_df

    if uploaded_excel:
        df_raw = pd.read_excel(uploaded_excel)
        final_df = process_and_flatten_excel(df_raw)
        
        if not final_df.empty:
            st.subheader(f"✅ Final Flattened Table ({len(final_df)} Total MM Points)")
            st.dataframe(final_df, use_container_width=True)
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                final_df.to_excel(writer, sheet_name='Flattened_Calibration', index=False)
            buffer.seek(0)
            
            st.download_button("📥 Download Final Flattened Excel", buffer, "Final_Calibration_Table.xlsx")
        else:
            st.error("No valid table records recognized in range 0-5000 MM. Verify column values in the input Excel file.")
