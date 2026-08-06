# Composants tiers

Le bundle installe les versions verrouillées dans `requirements-web.lock` et `requirements-ocr.lock`.

| Composant | Version | Licence principale |
|---|---:|---|
| FastAPI | 0.128.2 | MIT |
| Starlette | 0.50.0 | BSD-3-Clause |
| Uvicorn | 0.48.0 | BSD-3-Clause |
| Pydantic | 2.13.4 | MIT |
| Requests | 2.32.5 | Apache-2.0 |
| Beautiful Soup | 4.14.3 | MIT |
| Argon2-cffi | 25.1.0 | MIT |
| PyMuPDF | 1.26.7 | AGPL-3.0 ou licence commerciale Artifex |
| pytesseract | 0.3.13 | Apache-2.0 |
| Pillow | 12.2.0 | HPND |
| OpenCV Python Headless | 4.13.0.92 | Apache-2.0 |
| NumPy | 2.3.5 | BSD-3-Clause |

Tesseract OCR et ses données linguistiques sont installés par le gestionnaire de paquets du système et conservent leurs propres licences.

Ce tableau est informatif. Les métadonnées et textes de licence fournis par chaque paquet restent la référence. Le fichier `LICENSES/PyMuPDF.txt` reproduit la mention de licence distribuée avec PyMuPDF.
