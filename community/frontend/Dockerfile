FROM node:24-alpine
RUN corepack enable
WORKDIR /app
COPY community/frontend/package.json community/frontend/pnpm-lock.yaml community/frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY community/frontend ./
COPY community/forms ../forms
RUN pnpm build
CMD ["pnpm", "start"]
