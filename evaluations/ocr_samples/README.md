# OCR gold assets

These are small, artificial, non-production samples designed by maintainers;
their expected text, fields, cells, tokens and pages are written independently
in `../ocr_gold.json`, never copied from OCR output. Generate them only with:

```bash
conda run --no-capture-output -n fab-insight-agent python scripts/generate_ocr_gold_assets.py
```

Generation is offline and requires `/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc` plus Pillow and PyMuPDF. Evaluation only reads these committed binary assets and does not require that font. Current SHA-256 values are emitted by the generator after its format/page validation.

| Asset | SHA-256 |
|---|---|
| chinese.png | f8182d355b53b7bdb798c4459cfcc774a73a31d1641b85a05854547b88299ac1 |
| english.png | aee92d5c1e7fe0b61bae090b7dadce6b264453763af60b042c66c73c4907ca06 |
| device.png | 60b4b5e1e6b43597f383da8d5b7174edbaa19f79ecafb2f8ceda86ce67bba3fa |
| table.png | 3b5ae8bf09de51c9f3feb86b34cd9b6c52921a47469a2d294f3d8576b264cc8e |
| formula.png | 7a9382289c3fd4a031a2923efea2378dae1e82228468d19f69b04ef212c75886 |
| multi.tiff | 2c67aca55761b10775451b15e52f09cd81922fef1be55efceafcb8ec1a8525c3 |
| scanned.pdf | 205ce53a5adffcc97329565e6bdb270713ae72ccd84f1c2d17b651d27bef950b |
| mixed.pdf | cd952c95473e5c6b21b132ec1dd54ba9f32b7cd514c785e86ca04fb3ebe7b981 |
