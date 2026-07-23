FROM nginx:1.27-alpine

RUN mkdir -p /var/cache/nginx/client_temp /var/cache/nginx/proxy_temp \
        /var/cache/nginx/fastcgi_temp /var/cache/nginx/uwsgi_temp \
        /var/cache/nginx/scgi_temp /var/log/nginx /var/run/nginx \
    && chown -R nginx:nginx /var/cache/nginx /var/log/nginx /var/run/nginx

COPY nginx.conf /etc/nginx/nginx.conf
COPY conf.d/default.conf /etc/nginx/conf.d/default.conf
COPY dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD wget -qO- http://127.0.0.1/healthz || exit 1

USER nginx

CMD ["nginx", "-g", "daemon off;"]
