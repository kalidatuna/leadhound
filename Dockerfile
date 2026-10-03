# leadhound for servers. Needs LEADHOUND_PASSWORD (8+ characters). Data lives in /data.
#   docker run -p 8787:8787 -e LEADHOUND_PASSWORD=... -v leadhound:/data ghcr.io/kalidatuna/leadhound
FROM python:3.12-slim

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY leadhound ./leadhound
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 leadhound \
    && mkdir /data && chown leadhound /data \
    && rm -rf /src

USER leadhound
WORKDIR /home/leadhound
ENV LEADHOUND_HOME=/data LEADHOUND_CLOUD=1 PORT=8787 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8787
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/', timeout=4)"
CMD ["leadhound", "serve", "--cloud"]
