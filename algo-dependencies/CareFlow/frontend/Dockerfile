# 多階段：先 build，再用 nginx 提供靜態檔案。
ARG CAREFLOW_VERSION=0.4.8

FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY . .
RUN npm run build

FROM nginx:alpine
ARG CAREFLOW_VERSION=0.4.8

LABEL org.opencontainers.image.title="CareFlow Frontend" \
      org.opencontainers.image.version="${CAREFLOW_VERSION}" \
      org.opencontainers.image.description="CareFlow React frontend"

ENV CAREFLOW_VERSION="${CAREFLOW_VERSION}"

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
