# Local development storage, built from the official pinned Community source.
FROM golang:1.24-bookworm AS build
WORKDIR /src
RUN git clone --depth 1 --branch RELEASE.2025-04-22T22-12-26Z https://github.com/minio/minio.git . \
    && test "$(git rev-parse HEAD)" = "0d7408fc9969caf07de6a8c3a84f9fbb10a6739e"
RUN CGO_ENABLED=0 go build -trimpath -o /minio .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /minio /usr/local/bin/minio
COPY --from=build /src/LICENSE /licenses/minio-LICENSE
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
