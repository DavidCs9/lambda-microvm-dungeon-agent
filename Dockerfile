FROM node:24-alpine

RUN addgroup -S app && adduser -S -G app app \
  && mkdir -p /app /workspace \
  && chown -R app:app /app /workspace

WORKDIR /app
COPY --chown=app:app package.json ./
COPY --chown=app:app src ./src

ENV NODE_ENV=production \
    PORT=8080 \
    WORKSPACE_DIR=/workspace

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/health >/dev/null || exit 1

CMD ["node", "src/server.js"]
