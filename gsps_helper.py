import re

def find_last(lst, elm):
    gen = (len(lst) - 1 - i for i, v in enumerate(reversed(lst)) if v == elm)
    return next(gen, None)

def filterNonPrint(string):
    filterChar = list(s for s in string if ( s.isprintable() or s == "\n") )
    return ''.join(filterChar)


def singleLine(regex,string):
    matches = re.search(regex, string)
    if(matches):
        return filterNonPrint(matches.group(1).strip())
    else:
        return None