#!/bin/bash

echo "============================================"
echo "  Instagram DM Analiz Sistemi - Kurulum"
echo "============================================"
echo ""

REPO_URL="https://github.com/seghobs/isimalv4-premium.git"
CLONE_DIR="/tmp/isimalv4-install-$$"
TARGET_DIR="mysite"

# Gecici klasore klonla
echo "[1/3] Proje indiriliyor..."
git clone "$REPO_URL" "$CLONE_DIR" 2>/dev/null

if [ $? -ne 0 ]; then
    echo "HATA: Repo klonlanamadi!"
    exit 1
fi

echo "[2/3] Mysite klasoru hazirlaniyor..."

# mysite klasoru varsa icindekileri temizle
if [ -d "$TARGET_DIR" ]; then
    echo "  -> Eski 'mysite' klasoru bulundu, temizleniyor..."
    rm -rf "$TARGET_DIR"/*
    rm -rf "$TARGET_DIR"/.[!.]* 2>/dev/null
else
    mkdir "$TARGET_DIR"
fi

# Klonlanan dosyalari mysite icine kopyala
echo "[3/3] Dosyalar kopyalaniyor..."
cp -r "$CLONE_DIR"/* "$TARGET_DIR"/
cp -r "$CLONE_DIR"/.[!.]* "$TARGET_DIR"/ 2>/dev/null

# Gecici klasoru sil
rm -rf "$CLONE_DIR"

echo ""
echo "============================================"
echo "  Kurulum tamamlandi!"
echo "  Dosyalar: ./$TARGET_DIR/"
echo "============================================"
