# pypdfium2 5.13.0 wheel license review

Updated: 2026-10-06. Decision: allow the exact reviewed installed wheel notice sets for repository dependency policy. This is a technical review of shipped notices, not a legal opinion or a blanket approval of PDFium builds.

The PDF MCP installs this package through pdfplumber. The original declaration is `BSD-3-Clause, Apache-2.0, dependency licenses`; it does not describe the complete bundle as one SPDX expression. CycloneDX 7.5.0 misses this package's nested `.dist-info/licenses` files, so the builder adds every file from that directory as a raw-byte base64 attachment, retaining the original declaration. The checker requires the exact package version, original declaration and entire filename/SHA-256 map in `.github/license-reviews/pypdfium2-5.13.0.json`. Changed, extra, duplicate or missing files, unsupported builds and version changes fail closed. A successful report includes the review reference and observed hashes.

Evidence: the installed PyPI 5.13.0 Linux x86_64 and Windows x64 wheels resolved from the committed PDF script lock; top-level `LICENSES/` and build-specific `data/<platform>/BUILD_LICENSES/` notices. The inventory includes all 19 files per wheel, not just the wrapper license. The manifest pins their raw-byte hashes; the generated SBOM preserves their complete contents.

Upstream sources: [package licensing](https://pypi.org/project/pypdfium2/5.13.0/#licensing), [release source notices](https://github.com/pypdfium2-team/pypdfium2/tree/5.13.0/BUILD_LICENSES). The publisher explicitly requires PDFium and dependency notices with binary distributions and notes that licensing depends on build configuration. This review covers the inspected standard wheels, not custom/V8/XFA/source builds or unlisted architectures.

| Shipped notice | Review and retained obligations |
| --- | --- |
| Apache-2.0, BSD-3-Clause | Wrapper code; preserve applicable license, attribution and modification notices. |
| CC-BY-4.0 | Documentation/examples, not a replacement license for the library. Preserve author/license attribution and mark adaptations when redistributing these materials. |
| pdfium.txt | BSD-3-Clause; preserve source/binary notices and avoid implied endorsement. |
| pdfium-binaries.txt, fast_float.txt, lcms.txt, simdutf.txt | MIT-style permission; preserve copyright and permission/disclaimer notices. |
| abseil.txt | Apache-2.0; preserve applicable license/NOTICE obligations. |
| agg23.txt | AGG 2.3 permission to copy/use/modify/sell/distribute with copyright notice; retain that notice. This is not the license of later AGG releases. |
| freetype.txt | FreeType Project License (FTL); preserve source notices, mark source changes, and acknowledge the FreeType Team in binary distribution documentation. |
| icu.txt | Unicode-3.0 plus historical ICU and dictionary/third-party notices; preserve the complete file, including BSD/MIT-style and IPADIC notices. GPL terms in this file concern named ICU4C build scripts and include explicit Autoconf distribution exceptions; they are not a blanket GPL declaration for the PDFium library. Custom/source distributions require their own review. |
| libjpeg_turbo.md, libjpeg_turbo.ijg | IJG/BSD/Zlib terms; preserve notices, mark source modifications, avoid endorsement and include the Independent JPEG Group acknowledgment with binary distribution documentation. |
| libopenjpeg.txt | BSD-2-Clause; preserve source/binary notices. |
| libpng.txt, zlib.txt | PNG/Zlib permissive terms; preserve notices, avoid misrepresenting origin and mark source modifications. |
| libtiff.txt | TIFF permission to use/copy/modify/distribute/sell; retain notices and avoid unauthorized use of names in publicity. |
| llvm-libc.txt | Apache-2.0 with LLVM exceptions and legacy NCSA notice; retain the complete notice rather than treating it as plain Apache-2.0. |

When distributing the PDF MCP environment or an image containing its wheel, include the wheel's full license directory and the relevant distribution acknowledgments. Policy acceptance checks the reviewed evidence; it does not automatically assemble a compliant release or verify undisclosed binary contents. General Docker/OS and other bundled binary auditing remain separate work.
