FROM node:22-slim AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_AIVD_API_BASE_URL
ARG NEXT_PUBLIC_AIVD_WS_URL
ENV NEXT_PUBLIC_AIVD_API_BASE_URL=${NEXT_PUBLIC_AIVD_API_BASE_URL}
ENV NEXT_PUBLIC_AIVD_WS_URL=${NEXT_PUBLIC_AIVD_WS_URL}
RUN npm run build

FROM node:22-slim
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /app ./
EXPOSE 8080
CMD ["./node_modules/.bin/vinext", "start", "--host", "0.0.0.0", "--port", "8080"]
