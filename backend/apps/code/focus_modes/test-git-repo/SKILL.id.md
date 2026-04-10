---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Uji repo git"
description: "Kloning repo git dan uji apakah berfungsi."
lang: id
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Uji repo git

## Process

- jika belum disediakan, minta pengguna untuk URL repo github/gitlab
- jika belum disediakan, tanya pengguna apa yang ingin mereka uji / apa kasus penggunaan mereka
- gunakan keahlian untuk memeriksa issues apakah ada masalah kritis yang baru-baru ini dilaporkan
- jika proyek dilaporkan rusak, tanya pengguna apakah ingin melanjutkan pengujian
- tanya pengguna di mana mengkloning dan menguji repo: mengatur mesin baru? menggunakan github codespaces? mesin lokal? dll.
- kloning repo ke lokasi yang ditentukan
- baca struktur folder dan file proyek serta readme.md untuk mendapatkan gambaran umum
- cari tahu cara menguji proyek dan mulai mengujinya
