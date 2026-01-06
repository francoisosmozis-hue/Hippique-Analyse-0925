import sys
import xml.etree.ElementTree as ET

try:
    with open('coverage.xml') as f:
        file_content = f.read()
except FileNotFoundError:
    print("Error: coverage.xml not found.")
    sys.exit(1)

root = ET.fromstring(file_content)

low_coverage_files = []

for package in root.findall('.//package'):
    package_name = package.get('name')
    # Check if package_name is not None before calling startswith
    if package_name and package_name.startswith('hippique_orchestrator'):
        for class_elem in package.findall('.//class'):
            filename = class_elem.get('filename')
            line_rate_str = class_elem.get('line-rate')

            if filename and line_rate_str:
                try:
                    line_rate = float(line_rate_str)
                    # Filter for files within hippique_orchestrator package and low coverage
                    # Ensure filename is relative to hippique_orchestrator/ if that's how it's stored in XML
                    if filename.startswith('hippique_orchestrator/') and line_rate < 0.8:
                        low_coverage_files.append((filename, line_rate))
                    elif not filename.startswith('hippique_orchestrator/') and line_rate < 0.8:
                        # Handle cases where the filename in XML might not have the full path prefix
                        # but still belongs to a hippique_orchestrator package.
                        # This part needs refinement based on exact XML structure.
                        pass
                except ValueError:
                    # Handle cases where line-rate might not be a valid float
                    pass

if low_coverage_files:
    print("Files in 'hippique_orchestrator' with line-rate < 0.8:")
    for filename, line_rate in low_coverage_files:
        print(f"- {filename}: {line_rate:.2f}")
else:
    print("No files in 'hippique_orchestrator' found with line-rate < 0.8.")
