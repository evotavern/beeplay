FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY assets/ /usr/share/nginx/html/assets/

# Source files are mode 0600; nginx workers run as the unprivileged `nginx` user.
# a+rX = readable for all, execute only on directories so they stay traversable.
RUN chmod -R a+rX /usr/share/nginx/html

EXPOSE 80
