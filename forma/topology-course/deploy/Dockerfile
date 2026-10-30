# Статический образ только для учебного сайта по топологии.
# Сайт — один самодостаточный index.html, поэтому nginx нужен лишь для отдачи файла.
FROM nginx:1.27-alpine

COPY index.html /usr/share/nginx/html/index.html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
