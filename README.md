# Huawei ONT WLAN / WAN Control

Script Python untuk mengontrol modem/router **Huawei HG8245W5-6T** via HTTP (request meniru browser secara utuh, termasuk token `x.X_HW_Token` dan urutan body).

## Fitur

- Cek status **WAN** (DNS/Internet, IP, gateway, koneksi, VLAN)
- **Auto Restart WAN** (disable → 2 detik → enable)
- **Restart Modem**
- Cek status **WLAN** 2.4G & 5G
- Ganti **SSID** WLAN (mendukung multi-SSID)
- Ganti **Password** WLAN
- **On / Off** WLAN per band
- **Channel & TX Power** WLAN (daftar channel tersedia diambil dari modem)
- Mode **DEBUG** (`--debug`) — menyimpan setiap request/response ke folder `debug/`

## Instalasi

```bash
pip install requests
```

### 1. Siapkan konfigurasi

```bash
copy .envhuawei-example .envhuawei
```

Lalu edit `.envhuawei`:

```
MODEM_IP=192.168.100.1
MODEM_USER=Support
MODEM_PASS=PASSWORD_MODEM
WAN_IF=2_INTERNET_R_VID_200
WAN_VID=200
```

> **JANGAN commit file `.envhuawei`** — isinya kredensial asli. File ini sudah dikecualikan di `.gitignore`. Yang di-upload hanya `.envhuawei-example` (template).

### 2. Jalankan

```bash
python wan_toggle.py
```

Output menu:

```
[1] Cek Status WAN
[2] Auto Restart WAN
[3] Restart Modem
[4] Cek Status WLAN (2.4G & 5G)
[5] WLAN: Ganti SSID
[6] WLAN: Ganti Password
[7] WLAN: On / Off
[8] WLAN: Channel & TX Power
[0] Keluar
```

## Cara kerja (ringkas)

1. Login via `/login.cgi` dengan password **base64** + token dari `/asp/GetRandCount.asp`, cookie disimpan sebagai `Cookie=sid=...:Language:english:id=1`.
2. Token untuk set WLAN diambil dari halaman **`WlanBasic.asp`** (token per-halaman), bukan dari `index.asp`.
3. Set WLAN memakai endpoint `set.cgi?...WifiCoverSetWlanBasic` dengan body lengkap `y.*` + `z.*` + `w.*` persis seperti browser — dan **`x.X_HW_Token` harus param terakhir**.
4. Daftar channel tersedia diambil dari `WlanChannel.asp` (freq + country + standard + width).

## Keamanan

Hanya untuk modem yang Anda miliki. Ganti semua kredensial default sebelum dipakai di jaringan produksi.