import streamlit as st
import pandas as pd
import io
import re

try:
    from PIL import Image
    import pytesseract
    from pdf2image import convert_from_bytes
except ImportError:
    pytesseract = None

st.set_page_config(page_title="Calibration Chart Converter", layout="wide")
st.title("📊 Tank Calibration Chart Converter & Flatten Tool")

uploaded_file = st.file_uploader(
    "Upload Calibration File", 
    type=["xlsx", "xls", "csv", "pdf", "png", "jpg", "jpeg"]
)

def parse_ocr_blocks_to_df(image):
    """
    Extracts text using bounding box coordinates to ensure numbers
    stay in their exact table columns and rows.
    """
    if not pytesseract:
        return pd.DataFrame()
    
    # Get bounding boxes and word coordinates
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DATAFRAME)
    data = data.dropna(subset=['text'])
    data['text'] = data['text'].astype(str).str.strip()
    data = data[data['text'] != '']
    
    # Group words by line coordinates
    lines = []
    grouped = data.groupby(['page_num', 'block_num', 'par_num', 'line_num'])
    for _, group in grouped:
        sorted_words = group.sort_values('left')['text'].tolist()
        lines.append(sorted_words)
    
    # Process numeric calibration rows
    structured_rows = []
    for words in lines:
        nums = []
        for w in words:
            cleaned = re.sub(r'[^0-9.]', '', w.replace(',', '.'))
            if cleaned:
                nums.append(cleaned)
        
        if len(nums) >= 2:
            structured_rows.append(nums)
            
    if structured_rows:
        max_cols = max(len(r) for r in structured_rows)
        padded = [r + [None]*(max_cols - len(r)) for r in structured_rows]
        cols = ['H_MM'] + [str(i) for i in range(max_cols - 1)]
        return pd.DataFrame(padded, columns=cols[:max_cols])
        
    return pd.DataFrame()

def flatten_calibration_df(df):
    records = []
    h_col = df.columns[0]
    
    for _, row in df.iterrows():
        try:
            base_mm = float(str(row[h_col]).replace(',', '').strip())
            for offset in range(10):
                col_key = str(offset)
                if col_key in df.columns and pd.notnull(row[col_key]):
                    val_str = str(row[col_key]).replace(',', '').strip()
                    val = float(val_str)
                    records.append({'MM': int(base_mm + offset), 'LTRS': val})
        except (ValueError, TypeError):
            continue
            
    flattened = pd.DataFrame(records)
    if not flattened.empty:
        flattened = flattened.sort_values('MM').drop_duplicates('MM').reset_index(drop=True)
        max_mm = int(flattened['MM'].max())
        
        # Build complete 0 to max_mm sequence
        full_range = pd.DataFrame({'MM': range(0, max_mm + 1)})
        merged = pd.merge(full_range, flattened, on='MM', how='left')
        
        # Linear interpolation for missing values
        merged['LTRS'] = merged['LTRS'].interpolate(method='linear').bfill().ffill()
        return merged
    return df

if uploaded_file:
    file_type = uploaded_file.name.split('.')[-1].lower()
    df_extracted = None

    if file_type in ['xlsx', 'xls', 'csv']:
        df_extracted = pd.read_csv(uploaded_file) if file_type == 'csv' else pd.read_excel(uploaded_file)

    elif file_type == 'pdf':
        st.info("📄 Processing multi-page PDF...")
        if pytesseract:
            try:
                uploaded_file.seek(0)
                images = convert_from_bytes(uploaded_file.read())
                
                all_page_dfs = []
                for i, img in enumerate(images):
                    st.write(f"🔍 Reading page {i+1} of {len(images)}...")
                    page_df = parse_ocr_blocks_to_df(img)
                    if not page_df.empty:
                        all_page_dfs.append(page_df)
                
                if all_page_dfs:
                    df_extracted = pd.concat(all_page_dfs, ignore_index=True)
            except Exception as e:
                st.error(f"OCR Exception: {e}")

    if df_extracted is not None and not df_extracted.empty:
        flattened_df = flatten_calibration_df(df_extracted)
        
        st.subheader(f"✅ Extracted & Flattened Data ({len(flattened_df)} total MM points)")
        st.dataframe(flattened_df, use_container_width=True)
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            flattened_df.to_excel(writer, sheet_name='Flattened_Calibration', index=False)
        buffer.seek(0)
        
        st.download_button(
            label="📥 Download Complete Flattened Excel File",
            data=buffer,
            file_name="Flattened_Calibration_Data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
