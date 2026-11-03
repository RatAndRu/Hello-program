FROM node:22-alpine
ENV NODE_ENV=production
WORKDIR /app
COPY . /app
ARG ORIGAMI_REVISION=local
ENV ORIGAMI_REVISION=$ORIGAMI_REVISION
ENV PORT=8080
USER node
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
CMD ["node", "server.mjs"]
