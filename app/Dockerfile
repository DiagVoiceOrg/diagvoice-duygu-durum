# Frontend — Coolify (CPU sunucusu) bu klasörü build eder.
# Coolify: Build Pack = Dockerfile, Base Directory = /app, Port = 80, Domain = algoritmalar.diagvoice.com
# TLS ve domain yönlendirmesini Coolify'ın kendi proxy'si yapar.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Backend adresi build sırasında bundle'a gömülür (Vite). Coolify'da "Build Variable" olarak değiştirilebilir.
ARG VITE_API_BASE=https://aiapi.diagvoice.com
ARG VITE_API_TIMEOUT_MS=600000
ENV VITE_API_BASE=$VITE_API_BASE \
    VITE_API_TIMEOUT_MS=$VITE_API_TIMEOUT_MS
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
