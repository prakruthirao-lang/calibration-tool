import streamlit as st
import pandas as pd
import io

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

st.set_page_config(page_title="Calibration Chart Converter", layout="wide")

st.title("📊 Tank Calibration Chart Converter & Flatten Tool")
st.write("Upload your calibration chart (**Excel, CSV, or PDF**) to flatten MM-to-LTRS rows and download the Excel output.")

uploaded_file = st.file_uploader(
    "Upload Calibration File", 
    type=["xlsx", "xls", "csv", "pdf", "png", "jpg", "jpeg"]
)

def process_calibration_data(df):
    records = []
    # Identify H column dynamically
    h_col = None
    for col in df.columns:
        if any(keyword in str(col).lower() for keyword in ['h', 'mm', 'height', 'depth']):
            h_col = col
            break
    if not h_col:
        h_col = df.columns[0]
        
    for _, row in df.iterrows():
        try:
            base_mm = float(str(row[h_col]).strip())
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
        st.info("📄 Processing PDF file...")
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
            else:
                st.warning("⚠️ No text or tables detected! This PDF is a scanned image (DocScan). Please upload an Excel/CSV file or a text-selectable PDF.")
        else:
            st.error("`pdfplumber` package missing in requirements.txt.")

    elif file_type in ['png', 'jpg', 'jpeg']:
        st.warning("⚠️ Image file detected. Please convert your image to an Excel or digital PDF file for extraction.")

    # Render results and Excel download button whenever data is extracted
    if df_extracted is not None and not df_extracted.empty:
        flattened_df = process_calibration_data(df_extracted)
        
        st.subheader("✅ Extracted & Flattened Data Preview")
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
