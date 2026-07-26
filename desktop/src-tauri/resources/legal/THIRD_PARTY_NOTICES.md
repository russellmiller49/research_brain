# Research Memory third-party notices

The release build includes open-source libraries and a local machine-learning model. The
machine-readable inventory, exact versions, source locations, package hashes, and declared
licenses are shipped with each release as `licenses.json` and
`sbom-complete.cdx.json`.

The OCR runtime is assembled only from the SHA-256-locked conda-forge packages listed in
`packaging/tesseract-components.json`. Tesseract is Apache-2.0. Its dynamically linked
runtime includes libraries under BSD, MIT, ISC, Apache, Zlib, HPND, 0BSD, and compatible
notice licenses.

GNU libiconv 1.18 is dynamically linked under LGPL-2.1-only. Research Memory does not
restrict reverse engineering for debugging modifications to that library. The corresponding
source is available from <https://ftp.gnu.org/pub/gnu/libiconv/libiconv-1.18.tar.gz>, and the
license text is available from <https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt>.
The relocatable library is a separate dylib in the application resources and the complete
packaging recipe is provided in `scripts/package-tesseract.sh`.

The bundled `BAAI/bge-small-en-v1.5` ONNX model is MIT licensed and is pinned by repository
revision and SHA-256 in `resources/models/model-manifest.json`.

Research Memory itself is MIT licensed. This notice is informational and does not replace
the terms supplied by each upstream project.
