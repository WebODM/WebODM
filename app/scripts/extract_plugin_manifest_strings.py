#!/usr/bin/python3

import json, os, glob

def extract_plugin_manifest_strings(plugins_dir, output):
    strings = []
    manifests = glob.glob(os.path.join(plugins_dir, "*", "manifest.json"), recursive=True)
    print("Found %s manifests" % len(manifests))

    for m in manifests:
        if os.path.isdir(os.path.join(os.path.dirname(m), "locale")):
            continue

        with open(m) as f:
            j = json.loads(f.read())
            if j.get("description"):
                strings.append(j.get("description")) 

    print("Found %s manifest strings" % len(strings))
    if len(strings) > 0:
        with open(output, "w") as f:
            f.write("// Auto-generated with extract_plugin_manifest_strings.py, do not edit!\n\n")
            f.write("from django.utils.translation import gettext as _\n")
            
            for s in strings:
                f.write("_(\"%s\")\n" % s.replace("\"", "\\\""))

        print("Wrote %s" % output)
    else:
        print("No strings found")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Extract plugin manifest strings.')
    parser.add_argument('input', type=str,
                        help='Path to plugins directory')
    parser.add_argument('output', type=str,
                        help='Where to write resulting translation file')
    args = parser.parse_args()
    extract_plugin_manifest_strings(args.input, args.output)