# syntax=docker/dockerfile:1
#
# impagina — Markdown -> PDF con template personalizzati
# Pipeline: pandoc (Markdown -> Typst) + typst (Typst -> PDF)
#
# Build:  docker build -t impagina .                    (CLI)
#         docker build --target api -t impagina-api .   (servizio API)

# ---------------------------------------------------------------------------
# Stage 1: scarica ed estrae pandoc, typst e i font. Nulla di tutto questo
# (curl, unzip, archivi) finisce nell'immagine finale.
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS fetch

ARG PANDOC_VERSION=3.11
ARG TYPST_VERSION=0.15.1
ARG INTER_VERSION=4.1
ARG JETBRAINS_MONO_VERSION=2.304

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip xz-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /staging

# pandoc: dal .deb ufficiale estraiamo il solo binario (i data file sono
# compilati dentro il binario nelle release ufficiali).
RUN curl -fsSL -o pandoc.deb \
      "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-amd64.deb" \
 && dpkg-deb -x pandoc.deb pandoc-pkg \
 && install -Dm755 pandoc-pkg/usr/bin/pandoc /staging/bin/pandoc

# typst: binario statico musl, funziona su qualunque distro glibc/musl.
RUN curl -fsSL -o typst.tar.xz \
      "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-x86_64-unknown-linux-musl.tar.xz" \
 && tar -xJf typst.tar.xz \
 && install -Dm755 typst-x86_64-unknown-linux-musl/typst /staging/bin/typst

# Font: solo i tagli statici che servono davvero (i variable font e la
# famiglia Display non sono usati dal template e peserebbero inutilmente).
RUN curl -fsSL -o inter.zip \
      "https://github.com/rsms/inter/releases/download/v${INTER_VERSION}/Inter-${INTER_VERSION}.zip" \
 && unzip -q inter.zip -d inter \
 && mkdir -p /staging/fonts/inter \
 && for f in Regular Italic Medium SemiBold Bold BoldItalic; do \
      cp "inter/extras/ttf/Inter-${f}.ttf" /staging/fonts/inter/; \
    done

RUN curl -fsSL -o jbmono.zip \
      "https://github.com/JetBrains/JetBrainsMono/releases/download/v${JETBRAINS_MONO_VERSION}/JetBrainsMono-${JETBRAINS_MONO_VERSION}.zip" \
 && unzip -q jbmono.zip -d jbmono \
 && mkdir -p /staging/fonts/jetbrains-mono \
 && for f in Regular Italic Bold BoldItalic; do \
      cp "jbmono/fonts/ttf/JetBrainsMono-${f}.ttf" /staging/fonts/jetbrains-mono/; \
    done

# ---------------------------------------------------------------------------
# Stage 2: base comune alla CLI e al servizio API
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS base

# libgmp10 e zlib1g sono le uniche dipendenze dinamiche di pandoc;
# python3 esegue la CLI usando solo la libreria standard (nessun pip).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libgmp10 zlib1g python3 \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man /usr/share/locale

COPY --from=fetch /staging/bin/pandoc /usr/local/bin/pandoc
COPY --from=fetch /staging/bin/typst  /usr/local/bin/typst
COPY --from=fetch /staging/fonts/     /usr/share/fonts/truetype/

# Template inclusi: vivono in /opt/impagina/templates e sono sempre
# disponibili. /templates e' la directory predefinita per i template esterni,
# montabile come volume; IMPAGINA_TEMPLATES_PATH ne indica altre (separate da
# ':'). Le directory esterne sono cercate per prime, quindi puoi ridefinire
# "company" o aggiungere template senza ricostruire l'immagine.
COPY src/       /opt/impagina/
COPY templates/ /opt/impagina/templates/
RUN mkdir -p /templates && chmod 755 /templates

# HOME e XDG_CACHE_HOME scrivibili: il container gira con --user <uid>:<gid>
# dell'utente host, che non ha una home dentro l'immagine.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    IMPAGINA_BUILTIN_TEMPLATES=/opt/impagina/templates \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ---------------------------------------------------------------------------
# Stage 3: servizio API (docker build --target api -t impagina-api .)
# ---------------------------------------------------------------------------
# Stessi strati della CLI: l'immagine pesa solo qualche KB in piu'. Il server
# gira con un utente dedicato, mai come root, e i lavori vivono in un volume.
FROM base AS api

RUN groupadd -g 10001 impagina \
 && useradd -u 10001 -g 10001 -d /nonexistent -s /usr/sbin/nologin impagina \
 && mkdir -p /var/lib/impagina-api /etc/impagina \
 && chown 10001:10001 /var/lib/impagina-api \
 && chmod 700 /var/lib/impagina-api

USER 10001:10001
EXPOSE 8080
VOLUME /var/lib/impagina-api
HEALTHCHECK --interval=60s --timeout=5s --start-period=5s \
  CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/salute', timeout=3)"]
ENTRYPOINT ["python3", "/opt/impagina/impagina-api.py"]

# ---------------------------------------------------------------------------
# Stage 4: CLI. Resta l'ultimo stage di proposito: "docker build -t impagina ."
# senza --target continua a produrre esattamente l'immagine di sempre.
# ---------------------------------------------------------------------------
FROM base

WORKDIR /data
ENTRYPOINT ["python3", "/opt/impagina/impagina.py"]
CMD ["--help"]
