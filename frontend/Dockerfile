FROM node:22-alpine AS build
WORKDIR /app
COPY package.json .
RUN npm install --no-audit --no-fund
COPY public ./public
COPY index.html src.jsx style.css ./
RUN npm run build

FROM nginx:stable-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 15-check-origin.sh /docker-entrypoint.d/15-check-origin.sh
ENV PORT=3000 API_BASE_URL=http://localhost:8000
EXPOSE 3000
