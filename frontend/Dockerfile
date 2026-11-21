FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html .
COPY src ./src
ARG VITE_API_BASE_URL
RUN npm run build

FROM nginx:alpine
ENV FRONTEND_PORT=3000
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 3000
