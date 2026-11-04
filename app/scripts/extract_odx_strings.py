#!/usr/bin/python3

import argparse, os, urllib.request, ast, sys
from io import StringIO

# Misc variables needed to get config to run
__version__ = '?'
class context:    
    root_path = ''
    num_cores = 4
class io:
    def path_or_json_string_to_dict(s):
        return s
def path_or_json_string(s):
    return s
class log:
    def ODM_ERROR(s):
        pass

def extract_odx_strings(url, outfile):
    strings = []
    print("Fetching %s ..." % url)
    res = urllib.request.urlopen(url)
    config_file = res.read().decode('utf-8')
    # config_file = open("test.py").read()

    options = {}
    class ArgumentParserStub(argparse.ArgumentParser):
        def add_argument(self, *args, **kwargs):
            argparse.ArgumentParser.add_argument(self, *args, **kwargs)
            options[args[0]] = {}
            for name, value in kwargs.items():
                options[args[0]][str(name)] = str(value)
        
        def add_mutually_exclusive_group(self):
            return ArgumentParserStub()

    # Voodoo! :)
    # ( parse AST, extract "def config()" function, set module to only
    # contain that function, execute module in current scope, 
    # run config function)
    root = ast.parse(config_file)
    new_body = []
    for stmt in root.body:
        # Assignments
        if hasattr(stmt, 'targets'):
            new_body.append(stmt)

        # Functions
        elif hasattr(stmt, 'name'):
            new_body.append(stmt)

    root.body = new_body
    exec(compile(root, filename="<ast>", mode="exec"), globals())



    config(["--project-path", "/bogus", "name"], parser=ArgumentParserStub())
    for opt in options:
        h = options[opt].get('help')
        if h:
            h = h.replace("\n", "")
            strings.append(h)

    strings = list(set(strings))
    print("Found %s ODX strings" % len(strings))
    if len(strings) > 0:
        with open(outfile, "w") as f:
            f.write("// Auto-generated with extract_odx_strings.py, do not edit!\n\n")

            for s in strings:
                f.write("_(\"%s\");\n" % s.replace("\"", "\\\""))

        print("Wrote %s" % outfile)
    else:
        print("No strings found")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Extract ODX strings.')
    parser.add_argument('input', type=str,
                        help='URL to ODX\'s config.py')
    parser.add_argument('output', type=str,
                        help='Where to write resulting translation file')
    args = parser.parse_args()

    url = args.input
    outfile = args.output
    extract_odx_strings(url, outfile)
