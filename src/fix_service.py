#!/usr/bin/env python3
import sys, re

try:
    with open('src/service.py', 'r') as f:
        content = f.read()
    
    # Backup
    with open('src/service.py.backup', 'w') as f:
        f.write(content)
    
    # Corrections multiples
    content = re.sub(r'\s*service_url\s*=\s*f?"https://[^"]+"\s*\n', '', content)
    content = content.replace('mode=request.mode,', 'mode=body.mode,')
    content = content.replace('service_url=service_url', 'correlation_id=correlation_id')
    content = content.replace('run_url=f"{service_url}/run"', 'correlation_id=correlation_id')
    content = re.sub(r'correlation_id=correlation_id\s*,\s*correlation_id=correlation_id', 'correlation_id=correlation_id', content)
    
    with open('src/service.py', 'w') as f:
        f.write(content)
    
    print("✅ Fichier corrigé")
    sys.exit(0)
except Exception as e:
    print(f"❌ {e}")
    sys.exit(1)
