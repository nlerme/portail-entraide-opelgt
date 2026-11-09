# Composants tiers

Le bundle installe les versions verrouillées dans `requirements-web.lock` et `requirements-ocr.lock`.

| Composant | Version | Licence principale |
|---|---:|---|
| FastAPI | 0.128.2 | MIT |
| Starlette | 0.50.0 | BSD-3-Clause |
| Uvicorn | 0.48.0 | BSD-3-Clause |
| Pydantic | 2.13.4 | MIT |
| lbc (etienne-hd/lbc) | 1.1.9 | MIT |
| curl-cffi | 0.15.0 | MIT (composants embarqués sous leurs licences respectives) |
| Requests | 2.32.5 | Apache-2.0 |
| Beautiful Soup | 4.14.3 | MIT |
| Argon2-cffi | 25.1.0 | MIT |
| PyMuPDF | 1.26.7 | AGPL-3.0 ou licence commerciale Artifex |
| PDF.js (`pdfjs-dist`, build legacy) | 6.4.299 | Apache-2.0 |
| Leaflet | 1.9.4 | BSD-2-Clause |
| pytesseract | 0.3.13 | Apache-2.0 |
| Pillow | 12.2.0 | HPND |
| OpenCV Python Headless | 4.13.0.92 | Apache-2.0 |
| NumPy | 2.3.5 | BSD-3-Clause |
| QR Code generator library (Project Nayuki, JavaScript embarqué) | empreinte dans `UPSTREAM.json` | MIT |

Tesseract OCR et ses données linguistiques sont installés par le gestionnaire de paquets du système et conservent leurs propres licences.

La carte des petites annonces embarque [Leaflet 1.9.4](https://leafletjs.com/) dans `static/vendor/leaflet-1.9.4/`, avec sa licence BSD-2-Clause. `UPSTREAM.json` conserve la provenance npm, l’intégrité SHA-512 du paquet et les SHA-256 des fichiers distribués. Les tuiles visibles proviennent d’[OpenStreetMap](https://www.openstreetmap.org/copyright), avec attribution et licence ODbL des données ; elles ne sont ni préchargées ni distribuées dans le bundle. La localisation des communes utilise l’API publique Découpage administratif, distincte du service Nominatim.

Ce tableau est informatif. Les métadonnées et textes de licence fournis par chaque paquet restent la référence. Le fichier `LICENSES/PyMuPDF.txt` reproduit la mention de licence distribuée avec PyMuPDF.

Le collecteur Leboncoin utilise [lbc](https://github.com/etienne-hd/lbc), copyright Étienne Hodé, installé depuis PyPI. Son code et ses dépendances ne sont pas recopiés dans cette archive. Les textes de licence installés avec ces paquets restent applicables.

La visionneuse des bulletins embarque [PDF.js](https://mozilla.github.io/pdf.js/), version `pdfjs-dist` 6.4.299, dans `static/vendor/pdfjs-6.4.299/`. Le fichier `LICENSE` de ce répertoire contient sa licence Apache-2.0. Les notices des polices, CMaps et décodeurs sont conservées dans leurs sous-répertoires. `UPSTREAM.json` indique la source npm, son intégrité SHA-512 et les empreintes SHA-256 des fichiers distribués. Aucune ressource PDF.js ne provient d’un CDN pendant la consultation.

Les QR codes des connexions utilisent la [bibliothèque de Project Nayuki](https://www.nayuki.io/page/qr-code-generator-library), distribuée avec sa notice MIT en tête de `static/vendor/qrcodegen/qrcodegen.js`. `UPSTREAM.json` conserve son URL et son SHA-256. Aucune adresse n’est transmise à un générateur externe.

Le logo Opel historique est une reproduction vectorielle du modèle de 1964, vérifié contre l’image des [archives Opel](https://www.opelpost.com/03/2019/opel-signs-of-the-times/). Le fichier `static/common/opel-classic.source.json` précise la provenance de la reproduction et son empreinte. Le dessin géométrique et le nom Opel restent associés à la marque de leur titulaire.

