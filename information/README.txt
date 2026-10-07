Drop your source files in this folder, then run:  python ingest.py
The script scans everything here (including subfolders), writes one row per
file into data.csv, and stores the full text in search_index.db so every word
in every document can be searched from index.py.

Supported file types:
  - PDFs ................ .pdf   (scanned PDFs have no text layer and need OCR)
  - Excel spreadsheets .. .xlsx .xlsm  (.xls needs: pip install xlrd)
  - Word documents ...... .docx
  - Plain text .......... .txt .md .csv
  - Images (OCR) ........ .png .jpg .jpeg .tif .tiff .bmp .gif  (needs: pip install easyocr)

This folder is git-ignored on purpose: your documents stay on your computer.
