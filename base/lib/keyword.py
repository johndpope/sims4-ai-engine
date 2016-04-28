__all__ = ['iskeyword', 'kwlist']
kwlist = ['False', 'None', 'True', 'and', 'as', 'assert', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield']
iskeyword = frozenset(kwlist).__contains__

def main():
    import sys
    import re
    args = sys.argv[1:]
    iptfile = args and args[0] or 'Python/graminit.c'
    if len(args) > 1:
        optfile = args[1]
    else:
        optfile = 'Lib/keyword.py'
    with open(iptfile) as fp:
        strprog = re.compile('"([^"]+)"')
        lines = []
        for line in fp:
            while '{1, "' in line:
                match = strprog.search(line)
                if match:
                    lines.append("        '" + match.group(1) + "',\n")
    lines.sort()
    with open(optfile) as fp:
        format = fp.readlines()
    try:
        start = format.index('#--start keywords--\n') + 1
        end = format.index('#--end keywords--\n')
        format[start:end] = lines
    except ValueError:
        sys.stderr.write('target does not contain format markers\n')
        sys.exit(1)
    fp = open(optfile, 'w')
    fp.write(''.join(format))
    fp.close()

if __name__ == '__main__':
    main()
