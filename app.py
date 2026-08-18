import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calibration Chart Converter", layout="wide")

st.title("📊 Tank Calibration Chart Converter & Flatten Tool")
st.write("Upload your calibration chart (Excel, CSV, or PDF) to automatically extract, flatten MM-to-LTRS rows, and interpolate missing values.")

uploaded_file = st.file_uploader("Upload Calibration Chart", type=["xlsx", "xls", "csv"])

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
        except ValueError:
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
    raw_df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
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
