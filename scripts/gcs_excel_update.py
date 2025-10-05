import argparse
import os
import tempfile
from google.cloud import storage
from openpyxl import load_workbook


def download_blob(bucket_name, blob_name, local_path):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    if not blob.exists(client):
        raise FileNotFoundError(f"gs://{bucket_name}/{blob_name} introuvable")
    blob.download_to_filename(local_path)


def upload_blob(bucket_name, blob_name, local_path):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(
        local_path,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def append_row(xlsx_path, row):
    wb = load_workbook(xlsx_path)
    ws = wb.active
    ws.append(row)
    wb.save(xlsx_path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bucket", required=True, help="Nom du bucket GCS")
    p.add_argument("--object", required=True, help="Chemin objet XLSX dans le bucket")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--reunion", required=True)
    p.add_argument("--course", required=True)
    p.add_argument("--hippodrome", default="")
    p.add_argument("--discipline", default="")
    p.add_argument("--phase", choices=["H-30", "H-5"], required=True)
    p.add_argument("--jouable", choices=["OUI", "NON", "A_SURVEILLER"], required=True)
    p.add_argument("--tickets", default="")
    p.add_argument("--mises", type=float, default=0.0)
    p.add_argument("--gains", type=float, default=0.0)
    p.add_argument("--roi-estime", type=float, default=0.0)
    p.add_argument("--roi-reel", type=float, default=0.0)
    p.add_argument("--notes", default="")
    args = p.parse_args()

    # temp file
    with tempfile.TemporaryDirectory() as td:
        local = os.path.join(td, "modele.xlsx")
        download_blob(args.bucket, args.object, local)

        # ligne au format de ta feuille "Suivi"
        # [date, reunion, course, hippodrome, discipline, phase, jouable, tickets, mises, gains, roi_estime, roi_reel, notes]
        row = [
            args.date,
            args.reunion,
            args.course,
            args.hippodrome,
            args.discipline,
            args.phase,
            args.jouable,
            args.tickets,
            args.mises,
            args.gains,
            args.__dict__["roi_estime"],
            args.__dict__["roi_reel"],
            args.notes,
        ]
        append_row(local, row)
        upload_blob(args.bucket, args.object, local)


if __name__ == "__main__":
    main()
