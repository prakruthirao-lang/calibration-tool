import streamlit as st
import pandas as pd
import numpy as np
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

st.set_page_config(page_title="Calibration Chart OCR & Flatten Tool", layout="wide")
st.title("📊 Multi-Format Calibration Chart OCR Tool")
st.write("Upload scanned PDF or Image calibration charts to extract and flatten custom table layouts.")

uploaded_file = st.file_uploader(
    "Upload Calibration Chart (PDF, PNG, JPG, JPEG)", 
    type=["pdf", "png", "jpg", "jpeg"]
)

def extract_rows_with_tesseract(image):
    """
    Extracts text bounding boxes via Tesseract positional data and groups 
    words into rows dynamically based on vertical (Y) coordinate alignment.
    """
    # Get positional data dictionary from image
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    
    word_boxes = []
    n_boxes = len(data['text'])
    for i in range(n_boxes):
        text = data['text'][i].strip()
        if text:  # Ignore empty spaces
            top = data['top'][i]
            left = data['left'][i]
            word_boxes.append({'top': top, 'left': left, 'text': text})
            
    # Sort detected words top-to-bottom by Y-coordinate
    word_boxes.sort(key=lambda item: item['top'])
    
    rows = []
    current_row = []
    last_y = None
    
    for box in word_boxes:
        y_coord = box['top']
        
        # Group text into the same line if vertical alignment is within 12px
        if last_y is None or abs(y_coord - last_y) < 12:
            current_row.append(box)
        else:
            # Sort line entries left-to-right by X-coordinate
            current_row.sort(key=lambda item: item['left'])
            rows.append([b['text'] for b in current_row])
            current_row = [box]
        last_y = y_coord
        
    if current_row:
        current_row.sort(key=lambda item: item['left'])
        rows.append([b['text'] for b in current_row])
        
    return rows

def normalize_calibration_table(raw_rows):
    """
    Identifies 10-column grids or 2-column lists dynamically and flattens to MM->LTRS pairs.
    """
    records = []
    
    for row in raw_rows:
        nums = []
        for word in row:
            cleaned = re.sub(r'[^0-9.]', '', word.replace(',', '.'))
            if cleaned:
                try:
                    nums.append(float(cleaned))
                except ValueError:
                    continue
        
        # Grid format: Base MM + 10 column values
        if len(nums) >= 11:
            base_mm = nums[0]
            for offset in range(10):
                records.append({'MM': int(base_mm + offset), 'LTRS': nums[offset + 1]})
                
        # List format: Pair of (MM, LTRS)
        elif len(nums) == 2:
            records.append({'MM': int(nums[0]), 'LTRS': nums[1]})
            
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values('MM').drop_duplicates('MM').reset_index(drop=True)
        
        # Build continuous MM sequence and interpolate
        max_mm = int(df['MM'].max())
        full_range = pd.DataFrame({'MM': range(0, max_mm + 1)})
        df = pd.merge(full_range, df, on='MM', how='left')
        df['LTRS'] = df['LTRS'].interpolate(method='linear').bfill().ffill()
        
    return df

if uploaded_file:
    if pytesseract is None:
        st.error("PyTesseract library is missing. Please check requirements.txt.")
    else:
        images = []
        file_type = uploaded_file.name.split('.')[-1].lower()
        
        if file_type == 'pdf':
            if convert_from_bytes is None:
                st.error("`pdf2image` module required to render PDF pages.")
            else:
                images = convert_from_bytes(uploaded_file.read())
        else:
            images = [Image.open(uploaded_file)]
            
        all_rows = []
        for idx, img in enumerate(images):
            st.info(f"🔍 Processing page {idx + 1} of {len(images)} with Tesseract OCR...")
            rows = extract_rows_with_tesseract(img)
            all_rows.extend(rows)
            
        final_df = normalize_calibration_table(all_rows)
        
        if not final_df.empty:
            st.subheader(f"✅ Extracted & Flattened Data ({len(final_df)} Total Points)")
            st.dataframe(final_df, use_container_width=True)
            
            # Export to Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                final_df.to_excel(writer, sheet_name='Calibration_Data', index=False)
            buffer.seek(0)
            
            st.download_button(
                label="📥 Download Excel File", 
                data=buffer, 
                file_name="Flattened_Calibration_Data.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("⚠️ No valid calibration entry layout was identified. Verify PDF quality or resolution.")
