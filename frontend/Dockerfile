FROM node:22-alpine

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

RUN corepack enable && pnpm install --frozen-lockfile

COPY . .

# Render exposes configured environment variables to Docker builds
# as build arguments. These are all NON-SECRET frontend configuration.
ARG CHOWLY_API_ORIGIN
ARG NEXT_PUBLIC_WS_URL
ARG NEXT_PUBLIC_CHOWLY_DEMO_MODE

ENV CHOWLY_API_ORIGIN=${CHOWLY_API_ORIGIN}
ENV NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}
ENV NEXT_PUBLIC_CHOWLY_DEMO_MODE=${NEXT_PUBLIC_CHOWLY_DEMO_MODE}

RUN pnpm build

EXPOSE 3000

CMD ["pnpm", "start"]