FROM node:24.18.0-alpine AS web-build

WORKDIR /workspace/desktop

COPY desktop/package.json desktop/package-lock.json ./
RUN npm ci

COPY desktop/index.html desktop/tsconfig.json desktop/tsconfig.app.json \
  desktop/tsconfig.node.json desktop/vite.config.ts ./
COPY desktop/src ./src

ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ARG VITE_MAC_DOWNLOAD_URL=https://github.com/russellmiller49/research_brain/releases

ENV VITE_SUPABASE_URL=${VITE_SUPABASE_URL}
ENV VITE_SUPABASE_PUBLISHABLE_KEY=${VITE_SUPABASE_PUBLISHABLE_KEY}
ENV VITE_MAC_DOWNLOAD_URL=${VITE_MAC_DOWNLOAD_URL}

RUN test -n "${VITE_SUPABASE_URL}" \
  && test -n "${VITE_SUPABASE_PUBLISHABLE_KEY}" \
  && npm run build:web

FROM caddy:2.10.2-alpine

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=web-build /workspace/desktop/dist /srv

EXPOSE 8080

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
