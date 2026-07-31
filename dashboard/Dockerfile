FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# Start the Vite dev server bound to 0.0.0.0
CMD ["npm", "run", "dev"]
