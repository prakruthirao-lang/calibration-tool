import streamlit as st
import pandas as pd
import numpy as np
import io
import re
from PIL import Image

try:
    import easyocr
    reader = easyocr.Reader(['en'], gpu=False)
except ImportError:
    reader = None

try:
    from pdf2image import convert_from_bytes
except ImportError:
    convert_from_bytes = None

st.set_page_config(page_title="Advanced OCR Table Extractor", layout="wide")
st.title("📊 Multi-Format Calibration Chart OCR Tool")

uploaded_file = st.file_uploader(
    "Upload Scanned Chart (PDF, PNG, JPG)", 
    type=["pdf", "png", "jpg", "jpeg"]
)

def extract_rows_with_easyocr(image):
    """
    Extracts text blocks with pixel coordinates and groups them into rows 
    based on vertical (Y) alignment to handle different table structures.
    """
    img_np = np.array(image)
    # OCR returns: [ [bbox, text, confidence], ... ]
    results = reader.readtext(img_np)
    
    # Sort detected text vertically by Y-min coordinate
    results.sort(key=lambda x: x[0][0][1])
    
    rows = []
    current_row = []
    last_y = None
    
    for bbox, text, conf in results:
        y_min = bbox[0][1]
        
        # Group text into the same row if Y-coordinates are within 10 pixels
        if last_y is None or abs(y_min - last_y) < 12:
            current_row.append((bbox[0][0], text)) # Store (X-coord, text)
        else:
            # Sort items in the completed row left-to-right by X-coord
            current_row.sort(key=lambda x: x[0])
            rows.append([item[1] for item in current_row])
            current_row = [(bbox[0][0], text)]
        last_y = y_min
        
    if current_row:
        current_row.sort(key=lambda x: x[0])
        rows.append([item[1] for item in current_row])
        
    return rows

def normalize_calibration_table(raw_rows):
    """
    Dynamically identifies if the extracted table is a 10-column grid 
    or a 2-column list, then flattens it to single MM->LTRS pairs.
    """
    records = []
    
    for row in raw_rows:
        # Extract all numeric values in the row
        nums = []
        for word in row:
            cleaned = re.sub(r'[^0-9.]', '', word.replace(',', '.'))
            if cleaned:
                try:
                    nums.append(float(cleaned))
                except ValueError:
                    continue
        
        # Case A: 10-Column Grid Matrix (Base MM + 10 Offsets)
        if len(nums) >= 11:
            base_mm = nums[0]
            for offset in range(10):
                records.append({'MM': int(base_mm + offset), 'LTRS': nums[offset + 1]})
                
        # Case B: Standard 2-Column Format (MM, LTRS)
        elif len(nums) == 2:
            records.append({'MM': int(nums[0]), 'LTRS': nums[1]})
            
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values('MM').drop_duplicates('MM').reset_index(drop=True)
        
        # Fill missing values across the full millimeter height range
        full_range = pd.DataFrame({'MM': range(0, int(df['MM'].max()) + 1)})
        df = pd.merge(full_range, df, on='MM', how='left')
        df['LTRS'] = df['LTRS'].interpolate(method='linear').bfill().ffill()
        
    return df

if uploaded_file:
    if reader is None:
        st.error("Please install EasyOCR: `pip install easyocr`")
    else:
        images = []
        file_type = uploaded_file.name.split('.')[-1].lower()
        
        if file_type == 'pdf':
            images = convert_from_bytes(uploaded_file.read())
        else:
            images = [Image.open(uploaded_file)]
            
        all_rows = []
        for idx, img in enumerate(images):
            st.write(f"🔍 Performing Deep Spatial OCR on page {idx + 1}...")
            rows = extract_rows_with_easyocr(img)
            all_rows.extend(rows)
            
        final_df = normalize_calibration_table(all_rows)
        
        if not final_df.empty:
            st.subheader(f"✅ Extracted & Flattened Calibration ({len(final_df)} MM entries)")
            st.dataframe(final_df, use_container_width=True)
            
            # Export to Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                final_df.to_excel(writer, index=False)
            buffer.seek(0)
            st.download_button("📥 Download Excel File", buffer, "calibration.xlsx")
        else:
            st.warning("Could not structure table from image. Ensure image clarity is high.")
