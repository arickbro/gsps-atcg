def find_last(lst, elm):
    gen = (len(lst) - 1 - i for i, v in enumerate(reversed(lst)) if v == elm)
    return next(gen, None)