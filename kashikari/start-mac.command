#!/bin/sh
# Mac用: このファイルをダブルクリックすると起動します
cd "$(dirname "$0")" || exit 1
node server.js
