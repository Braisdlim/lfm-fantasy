FROM node:24-bookworm-slim
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web ./
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
