# macOS Beta Release Checklist

## Freeze

- [ ] Freeze product name and reverse-DNS bundle identifier.
- [ ] Tag an immutable candidate commit and verify a clean working tree.
- [ ] Record supported Apple-silicon hardware and macOS 13+ baseline.
- [ ] Freeze Python, Node, Rust, npm, Cargo, model revision/checksum, and Tesseract inputs.

## Automated evidence

- [ ] Python lint, formatting, type checks, tests, and migrations pass on 3.11, 3.12, and
  3.13.
- [ ] React tests, accessibility smoke test, production build, and npm audit pass.
- [ ] Rust fmt, clippy, tests, and locked build pass.
- [ ] pip/cargo/npm vulnerability audits have no release-blocking result.
- [ ] License policy passes and third-party inventory is archived.
- [ ] CycloneDX SBOM is archived.
- [ ] OCR package hashes match the explicit arm64 lock and every bundled Mach-O has an arm64
  slice with a deployment target no newer than macOS 13.
- [ ] The bundled model hash matches its pinned manifest; the packaged app launches its
  private core; and bundled Tesseract loads its native libraries plus `eng`/`osd` data.
- [ ] Retrieval benchmark report passes every enforced threshold.

## Recovery and compatibility

- [ ] Ingestion crash matrix and exact-resume assertions pass.
- [ ] 10,000-PDF performance run passes.
- [ ] Reading-order/identifier/merge corpus passes.
- [ ] Preview/Acrobat/PDF.js annotation round trip passes.
- [ ] Zotero reimport and missing-attachment corpus passes.
- [ ] Backup, destructive restore, trash restore, and purge drills pass.

## Signing and distribution

- [ ] Developer ID certificate and notarization credentials are scoped to the release
  environment.
- [ ] Separate internal/beta updater keys are stored as protected secrets.
- [ ] HTTPS update endpoint and signed manifest are live.
- [ ] PyInstaller sidecar and relocatable Tesseract dependencies are individually signed.
- [ ] Hardened-runtime app and DMG build on a clean hosted arm64 runner.
- [ ] `codesign --verify`, `spctl`, notarization stapling, mounted-app identity, and updater
  signature checks pass.
- [ ] Install, upgrade, rollback-by-reinstall, and first-run flows pass on a clean Mac.

## Human promotion

- [ ] Security review has no unresolved Critical/High findings.
- [ ] Internal alpha sign-off recorded.
- [ ] Five-user design-partner trial completed.
- [ ] Two-week no-data-loss and 99.5% crash-free thresholds met.
- [ ] Privacy/intended-use text and support process reviewed.
- [ ] Release notes identify deferred features and known residual risks.

Only a candidate with evidence attached for every applicable item may enter the 20–50-user
beta channel.
