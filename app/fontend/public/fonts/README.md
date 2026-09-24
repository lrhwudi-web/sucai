# Noto Sans SC for editable PDFs

NotoSansSC-Regular.ttf is a static weight-400 instance of the OFL-licensed Noto Sans SC variable font. Its source is https://github.com/google/fonts/tree/main/ofl/notosanssc. See OFL.txt for copyright and license terms.

The static instance was generated with fontTools 4.64.0:

```
python -m fontTools.varLib.instancer NotoSansSC-VF.ttf wght=400 --output=NotoSansSC-Regular.ttf
```

This file loads only during exports that contain non-ASCII text. Do not replace it with the variable source without checking rendered PDF text and form fields.
