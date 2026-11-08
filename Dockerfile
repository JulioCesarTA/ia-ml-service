# ============ STAGE 1: build-wheels ============
FROM python:3.12-slim AS build
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============ STAGE 2: runtime ============
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app && adduser --system --ingroup app app
WORKDIR /app
COPY --from=build /install /usr/local
# Pesos de la CNN (MobileNetV2) dentro de la imagen: el análisis de fotos funciona sin internet
ENV KERAS_HOME=/opt/keras
RUN python -c "import tensorflow as tf; tf.keras.applications.MobileNetV2(weights='imagenet', include_top=False, input_shape=(224,224,3)); print('pesos ok')"     && chown -R app:app /opt/keras
COPY app ./app
RUN mkdir -p /data && chown -R app:app /app /data
USER app
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fs http://localhost:8080/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
