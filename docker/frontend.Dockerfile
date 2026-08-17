FROM node:22-alpine

ENV NODE_ENV=development
WORKDIR /app

COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./

EXPOSE 3000
CMD ["npm", "run", "dev"]
