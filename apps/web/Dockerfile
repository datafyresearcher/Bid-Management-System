FROM node:22-alpine

WORKDIR /app

# The API base URL is baked into the client bundle at build time. Empty
# string = same origin, which is what the self-hosted stack (nginx in front
# of both services) uses. A deployment that exposes the API on its own
# address instead passes it here, e.g. http://10.0.0.5:8000.
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# The build does not need to phone home.
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

ENV NODE_ENV=production
EXPOSE 3000

# .next is built as root above; hand the app tree to the unprivileged user
# that runs the server.
RUN chown -R node:node /app
USER node

# busybox wget ships with alpine; a 200 from the server itself is all the
# healthcheck needs to distinguish "running" from "started but stuck".
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1

CMD ["npm", "start"]
