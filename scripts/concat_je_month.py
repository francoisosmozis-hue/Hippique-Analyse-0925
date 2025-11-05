#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Concatène tous les fichiers *_je.csv d'un répertoire (récursif),
filtre par mois (YYYY-MM) et produit :
  - JE_YYYY-MM.csv (lignes détaillées)
  - JE_YYYY-MM_summary_jockey.csv (agrégats par jockey/driver)
  - JE_YYYY-MM_summary_entraineur.csv (agrégats par entraîneur)
Usage :
  python concat_je_month.py --data-dir data --month 2025-09 --outdir out
"""
import argparse
import re
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

STD_COLUMNS = [
    'date','reunion','course','hippodrome','discipline','cheval','num',
    'jockey','entraineur','j_rate','e_rate','source','race_id'
]

CANDIDATES = {
    'date':        ['date','jour','meeting_date','race_date'],
    'reunion':     ['reunion','r','reunion_num','meeting','meeting_num'],
    'course':      ['course','c','course_num','race','race_num'],
    'hippodrome':  ['hippodrome','track','venue'],
    'discipline':  ['discipline','disc','type_course','type'],
    'cheval':      ['cheval','horse','runner','name','nom'],
    'num':         ['num','numero','n','start','saddle','n°','#'],
    'jockey':      ['jockey','driver','pilote','cavalier'],
    'entraineur':  ['entraineur','entraîneur','trainer','handler','coach'],
    'j_rate':      ['j_rate','jockey_rate','j_success','j_percent','j_place_rate','j%'],
    'e_rate':      ['e_rate','trainer_rate','e_success','e_percent','e_place_rate','e%'],
    'source':      ['source','src'],
    'race_id':     ['race_id','race_key','race_uid','uid','id_course']
}

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols_lower = {c.lower(): c for c in df.columns}
    rename = {}
    for std, cands in CANDIDATES.items():
        for cand in cands:
            if cand in cols_lower:
                rename[cols_lower[cand]] = std
                break
    df = df.rename(columns=rename)
    # Ensure all expected columns exist
    for col in STD_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    # Clean date
    df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.date
    # Standardize strings
    for col in ['hippodrome','discipline','cheval','jockey','entraineur','source']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    # num as int where possible
    if 'num' in df.columns:
        df['num'] = pd.to_numeric(df['num'], errors='coerce').astype('Int64')
    # rates numeric
    for col in ['j_rate','e_rate']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

def _infer_date_from_path(p: Path):
    m = re.search(r'(20\d{2})[-_]?(\d{2})[-_]?(\d{2})', str(p))
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except Exception:
            return None
    return None

def load_and_filter(paths, month: str) -> pd.DataFrame:
    y = int(month.split('-')[0])
    m = int(month.split('-')[1])
    frames = []
    for p in paths:
        try:
            df = pd.read_csv(p)
        except Exception:
            try:
                df = pd.read_csv(p, sep=';')
            except Exception:
                # skip unreadable
                continue
        df = _normalize_columns(df)
        if df['date'].isna().all():
            inferred = _infer_date_from_path(p)
            if inferred:
                df['date'] = inferred
        mask = (
            pd.to_datetime(df['date'], errors='coerce').dt.year.eq(y) &
            pd.to_datetime(df['date'], errors='coerce').dt.month.eq(m)
        )
        df = df[mask]
        if not df.empty:
            df['__source_file'] = str(p)
            frames.append(df[STD_COLUMNS + ['__source_file']])
    if frames:
        all_df = pd.concat(frames, ignore_index=True)
        # drop obvious dupes
        all_df = all_df.drop_duplicates()
        return all_df
    return pd.DataFrame(columns=STD_COLUMNS + ['__source_file'])

def summarize_month(all_df: pd.DataFrame):
    base = all_df.copy()
    # Aggregation by jockey/driver
    j_cols = ['jockey']
    if base['jockey'].notna().any():
        j_sum = (
            base
            .groupby('jockey', dropna=True, as_index=False)
            .agg(starts=('jockey','size'),
                 mean_j_rate=('j_rate','mean'),
                 median_j_rate=('j_rate','median'),
                 sd_j_rate=('j_rate','std')))
        j_sum = j_sum.sort_values(['starts','mean_j_rate'], ascending=[False, False])
    else:
        j_sum = pd.DataFrame(columns=['jockey','starts','mean_j_rate','median_j_rate','sd_j_rate'])

    # Aggregation by trainer
    if base['entraineur'].notna().any():
        e_sum = (
            base
            .groupby('entraineur', dropna=True, as_index=False)
            .agg(starts=('entraineur','size'),
                 mean_e_rate=('e_rate','mean'),
                 median_e_rate=('e_rate','median'),
                 sd_e_rate=('e_rate','std')))
        e_sum = e_sum.sort_values(['starts','mean_e_rate'], ascending=[False, False])
    else:
        e_sum = pd.DataFrame(columns=['entraineur','starts','mean_e_rate','median_e_rate','sd_e_rate'])

    return j_sum, e_sum

def main():
    ap = argparse.ArgumentParser(description="Concatène tous les *_je.csv d'un mois et produit des résumés J/E.")
    ap.add_argument('--data-dir', default='data', help='Racine des fichiers (récursif)')
    ap.add_argument('--month', default='2025-09', help='Mois au format YYYY-MM (ex: 2025-09)')
    ap.add_argument('--outdir', default='.', help='Répertoire de sortie')
    args = ap.parse_args()

    root = Path(args.data_dir)
    if not root.exists():
        raise SystemExit(f"Répertoire introuvable: {root}")

    # Collecte des fichiers *_je.csv (fallback si pattern différent)
    paths = list(root.rglob("*_je.csv"))
    if not paths:
        # Fallback : quelques variantes fréquentes
        candidates = [p for p in root.rglob("*.csv")
                      if p.name.lower() in ("je.csv",) or
                         p.name.lower().endswith(("_je_h5.csv", "_JE.csv"))]
        paths = candidates

    if not paths:
        print("Aucun fichier *_je.csv trouvé sous", root)
    else:
        print(f"Fichiers candidats trouvés : {len(paths)}")

    all_df = load_and_filter(paths, args.month)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    outbase = outdir / f"JE_{args.month}.csv"
    out_j = outdir / f"JE_{args.month}_summary_jockey.csv"
    out_e = outdir / f"JE_{args.month}_summary_entraineur.csv"

    all_df.to_csv(outbase, index=False, encoding='utf-8')
    j_sum, e_sum = summarize_month(all_df)
    j_sum.to_csv(out_j, index=False, encoding='utf-8')
    e_sum.to_csv(out_e, index=False, encoding='utf-8')

    print(f"[OK] Écrits :\n - {outbase}\n - {out_j}\n - {out_e}")

if __name__ == '__main__':
    main()
