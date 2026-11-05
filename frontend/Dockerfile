# Frontend image for the self-hosted kit (deploy/): builds the Angular app and
# serves it with nginx, which also forwards /api/* to the backend container.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npx ng build
# Same-origin API: the app calls /api/..., nginx proxies it (see nginx.conf).
RUN echo "window.__API_URL__ = '/api';" > dist/frontend/browser/config.js \
 && sed -i 's#</head>#<script src="config.js"></script></head>#' dist/frontend/browser/index.html \
 && grep -q 'config.js' dist/frontend/browser/index.html

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist/frontend/browser /usr/share/nginx/html
