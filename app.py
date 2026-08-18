import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import cv2
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

mode = st.sidebar.radio("Select Pipeline Stage", ["Stage 1: Grid-Aware Table Extractor", "Stage 2: Excel Normalizer & Flatten"])

# ---------------------------------------------------------
# STAGE 1: GRID-BASED TABLE EXTRACTION
# ---------------------------------------------------------
if mode == "Stage 1: Grid-Aware Table Extractor":
    st.title("📄 Stage 1: OpenCV Grid Cell Extractor")
    st.write("Extracts text by detecting image table lines directly, preserving exact row and column structure.")

    uploaded_file = st.file_uploader("Upload Chart (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])

    def clean_text(text):
        cleaned = re.sub(r'[\|\\/_~\-\[\]\{\}\(\)\*\$\^#@!&=+<>]', '', text)
        cleaned = cleaned.replace(',', '.')
        return cleaned.strip()

    def extract_table_cells_opencv(pil_img):
        """Detects explicit table grid boxes using computer vision morphological operations."""
        img_np = np.array(pil_img.convert('RGB'))
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        
        # Threshold image to binary
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        
        # Detect vertical lines
        kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 30))
        vert = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_v)
        
        # Detect horizontal lines
        kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1))
        horiz = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_h)
        
        # Combine grid lines
        table_grid = cv2.add(vert, horiz)
        
        # Find table cell contours
        contours, _ = cv2.findContours(table_grid, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        
        boxes = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            # Filter out tiny noise boxes and page border frames
            if 15 < w < (img_np.shape[1] * 0.8) and 10 < h < (img_np.shape[0] * 0.5):
                boxes.append((x, y, w, h))
                
        if not boxes:
            # Fallback to pure OCR if no grid lines detected
            return None

        # Sort detected boxes into structured rows & columns
        boxes = sorted(boxes, key=lambda b: b[1])  # Sort top-to-bottom
        
        # Cluster boxes by horizontal row coordinates
        rows = []
        current_row = [boxes[0]]
        for b in boxes[1:]:
            if abs(b[1] - current_row[0][1]) < 12:
                current_row.append(b)
            else:
                rows.append(sorted(current_row, key=lambda item: item[0])) # Sort left-to-right
                current_row = [b]
        if current_row:
            rows.append(sorted(current_row, key=lambda item: item[0]))
            
        # OCR process each isolated grid cell
        matrix = []
        for row in rows:
            row_data = []
            for (x, y, w, h) in row:
                cell_crop = gray[y:y+h, x:x+w]
                # Upsample cell for better OCR accuracy
                cell_crop = cv2.resize(cell_crop, (0, 0), fx=2, fy=2)
                raw_text = pytesseract.image_to_string(cell_crop, config='--psm 6').strip()
                row_data.append(clean_text(raw_text))
            matrix.append(row_data)
            
        return matrix

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
                
            raw_matrix = []
            for idx, img in enumerate(images):
                st.info(f"Extracting grid cell topology from page {idx + 1}...")
                page_data = extract_table_cells_opencv(img)
                if page_data:
                    raw_matrix.extend(page_data)
                    
            if raw_matrix:
                max_cols = max([len(r) for r in raw_matrix])
                df_raw = pd.DataFrame([r + [''] * (max_cols - len(r)) for r in raw_matrix])
                
                st.subheader("📋 OpenCV Grid Matrix Preview")
                st.dataframe(df_raw, use_container_width=True)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_raw.to_excel(writer, index=False, header=[f"Col_{i+1}" for i in range(max_cols)])
                buffer.seek(0)
                st.download_button("📥 Download Grid Excel", buffer, "raw_grid_output.xlsx")
            else:
                st.warning("No explicit grid lines detected. Verify chart scan quality.")

# ---------------------------------------------------------
# STAGE 2: EXCEL NORMALIZATION & FLATTENING
# ---------------------------------------------------------
else:
    st.title("⚙️ Stage 2: Cleaned Excel to Flattened Table")
    st.write("Upload your Stage 1 Excel file (`raw_grid_output.xlsx`) to generate the final dataset.")

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
            st.error("No valid table records recognized in range 0-5000 MM.")
