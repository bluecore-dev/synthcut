# syntax=docker/dockerfile:1.7
# Telegram Mini App: Vite build served by an unprivileged nginx.

FROM node:22-alpine AS build
WORKDIR /web
COPY apps/mini-app/package.json apps/mini-app/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY apps/mini-app/ ./
# Type checking runs before commit (make lint); the shared VPS only bundles.
RUN npx vite build

FROM nginxinc/nginx-unprivileged:stable-alpine
LABEL com.synthcut.project="synthcut"
COPY infrastructure/nginx/web.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
