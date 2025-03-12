FROM node:18-alpine

WORKDIR /app

# Copy package.json and package-lock.json files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy application files
COPY . .

# Create the temp directory for compiled templates
RUN mkdir -p temp

# Create templates directory if it doesn't exist
RUN mkdir -p templates

# Expose the port
EXPOSE 3030

# Set command to run the server
CMD ["node", "server.js"]
