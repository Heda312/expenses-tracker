"""Format export CSV generik yang kompatibel dengan workflow bank."""

from io import StringIO
import csv


def build_bank_csv(rows: list[dict], bank: str = "umum") -> StringIO:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Tanggal", "Waktu", "Deskripsi", "Debit", "Kredit", "Nominal", "Saldo", "Dompet", "Kategori", "Reference ID"])
    for row in rows:
        amount = row["amount"]
        debit = amount if row["kind"] == "expense" else 0
        credit = amount if row["kind"] == "income" else 0
        writer.writerow([row["date"], row.get("time", ""), row["merchant"], debit, credit, amount, "", row["account"], row["category"], row.get("id", "")])
    output.seek(0)
    return output
