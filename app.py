import streamlit as st
import pandas as pd
import io

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

st.set_page_config(page_title="Calibration Chart Converter", layout="wide")

st.title("📊 Tank Calibration Chart Converter & Flatten Tool")

# Expanded file uploader to enable PDF and Image selection
uploaded_file = st.file_uploader(
    "Upload Calibration Chart", 
    type=["xlsx", "xls", "csv", "pdf", "png", "jpg", "jpeg"]
)

def process_calibration_data(df):
    records = []
    h_col = 'H (mm)' if 'H (mm)' in df.columns else ('MM' if 'MM' in df.columns else df.columns[0])
    
    for _, row in df.iterrows():
        try:
            base_mm = float(row[h_col])
            for offset in range(10):
                col_str = str(offset)
                if col_str in df.columns and pd.notnull(row[col_str]):
                    records.append({'MM': int(base_mm + offset), 'LTRS': float(row[col_str])})
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
    
    if file_type in ['png', 'jpg', 'jpeg']:
        st.info("📷 Image file loaded successfully.")
        st.image(uploaded_file, caption="Uploaded Image Preview", use_column_width=True)

    elif file_type == 'pdf':
        st.info("📄 PDF file loaded successfully.")
        if pdfplumber:
            with pdfplumber.open(uploaded_file) as pdf:
                all_tables = []
                for page in pdf.pages:
                    table = page.extract_table()
                    if table:
                        all_tables.extend(table)
                if all_tables:
                    df = pd.DataFrame(all_tables[1:], columns=all_tables[0])
                    flattened_df = process_calibration_data(df)
                    st.dataframe(flattened_df.head(15))

    elif file_type in ['xlsx', 'xls', 'csv']:
        raw_df = pd.read_csv(uploaded_file) if file_type == 'csv' else pd.read_excel(uploaded_file)
        flattened_df = process_calibration_data(raw_df)
        st.dataframe(flattened_df.head(15))
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            flattened_df.to_excel(writer, sheet_name='Flattened_Data', index=False)
        buffer.seek(0)
        
        st.download_button(
            label="📥 Download Flattened Excel File",
            data=buffer,
            file_name="Flattened_Calibration_Data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
