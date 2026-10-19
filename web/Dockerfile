FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
USER node
CMD ["node","node_modules/next/dist/bin/next","start","-H","0.0.0.0","-p","3100"]
