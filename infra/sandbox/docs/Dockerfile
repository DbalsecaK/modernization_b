# Sandbox image of the document converter (spec 7.1, 15.4; ADR-0018): Word and Excel are read with the Python
# standard library; PDF with pypdf, installed at build time with its exact version and hash because the sandbox runs
# without network. Base image pinned by digest (the default sandbox image).
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
RUN printf 'pypdf==6.19.0 --hash=sha256:7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14\n' > /tmp/req.txt \
    && pip install --no-cache-dir --require-hashes --no-deps -r /tmp/req.txt && rm /tmp/req.txt \
    && python -c "import pypdf"
LABEL org.opencontainers.image.title="nexti-sandbox-docs" org.opencontainers.image.description="Sandbox that converts documents to text"
