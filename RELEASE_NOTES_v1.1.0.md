# v1.1.0 - Enhanced UI with Grid Layout

## 🎨 UI Improvements

### Grid Layout yang Jelas
- Budget preview dengan box grid layout (╔═╗║╠╣╚═╝)
- Transaction detail dengan format terstruktur
- Delete confirmation menampilkan detail lengkap transaksi
- Saldo response dengan grid konsisten

### Response Improvements
- **Budget response** menampilkan perbandingan dengan budget sebelumnya (naik/turun)
- **Budget list** dengan status visual (🔴 over budget vs 💚 on track)
- **Delete transaction** menampilkan semua detail transaksi yang dihapus
- **Saldo** dengan emoji per jenis akun (💳 bank, 📱 e-wallet, 💵 cash)

### Technical Changes
- Semua response menggunakan box character untuk grid yang jelas
- Format konsisten di seluruh aplikasi
- Mudah dibaca dan lebih menarik secara visual

## 📦 Installation

```bash
git clone https://github.com/Heda312/expenses-tracker.git
cd expenses-tracker
git checkout v1.1.0
docker compose up -d
```

## 🔄 Upgrade from v1.0.0

```bash
git pull
git checkout v1.1.0
docker compose restart bot
```
