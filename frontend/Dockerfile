FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.31-alpine3.23

# Apply Alpine security updates for packages already present in the image.
# Upgrading only the affected packages avoids pulling in new tools or
# changing the nginx package itself.
RUN apk upgrade --no-cache \
    brotli-libs c-ares curl libcrypto3 libcurl libexpat libpng libssl3 \
    libuuid libxml2 libxslt musl musl-utils nghttp2-libs pcre2 tiff zlib

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN chown -R nginx:nginx /usr/share/nginx/html
USER nginx
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
