FROM python:3.13.16-alpine

WORKDIR /app
COPY app/ /app/

# Pasta app-data do Umbrel, montada somente leitura pelo docker-compose
ENV UMBREL_APP_DATA=/umbrel-app-data \
    TARGETS_DB=/data/targets.db \
    PORT=8080 \
    PYTHONUNBUFFERED=1

# /data guarda o SQLite com o domínio e os subdomínios; monte um volume aqui
RUN mkdir /data && chown 1000:1000 /data
VOLUME /data

# Mesmo uid do usuário "umbrel", dono dos arquivos em app-data
USER 1000:1000
EXPOSE 8080

HEALTHCHECK --interval=1m --timeout=5s CMD wget -qO- "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["python", "/app/targets.py", "--serve"]
