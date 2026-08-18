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
mode = st.sidebar.radio("Select Pipeline Stage", ["Stage 1: Clean Raw OCR Extractor", "Stage 2: Excel Normalizer & Flatten"])

# ---------------------------------------------------------
# STAGE 1: CLEAN RAW OCR EXTRACTION
# ---------------------------------------------------------
if mode == "Stage 1: Clean Raw OCR Extractor":
    st.title("📄 Stage 1: Clean Raw OCR Extraction to Excel")
    st.write("Upload your chart to extract raw scanned table lines with special characters (`|`, `_`, `~`, etc.) automatically removed.")

    uploaded_file = st.file_uploader("Upload Chart (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])

    def clean_text(text):
        """Strips out vertical table borders '|', brackets, and punctuation artifacts."""
        # Remove pipe symbols, slashes, brackets, and random noise chars
        cleaned = re.sub(r'[\|\\/_~\-\[\]\{\}\(\)\*\$\^#@!&=+<>]', '', text)
        # Standardize commas to decimal points for clean number representation
        cleaned = cleaned.replace(',', '.')
        return cleaned.strip()

    def extract_raw_rows(image):
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        word_boxes = []
        
        for i in range(len(data['text'])):
            raw_text = data['text'][i].strip()
            cleaned = clean_text(raw_text)
            
            # Keep non-empty text boxes after symbol removal
            if cleaned:
                word_boxes.append({'top': data['top'][i], 'left': data['left'][i], 'text': cleaned})
                
        # Sort text blocks top-to-bottom
        word_boxes.sort(key=lambda item: item['top'])
        
        rows, current_row, last_y = [], [], None
        for box in word_boxes:
            # Group into the same horizontal row if Y-coordinates are within 12 pixels
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
            st.error("PyTesseract module is missing.")
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
                st.subheader("📋 Cleaned Raw OCR Matrix Preview")
                st.dataframe(df_raw, use_container_width=True)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_raw.to_excel(writer, index=False, header=[f"Col_{i+1}" for i in range(max_cols)])
                buffer.seek(0)
                
                st.download_button("📥 Download Cleaned Raw Excel", buffer, "raw_ocr_output_cleaned.xlsx")

# ---------------------------------------------------------
# STAGE 2: EXCEL NORMALIZATION & FLATTENING
# ---------------------------------------------------------
else:
    st.title("⚙️ Stage 2: Cleaned Excel to Flattened Table")
    st.write("Upload your Stage 1 cleaned Excel file (`raw_ocr_output_cleaned.xlsx`) to generate the final dataset.")

    uploaded_excel = st.file_uploader("Upload Intermediate Excel File", type=["xlsx", "xls"])

    def process_and_flatten_excel(df):
        records = []
        for _, row in df.iterrows():
            nums = []
            for cell in row.dropna():
                cleaned = re.sub(r'[^0-9.]', '', str(cell))
                if cleaned:
                    try:
                        nums.append(float(cleaned))
                    except ValueError:
                        continue
            
            # Format 1: Base MM + 10 Offset Columns (0 to 9)
            if len(nums) >= 11:
                base_mm = nums[0]
                if 0 <= base_mm <= 5000:
                    for offset in range(10):
                        records.append({'MM': int(base_mm + offset), 'LTRS': nums[offset + 1]})
            # Format 2: Direct Pair [MM, LTRS]
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
