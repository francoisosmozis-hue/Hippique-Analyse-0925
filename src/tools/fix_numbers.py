#!/usr/bin/env python3
import argparse
import json
import pathlib
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap", required=True, help="Chemin du snapshot H-30 (ex: data/meeting/R5_H-30.json)")
    ap.add_argument("--geny-url", default=None)
    ap.add_argument("--pmu-url", default=None)
    ap.add_argument("--boturfers-url", default=None)
    ap.add_argument("--force-enumerate", action="store_true")
    args = ap.parse_args()

    snap_path = pathlib.Path(args.snap)
    if not snap_path.exists():
        print(f"[ERROR] Snapshot introuvable: {snap_path}", file=sys.stderr)
        return 2

    # Importe les helpers depuis src/
    sys.path.append("src")
    try:
        from online_fetch_zeturf import _extract_course_numbers_from_html, _fetch_html_playwright
    except Exception as e:
        print(f"[ERROR] Impossible d'importer les helpers Playwright depuis src/: {e}", file=sys.stderr)
        return 3

    # Charge le snapshot
    data = json.loads(snap_path.read_text(encoding="utf-8"))
    courses = data.get("courses", [])
    if not isinstance(courses, list) or not courses:
        print("[WARN] Pas de liste 'courses' dans le snapshot, rien à faire.")
        return 0

    # Si déjà numéroté → ne rien faire
    if all(c.get("course_num") not in (None, "", "null") for c in courses) and not args.force_enumerate:
        print("[OK] Tous les numéros sont déjà présents. Aucune modification.")
        return 0

    providers = [args.geny_url, args.pmu_url, args.boturfers_url]
    providers = [u for u in providers if u]

    def fetch_nums(url: str):
        try:
            html = _fetch_html_playwright(url)
            nums = _extract_course_numbers_from_html(html)
            nums = [n for n in nums if n and str(n).isdigit()]
            return nums
        except Exception as e:
            print(f"[WARN] Provider KO: {url} ({e})")
            return []

    nums = []
    if args.force_enumerate:
        nums = [str(i+1) for i in range(len(courses))]
    else:
        for u in providers:
            nums = fetch_nums(u)
            if nums:
                print(f"[OK] Numéros trouvés via: {u} => {nums[:10]}{'...' if len(nums)>10 else ''}")
                break
        if not nums:
            print("[WARN] Aucun provider n'a renvoyé de numéros → fallback 1..N")
            nums = [str(i+1) for i in range(len(courses))]

    # Injection (alignement au mieux)
    for i, c in enumerate(courses):
        c["course_num"] = nums[i] if i < len(nums) else str(i+1)

    data["courses"] = courses
    snap_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[DONE] Snapshot mis à jour:", snap_path)
    print("[CHECK]", [c.get("course_num") for c in courses][:12])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
