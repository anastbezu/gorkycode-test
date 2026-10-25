FROM nginx:alpine

# Временная статическая страница, пока нет задачи фронтенда. Лишнее отсекает .dockerignore.
COPY . /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
