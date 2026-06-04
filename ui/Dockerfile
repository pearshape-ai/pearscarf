# pearscarf-ui — Next.js standalone build.
#
# Usage:
#   docker build -t pearscarf-ui .
#   docker run --rm -p 3000:3000 \
#       -e DATABASE_URL=postgres://... \
#       pearscarf-ui

# --- deps stage: install everything for build ---
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

# --- build stage ---
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Next.js standalone output mode keeps only the bits the server needs.
RUN npm run build

# --- runtime stage: minimal image ---
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Copy the standalone server + static assets + public dir.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
