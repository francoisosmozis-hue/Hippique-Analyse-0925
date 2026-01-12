import importlib

for m in ['scripts', 'scripts.online_fetch_zeturf']:
    try:
        importlib.import_module(m)
        print('[OK]', m)
    except Exception as e:
        print('[KO]', m, e)
