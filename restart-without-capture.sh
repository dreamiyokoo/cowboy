#!/bin/bash
# capture を除く全サービスをビルドして再起動する
docker compose up --build -d api frontend db redis cloudflared
